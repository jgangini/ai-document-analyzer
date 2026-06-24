"""Minimal chat API contract for external RAG clients."""

from __future__ import annotations

from pydantic import Field

from apps.backend.app.contracts.common import APIModel


class ChatRequest(APIModel):
    message: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    reset_session: bool = False


class ChatResponse(APIModel):
    answer: str
    sources: list[str] = Field(default_factory=list)
