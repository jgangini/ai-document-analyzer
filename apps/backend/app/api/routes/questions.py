"""QA routes for ingested documents."""

from __future__ import annotations

import json
from collections.abc import Iterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from apps.backend.app.contracts.questions import (
    AskQuestionRequest,
    AskQuestionResponse,
    CitationItem,
    EvidenceItem,
    GraphDefinitionResponse,
    GraphEdgeItem,
    GraphNodeItem,
    ReasoningStageItem,
    ReasoningStagesResponse,
    ScopeOptionsResponse,
    SourceItem,
)
from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.security import get_optional_current_user
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.agent.service import get_qa_graph_service
from apps.backend.app.rag.query_selectors import build_effective_selector_question, merge_question_selectors
from apps.backend.app.rag.scope_resolver import ScopeResolutionError
from apps.backend.app.repositories.file_repository import FileRepository
from apps.backend.app.services.metadata_keys import canonicalize_file_key

router = APIRouter(
    prefix="/questions",
    tags=["questions"],
    dependencies=[Depends(require_setup_completed)],
)


def _collect_exception_messages(exc: BaseException) -> list[str]:
    messages = [str(exc)]
    nested = getattr(exc, "exceptions", None)
    if nested:
        for child in nested:
            messages.extend(_collect_exception_messages(child))
    return messages


def _is_provider_unavailable_error(exc: BaseException) -> bool:
    combined = " | ".join(_collect_exception_messages(exc)).lower()
    hints = (
        "oci.exceptions.serviceerror",
        "generative_ai_inference",
        "authorization failed or requested resource not found",
        "notauthorizedornotfound",
        "status': 404",
        "status': 401",
        "status': 403",
    )
    return any(hint in combined for hint in hints)


def _normalize_chat_history(raw_history: list[dict[str, str]]) -> list[dict[str, str]]:
    normalized: list[dict[str, str]] = []
    for item in raw_history:
        role = str(item.get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        normalized.append({"role": role, "content": content[:2000]})
    return normalized[-24:]


def _dedupe_positive_ids(values: list[int] | None) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for raw_value in list(values or []):
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _normalize_archive_slugs(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_value in list(values or []):
        normalized = canonicalize_file_key(str(raw_value or "").strip())
        normalized_key = normalized.lower()
        if not normalized or normalized_key in seen:
            continue
        seen.add(normalized_key)
        ordered.append(normalized)
    return ordered


def _normalize_metadata_fields(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_value in list(values or []):
        normalized = str(raw_value or "").strip()
        normalized_key = normalized.casefold()
        if not normalized or normalized_key in seen:
            continue
        seen.add(normalized_key)
        ordered.append(normalized)
    return ordered


def _read_lob_value(value: object) -> object:
    if hasattr(value, "read"):
        return value.read()
    return value


def _extract_metadata_upload_columns(raw_value: object) -> list[str]:
    raw_value = _read_lob_value(raw_value)
    if isinstance(raw_value, (list, tuple)):
        parsed_columns = list(raw_value)
    else:
        try:
            parsed_columns = json.loads(str(raw_value or "[]"))
        except Exception:
            return []
    if not isinstance(parsed_columns, list):
        return []
    columns: list[str] = []
    for raw_column in parsed_columns:
        column = str(raw_column or "").strip()
        if not column or column.casefold() == "file":
            continue
        columns.append(column)
    return columns


def _extract_metadata_json_fields(raw_value: object) -> list[str]:
    raw_value = _read_lob_value(raw_value)
    try:
        metadata_payload = json.loads(str(raw_value or "{}"))
    except Exception:
        return []
    raw_fields = metadata_payload.get("fields")
    if not isinstance(raw_fields, dict):
        return []
    fields: list[str] = []
    for raw_key in raw_fields.keys():
        key = str(raw_key or "").strip()
        if not key or key.casefold() == "file":
            continue
        fields.append(key)
    return fields


def _load_visible_scope_options(*, repository: FileRepository, user_id: int) -> ScopeOptionsResponse:
    if int(user_id) < 0:
        return ScopeOptionsResponse()
    file_rows = list(repository.list_files_for_user(user_id=int(user_id), include_shared=True))
    files = _normalize_archive_slugs(
        [
            str(row.get("archive_slug") or "").strip()
            for row in file_rows
            if str(row.get("archive_slug") or "").strip()
        ]
    )

    upload_column_fields: list[str] = []
    persisted_metadata_fields: list[str] = []
    try:
        metadata_rows = list(repository.list_archive_metadata_for_user(user_id=int(user_id), include_shared=True))
    except Exception:
        metadata_rows = []
    for row in metadata_rows:
        upload_column_fields.extend(_extract_metadata_upload_columns(row.get("column_names_json")))
        persisted_metadata_fields.extend(_extract_metadata_json_fields(row.get("metadata_json")))
    metadata_fields = _normalize_metadata_fields(upload_column_fields)
    if not metadata_fields:
        metadata_fields = _normalize_metadata_fields(persisted_metadata_fields)

    return ScopeOptionsResponse(
        files=files,
        metadata_fields=metadata_fields,
        has_metadata=bool(metadata_fields),
    )


def _build_request_history(request: AskQuestionRequest) -> list[dict[str, str]]:
    return _normalize_chat_history(
        [
            {"role": item.role, "content": item.content}
            for item in list(request.history or [])
        ]
    )


def _load_conversation_messages(*, user_id: int, conversation_id: int | None) -> list[dict[str, object]]:
    if conversation_id is None:
        return []
    if user_id < 0:
        return []
    try:
        repository = FileRepository(get_db_manager())
        return list(repository.list_qa_conversation_messages(
            user_id=int(user_id),
            conversation_id=int(conversation_id),
        ))
    except Exception:
        return []


def _build_chat_history_from_conversation_messages(
    conversation_messages: list[dict[str, object]],
) -> list[dict[str, str]]:
    return _normalize_chat_history(
        [
            {"role": str(item.get("role") or ""), "content": str(item.get("content") or "")}
            for item in list(conversation_messages or [])
        ]
    )


def _extract_latest_conversation_scope_from_messages(
    *,
    conversation_messages: list[dict[str, object]],
    archive_slug_map_resolver=None,
) -> dict[str, object]:
    seen_session_ids: set[int] = set()
    for item in reversed(list(conversation_messages or [])):
        raw_session_id = item.get("session_id")
        try:
            session_id = int(raw_session_id) if raw_session_id is not None else 0
        except (TypeError, ValueError):
            session_id = 0
        if session_id > 0 and session_id in seen_session_ids:
            continue
        retrieval_metadata = item.get("retrieval_metadata")
        if not isinstance(retrieval_metadata, dict):
            continue
        scope_file_ids = _dedupe_positive_ids(
            list(retrieval_metadata.get("scope_file_ids") or [])
            or ([retrieval_metadata.get("scope_file_id")] if retrieval_metadata.get("scope_file_id") else [])
        )
        scope_archive_slugs = _normalize_archive_slugs(
            list(retrieval_metadata.get("scope_archive_slugs") or [])
        )
        scope_metadata_fields = _normalize_metadata_fields(
            list(retrieval_metadata.get("resolved_metadata_fields") or [])
            or list(retrieval_metadata.get("requested_metadata_fields") or [])
        )
        if not scope_archive_slugs and scope_file_ids and callable(archive_slug_map_resolver):
            try:
                archive_slug_map = dict(archive_slug_map_resolver(scope_file_ids) or {})
            except Exception:
                archive_slug_map = {}
            scope_archive_slugs = _normalize_archive_slugs(
                [archive_slug_map.get(file_id) for file_id in scope_file_ids]
            )
        if not scope_file_ids and not scope_archive_slugs:
            continue
        if session_id > 0:
            seen_session_ids.add(session_id)
        return {
            "conversation_scope_file_ids": scope_file_ids,
            "conversation_scope_archive_slugs": scope_archive_slugs,
            "conversation_scope_metadata_fields": scope_metadata_fields,
            "conversation_scope_turn_index": int(item.get("turn_index") or 0),
            "conversation_scope_question_class": str(retrieval_metadata.get("question_class") or ""),
            "conversation_scope_answer_mode": str(retrieval_metadata.get("answer_mode") or ""),
            "conversation_scope_answer_override_used": bool(
                retrieval_metadata.get("answer_override_used") or False
            ),
        }
    return {
        "conversation_scope_file_ids": [],
        "conversation_scope_archive_slugs": [],
        "conversation_scope_metadata_fields": [],
        "conversation_scope_turn_index": 0,
        "conversation_scope_question_class": "",
        "conversation_scope_answer_mode": "",
        "conversation_scope_answer_override_used": False,
    }


def _resolve_effective_conversation_scope(
    *,
    user_id: int,
    conversation_messages: list[dict[str, object]],
) -> dict[str, object]:
    if not conversation_messages or user_id < 0:
        return {
            "conversation_scope_file_ids": [],
            "conversation_scope_archive_slugs": [],
            "conversation_scope_metadata_fields": [],
            "conversation_scope_turn_index": 0,
            "conversation_scope_question_class": "",
            "conversation_scope_answer_mode": "",
            "conversation_scope_answer_override_used": False,
        }
    repository = FileRepository(get_db_manager())
    return _extract_latest_conversation_scope_from_messages(
        conversation_messages=conversation_messages,
        archive_slug_map_resolver=lambda file_ids: repository.get_archive_slug_map_for_file_ids(
            user_id=int(user_id),
            file_ids=file_ids,
            include_shared=True,
        ),
    )


def _resolve_effective_user_id(*, current_user: dict | None, request: AskQuestionRequest) -> int:
    token_user_id = None
    if current_user is not None and current_user.get("user_id") is not None:
        try:
            token_user_id = int(current_user.get("user_id"))
        except (TypeError, ValueError):
            token_user_id = None
    return token_user_id if token_user_id is not None else (
        int(request.user_id) if request.user_id is not None else 0
    )


def _resolve_effective_chat_history(
    *,
    request: AskQuestionRequest,
    user_id: int,
    conversation_messages: list[dict[str, object]] | None = None,
) -> list[dict[str, str]]:
    request_history = _build_request_history(request)
    loaded_messages = list(conversation_messages or [])
    if not loaded_messages:
        loaded_messages = _load_conversation_messages(
            user_id=user_id,
            conversation_id=request.conversation_id,
        )
    conversation_history = _build_chat_history_from_conversation_messages(loaded_messages)
    return conversation_history if conversation_history else request_history


def _build_citations_and_cited_sources(
    *,
    analyzed_evidence: list,
    citation_numbers: list[int],
) -> tuple[list[CitationItem], list[SourceItem]]:
    def _to_source_items(items: list) -> list[SourceItem]:
        return [
            SourceItem(
                doc_id=str(item.source_number),
                name=f"{item.file_name} - page {item.page_number}",
                source_number=int(item.source_number),
                file_id=int(item.file_id),
                page_number=int(item.page_number),
                object_name_page=str(item.object_name_page or ""),
                snippet=str(item.summary_text or "")[:500],
            )
            for item in items
        ]

    citation_set = {int(item) for item in citation_numbers if int(item) > 0}
    cited_items = [
        item
        for item in analyzed_evidence
        if int(getattr(item, "source_number", 0)) in citation_set
    ]
    citations = [
        CitationItem(
            source_number=item.source_number,
            file_name=item.file_name,
            page_number=item.page_number,
            score=item.score,
            snippet=item.summary_text[:280],
        )
        for item in cited_items
    ]
    cited_sources = _to_source_items(cited_items)
    return citations, cited_sources


def _build_ask_response_from_execution(execution) -> AskQuestionResponse:
    analyzed_evidence = execution.evidence
    enriched_answer = execution.answer
    citations, cited_sources = _build_citations_and_cited_sources(
        analyzed_evidence=analyzed_evidence,
        citation_numbers=list(enriched_answer.citation_source_numbers or []),
    )
    return AskQuestionResponse(
        answer=enriched_answer.answer_text,
        answer_text=enriched_answer.answer_text,
        executive_summary=enriched_answer.executive_summary,
        key_points=enriched_answer.key_points,
        obligations=enriched_answer.obligations,
        citations=citations,
        cited_sources=cited_sources,
        model_used=enriched_answer.model_used,
        strategy=execution.strategy,
        answer_mode=execution.answer_mode,
        visual_confirmation_used=execution.visual_confirmation_used,
        analyzed_pages=execution.analyzed_pages,
        confidence_notes=execution.confidence_notes,
        ocr_vs_visual_discrepancies=execution.ocr_vs_visual_discrepancies,
        evidence=analyzed_evidence,
        thread_id=execution.thread_id or None,
        telemetry=dict(execution.telemetry or {}),
    )


def _build_ask_response_from_stream_payload(payload: dict) -> AskQuestionResponse:
    evidence_items: list[EvidenceItem] = []
    for raw_item in list(payload.get("evidence") or []):
        try:
            evidence_items.append(EvidenceItem(**raw_item))
        except Exception:
            continue
    answer = payload.get("answer") if isinstance(payload.get("answer"), dict) else {}
    citation_numbers = [
        int(item)
        for item in list(answer.get("citation_source_numbers") or [])
        if isinstance(item, int) or (isinstance(item, str) and str(item).isdigit())
    ]
    citations, cited_sources = _build_citations_and_cited_sources(
        analyzed_evidence=evidence_items,
        citation_numbers=citation_numbers,
    )
    return AskQuestionResponse(
        answer=str(answer.get("answer_text") or ""),
        answer_text=str(answer.get("answer_text") or ""),
        executive_summary=str(answer.get("executive_summary") or ""),
        key_points=[str(item) for item in list(answer.get("key_points") or [])],
        obligations=[str(item) for item in list(answer.get("obligations") or [])],
        citations=citations,
        cited_sources=cited_sources,
        model_used=str(answer.get("model_used") or ""),
        strategy=str(payload.get("strategy") or ""),
        answer_mode=str(payload.get("answer_mode") or ""),
        visual_confirmation_used=bool(payload.get("visual_confirmation_used") or False),
        analyzed_pages=[
            int(item)
            for item in list(payload.get("analyzed_pages") or [])
            if isinstance(item, int) or (isinstance(item, str) and str(item).isdigit())
        ],
        confidence_notes=[str(item) for item in list(payload.get("confidence_notes") or [])],
        ocr_vs_visual_discrepancies=[str(item) for item in list(payload.get("ocr_vs_visual_discrepancies") or [])],
        evidence=evidence_items,
        thread_id=str(payload.get("thread_id") or "") or None,
        telemetry=dict(payload.get("telemetry") or {}),
    )


def _sse_packet(*, event_name: str, payload: dict) -> str:
    return f"event: {event_name}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _question_uses_inline_selectors(question: str) -> bool:
    normalized = str(question or "").lower()
    return "@metadata" in normalized or "/file:" in normalized or "/col:" in normalized


@router.get("/scope-options", response_model=ScopeOptionsResponse)
def get_scope_options(
    current_user: dict | None = Depends(get_optional_current_user),
) -> ScopeOptionsResponse:
    effective_user_id = -1
    if current_user is not None and current_user.get("user_id") is not None:
        try:
            effective_user_id = int(current_user.get("user_id"))
        except (TypeError, ValueError):
            effective_user_id = -1
    repository = FileRepository(get_db_manager())
    return _load_visible_scope_options(repository=repository, user_id=effective_user_id)


@router.post("/ask", response_model=AskQuestionResponse)
def ask_question(
    request: AskQuestionRequest,
    current_user: dict | None = Depends(get_optional_current_user),
) -> AskQuestionResponse:
    qa_graph_service = get_qa_graph_service()
    effective_user_id = _resolve_effective_user_id(current_user=current_user, request=request)
    repository = FileRepository(get_db_manager())
    scope_options = ScopeOptionsResponse()
    if (
        request.metadata_mode == "metadata_first"
        or request.archive_slugs
        or request.metadata_fields
        or _question_uses_inline_selectors(request.question)
    ):
        scope_options = _load_visible_scope_options(repository=repository, user_id=effective_user_id)
    merged_selectors = merge_question_selectors(
        question=request.question,
        request_metadata_mode=request.metadata_mode,
        request_archive_slugs=request.archive_slugs,
        request_metadata_fields=request.metadata_fields,
        available_archive_slugs=scope_options.files,
        available_metadata_fields=scope_options.metadata_fields,
    )
    cleaned_question = build_effective_selector_question(merged_selectors)
    if len(cleaned_question) < 3:
        raise HTTPException(
            status_code=400,
            detail="The question must contain text or a valid @metadata, /file:, or /col: selector intent.",
        )
    conversation_messages = _load_conversation_messages(
        user_id=effective_user_id,
        conversation_id=request.conversation_id,
    )
    effective_chat_history = _resolve_effective_chat_history(
        request=request,
        user_id=effective_user_id,
        conversation_messages=conversation_messages,
    )
    effective_conversation_scope = _resolve_effective_conversation_scope(
        user_id=effective_user_id,
        conversation_messages=conversation_messages,
    )
    try:
        execution = qa_graph_service.run(
            question=cleaned_question,
            raw_question=request.question,
            file_ids=request.file_ids,
            allow_inferred_scope=request.allow_inferred_scope,
            top_k=request.top_k,
            candidate_k=request.candidate_k,
            min_pages_per_selected_doc=request.min_pages_per_selected_doc,
            summary_mode=request.summary_mode,
            metadata_mode=merged_selectors.metadata_mode,
            archive_slugs=list(merged_selectors.archive_slugs or []),
            metadata_fields=list(merged_selectors.metadata_fields or []),
            chat_history=effective_chat_history,
            conversation_id=request.conversation_id,
            user_id=effective_user_id,
            current_date=request.current_date,
            conversation_scope_file_ids=list(effective_conversation_scope.get("conversation_scope_file_ids") or []),
            conversation_scope_archive_slugs=list(
                effective_conversation_scope.get("conversation_scope_archive_slugs") or []
            ),
            conversation_scope_metadata_fields=list(
                effective_conversation_scope.get("conversation_scope_metadata_fields") or []
            ),
            conversation_scope_turn_index=int(
                effective_conversation_scope.get("conversation_scope_turn_index") or 0
            ),
            conversation_scope_question_class=str(
                effective_conversation_scope.get("conversation_scope_question_class") or ""
            ),
        )
    except ScopeResolutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except BaseExceptionGroup as exc:
        if _is_provider_unavailable_error(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "OCI Generative AI is unavailable or unauthorized for the configured model/compartment. "
                    "Review `genai.model`, `oci.compartment_id`, endpoint and IAM policies."
                ),
            ) from exc
        raise
    except Exception as exc:
        if _is_provider_unavailable_error(exc):
            raise HTTPException(
                status_code=503,
                detail=(
                    "OCI Generative AI is unavailable or unauthorized for the configured model/compartment. "
                    "Review `genai.model`, `oci.compartment_id`, endpoint and IAM policies."
                ),
            ) from exc
        raise
    return _build_ask_response_from_execution(execution)


@router.get("/reasoning/stages", response_model=ReasoningStagesResponse)
def get_reasoning_stages() -> ReasoningStagesResponse:
    qa_graph_service = get_qa_graph_service()
    payload = qa_graph_service.get_reasoning_stages()
    return ReasoningStagesResponse(
        search=[ReasoningStageItem(**item) for item in payload.get("search", [])],
        document=[ReasoningStageItem(**item) for item in payload.get("document", [])],
    )


@router.get("/graph/definition", response_model=GraphDefinitionResponse)
def get_graph_definition() -> GraphDefinitionResponse:
    qa_graph_service = get_qa_graph_service()
    payload = qa_graph_service.get_graph_definition()
    return GraphDefinitionResponse(
        nodes=[GraphNodeItem(**item) for item in payload.get("nodes", [])],
        edges=[GraphEdgeItem(**item) for item in payload.get("edges", [])],
        start_node=str(payload.get("start_node") or "classify_intent"),
        end_node=str(payload.get("end_node") or "persist_turn"),
    )


@router.post("/ask/stream")
def ask_question_stream(
    request: AskQuestionRequest,
    current_user: dict | None = Depends(get_optional_current_user),
) -> StreamingResponse:
    qa_graph_service = get_qa_graph_service()
    effective_user_id = _resolve_effective_user_id(current_user=current_user, request=request)
    repository = FileRepository(get_db_manager())
    scope_options = ScopeOptionsResponse()
    if (
        request.metadata_mode == "metadata_first"
        or request.archive_slugs
        or request.metadata_fields
        or _question_uses_inline_selectors(request.question)
    ):
        scope_options = _load_visible_scope_options(repository=repository, user_id=effective_user_id)
    merged_selectors = merge_question_selectors(
        question=request.question,
        request_metadata_mode=request.metadata_mode,
        request_archive_slugs=request.archive_slugs,
        request_metadata_fields=request.metadata_fields,
        available_archive_slugs=scope_options.files,
        available_metadata_fields=scope_options.metadata_fields,
    )
    cleaned_question = build_effective_selector_question(merged_selectors)
    if len(cleaned_question) < 3:
        raise HTTPException(
            status_code=400,
            detail="The question must contain text or a valid @metadata, /file:, or /col: selector intent.",
        )
    conversation_messages = _load_conversation_messages(
        user_id=effective_user_id,
        conversation_id=request.conversation_id,
    )
    effective_chat_history = _resolve_effective_chat_history(
        request=request,
        user_id=effective_user_id,
        conversation_messages=conversation_messages,
    )
    effective_conversation_scope = _resolve_effective_conversation_scope(
        user_id=effective_user_id,
        conversation_messages=conversation_messages,
    )

    def iter_sse() -> Iterator[str]:
        try:
            for event in qa_graph_service.stream_run(
                question=cleaned_question,
                raw_question=request.question,
                file_ids=request.file_ids,
                allow_inferred_scope=request.allow_inferred_scope,
                top_k=request.top_k,
                candidate_k=request.candidate_k,
                min_pages_per_selected_doc=request.min_pages_per_selected_doc,
                summary_mode=request.summary_mode,
                metadata_mode=merged_selectors.metadata_mode,
                archive_slugs=list(merged_selectors.archive_slugs or []),
                metadata_fields=list(merged_selectors.metadata_fields or []),
                chat_history=effective_chat_history,
                conversation_id=request.conversation_id,
                user_id=effective_user_id,
                current_date=request.current_date,
                conversation_scope_file_ids=list(effective_conversation_scope.get("conversation_scope_file_ids") or []),
                conversation_scope_archive_slugs=list(
                    effective_conversation_scope.get("conversation_scope_archive_slugs") or []
                ),
                conversation_scope_metadata_fields=list(
                    effective_conversation_scope.get("conversation_scope_metadata_fields") or []
                ),
                conversation_scope_turn_index=int(
                    effective_conversation_scope.get("conversation_scope_turn_index") or 0
                ),
                conversation_scope_question_class=str(
                    effective_conversation_scope.get("conversation_scope_question_class") or ""
                ),
            ):
                if str(event.get("event_type")) == "run_completed":
                    execution_payload = event.get("execution")
                    if isinstance(execution_payload, dict):
                        ask_response = _build_ask_response_from_stream_payload(execution_payload)
                        event["final_response"] = ask_response.model_dump(mode="json")
                if str(event.get("event_type")) == "run_failed":
                    event_name = "error"
                else:
                    event_name = "graph_event"
                yield _sse_packet(event_name=event_name, payload=event)
            yield _sse_packet(event_name="done", payload={"done": True})
        except ScopeResolutionError as exc:
            yield _sse_packet(event_name="error", payload={"detail": str(exc), "status_code": exc.status_code})
            yield _sse_packet(event_name="done", payload={"done": True})
        except RuntimeError as exc:
            yield _sse_packet(event_name="error", payload={"detail": str(exc)})
            yield _sse_packet(event_name="done", payload={"done": True})
        except BaseExceptionGroup as exc:
            if _is_provider_unavailable_error(exc):
                yield _sse_packet(
                    event_name="error",
                    payload={
                        "detail": (
                            "OCI Generative AI is unavailable or unauthorized for the configured model/compartment. "
                            "Review `genai.model`, `oci.compartment_id`, endpoint and IAM policies."
                        )
                    },
                )
                yield _sse_packet(event_name="done", payload={"done": True})
                return
            yield _sse_packet(event_name="error", payload={"detail": str(exc)})
            yield _sse_packet(event_name="done", payload={"done": True})
        except Exception as exc:
            if _is_provider_unavailable_error(exc):
                yield _sse_packet(
                    event_name="error",
                    payload={
                        "detail": (
                            "OCI Generative AI is unavailable or unauthorized for the configured model/compartment. "
                            "Review `genai.model`, `oci.compartment_id`, endpoint and IAM policies."
                        )
                    },
                )
                yield _sse_packet(event_name="done", payload={"done": True})
                return
            yield _sse_packet(event_name="error", payload={"detail": str(exc)})
            yield _sse_packet(event_name="done", payload={"done": True})

    return StreamingResponse(
        iter_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
