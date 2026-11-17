"""QA graph execution service."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import date, datetime, timezone
from functools import lru_cache
from importlib import import_module
import uuid
from typing import Any, Iterator

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.core.tracing import checkpoint
from apps.backend.app.agent.contracts import LLMResult, QueryExecutionResult

SEARCH_REASONING_STAGES: list[dict[str, Any]] = [
    {"key": "classify_intent", "label": "Classifying intent", "starts_at_seconds": 0},
    {"key": "search_response", "label": "Generating conversational response", "starts_at_seconds": 2},
]

DOCUMENT_REASONING_STAGES: list[dict[str, Any]] = [
    {"key": "classify_intent", "label": "Classifying intent", "starts_at_seconds": 0},
    {"key": "resolve_scope", "label": "Resolving document scope", "starts_at_seconds": 1},
    {"key": "classify_question", "label": "Classifying question type", "starts_at_seconds": 2},
    {"key": "resolve_facts", "label": "Resolving structured facts", "starts_at_seconds": 3},
    {"key": "decide_answerability", "label": "Deciding answerability route", "starts_at_seconds": 4},
    {"key": "retrieve_candidates", "label": "Retrieving multimodal candidates", "starts_at_seconds": 5},
    {"key": "fuse_page_evidence", "label": "Fusing page evidence", "starts_at_seconds": 7},
    {"key": "maybe_verify_visual", "label": "Selective visual verification", "starts_at_seconds": 9},
    {"key": "synthesize_document_answer", "label": "Synthesizing final answer", "starts_at_seconds": 11},
]

GRAPH_NODES: list[dict[str, str]] = [
    {"key": "classify_intent", "label": "Classify intent", "kind": "decision"},
    {"key": "search_response", "label": "Search response", "kind": "terminal_branch"},
    {"key": "resolve_scope", "label": "Resolve scope", "kind": "decision"},
    {"key": "classify_question", "label": "Classify question", "kind": "decision"},
    {"key": "resolve_facts", "label": "Resolve facts", "kind": "decision"},
    {"key": "decide_answerability", "label": "Decide answerability", "kind": "decision"},
    {"key": "retrieve_candidates", "label": "Retrieve candidates", "kind": "retrieval"},
    {"key": "fuse_page_evidence", "label": "Fuse page evidence", "kind": "merge"},
    {"key": "maybe_verify_visual", "label": "Maybe verify visual", "kind": "multimodal"},
    {"key": "synthesize_document_answer", "label": "Synthesize answer", "kind": "synthesis"},
    {"key": "persist_turn", "label": "Persist turn", "kind": "persistence"},
]

GRAPH_EDGES: list[dict[str, str]] = [
    {"source": "START", "target": "classify_intent", "condition": ""},
    {"source": "classify_intent", "target": "search_response", "condition": "route=search"},
    {"source": "classify_intent", "target": "resolve_scope", "condition": "route=document"},
    {"source": "search_response", "target": "persist_turn", "condition": ""},
    {"source": "resolve_scope", "target": "classify_question", "condition": ""},
    {"source": "classify_question", "target": "resolve_facts", "condition": ""},
    {"source": "resolve_facts", "target": "decide_answerability", "condition": ""},
    {"source": "decide_answerability", "target": "retrieve_candidates", "condition": "answerability_route!=metadata"},
    {"source": "decide_answerability", "target": "synthesize_document_answer", "condition": "answerability_route=metadata"},
    {"source": "retrieve_candidates", "target": "fuse_page_evidence", "condition": ""},
    {"source": "fuse_page_evidence", "target": "maybe_verify_visual", "condition": ""},
    {"source": "maybe_verify_visual", "target": "synthesize_document_answer", "condition": ""},
    {"source": "synthesize_document_answer", "target": "persist_turn", "condition": ""},
    {"source": "persist_turn", "target": "END", "condition": ""},
]


class QAGraphService:
    """QA entrypoint backed by a LangGraph workflow."""

    def __init__(self, *, graph, trace_repository: Any | None = None) -> None:
        self._graph = graph
        self._trace_repository = trace_repository

    @staticmethod
    def _utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _resolve_thread_id(*, conversation_id: int | None, thread_id: str | None) -> str:
        return thread_id or (
            f"conversation-{int(conversation_id)}"
            if conversation_id is not None
            else str(uuid.uuid4())
        )

    @staticmethod
    def _build_graph_input(
        *,
        question: str,
        raw_question: str | None,
        file_ids: list[int] | None,
        allow_inferred_scope: bool,
        top_k: int,
        candidate_k: int | None,
        min_pages_per_selected_doc: int,
        summary_mode: str,
        metadata_mode: str,
        archive_slugs: list[str] | None,
        metadata_fields: list[str] | None,
        chat_history: list[dict[str, str]] | None,
        conversation_id: int | None,
        user_id: int | None,
        thread_id: str,
        current_date: date | None,
        conversation_scope_file_ids: list[int] | None,
        conversation_scope_archive_slugs: list[str] | None,
        conversation_scope_metadata_fields: list[str] | None,
        conversation_scope_turn_index: int | None,
        conversation_scope_question_class: str | None,
    ) -> dict[str, Any]:
        safe_summary_mode = "per_document" if str(summary_mode).strip().lower() == "per_document" else "default"
        safe_file_ids = list(file_ids or [])
        safe_archive_slugs = [
            str(item).strip()
            for item in list(archive_slugs or [])
            if str(item).strip()
        ]
        safe_metadata_fields = [
            str(item).strip()
            for item in list(metadata_fields or [])
            if str(item).strip()
        ]
        safe_metadata_mode = (
            "metadata_first"
            if str(metadata_mode or "").strip().lower() == "metadata_first"
            else "auto"
        )
        return {
            "question": question,
            "raw_question": str(raw_question or question),
            "original_question": question,
            "effective_question": question,
            "metadata_mode": safe_metadata_mode,
            "requested_file_ids": safe_file_ids,
            "requested_archive_slugs": safe_archive_slugs,
            "requested_metadata_fields": safe_metadata_fields,
            "file_ids": safe_file_ids,
            "allow_inferred_scope": bool(allow_inferred_scope),
            "top_k": max(1, int(top_k)),
            "candidate_k": int(candidate_k) if candidate_k is not None else None,
            "min_pages_per_selected_doc": max(0, int(min_pages_per_selected_doc)),
            "summary_mode": safe_summary_mode,
            "retry_count": 0,
            "coverage_ratio": 0.0,
            "selected_docs_count": len(safe_file_ids),
            "distinct_files_in_evidence": 0,
            "chat_history": list(chat_history or []),
            "conversation_id": conversation_id,
            "user_id": user_id,
            "thread_id": thread_id,
            "current_date": current_date,
            "conversation_scope_file_ids": [int(file_id) for file_id in list(conversation_scope_file_ids or []) if int(file_id) > 0],
            "conversation_scope_archive_slugs": [
                str(item).strip()
                for item in list(conversation_scope_archive_slugs or [])
                if str(item).strip()
            ],
            "conversation_scope_metadata_fields": [
                str(item).strip()
                for item in list(conversation_scope_metadata_fields or [])
                if str(item).strip()
            ],
            "conversation_scope_turn_index": int(conversation_scope_turn_index or 0),
            "conversation_scope_question_class": str(conversation_scope_question_class or ""),
            "conversation_scope_applied": False,
            "question_class": "extractive",
            "question_class_rationale": "",
            "scope_origin": "manual" if safe_file_ids else "global",
            "scope_document_codes": [],
            "scope_archive_slugs": [],
            "resolved_scope_file_count": len(safe_file_ids),
            "scope_resolution_ms": 0,
            "ignored_inferred_scope": False,
            "fact_context_text": "",
            "answer_override": None,
            "facts_used_count": 0,
            "file_group_ids": [],
            "metadata_phase_used": False,
            "document_phase_used": False,
            "resolved_archive_slugs": list(safe_archive_slugs),
            "resolved_metadata_fields": list(safe_metadata_fields),
            "metadata_only_reason": "",
            "answerability_route": "",
            "doc_shortlist_count": 0,
            "text_candidates_count": 0,
            "image_candidates_count": 0,
            "page_text_count": 0,
            "page_image_count": 0,
            "oracle_text_count": 0,
            "fused_pages_count": 0,
            "rerank_count": 0,
            "metadata_prefilter_count": 0,
            "metadata_prefilter_ms": 0,
            "metadata_prefilter_applied": False,
            "query_embedding_ms": 0,
            "doc_search_ms": 0,
            "page_search_ms": 0,
            "rerank_ms": 0,
            "retrieval_total_ms": 0,
            "image_retrieval_enabled": False,
            "retrieval_route": "",
            "visual_checks_count": 0,
            "evidence_recall_proxy": 0.0,
            "node_timings_ms": {},
        }

    @classmethod
    def _to_jsonable(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, date):
            return value.isoformat()
        if isinstance(value, datetime):
            return value.isoformat()
        if isinstance(value, dict):
            return {str(k): cls._to_jsonable(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._to_jsonable(item) for item in value]
        if hasattr(value, "model_dump"):
            try:
                dumped = value.model_dump(mode="json")
            except TypeError:
                dumped = value.model_dump()
            return cls._to_jsonable(dumped)
        if is_dataclass(value):
            return cls._to_jsonable(asdict(value))
        return str(value)

    @staticmethod
    def _coerce_evidence_item(value: Any) -> EvidenceItem | None:
        if isinstance(value, EvidenceItem):
            return value
        if isinstance(value, dict):
            try:
                return EvidenceItem(**value)
            except Exception:
                return None
        return None

    @staticmethod
    def _coerce_llm_result(value: Any) -> LLMResult | None:
        if isinstance(value, LLMResult):
            return value
        if isinstance(value, dict):
            try:
                return LLMResult(
                    answer_text=str(value.get("answer_text", "")).strip(),
                    executive_summary=str(value.get("executive_summary", "")).strip(),
                    key_points=[str(item).strip() for item in list(value.get("key_points") or []) if str(item).strip()],
                    obligations=[str(item).strip() for item in list(value.get("obligations") or []) if str(item).strip()],
                    citation_source_numbers=[
                        int(item)
                        for item in list(value.get("citation_source_numbers") or [])
                        if isinstance(item, int) or (isinstance(item, str) and item.isdigit())
                    ],
                    model_used=str(value.get("model_used", "")).strip(),
                )
            except Exception:
                return None
        return None

    def _state_to_execution_result(self, *, state: dict[str, Any], thread_id: str) -> QueryExecutionResult:
        evidence_values = list(state.get("evidence") or [])
        evidence = [
            item
            for item in (self._coerce_evidence_item(raw_item) for raw_item in evidence_values)
            if item is not None
        ]
        llm_result = self._coerce_llm_result(state.get("answer"))
        if llm_result is None:
            raise RuntimeError("Graph execution did not produce a valid answer payload.")
        return QueryExecutionResult(
            strategy=str(state.get("strategy") or "search"),
            selected_provider=str(state.get("selected_provider") or "supervisor-graph"),
            evidence=evidence,
            answer=llm_result,
            answer_mode=str(state.get("answer_mode") or "small_talk"),
            visual_confirmation_used=bool(state.get("visual_confirmation_used") or False),
            analyzed_pages=[
                int(item)
                for item in list(state.get("analyzed_pages") or [])
                if isinstance(item, int) or (isinstance(item, str) and str(item).isdigit())
            ],
            confidence_notes=[str(item) for item in list(state.get("confidence_notes") or [])],
            ocr_vs_visual_discrepancies=[str(item) for item in list(state.get("ocr_vs_visual_discrepancies") or [])],
            thread_id=str(thread_id),
            telemetry={
                "question_class": str(state.get("question_class") or ""),
                "question_class_rationale": str(state.get("question_class_rationale") or ""),
                "selected_docs_count": int(state.get("selected_docs_count") or len(list(state.get("file_ids") or []))),
                "distinct_files_in_evidence": int(state.get("distinct_files_in_evidence") or 0),
                "coverage_ratio": float(state.get("coverage_ratio") or 0.0),
                "summary_mode": str(state.get("summary_mode") or "default"),
                "top_k": int(state.get("top_k") or 5),
                "candidate_k": int(state.get("candidate_k") or 0),
                "min_pages_per_selected_doc": int(state.get("min_pages_per_selected_doc") or 0),
                "metadata_mode": str(state.get("metadata_mode") or "auto"),
                "requested_archive_slugs": list(state.get("requested_archive_slugs") or []),
                "requested_metadata_fields": list(state.get("requested_metadata_fields") or []),
                "metadata_phase_used": bool(state.get("metadata_phase_used") or False),
                "document_phase_used": bool(state.get("document_phase_used") or False),
                "resolved_archive_slugs": list(state.get("resolved_archive_slugs") or []),
                "resolved_metadata_fields": list(state.get("resolved_metadata_fields") or []),
                "metadata_only_reason": str(state.get("metadata_only_reason") or ""),
                "answerability_route": str(state.get("answerability_route") or ""),
                "scope_origin": str(state.get("scope_origin") or ""),
                "scope_document_codes": list(state.get("scope_document_codes") or []),
                "scope_archive_slugs": list(state.get("scope_archive_slugs") or []),
                "resolved_scope_file_count": int(state.get("resolved_scope_file_count") or 0),
                "scope_resolution_ms": int(state.get("scope_resolution_ms") or 0),
                "ignored_inferred_scope": bool(state.get("ignored_inferred_scope") or False),
                "facts_used_count": int(state.get("facts_used_count") or 0),
                "file_group_ids": [int(item) for item in list(state.get("file_group_ids") or []) if int(item) > 0],
                "doc_shortlist_count": int(state.get("doc_shortlist_count") or 0),
                "text_candidates_count": int(state.get("text_candidates_count") or 0),
                "image_candidates_count": int(state.get("image_candidates_count") or 0),
                "page_text_count": int(state.get("page_text_count") or 0),
                "page_image_count": int(state.get("page_image_count") or 0),
                "oracle_text_count": int(state.get("oracle_text_count") or 0),
                "fused_pages_count": int(state.get("fused_pages_count") or 0),
                "rerank_count": int(state.get("rerank_count") or 0),
                "metadata_prefilter_count": int(state.get("metadata_prefilter_count") or 0),
                "metadata_prefilter_ms": int(state.get("metadata_prefilter_ms") or 0),
                "metadata_prefilter_applied": bool(state.get("metadata_prefilter_applied") or False),
                "query_embedding_ms": int(state.get("query_embedding_ms") or 0),
                "doc_search_ms": int(state.get("doc_search_ms") or 0),
                "page_search_ms": int(state.get("page_search_ms") or 0),
                "rerank_ms": int(state.get("rerank_ms") or 0),
                "retrieval_total_ms": int(state.get("retrieval_total_ms") or 0),
                "image_retrieval_enabled": bool(state.get("image_retrieval_enabled") or False),
                "retrieval_route": str(state.get("retrieval_route") or ""),
                "visual_checks_count": int(state.get("visual_checks_count") or 0),
                "evidence_recall_proxy": float(state.get("evidence_recall_proxy") or 0.0),
                "evidence_sources_count": int(state.get("evidence_sources_count") or len(evidence)),
                "cited_sources_count": int(state.get("cited_sources_count") or 0),
                "node_timings_ms": {
                    str(key): int(value)
                    for key, value in dict(state.get("node_timings_ms") or {}).items()
                },
            },
        )

    def _start_trace(
        self,
        *,
        trace_id: str,
        thread_id: str,
        user_id: int | None,
        conversation_id: int | None,
        question: str,
        metadata: dict[str, Any],
    ) -> None:
        if self._trace_repository is None:
            return
        self._trace_repository.start_run(
            trace_id=trace_id,
            thread_id=thread_id,
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
            run_metadata=metadata,
        )

    def _record_trace_step(self, *, trace_id: str, event: dict[str, Any]) -> None:
        if self._trace_repository is None:
            return
        state_patch = event.get("state_patch") if isinstance(event.get("state_patch"), dict) else {}
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        self._trace_repository.record_step(
            trace_id=trace_id,
            node_key=str(event.get("node_key") or ""),
            status=str(event.get("status") or "info"),
            payload=payload,
            state_patch=state_patch,
            duration_ms=int(event["duration_ms"]) if event.get("duration_ms") is not None else None,
            error=str(event.get("error") or "") or None,
        )

    def _finish_trace(
        self,
        *,
        trace_id: str,
        status: str,
        execution: QueryExecutionResult | None = None,
        error: str | None = None,
    ) -> None:
        if self._trace_repository is None:
            return
        telemetry = dict(execution.telemetry or {}) if execution is not None else {}
        self._trace_repository.finish_run(
            trace_id=trace_id,
            status=status,
            answerability_route=str(telemetry.get("answerability_route") or ""),
            answer_text=execution.answer.answer_text if execution is not None else "",
            cited_sources_count=int(telemetry.get("cited_sources_count") or 0),
            evidence_sources_count=int(telemetry.get("evidence_sources_count") or telemetry.get("evidence_count") or 0),
            run_metadata=telemetry,
            error=error,
        )

    @classmethod
    def _serialize_execution_result(cls, execution: QueryExecutionResult) -> dict[str, Any]:
        return {
            "thread_id": execution.thread_id,
            "strategy": execution.strategy,
            "selected_provider": execution.selected_provider,
            "answer_mode": execution.answer_mode,
            "visual_confirmation_used": execution.visual_confirmation_used,
            "analyzed_pages": list(execution.analyzed_pages),
            "confidence_notes": list(execution.confidence_notes),
            "ocr_vs_visual_discrepancies": list(execution.ocr_vs_visual_discrepancies),
            "answer": {
                "answer_text": execution.answer.answer_text,
                "executive_summary": execution.answer.executive_summary,
                "key_points": list(execution.answer.key_points),
                "obligations": list(execution.answer.obligations),
                "citation_source_numbers": list(execution.answer.citation_source_numbers),
                "model_used": execution.answer.model_used,
            },
            "evidence": [item.model_dump(mode="json") for item in execution.evidence],
            "telemetry": dict(execution.telemetry or {}),
        }

    @classmethod
    def _normalize_stream_part(
        cls,
        *,
        part: Any,
        thread_id: str,
        node_start_times: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        start_times = node_start_times if node_start_times is not None else {}

        def _duration_ms(start_ts: str | None, end_ts: str) -> int | None:
            if not start_ts:
                return None
            try:
                from datetime import datetime

                start_dt = datetime.fromisoformat(start_ts.replace("Z", "+00:00"))
                end_dt = datetime.fromisoformat(end_ts.replace("Z", "+00:00"))
                diff = end_dt - start_dt
                return max(0, int(diff.total_seconds() * 1000))
            except Exception:
                return None

        if not isinstance(part, dict):
            timestamp = cls._utc_now_iso()
            return [
                {
                    "event_type": "graph_event",
                    "thread_id": thread_id,
                    "timestamp": timestamp,
                    "langgraph_type": "unknown",
                    "node_key": "",
                    "status": "info",
                    "payload": cls._to_jsonable(part),
                }
            ]
        part_type = str(part.get("type") or "").strip().lower() or "unknown"
        payload = cls._to_jsonable(part.get("data"))
        events: list[dict[str, Any]] = []

        if part_type == "updates" and isinstance(payload, dict):
            for node_key, state_patch in payload.items():
                nk = str(node_key)
                evt: dict[str, Any] = {
                    "event_type": "node_update",
                    "thread_id": thread_id,
                    "timestamp": cls._utc_now_iso(),
                    "langgraph_type": part_type,
                    "node_key": nk,
                    "status": "completed",
                    "state_patch": state_patch if isinstance(state_patch, dict) else {},
                    "payload": state_patch,
                }
                events.append(evt)
            if events:
                return events

        if part_type == "tasks":
            task_items: list[Any]
            if isinstance(payload, list):
                task_items = payload
            else:
                task_items = [payload]
            for task in task_items:
                event_ts = cls._utc_now_iso()
                if isinstance(task, dict):
                    node_key = str(task.get("name") or task.get("node") or "")
                    has_error = bool(task.get("error"))
                    has_result = "result" in task or "error" in task
                    has_input = "input" in task
                    status = (
                        "failed"
                        if has_error
                        else ("started" if (has_input and not has_result) else "completed")
                    )
                else:
                    node_key = ""
                    status = "info"
                evt: dict[str, Any] = {
                    "event_type": "node_task",
                    "thread_id": thread_id,
                    "timestamp": event_ts,
                    "langgraph_type": part_type,
                    "node_key": node_key,
                    "status": status,
                    "payload": task,
                }
                if status == "started" and node_key:
                    start_times[node_key] = event_ts
                elif status in ("completed", "failed") and node_key:
                    start_ts = start_times.pop(node_key, None)
                    d = _duration_ms(start_ts, event_ts) if start_ts else None
                    if d is not None:
                        evt["duration_ms"] = d
                events.append(evt)
            if events:
                return events

        if part_type == "checkpoints":
            timestamp = cls._utc_now_iso()
            return [
                {
                    "event_type": "checkpoint",
                    "thread_id": thread_id,
                    "timestamp": timestamp,
                    "langgraph_type": part_type,
                    "node_key": "",
                    "status": "snapshot",
                    "payload": payload,
                }
            ]

        timestamp = cls._utc_now_iso()
        return [
            {
                "event_type": "graph_event",
                "thread_id": thread_id,
                "timestamp": timestamp,
                "langgraph_type": part_type,
                "node_key": "",
                "status": "info",
                "payload": payload,
            }
        ]

    def run(
        self,
        *,
        question: str,
        raw_question: str | None = None,
        file_ids: list[int] | None = None,
        allow_inferred_scope: bool = True,
        top_k: int = 5,
        candidate_k: int | None = None,
        min_pages_per_selected_doc: int = 0,
        summary_mode: str = "default",
        metadata_mode: str = "auto",
        archive_slugs: list[str] | None = None,
        metadata_fields: list[str] | None = None,
        chat_history: list[dict[str, str]] | None = None,
        conversation_id: int | None = None,
        user_id: int | None = None,
        thread_id: str | None = None,
        current_date: date | None = None,
        conversation_scope_file_ids: list[int] | None = None,
        conversation_scope_archive_slugs: list[str] | None = None,
        conversation_scope_metadata_fields: list[str] | None = None,
        conversation_scope_turn_index: int | None = None,
        conversation_scope_question_class: str | None = None,
    ) -> QueryExecutionResult:
        resolved_thread_id = self._resolve_thread_id(
            conversation_id=conversation_id,
            thread_id=thread_id,
        )
        trace_id = uuid.uuid4().hex
        input_state = self._build_graph_input(
            question=question,
            raw_question=raw_question,
            file_ids=file_ids,
            allow_inferred_scope=allow_inferred_scope,
            top_k=top_k,
            candidate_k=candidate_k,
            min_pages_per_selected_doc=min_pages_per_selected_doc,
            summary_mode=summary_mode,
            metadata_mode=metadata_mode,
            archive_slugs=archive_slugs,
            metadata_fields=metadata_fields,
            chat_history=chat_history,
            conversation_id=conversation_id,
            user_id=user_id,
            thread_id=resolved_thread_id,
            current_date=current_date,
            conversation_scope_file_ids=conversation_scope_file_ids,
            conversation_scope_archive_slugs=conversation_scope_archive_slugs,
            conversation_scope_metadata_fields=conversation_scope_metadata_fields,
            conversation_scope_turn_index=conversation_scope_turn_index,
            conversation_scope_question_class=conversation_scope_question_class,
        )
        config = {"configurable": {"thread_id": resolved_thread_id}}
        self._start_trace(
            trace_id=trace_id,
            thread_id=resolved_thread_id,
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
            metadata={
                "mode": "sync",
                "top_k": max(1, int(top_k)),
                "candidate_k": int(candidate_k) if candidate_k is not None else None,
                "summary_mode": str(summary_mode or "default"),
            },
        )
        try:
            state = self._graph.invoke(
                input_state,
                config,
            )
            if not isinstance(state, dict):
                raise RuntimeError("Graph execution returned an invalid state.")
            execution = self._state_to_execution_result(
                state=state,
                thread_id=resolved_thread_id,
            )
            execution.telemetry["trace_id"] = trace_id
            for node_key, duration_ms in dict(state.get("node_timings_ms") or {}).items():
                self._trace_repository.record_step(
                    trace_id=trace_id,
                    node_key=str(node_key),
                    status="completed",
                    payload={},
                    state_patch={"duration_ms": int(duration_ms)},
                    duration_ms=int(duration_ms),
                ) if self._trace_repository is not None else None
            self._finish_trace(trace_id=trace_id, status="completed", execution=execution)
            return execution
        except Exception as exc:
            self._finish_trace(trace_id=trace_id, status="failed", error=str(exc))
            raise

    def warmup(self) -> None:
        return None

    def get_graph_definition(self) -> dict[str, Any]:
        return {
            "nodes": [dict(item) for item in GRAPH_NODES],
            "edges": [dict(item) for item in GRAPH_EDGES],
            "start_node": "classify_intent",
            "end_node": "persist_turn",
        }

    def get_reasoning_stages(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "search": [dict(item) for item in SEARCH_REASONING_STAGES],
            "document": [dict(item) for item in DOCUMENT_REASONING_STAGES],
        }

    def stream_run(
        self,
        *,
        question: str,
        raw_question: str | None = None,
        file_ids: list[int] | None = None,
        allow_inferred_scope: bool = True,
        top_k: int = 5,
        candidate_k: int | None = None,
        min_pages_per_selected_doc: int = 0,
        summary_mode: str = "default",
        metadata_mode: str = "auto",
        archive_slugs: list[str] | None = None,
        metadata_fields: list[str] | None = None,
        chat_history: list[dict[str, str]] | None = None,
        conversation_id: int | None = None,
        user_id: int | None = None,
        thread_id: str | None = None,
        current_date: date | None = None,
        conversation_scope_file_ids: list[int] | None = None,
        conversation_scope_archive_slugs: list[str] | None = None,
        conversation_scope_metadata_fields: list[str] | None = None,
        conversation_scope_turn_index: int | None = None,
        conversation_scope_question_class: str | None = None,
    ) -> Iterator[dict[str, Any]]:
        resolved_thread_id = self._resolve_thread_id(
            conversation_id=conversation_id,
            thread_id=thread_id,
        )
        trace_id = uuid.uuid4().hex
        input_state = self._build_graph_input(
            question=question,
            raw_question=raw_question,
            file_ids=file_ids,
            allow_inferred_scope=allow_inferred_scope,
            top_k=top_k,
            candidate_k=candidate_k,
            min_pages_per_selected_doc=min_pages_per_selected_doc,
            summary_mode=summary_mode,
            metadata_mode=metadata_mode,
            archive_slugs=archive_slugs,
            metadata_fields=metadata_fields,
            chat_history=chat_history,
            conversation_id=conversation_id,
            user_id=user_id,
            thread_id=resolved_thread_id,
            current_date=current_date,
            conversation_scope_file_ids=conversation_scope_file_ids,
            conversation_scope_archive_slugs=conversation_scope_archive_slugs,
            conversation_scope_metadata_fields=conversation_scope_metadata_fields,
            conversation_scope_turn_index=conversation_scope_turn_index,
            conversation_scope_question_class=conversation_scope_question_class,
        )
        config = {"configurable": {"thread_id": resolved_thread_id}}

        run_started_ts = self._utc_now_iso()
        self._start_trace(
            trace_id=trace_id,
            thread_id=resolved_thread_id,
            user_id=user_id,
            conversation_id=conversation_id,
            question=question,
            metadata={
                "mode": "stream",
                "top_k": max(1, int(top_k)),
                "candidate_k": int(candidate_k) if candidate_k is not None else None,
                "summary_mode": str(summary_mode or "default"),
            },
        )
        yield {
            "event_type": "run_started",
            "thread_id": resolved_thread_id,
            "timestamp": run_started_ts,
            "langgraph_type": "run",
            "node_key": "classify_intent",
            "status": "started",
            "payload": {
                "question": question,
                "top_k": max(1, int(top_k)),
                "candidate_k": int(candidate_k) if candidate_k is not None else None,
                "min_pages_per_selected_doc": max(0, int(min_pages_per_selected_doc)),
                "summary_mode": str(summary_mode or "default"),
                "metadata_mode": str(metadata_mode or "auto"),
                "allow_inferred_scope": bool(allow_inferred_scope),
                "file_ids_count": len(list(file_ids or [])),
                "archive_slugs_count": len(list(archive_slugs or [])),
                "metadata_fields_count": len(list(metadata_fields or [])),
                "conversation_id": conversation_id,
                "current_date": current_date.isoformat() if isinstance(current_date, date) else None,
                "conversation_scope_file_ids_count": len(list(conversation_scope_file_ids or [])),
            },
        }

        accumulated_state: dict[str, Any] = dict(input_state)
        node_start_times: dict[str, str] = {"classify_intent": run_started_ts}
        try:
            for part in self._graph.stream(
                input_state,
                config,
                stream_mode=["updates", "tasks", "checkpoints"],
                version="v2",
            ):
                normalized_events = self._normalize_stream_part(
                    part=part,
                    thread_id=resolved_thread_id,
                    node_start_times=node_start_times,
                )
                for event in normalized_events:
                    self._record_trace_step(trace_id=trace_id, event=event)
                    patch = event.get("state_patch")
                    if isinstance(patch, dict):
                        accumulated_state.update(patch)
                    yield event

            final_state: dict[str, Any] = {}
            try:
                snapshot = self._graph.get_state(config)
                values = getattr(snapshot, "values", None)
                if isinstance(values, dict):
                    final_state = dict(values)
            except Exception:
                final_state = {}
            if not final_state:
                final_state = dict(accumulated_state)

            execution = self._state_to_execution_result(
                state=final_state,
                thread_id=resolved_thread_id,
            )
            execution.telemetry["trace_id"] = trace_id
            checkpoint(
                "qa_run_completed",
                tags={
                    "thread_id": resolved_thread_id,
                    "selected_docs_count": int(execution.telemetry.get("selected_docs_count") or 0),
                    "distinct_files_in_evidence": int(execution.telemetry.get("distinct_files_in_evidence") or 0),
                    "coverage_ratio": float(execution.telemetry.get("coverage_ratio") or 0.0),
                    "scope_origin": str(execution.telemetry.get("scope_origin") or ""),
                    "visual_checks_count": int(execution.telemetry.get("visual_checks_count") or 0),
                },
            )
            self._finish_trace(trace_id=trace_id, status="completed", execution=execution)
            yield {
                "event_type": "run_completed",
                "thread_id": resolved_thread_id,
                "timestamp": self._utc_now_iso(),
                "langgraph_type": "run",
                "node_key": "persist_turn",
                "status": "completed",
                "execution": self._serialize_execution_result(execution),
            }
        except Exception as exc:
            self._finish_trace(trace_id=trace_id, status="failed", error=str(exc))
            yield {
                "event_type": "run_failed",
                "thread_id": resolved_thread_id,
                "timestamp": self._utc_now_iso(),
                "langgraph_type": "run",
                "node_key": "",
                "status": "failed",
                "error": str(exc),
            }


def _load_attr(module_name: str, attr_name: str) -> Any:
    # Keep graph assembly dependencies out of the service module import path.
    return getattr(import_module(module_name), attr_name)


@lru_cache(maxsize=1)
def get_qa_graph_service() -> QAGraphService:
    get_settings = _load_attr("apps.backend.app.core.config", "get_settings")
    get_db_manager = _load_attr("apps.backend.app.core.session", "get_db_manager")
    AnalysisAgent = _load_attr("apps.backend.app.agent.agents", "AnalysisAgent")
    SupervisorAgent = _load_attr("apps.backend.app.agent.agents", "SupervisorAgent")
    SynthesisAgent = _load_attr("apps.backend.app.agent.agents", "SynthesisAgent")
    build_qa_graph = _load_attr("apps.backend.app.agent.document_graph", "build_qa_graph")
    OracleLangGraphCheckpointer = _load_attr(
        "apps.backend.app.agent.memory.checkpointer_oracle",
        "OracleLangGraphCheckpointer",
    )
    QAGraphNodes = _load_attr("apps.backend.app.agent.nodes", "QAGraphNodes")
    GraphIntentRouter = _load_attr("apps.backend.app.agent.router", "GraphIntentRouter")
    GraphSearchResponder = _load_attr("apps.backend.app.agent.router", "GraphSearchResponder")
    HybridAnswerTool = _load_attr(
        "apps.backend.app.agent.tools.hybrid_answer_tool",
        "HybridAnswerTool",
    )
    PageVisionTool = _load_attr("apps.backend.app.agent.tools.multimodal_tool", "PageVisionTool")
    OracleRetrievalTool = _load_attr(
        "apps.backend.app.agent.tools.oracle_retrieval_tool",
        "OracleRetrievalTool",
    )
    OCIGenerativeAIService = _load_attr(
        "apps.backend.app.integrations.generative_ai",
        "OCIGenerativeAIService",
    )
    EmbeddingService = _load_attr("apps.backend.app.rag.embedding_service", "EmbeddingService")
    QuestionFactResolver = _load_attr(
        "apps.backend.app.rag.facts_query_service",
        "QuestionFactResolver",
    )
    QuestionClassifier = _load_attr("apps.backend.app.rag.question_classifier", "QuestionClassifier")
    QuestionScopeResolver = _load_attr("apps.backend.app.rag.scope_resolver", "QuestionScopeResolver")
    RetrievalPipelineService = _load_attr(
        "apps.backend.app.rag.retrieval.query_service",
        "RetrievalPipelineService",
    )
    HybridLocalOnnxRerankService = _load_attr(
        "apps.backend.app.rag.reranker_service",
        "HybridLocalOnnxRerankService",
    )
    FileRepository = _load_attr("apps.backend.app.repositories.file_repository", "FileRepository")
    QATraceRepository = _load_attr(
        "apps.backend.app.repositories.qa_trace_repository",
        "QATraceRepository",
    )
    ConfigService = _load_attr(
        "apps.backend.app.services.runtime_config_service",
        "ConfigService",
    )

    settings = get_settings()
    db_manager = get_db_manager()
    config_service = ConfigService(db_manager)
    oci_provider = OCIGenerativeAIService(settings=settings, config_service=config_service)
    retrieval_pipeline_service = RetrievalPipelineService(
        db_manager=db_manager,
        embedding_service=EmbeddingService(settings),
        rerank_service=HybridLocalOnnxRerankService(settings),
    )
    retrieval_tool = OracleRetrievalTool(retrieval_pipeline_service=retrieval_pipeline_service)
    supervisor = SupervisorAgent()
    analysis = AnalysisAgent()
    synthesis = SynthesisAgent(
        settings=settings,
        config_service=config_service,
        oci_provider=oci_provider,
    )
    page_vision_tool = PageVisionTool(settings, config_service=config_service, oci_provider=oci_provider)
    hybrid_answer_tool = HybridAnswerTool(
        settings=settings,
        page_vision_tool=page_vision_tool,
        synthesis_agent=synthesis,
    )
    repository = FileRepository(db_manager)
    scope_resolver = QuestionScopeResolver(repository)
    question_classifier = QuestionClassifier()
    fact_resolver = QuestionFactResolver(
        repository.document_facts,
        file_repository=repository,
    )

    def resolve_assistant_name() -> str:
        try:
            value = config_service.get_value("app.agent_name", "").strip()
            if not value:
                value = config_service.get_value("app.name", "Nadia Assist").strip()
            return value or "Nadia Assist"
        except Exception:
            return "Nadia Assist"

    nodes = QAGraphNodes(
        intent_router=GraphIntentRouter(provider=oci_provider),
        casual_responder=GraphSearchResponder(
            provider=oci_provider,
            assistant_name_provider=resolve_assistant_name,
        ),
        supervisor=supervisor,
        scope_resolver=scope_resolver,
        question_classifier=question_classifier,
        fact_resolver=fact_resolver,
        retrieval_tool=retrieval_tool,
        analysis_agent=analysis,
        hybrid_answer_tool=hybrid_answer_tool,
        page_vision_tool=page_vision_tool,
        repository=repository,
    )
    checkpointer = OracleLangGraphCheckpointer(db_manager)
    graph = build_qa_graph(nodes=nodes, checkpointer=checkpointer)
    return QAGraphService(graph=graph, trace_repository=QATraceRepository(db_manager))
