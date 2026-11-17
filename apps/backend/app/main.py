"""FastAPI entrypoint for the migrated backend layout."""

from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from apps.backend.app.core import security
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.core.logging_config import configure_logging
from apps.backend.app.core.tracing import checkpoint, set_trace_id
from apps.backend.app.agent.service import get_qa_graph_service
from apps.backend.app.api.routes import (
    auth,
    chats,
    config,
    documents,
    file,
    health,
    improvement,
    metadata,
    questions,
    settings as settings_route,
    setup,
    users,
)


def _ensure_utf8_console() -> None:
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_ensure_utf8_console()
configure_logging()
logger = logging.getLogger(__name__)

settings = get_settings()
security.set_settings(settings)
db_manager = DatabaseManager.get_instance(settings)


async def _warmup_qa_graph_service() -> None:
    try:
        logger.info("Starting QA graph warmup in background...")
        qa_graph_service = get_qa_graph_service()
        await asyncio.to_thread(qa_graph_service.warmup)
        logger.info("QA graph warmup completed.")
    except asyncio.CancelledError:
        logger.info("QA graph warmup cancelled.")
        raise
    except Exception:
        logger.exception("QA graph warmup failed.")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AI Document Analyzer...")
    logger.info("Database pool initializes on first login")
    warmup_task: asyncio.Task[None] | None = None
    try:
        logger.info("Scheduling QA graph warmup...")
        warmup_task = asyncio.create_task(_warmup_qa_graph_service())
        app.state.qa_graph_warmup_task = warmup_task
        yield
    except asyncio.CancelledError:
        logger.info("Shutdown signal received")
        raise
    finally:
        logger.info("Shutting down...")
        if warmup_task is not None and not warmup_task.done():
            warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await warmup_task
        try:
            db_manager.close_pool()
        except Exception:
            pass


app = FastAPI(title="AI Document Analyzer API", version="1.0.0", lifespan=lifespan)


class TracingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if __import__("os").environ.get("TRACE", "0") != "1":
            return await call_next(request)
        trace_id = str(uuid.uuid4())
        set_trace_id(trace_id)
        checkpoint("request_start", tags={"method": request.method, "path": request.url.path})
        start = time.perf_counter()
        try:
            response = await call_next(request)
            checkpoint(
                "request_end",
                tags={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                },
            )
            return response
        except Exception:
            checkpoint(
                "request_end",
                tags={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.perf_counter() - start) * 1000, 2),
                    "error": True,
                },
            )
            raise


app.add_middleware(TracingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup.settings = settings
setup.db_manager = db_manager
auth.settings = settings
auth.db_manager = db_manager
users.settings = settings
users.db_manager = db_manager
file.db_manager = db_manager

app.include_router(setup.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(health.router, prefix="/api")
app.include_router(config.router, prefix="/api")
app.include_router(settings_route.router, prefix="/api")
app.include_router(documents.router, prefix="/api")
app.include_router(improvement.router, prefix="/api")
app.include_router(metadata.router, prefix="/api")
app.include_router(questions.router, prefix="/api")
app.include_router(chats.router, prefix="/api")
app.include_router(file.router, prefix="/api")


@app.get("/")
def root():
    return {"app": "AI Document Analyzer", "version": "1.0.0", "status": "running"}
