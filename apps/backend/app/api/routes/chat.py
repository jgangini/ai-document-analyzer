"""Stable `/api/chat` facade for pod-safe document RAG sessions."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.backend.app.agent.service import get_qa_graph_service
from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.api.routes.chats import append_local_chat_turn
from apps.backend.app.contracts.chat import ChatRequest, ChatResponse
from apps.backend.app.core.config import get_settings
from apps.backend.app.evidence.service import source_labels_from_evidence
from apps.backend.app.services.local_rag_service import answer_local_chat
from apps.backend.app.services.session_memory import get_session_memory_store, normalize_session_id

router = APIRouter(tags=["chat"], dependencies=[Depends(require_setup_completed)])


@router.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    message = str(request.message or "").strip()
    if not message:
        raise HTTPException(status_code=400, detail="message is required.")
    try:
        session_id = normalize_session_id(request.session_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    memory = get_session_memory_store()
    if request.reset_session:
        memory.reset_session(session_id)
    history = memory.get_history(session_id)

    if get_settings().local_rag_enabled:
        result = answer_local_chat(message)
        memory.append_turn(
            session_id=session_id,
            user_message=message,
            assistant_answer=result.answer,
        )
        append_local_chat_turn(
            session_id=session_id,
            user_message=message,
            assistant_answer=result.answer,
            sources=result.sources,
        )
        return ChatResponse(answer=result.answer, sources=result.sources)

    try:
        execution = get_qa_graph_service().run(
            question=message,
            raw_question=message,
            file_ids=[],
            allow_inferred_scope=True,
            top_k=8,
            candidate_k=80,
            min_pages_per_selected_doc=1,
            summary_mode="default",
            metadata_mode="auto",
            archive_slugs=[],
            metadata_fields=[],
            chat_history=history,
            conversation_id=None,
            user_id=0,
            thread_id=session_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    answer = execution.answer.answer_text
    sources = source_labels_from_evidence(
        evidence=list(execution.evidence or []),
        citation_source_numbers=list(execution.answer.citation_source_numbers or []),
    )
    memory.append_turn(
        session_id=session_id,
        user_message=message,
        assistant_answer=answer,
    )
    return ChatResponse(answer=answer, sources=sources)
