"""Rutas para conversaciones persistentes de chat QA."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from apps.backend.app.contracts.chats import (
    ConversationListResponse,
    ConversationMessage,
    ConversationMessagesResponse,
    ConversationSummary,
    CreateConversationRequest,
    RenameConversationRequest,
)
from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.security import get_current_user
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.repositories.file_repository import FileRepository

router = APIRouter(
    prefix="/chats",
    tags=["chats"],
    dependencies=[Depends(require_setup_completed)],
)


def _get_repository() -> FileRepository:
    return FileRepository(get_db_manager())


def _require_user_id(current_user: dict) -> int:
    user_id = current_user.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _map_summary(item: dict) -> ConversationSummary:
    return ConversationSummary(
        conversation_id=int(item.get("qa_conversations_id") or 0),
        title=str(item.get("qa_conversations_title") or "New chat"),
        turns=int(item.get("turns") or 0),
        last_message_preview=str(item.get("last_message_preview") or ""),
        created_at=item.get("qa_conversations_created"),
        updated_at=item.get("qa_conversations_updated"),
    )


@router.get("", response_model=ConversationListResponse)
def list_chats(
    search: str | None = Query(default=None, max_length=120),
    current_user: dict = Depends(get_current_user),
) -> ConversationListResponse:
    repository = _get_repository()
    user_id = _require_user_id(current_user)
    items = repository.list_qa_conversations(user_id=user_id, search=search)
    return ConversationListResponse(items=[_map_summary(item) for item in items])


@router.post("", response_model=ConversationSummary)
def create_chat(
    request: CreateConversationRequest,
    current_user: dict = Depends(get_current_user),
) -> ConversationSummary:
    repository = _get_repository()
    user_id = _require_user_id(current_user)
    created = repository.create_qa_conversation(user_id=user_id, title=request.title)
    if not created:
        raise HTTPException(status_code=503, detail="Chat conversations table is not available")
    return _map_summary({**created, "turns": 0, "last_message_preview": ""})


@router.patch("/{conversation_id}", response_model=ConversationSummary)
def rename_chat(
    conversation_id: int,
    request: RenameConversationRequest,
    current_user: dict = Depends(get_current_user),
) -> ConversationSummary:
    repository = _get_repository()
    user_id = _require_user_id(current_user)
    updated = repository.rename_qa_conversation(
        user_id=user_id,
        conversation_id=int(conversation_id),
        title=request.title,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Conversation not found")
    item = repository.get_qa_conversation(user_id=user_id, conversation_id=int(conversation_id))
    if not item:
        raise HTTPException(status_code=404, detail="Conversation not found")
    turns = repository.list_qa_conversation_messages(user_id=user_id, conversation_id=int(conversation_id))
    return _map_summary(
        {
            **item,
            "turns": len([msg for msg in turns if msg.get("role") == "assistant"]),
            "last_message_preview": turns[-1]["content"][:280] if turns else "",
        }
    )


@router.delete("/{conversation_id}")
def delete_chat(conversation_id: int, current_user: dict = Depends(get_current_user)):
    repository = _get_repository()
    user_id = _require_user_id(current_user)
    deleted = repository.delete_qa_conversation(user_id=user_id, conversation_id=int(conversation_id))
    if not deleted:
        raise HTTPException(status_code=404, detail="Conversation not found")
    return {"deleted": True, "conversation_id": int(conversation_id)}


@router.get("/{conversation_id}/messages", response_model=ConversationMessagesResponse)
def list_chat_messages(
    conversation_id: int,
    current_user: dict = Depends(get_current_user),
) -> ConversationMessagesResponse:
    repository = _get_repository()
    user_id = _require_user_id(current_user)
    conversation = repository.get_qa_conversation(user_id=user_id, conversation_id=int(conversation_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    raw_messages = repository.list_qa_conversation_messages(user_id=user_id, conversation_id=int(conversation_id))
    messages = [
        ConversationMessage(
            message_id=str(item.get("message_id") or ""),
            role=str(item.get("role") or "assistant"),
            content=str(item.get("content") or ""),
            created_at=item.get("created_at"),
            model_used=str(item.get("model_used") or ""),
            retrieval_metadata=(item.get("retrieval_metadata") if isinstance(item.get("retrieval_metadata"), dict) else {}),
        )
        for item in raw_messages
    ]
    return ConversationMessagesResponse(
        conversation_id=int(conversation.get("qa_conversations_id") or 0),
        title=str(conversation.get("qa_conversations_title") or "New chat"),
        messages=messages,
    )


@router.get("/{conversation_id}/export")
def export_chat(
    conversation_id: int,
    format: str = Query(default="markdown", pattern="^(markdown|json)$"),
    current_user: dict = Depends(get_current_user),
):
    repository = _get_repository()
    user_id = _require_user_id(current_user)
    conversation = repository.get_qa_conversation(user_id=user_id, conversation_id=int(conversation_id))
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    raw_messages = repository.list_qa_conversation_messages(user_id=user_id, conversation_id=int(conversation_id))
    title = str(conversation.get("qa_conversations_title") or "New chat")
    if format == "json":
        payload = {"conversation_id": int(conversation_id), "title": title, "messages": raw_messages}
        return JSONResponse(content=jsonable_encoder(payload))
    lines: list[str] = [f"# {title}", ""]
    for item in raw_messages:
        role = "User" if item.get("role") == "user" else "Assistant"
        created_at = item.get("created_at")
        timestamp = created_at.isoformat(timespec="seconds") if isinstance(created_at, datetime) else ""
        content = str(item.get("content") or "").strip()
        lines.append(f"## {role}{f' ({timestamp})' if timestamp else ''}")
        lines.append("")
        lines.append(content if content else "_No content_")
        lines.append("")
    markdown = "\n".join(lines).strip() + "\n"
    safe_title = "".join(ch for ch in title if ch.isalnum() or ch in {" ", "-", "_"}).strip()
    filename = (safe_title or "chat").replace(" ", "_")
    headers = {"Content-Disposition": f'attachment; filename="{filename}.md"'}
    return Response(content=markdown, media_type="text/markdown; charset=utf-8", headers=headers)

