"""Local improvement loop routes for QA traces, evaluations, and feedback."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from apps.backend.app.agent.service import get_qa_graph_service
from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.security import get_current_user
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.repositories.qa_trace_repository import QATraceRepository


router = APIRouter(
    prefix="/improvement",
    tags=["improvement"],
    dependencies=[Depends(require_setup_completed)],
)


class FeedbackEventRequest(BaseModel):
    event_type: str = Field(default="", max_length=64)
    value: str = Field(default="", max_length=64)
    conversation_id: int | None = Field(default=None, ge=1)
    trace_id: str | None = Field(default=None, max_length=64)
    assistant_message_id: str = Field(default="", max_length=128)
    user_prompt: str = Field(default="")
    assistant_answer: str = Field(default="")
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvalCaseRequest(BaseModel):
    name: str = Field(default="", max_length=255)
    category: str = Field(default="manual", max_length=64)
    question: str = Field(default="")
    expected: dict[str, Any] = Field(default_factory=dict)
    source: str = Field(default="manual", max_length=255)


class EvalRunRequest(BaseModel):
    name: str = Field(default="", max_length=255)
    case_ids: list[int] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)


def _repository() -> QATraceRepository:
    return QATraceRepository(get_db_manager())


def _require_user_id(current_user: dict) -> int:
    user_id = current_user.get("user_id")
    if user_id is None:
        raise HTTPException(status_code=401, detail="Unauthorized")
    try:
        return int(user_id)
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Unauthorized")


def _user_filter(current_user: dict) -> int | None:
    user_id = _require_user_id(current_user)
    try:
        group_id = int(current_user.get("group_id"))
    except (TypeError, ValueError):
        group_id = -1
    return None if group_id == 0 else user_id


def _text_terms(value: Any) -> list[str]:
    if isinstance(value, str):
        raw_items = [value]
    elif isinstance(value, list):
        raw_items = value
    else:
        raw_items = []
    terms: list[str] = []
    for raw_item in raw_items:
        term = str(raw_item or "").strip().casefold()
        if term:
            terms.append(term)
    return terms


def _score_eval_result(*, answer: str, telemetry: dict[str, Any], expected: dict[str, Any]) -> tuple[str, float, dict[str, Any]]:
    answer_text = str(answer or "").strip()
    answer_normalized = answer_text.casefold()
    cited_sources_count = int(telemetry.get("cited_sources_count") or 0)
    requires_citations = bool(expected.get("requires_citations", True))
    try:
        minimum_citations = max(0, int(expected.get("minimum_citations", 1 if requires_citations else 0)))
    except (TypeError, ValueError):
        minimum_citations = 1 if requires_citations else 0
    required_terms = _text_terms(expected.get("must_include_terms"))
    blocked_terms = _text_terms(expected.get("must_not_include_terms"))

    answer_score = 0.25 if len(answer_text) >= 20 else 0.0
    citation_score = 0.35
    if requires_citations:
        citation_score = 0.35 if cited_sources_count >= minimum_citations else 0.0
    required_score = 0.25
    if required_terms:
        matched_required = [term for term in required_terms if term in answer_normalized]
        required_score = 0.25 * (len(matched_required) / len(required_terms))
    blocked_hits = [term for term in blocked_terms if term in answer_normalized]
    blocked_score = 0.15 if not blocked_hits else 0.0
    score = round(answer_score + citation_score + required_score + blocked_score, 4)
    status = "passed" if score >= float(expected.get("pass_threshold") or 0.8) else "review"
    details = {
        "answer_length": len(answer_text),
        "cited_sources_count": cited_sources_count,
        "minimum_citations": minimum_citations,
        "requires_citations": requires_citations,
        "required_terms": required_terms,
        "blocked_terms": blocked_terms,
        "blocked_hits": blocked_hits,
        "answerability_route": str(telemetry.get("answerability_route") or ""),
    }
    return status, score, details


def _positive_ints(value: Any) -> list[int]:
    if not isinstance(value, list):
        return []
    normalized: list[int] = []
    for raw_item in value:
        try:
            parsed = int(raw_item)
        except (TypeError, ValueError):
            continue
        if parsed > 0:
            normalized.append(parsed)
    return normalized


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item or "").strip()]


@router.get("/overview")
def get_improvement_overview(current_user: dict = Depends(get_current_user)) -> dict[str, Any]:
    return _repository().get_overview(user_id=_user_filter(current_user))


@router.get("/traces")
def list_trace_runs(
    limit: int = Query(default=25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    return {"items": _repository().list_trace_runs(user_id=_user_filter(current_user), limit=limit)}


@router.get("/traces/{trace_id}/steps")
def list_trace_steps(
    trace_id: str,
    limit: int = Query(default=200, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    return {
        "items": _repository().get_trace_steps(
            trace_id=trace_id,
            user_id=_user_filter(current_user),
            limit=limit,
        )
    }


@router.get("/feedback")
def list_feedback_events(
    limit: int = Query(default=25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    return {"items": _repository().list_feedback_events(user_id=_user_filter(current_user), limit=limit)}


@router.post("/feedback")
def record_feedback_event(
    request: FeedbackEventRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = _require_user_id(current_user)
    recorded = _repository().record_feedback_event(
        user_id=user_id,
        conversation_id=request.conversation_id,
        trace_id=request.trace_id,
        event_type=request.event_type,
        value=request.value,
        assistant_message_id=request.assistant_message_id,
        user_prompt=request.user_prompt,
        assistant_answer=request.assistant_answer,
        metadata=request.metadata,
    )
    return {"success": True, "item": recorded}


@router.get("/eval-cases")
def list_eval_cases(
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    _require_user_id(current_user)
    return {"items": _repository().list_eval_cases(limit=limit)}


@router.post("/eval-cases")
def create_eval_case(
    request: EvalCaseRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    _require_user_id(current_user)
    if not request.name.strip():
        raise HTTPException(status_code=400, detail="Name is required")
    if not request.question.strip():
        raise HTTPException(status_code=400, detail="Question is required")
    return {
        "item": _repository().create_eval_case(
            name=request.name,
            category=request.category,
            question=request.question,
            expected=request.expected,
            source=request.source,
        )
    }


@router.get("/eval-runs")
def list_eval_runs(
    limit: int = Query(default=25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    _require_user_id(current_user)
    return {"items": _repository().list_eval_runs(limit=limit)}


@router.get("/eval-runs/{run_id}/results")
def list_eval_results(
    run_id: int,
    limit: int = Query(default=100, ge=1, le=500),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    _require_user_id(current_user)
    return {"items": _repository().list_eval_results(run_id=run_id, limit=limit)}


@router.get("/checkpoints")
def list_checkpoint_threads(
    limit: int = Query(default=25, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    _require_user_id(current_user)
    return {"items": _repository().list_checkpoint_threads(limit=limit)}


@router.post("/eval-runs")
def create_eval_run(
    request: EvalRunRequest,
    current_user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    user_id = _require_user_id(current_user)
    repository = _repository()
    cases = repository.get_eval_cases_by_ids(case_ids=request.case_ids)
    if not cases:
        raise HTTPException(status_code=400, detail="At least one evaluation case is required")
    run_name = request.name.strip() or "Manual evaluation run"
    run_id = repository.create_eval_run(
        name=run_name,
        metadata={"case_count": len(cases), "requested_case_ids": request.case_ids},
    )
    qa_graph_service = get_qa_graph_service()
    results: list[dict[str, Any]] = []
    completed = 0
    try:
        for case in cases:
            try:
                execution = qa_graph_service.run(
                    question=str(case.get("question") or ""),
                    raw_question=str(case.get("question") or ""),
                    file_ids=_positive_ints(dict(case.get("expected") or {}).get("file_ids")),
                    archive_slugs=_string_list(dict(case.get("expected") or {}).get("archive_slugs")),
                    metadata_fields=_string_list(dict(case.get("expected") or {}).get("metadata_fields")),
                    user_id=user_id,
                    top_k=request.top_k,
                    metadata_mode=str(dict(case.get("expected") or {}).get("metadata_mode") or "auto"),
                    summary_mode=str(dict(case.get("expected") or {}).get("summary_mode") or "default"),
                )
                telemetry = dict(execution.telemetry or {})
                trace_id = str(telemetry.get("trace_id") or "")
                status, score, details = _score_eval_result(
                    answer=execution.answer.answer_text,
                    telemetry=telemetry,
                    expected=dict(case.get("expected") or {}),
                )
                details.update(
                    {
                        "answer_preview": execution.answer.answer_text[:900],
                        "model_used": execution.answer.model_used,
                    }
                )
                completed += 1
            except Exception as exc:
                trace_id = ""
                status = "failed"
                score = 0.0
                details = {"error": str(exc)}
            repository.insert_eval_result(
                run_id=run_id,
                case_id=int(case.get("eval_case_id") or 0),
                trace_id=trace_id or None,
                status=status,
                score=score,
                details=details,
            )
            results.append(
                {
                    "eval_case_id": int(case.get("eval_case_id") or 0),
                    "status": status,
                    "score": score,
                    "trace_id": trace_id,
                    "details": details,
                }
            )
        passed = len([item for item in results if item["status"] == "passed"])
        run_status = "completed" if completed == len(cases) else "partial"
        repository.finish_eval_run(
            run_id=run_id,
            status=run_status,
            metadata={"case_count": len(cases), "completed": completed, "passed": passed},
        )
        return {"eval_run_id": run_id, "status": run_status, "results": results}
    except Exception:
        repository.finish_eval_run(
            run_id=run_id,
            status="failed",
            metadata={"case_count": len(cases), "completed": completed},
        )
        raise
