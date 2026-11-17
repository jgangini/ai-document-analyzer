"""Schemas for persistent QA chat conversations and messages."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from apps.backend.app.contracts.common import APIModel


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)


class RenameConversationRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)


class ConversationSummary(APIModel):
    conversation_id: int
    title: str
    turns: int
    last_message_preview: str
    created_at: datetime
    updated_at: datetime


class ConversationListResponse(APIModel):
    items: list[ConversationSummary]


class ConversationMessage(APIModel):
    message_id: str
    role: str
    content: str
    created_at: datetime
    model_used: str
    retrieval_metadata: dict


class ConversationMessagesResponse(APIModel):
    conversation_id: int
    title: str
    messages: list[ConversationMessage]
