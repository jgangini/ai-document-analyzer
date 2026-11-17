"""Agent graph nodes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from time import perf_counter
from typing import Any

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.agent.contracts import HybridAnswerResult, LLMResult, VisualInspectionResult
from apps.backend.app.agent.state import QAGraphState

_METADATA_DOCUMENT_MIN_CANDIDATE_K = 80
_METADATA_DOCUMENT_MIN_PAGES_PER_DOC = 2
_METADATA_DOCUMENT_COVERAGE_SCOPE_LIMIT = 24


@dataclass(frozen=True, slots=True)
class _RetrievalControls:
    candidate_k: int | None
    min_pages_per_selected_doc: int
    summary_mode: str
    coverage_boosted: bool = False


def _empty_visual_result() -> VisualInspectionResult:
    return VisualInspectionResult(
        used=False,
        analyzed_pages=[],
        visual_context="",
        confidence_notes=[],
        ocr_vs_visual_discrepancies=[],
    )


def _merge_node_timing(state: QAGraphState, *, node_key: str, started_at: float) -> dict[str, int]:
    timings = {
        str(key): int(value)
        for key, value in dict(state.get("node_timings_ms") or {}).items()
    }
    timings[node_key] = max(0, int((perf_counter() - started_at) * 1000))
    return timings


def _resolve_answerability_route(
    *,
    answerability_route: str,
    metadata_phase_used: bool,
    document_phase_required: bool,
    answer_override: str | None,
) -> str:
    explicit_route = str(answerability_route or "").strip()
    if explicit_route:
        return explicit_route
    if metadata_phase_used and document_phase_required:
        return "hybrid"
    if metadata_phase_used and answer_override:
        return "metadata"
    if document_phase_required:
        return "documents"
    return ""


def _build_retrieval_question(
    *,
    question: str,
    answerability_route: str = "",
) -> str:
    safe_question = str(question or "").strip()
    if str(answerability_route or "").strip() == "hybrid":
        return (
            f"{safe_question}\n\n"
            "Busqueda documental ampliada: recuperar evidencia directa o indirecta sobre la pregunta, "
            "incluyendo equivalentes, sinonimos, parafrasis, condiciones, excepciones, consecuencias, "
            "obligaciones, restricciones, montos, fechas, plazos, estados, causas, efectos, "
            "negaciones explicitas y ausencia de informacion relevante."
        )
    return safe_question


def _resolve_retrieval_controls(state: QAGraphState) -> _RetrievalControls:
    candidate_k = int(state.get("candidate_k")) if state.get("candidate_k") is not None else None
    min_pages_per_selected_doc = max(0, int(state.get("min_pages_per_selected_doc") or 0))
    summary_mode = str(state.get("summary_mode") or "default").strip() or "default"
    answerability_route = str(state.get("answerability_route") or "").strip()
    conversation_scoped = str(state.get("scope_origin") or "").strip().lower() == "conversation"
    if answerability_route != "hybrid" and not conversation_scoped:
        return _RetrievalControls(
            candidate_k=candidate_k,
            min_pages_per_selected_doc=min_pages_per_selected_doc,
            summary_mode=summary_mode,
        )

    scoped_file_ids = [int(file_id) for file_id in list(state.get("file_ids") or []) if int(file_id) > 0]
    scoped_archive_slugs = [
        str(item).strip()
        for item in list(
            state.get("resolved_archive_slugs")
            or state.get("requested_archive_slugs")
            or state.get("scope_archive_slugs")
            or []
        )
        if str(item).strip()
    ]
    scoped_item_count = len(scoped_file_ids) or len(scoped_archive_slugs)
    boosted_candidate_k = max(candidate_k or 0, _METADATA_DOCUMENT_MIN_CANDIDATE_K) or None
    if scoped_item_count <= 0 or scoped_item_count > _METADATA_DOCUMENT_COVERAGE_SCOPE_LIMIT:
        return _RetrievalControls(
            candidate_k=boosted_candidate_k,
            min_pages_per_selected_doc=min_pages_per_selected_doc,
            summary_mode=summary_mode,
            coverage_boosted=boosted_candidate_k != candidate_k,
        )

    boosted_min_pages = max(min_pages_per_selected_doc, _METADATA_DOCUMENT_MIN_PAGES_PER_DOC)
    boosted_summary_mode = "per_document" if summary_mode == "default" else summary_mode
    return _RetrievalControls(
        candidate_k=boosted_candidate_k,
        min_pages_per_selected_doc=boosted_min_pages,
        summary_mode=boosted_summary_mode,
        coverage_boosted=(
            boosted_candidate_k != candidate_k
            or boosted_min_pages != min_pages_per_selected_doc
            or boosted_summary_mode != summary_mode
        ),
    )


@dataclass(slots=True)
class QAGraphNodes:
    intent_router: Any
    casual_responder: Any
    supervisor: Any
    scope_resolver: Any
    question_classifier: Any
    fact_resolver: Any
    retrieval_tool: Any
    analysis_agent: Any
    hybrid_answer_tool: Any
    page_vision_tool: Any
    repository: Any

    @staticmethod
    def _build_conversation_scoped_question(
        *,
        question: str,
        archive_slugs: list[str],
        chat_history: list[dict[str, str]] | None = None,
    ) -> str:
        safe_question = str(question or "").strip()
        safe_archive_slugs = [str(item).strip() for item in list(archive_slugs or []) if str(item).strip()]
        history_items = list(chat_history or [])[-8:]
        previous_user = ""
        previous_assistant = ""
        for item in reversed(history_items):
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role == "assistant" and not previous_assistant:
                previous_assistant = content[:1200]
            elif role == "user" and not previous_user:
                previous_user = content[:600]
            if previous_user and previous_assistant:
                break
        context_lines = [f"Follow-up question: {safe_question}"]
        if previous_user:
            context_lines.append(f"Previous user question: {previous_user}")
        if previous_assistant:
            context_lines.append(f"Previous assistant answer excerpt: {previous_assistant}")
        if not safe_archive_slugs:
            return "\n".join(context_lines)
        rendered_scope = ", ".join(safe_archive_slugs[:24])
        if len(safe_archive_slugs) > 24:
            rendered_scope += ", ..."
        context_lines.append(f"Scoped archives inherited from the previous turn: {rendered_scope}.")
        return "\n".join(context_lines)

    def classify_intent(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        has_explicit_selector_scope = bool(
            state.get("metadata_mode") == "metadata_first"
            or list(state.get("requested_archive_slugs") or [])
            or list(state.get("requested_metadata_fields") or [])
        )
        route = "document" if has_explicit_selector_scope else self.intent_router.classify(
            question=state["question"],
            file_ids=list(state.get("requested_file_ids") or state.get("file_ids") or []),
            chat_history=list(state.get("chat_history") or []),
        )
        return {
            "route": route,
            "node_timings_ms": _merge_node_timing(state, node_key="classify_intent", started_at=started_at),
        }

    def search_response(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        answer = self.casual_responder.respond(
            question=state["question"],
            chat_history=list(state.get("chat_history") or []),
        )
        return {
            "strategy": "search",
            "selected_provider": "supervisor-search",
            "evidence": [],
            "answer": answer,
            "answer_mode": "small_talk",
            "visual_confirmation_used": False,
            "analyzed_pages": [],
            "confidence_notes": ["Ruta Supervisor: SEARCH."],
            "ocr_vs_visual_discrepancies": [],
            "visual_result": _empty_visual_result(),
            "question_class": "search",
            "question_class_rationale": "casual-search-route",
            "scope_archive_slugs": [],
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
            "retrieval_route": "search",
            "visual_checks_count": 0,
            "facts_used_count": 0,
            "metadata_phase_used": False,
            "document_phase_used": False,
            "resolved_archive_slugs": [],
            "resolved_metadata_fields": [],
            "metadata_only_reason": "",
            "answerability_route": "",
            "evidence_recall_proxy": 0.0,
            "node_timings_ms": _merge_node_timing(state, node_key="search_response", started_at=started_at),
        }

    def resolve_scope(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        original_question = str(state.get("original_question") or state["question"])
        resolution = self.scope_resolver.resolve(
            question=original_question,
            user_id=int(state.get("user_id") or 0),
            file_ids=list(state.get("requested_file_ids") or state.get("file_ids") or []),
            archive_slugs=list(state.get("requested_archive_slugs") or []),
            allow_inferred_scope=bool(state.get("allow_inferred_scope", True)),
            conversation_file_ids=list(state.get("conversation_scope_file_ids") or []),
            conversation_archive_slugs=list(state.get("conversation_scope_archive_slugs") or []),
        )
        resolved_file_ids = list(resolution.file_ids)
        conversation_scope_applied = str(resolution.scope_origin or "") == "conversation"
        effective_question = original_question
        if conversation_scope_applied and resolution.scope_archive_slugs:
            effective_question = self._build_conversation_scoped_question(
                question=original_question,
                archive_slugs=list(resolution.scope_archive_slugs),
                chat_history=list(state.get("chat_history") or []),
            )
        return {
            "file_ids": resolved_file_ids,
            "effective_question": effective_question,
            "scope_origin": resolution.scope_origin,
            "scope_document_codes": list(resolution.scope_document_codes),
            "scope_archive_slugs": list(resolution.scope_archive_slugs),
            "resolved_scope_file_count": int(resolution.resolved_scope_file_count),
            "scope_resolution_ms": int(resolution.scope_resolution_ms),
            "ignored_inferred_scope": bool(resolution.ignored_inferred_scope),
            "conversation_scope_applied": conversation_scope_applied,
            "resolved_archive_slugs": list(resolution.scope_archive_slugs or state.get("resolved_archive_slugs") or []),
            "selected_docs_count": len(resolved_file_ids),
            "node_timings_ms": _merge_node_timing(state, node_key="resolve_scope", started_at=started_at),
        }

    def classify_question(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        classification = self.question_classifier.classify(
            question=str(state.get("original_question") or state["question"]),
        )
        return {
            "question_class": classification.question_class,
            "question_class_rationale": classification.rationale,
            "node_timings_ms": _merge_node_timing(state, node_key="classify_question", started_at=started_at),
        }

    def resolve_facts(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        current_date = state.get("current_date")
        if current_date is not None and not isinstance(current_date, date):
            current_date = None
        prior_file_ids = [int(file_id) for file_id in list(state.get("file_ids") or []) if int(file_id) > 0]
        question_class = str(state.get("question_class") or "extractive")
        requested_metadata_fields = list(state.get("requested_metadata_fields") or [])
        if (
            state.get("conversation_scope_applied")
            and not requested_metadata_fields
            and question_class not in {"metadata_comparison", "analytics"}
            and str(state.get("metadata_mode") or "auto").strip().lower() != "metadata_first"
        ):
            return {
                "file_ids": prior_file_ids,
                "selected_docs_count": len(prior_file_ids),
                "fact_context_text": "",
                "answer_override": None,
                "facts_used_count": 0,
                "file_group_ids": [],
                "metadata_phase_used": False,
                "resolved_archive_slugs": list(state.get("scope_archive_slugs") or []),
                "resolved_metadata_fields": [],
                "metadata_only_reason": "",
                "answerability_route": "documents",
                "confidence_notes": list(state.get("confidence_notes") or [])
                + ["Conversation scope was reused for document retrieval."],
                "node_timings_ms": _merge_node_timing(state, node_key="resolve_facts", started_at=started_at),
            }
        carry_conversation_metadata_fields = bool(
            state.get("conversation_scope_metadata_fields")
            and question_class in {"metadata_comparison", "analytics"}
        )
        resolution = self.fact_resolver.resolve(
            question_class=question_class,
            question=str(state.get("original_question") or state["question"]),
            user_id=int(state.get("user_id") or 0),
            file_ids=prior_file_ids,
            metadata_mode=str(state.get("metadata_mode") or "auto"),
            archive_slugs=list(state.get("requested_archive_slugs") or state.get("scope_archive_slugs") or []),
            metadata_fields=list(
                requested_metadata_fields
                or (state.get("conversation_scope_metadata_fields") if carry_conversation_metadata_fields else [])
                or []
            ),
            reference_date=current_date,
        )
        resolved_file_ids = (
            [int(file_id) for file_id in list(resolution.narrowed_file_ids) if int(file_id) > 0]
            if resolution.narrowed_file_ids
            else prior_file_ids
        )
        prior_notes = list(state.get("confidence_notes") or [])
        merged_notes = prior_notes + [
            note for note in resolution.confidence_notes if note not in prior_notes
        ]
        answerability_route = _resolve_answerability_route(
            answerability_route=str(resolution.answerability_route or ""),
            metadata_phase_used=bool(resolution.metadata_phase_used),
            document_phase_required=bool(resolution.document_phase_required),
            answer_override=resolution.answer_override,
        )
        return {
            "file_ids": resolved_file_ids,
            "selected_docs_count": len(resolved_file_ids),
            "fact_context_text": resolution.fact_context_text,
            "answer_override": resolution.answer_override,
            "facts_used_count": int(resolution.facts_used_count),
            "file_group_ids": [int(item) for item in list(resolution.file_group_ids or []) if int(item) > 0],
            "metadata_phase_used": bool(resolution.metadata_phase_used),
            "resolved_archive_slugs": list(
                resolution.resolved_archive_slugs
                or state.get("resolved_archive_slugs")
                or state.get("scope_archive_slugs")
                or []
            ),
            "resolved_metadata_fields": list(resolution.resolved_metadata_fields or []),
            "metadata_only_reason": str(resolution.metadata_only_reason or ""),
            "answerability_route": answerability_route,
            "confidence_notes": merged_notes,
            "node_timings_ms": _merge_node_timing(state, node_key="resolve_facts", started_at=started_at),
        }

    def decide_answerability(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        raw_route = str(state.get("answerability_route") or "").strip().lower()
        has_metadata = bool(state.get("metadata_phase_used") or state.get("fact_context_text"))
        has_answer_override = bool(str(state.get("answer_override") or "").strip())
        route = raw_route if raw_route in {"metadata", "hybrid", "documents"} else ""
        if not route:
            if has_metadata and has_answer_override:
                route = "metadata"
            elif has_metadata:
                route = "hybrid"
            else:
                route = "documents"

        answer_override = str(state.get("answer_override") or "").strip() or None
        strategy = str(state.get("strategy") or "").strip()
        retrieval_route = str(state.get("retrieval_route") or "").strip()
        document_phase_used = bool(state.get("document_phase_used") or False)
        if route == "metadata":
            strategy = strategy or "facts-first"
            retrieval_route = retrieval_route or str(state.get("metadata_only_reason") or "metadata")
            document_phase_used = False
        else:
            answer_override = None
            retrieval_route = retrieval_route or route

        return {
            "answerability_route": route,
            "answer_override": answer_override,
            "strategy": strategy,
            "retrieval_route": retrieval_route,
            "document_phase_used": document_phase_used,
            "evidence": [] if route == "metadata" else list(state.get("evidence") or []),
            "analyzed_pages": [] if route == "metadata" else list(state.get("analyzed_pages") or []),
            "visual_result": _empty_visual_result() if route == "metadata" else state.get("visual_result"),
            "node_timings_ms": _merge_node_timing(state, node_key="decide_answerability", started_at=started_at),
        }

    def retrieve_candidates(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        retrieval_question = _build_retrieval_question(
            question=str(state.get("effective_question") or state["question"]).strip(),
            answerability_route=str(state.get("answerability_route") or ""),
        )
        retrieval_controls = _resolve_retrieval_controls(state)
        plan = self.supervisor.create_plan(
            question=retrieval_question,
            requested_top_k=int(state["top_k"]),
            question_class=str(state.get("question_class") or "extractive"),
        )
        retrieval_result = self.retrieval_tool.retrieve(
            question=retrieval_question,
            user_id=int(state.get("user_id") or 0),
            file_ids=list(state.get("file_ids") or []),
            archive_slugs=list(
                state.get("resolved_archive_slugs")
                or state.get("requested_archive_slugs")
                or state.get("scope_archive_slugs")
                or []
            ),
            top_k=plan.top_k,
            candidate_k=retrieval_controls.candidate_k,
            min_pages_per_selected_doc=retrieval_controls.min_pages_per_selected_doc,
            summary_mode=retrieval_controls.summary_mode,
            question_class=str(state.get("question_class") or "extractive"),
            scope_origin=str(state.get("scope_origin") or "global"),
        )
        confidence_notes = list(state.get("confidence_notes") or [])
        if retrieval_controls.coverage_boosted:
            coverage_note = (
                "Hybrid route expanded generic per-document retrieval coverage "
                "within the resolved metadata scope."
            )
            if coverage_note not in confidence_notes:
                confidence_notes.append(coverage_note)
        return {
            "strategy": plan.strategy,
            "selected_provider": plan.selected_provider,
            "evidence": list(retrieval_result.evidence),
            "candidate_k": retrieval_controls.candidate_k,
            "min_pages_per_selected_doc": retrieval_controls.min_pages_per_selected_doc,
            "summary_mode": retrieval_controls.summary_mode,
            "scope_origin": str(
                retrieval_result.telemetry.get("effective_scope_origin")
                or state.get("scope_origin")
                or "global"
            ),
            "doc_shortlist_count": int(retrieval_result.telemetry.get("doc_shortlist_count") or 0),
            "text_candidates_count": int(retrieval_result.telemetry.get("text_candidates_count") or 0),
            "image_candidates_count": int(retrieval_result.telemetry.get("image_candidates_count") or 0),
            "page_text_count": int(retrieval_result.telemetry.get("page_text_count") or 0),
            "page_image_count": int(retrieval_result.telemetry.get("page_image_count") or 0),
            "oracle_text_count": int(retrieval_result.telemetry.get("oracle_text_count") or 0),
            "fused_pages_count": int(retrieval_result.telemetry.get("fused_pages_count") or 0),
            "rerank_count": int(retrieval_result.telemetry.get("rerank_count") or 0),
            "metadata_prefilter_count": int(retrieval_result.telemetry.get("metadata_prefilter_count") or 0),
            "metadata_prefilter_ms": int(retrieval_result.telemetry.get("metadata_prefilter_ms") or 0),
            "metadata_prefilter_applied": bool(
                retrieval_result.telemetry.get("metadata_prefilter_applied") or False
            ),
            "full_document_coverage_requested": bool(
                retrieval_result.telemetry.get("full_document_coverage_requested") or False
            ),
            "full_document_page_limit": int(retrieval_result.telemetry.get("full_document_page_limit") or 0),
            "query_embedding_ms": int(retrieval_result.telemetry.get("query_embedding_ms") or 0),
            "doc_search_ms": int(retrieval_result.telemetry.get("doc_search_ms") or 0),
            "page_search_ms": int(retrieval_result.telemetry.get("page_search_ms") or 0),
            "rerank_ms": int(retrieval_result.telemetry.get("rerank_ms") or 0),
            "retrieval_total_ms": int(retrieval_result.telemetry.get("retrieval_total_ms") or 0),
            "image_retrieval_enabled": bool(
                retrieval_result.telemetry.get("image_retrieval_enabled") or False
            ),
            "retrieval_route": str(retrieval_result.telemetry.get("retrieval_route") or "global_semantic"),
            "evidence_recall_proxy": float(retrieval_result.telemetry.get("evidence_recall_proxy") or 0.0),
            "document_phase_used": True,
            "confidence_notes": confidence_notes,
            "node_timings_ms": _merge_node_timing(state, node_key="retrieve_candidates", started_at=started_at),
        }

    def fuse_page_evidence(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        analyzed = self.analysis_agent.run(evidence=list(state.get("evidence") or []))
        distinct_files = len({int(item.file_id) for item in analyzed if int(item.file_id) > 0})
        scope_size = max(0, int(state.get("resolved_scope_file_count") or len(list(state.get("file_ids") or []))))
        coverage_ratio = float(distinct_files / scope_size) if scope_size > 0 else 0.0
        notes = list(state.get("confidence_notes") or [])
        if analyzed:
            notes.append(
                f"Retrieval fusion: {len(analyzed)} pages in the shortlist, {distinct_files} distinct documents."
            )
        elif state.get("answer_override"):
            notes.append("Facts resolver returned a deterministic answer without additional retrieval.")
        return {
            "evidence": analyzed,
            "distinct_files_in_evidence": distinct_files,
            "coverage_ratio": coverage_ratio,
            "confidence_notes": notes,
            "node_timings_ms": _merge_node_timing(state, node_key="fuse_page_evidence", started_at=started_at),
        }

    def maybe_verify_visual(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        visual_targets = [
            item
            for item in list(state.get("evidence") or [])
            if bool(getattr(item, "needs_visual_check", False))
        ]
        if not visual_targets:
            return {
                "visual_result": _empty_visual_result(),
                "visual_checks_count": 0,
                "node_timings_ms": _merge_node_timing(state, node_key="maybe_verify_visual", started_at=started_at),
            }
        visual_result = self.page_vision_tool.analyze(
            question=str(state.get("original_question") or state["question"]),
            evidence=visual_targets,
            require_visual=True,
        )
        return {
            "visual_result": visual_result,
            "visual_checks_count": len(list(visual_result.analyzed_pages or [])),
            "node_timings_ms": _merge_node_timing(state, node_key="maybe_verify_visual", started_at=started_at),
        }

    def synthesize_document_answer(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        visual_result = state.get("visual_result")
        if not isinstance(visual_result, VisualInspectionResult):
            visual_result = _empty_visual_result()
        hybrid_answer: HybridAnswerResult = self.hybrid_answer_tool.answer(
            question=str(
                state.get("effective_question")
                if state.get("conversation_scope_applied")
                else state.get("original_question")
                or state["question"]
            ),
            evidence=list(state.get("evidence") or []),
            strategy=str(state.get("strategy") or "fast-grounded"),
            visual_result=visual_result,
            summary_mode=str(state.get("summary_mode") or "default"),
            selected_docs_count=max(0, int(state.get("selected_docs_count") or len(list(state.get("file_ids") or [])))),
            question_class=str(state.get("question_class") or "extractive"),
            fact_context_text=str(state.get("fact_context_text") or ""),
            answer_override=(str(state.get("answer_override") or "").strip() or None),
        )
        prior_notes = list(state.get("confidence_notes") or [])
        merged_notes = prior_notes + [note for note in hybrid_answer.confidence_notes if note not in prior_notes]
        return {
            "hybrid_answer": hybrid_answer,
            "answer": hybrid_answer.llm_result,
            "answer_mode": hybrid_answer.answer_mode,
            "visual_confirmation_used": hybrid_answer.visual_confirmation_used,
            "analyzed_pages": hybrid_answer.analyzed_pages,
            "confidence_notes": merged_notes,
            "ocr_vs_visual_discrepancies": hybrid_answer.ocr_vs_visual_discrepancies,
            "node_timings_ms": _merge_node_timing(state, node_key="synthesize_document_answer", started_at=started_at),
        }

    def persist_turn(self, state: QAGraphState) -> dict[str, Any]:
        started_at = perf_counter()
        answer = state.get("answer")
        if answer is None:
            return {}
        question = state["question"]
        raw_question = str(state.get("raw_question") or question)
        file_ids = list(state.get("file_ids") or [])
        requested_file_ids = list(state.get("requested_file_ids") or [])
        evidence = list(state.get("evidence") or [])
        def build_source_metadata(item: EvidenceItem, *, include_snippet: bool = False) -> dict[str, object]:
            payload: dict[str, object] = {
                "source_number": int(item.source_number),
                "file_id": int(item.file_id),
                "file_name": str(item.file_name),
                "page_number": int(item.page_number),
                "object_name_page": str(item.object_name_page or ""),
            }
            if include_snippet:
                payload["snippet"] = str(item.summary_text or "")[:500]
            return payload

        evidence_sources = [
            build_source_metadata(item)
            for item in evidence
        ]
        selected_citations = sorted(
            {int(value) for value in list(answer.citation_source_numbers or []) if int(value) > 0}
        )
        selected_citations_set = set(selected_citations)
        cited_sources = [
            build_source_metadata(item, include_snippet=True)
            for item in evidence
            if int(item.source_number) in selected_citations_set
        ]
        distinct_files = sorted({int(item.file_id) for item in evidence if int(item.file_id) > 0})
        scope_file_ids = sorted({int(file_id) for file_id in file_ids if int(file_id) > 0})
        scope_file_id = scope_file_ids[0] if len(scope_file_ids) == 1 else None
        retrieval_metadata = {
            "raw_question": raw_question,
            "cleaned_question": question,
            "requested_file_ids": requested_file_ids,
            "metadata_mode": str(state.get("metadata_mode") or "auto"),
            "requested_archive_slugs": list(state.get("requested_archive_slugs") or []),
            "requested_metadata_fields": list(state.get("requested_metadata_fields") or []),
            "scope_file_ids": scope_file_ids,
            "scope_file_id": scope_file_id,
            "scope_origin": str(state.get("scope_origin") or ""),
            "scope_document_codes": list(state.get("scope_document_codes") or []),
            "scope_archive_slugs": list(state.get("scope_archive_slugs") or []),
            "resolved_archive_slugs": list(state.get("resolved_archive_slugs") or []),
            "resolved_metadata_fields": list(state.get("resolved_metadata_fields") or []),
            "metadata_phase_used": bool(state.get("metadata_phase_used") or False),
            "document_phase_used": bool(state.get("document_phase_used") or False),
            "metadata_only_reason": str(state.get("metadata_only_reason") or ""),
            "answerability_route": str(state.get("answerability_route") or ""),
            "conversation_scope_file_ids": [
                int(item)
                for item in list(state.get("conversation_scope_file_ids") or [])
                if int(item) > 0
            ],
            "conversation_scope_archive_slugs": list(state.get("conversation_scope_archive_slugs") or []),
            "conversation_scope_metadata_fields": list(
                state.get("conversation_scope_metadata_fields") or []
            ),
            "conversation_scope_turn_index": int(state.get("conversation_scope_turn_index") or 0),
            "conversation_scope_question_class": str(state.get("conversation_scope_question_class") or ""),
            "conversation_scope_applied": bool(state.get("conversation_scope_applied") or False),
            "resolved_scope_file_count": int(state.get("resolved_scope_file_count") or len(scope_file_ids)),
            "scope_resolution_ms": int(state.get("scope_resolution_ms") or 0),
            "ignored_inferred_scope": bool(state.get("ignored_inferred_scope") or False),
            "question_class": str(state.get("question_class") or ""),
            "question_class_rationale": str(state.get("question_class_rationale") or ""),
            "facts_used_count": int(state.get("facts_used_count") or 0),
            "file_group_ids": [int(item) for item in list(state.get("file_group_ids") or []) if int(item) > 0],
            "fact_context_text": str(state.get("fact_context_text") or ""),
            "answer_override_used": bool(state.get("answer_override") or False),
            "current_date": (
                state.get("current_date").isoformat()
                if isinstance(state.get("current_date"), date)
                else None
            ),
            "strategy": state.get("strategy") or "",
            "selected_provider": state.get("selected_provider") or "",
            "top_k": int(state.get("top_k") or 5),
            "candidate_k": int(state.get("candidate_k") or 0),
            "min_pages_per_selected_doc": int(state.get("min_pages_per_selected_doc") or 0),
            "evidence_count": len(evidence),
            "distinct_files_in_evidence": len(distinct_files),
            "coverage_ratio": float(state.get("coverage_ratio") or 0.0),
            "summary_mode": str(state.get("summary_mode") or "default"),
            "selected_docs_count": int(state.get("selected_docs_count") or len(scope_file_ids)),
            "answer_mode": state.get("answer_mode") or "",
            "visual_confirmation_used": bool(state.get("visual_confirmation_used") or False),
            "analyzed_pages": list(state.get("analyzed_pages") or []),
            "confidence_notes": list(state.get("confidence_notes") or []),
            "ocr_vs_visual_discrepancies": list(state.get("ocr_vs_visual_discrepancies") or []),
            "graph_route": state.get("route") or "",
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
            "full_document_coverage_requested": bool(state.get("full_document_coverage_requested") or False),
            "full_document_page_limit": int(state.get("full_document_page_limit") or 0),
            "query_embedding_ms": int(state.get("query_embedding_ms") or 0),
            "doc_search_ms": int(state.get("doc_search_ms") or 0),
            "page_search_ms": int(state.get("page_search_ms") or 0),
            "rerank_ms": int(state.get("rerank_ms") or 0),
            "retrieval_total_ms": int(state.get("retrieval_total_ms") or 0),
            "image_retrieval_enabled": bool(state.get("image_retrieval_enabled") or False),
            "retrieval_route": str(state.get("retrieval_route") or ""),
            "visual_checks_count": int(state.get("visual_checks_count") or 0),
            "evidence_recall_proxy": float(state.get("evidence_recall_proxy") or 0.0),
            "node_timings_ms": {
                str(key): int(value)
                for key, value in dict(state.get("node_timings_ms") or {}).items()
            },
            "evidence_sources": evidence_sources,
            "cited_sources": cited_sources,
            "selected_citations": selected_citations,
            "evidence_sources_count": len(evidence_sources),
            "cited_sources_count": len(cited_sources),
        }
        user_id = int(state.get("user_id") or 0)
        conversation_id = state.get("conversation_id")
        self.repository.save_qa_session(
            user_id=user_id,
            file_id=file_ids[0] if len(file_ids) == 1 else None,
            conversation_id=int(conversation_id) if conversation_id is not None else None,
            question=raw_question,
            retrieval_metadata=retrieval_metadata,
            answer=answer.answer_text,
            model_used=answer.model_used,
        )
        return {
            "evidence_sources_count": len(evidence_sources),
            "cited_sources_count": len(cited_sources),
            "node_timings_ms": _merge_node_timing(state, node_key="persist_turn", started_at=started_at),
        }
