"""Tool de retrieval para orquestacion de consultas."""

from __future__ import annotations

import json

from pydantic import BaseModel, Field

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.rag.retrieval.query_service import RetrievalPipelineService, RetrievalResult


class OracleRetrievalToolInput(BaseModel):
    question: str = Field(min_length=3)
    user_id: int | None = Field(default=None, ge=0)
    file_ids: list[int] = Field(default_factory=list)
    archive_slugs: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=12000)
    candidate_k: int | None = Field(default=None, ge=1, le=24000)
    min_pages_per_selected_doc: int = Field(default=0, ge=0, le=3)
    summary_mode: str = Field(default="default")
    question_class: str = Field(default="extractive")
    scope_origin: str = Field(default="global")


class OracleRetrievalTool:
    name: str = "oracle_retrieval_pipeline"
    description: str = (
        "Retrieve the most relevant pages from Oracle 26ai for a user question. "
        "Returns ranked evidence with file, page, score, and summary."
    )
    args_schema: type[BaseModel] = OracleRetrievalToolInput
    result_as_answer: bool = False

    def __init__(self, retrieval_pipeline_service: RetrievalPipelineService, **data) -> None:
        del data
        self._retrieval_pipeline_service = retrieval_pipeline_service

    def _run(
        self,
        question: str,
        user_id: int | None = None,
        file_ids: list[int] | None = None,
        archive_slugs: list[str] | None = None,
        top_k: int = 5,
        candidate_k: int | None = None,
        min_pages_per_selected_doc: int = 0,
        summary_mode: str = "default",
        question_class: str = "extractive",
        scope_origin: str = "global",
    ) -> str:
        results = self._retrieval_pipeline_service.retrieve(
            question=question,
            user_id=user_id,
            file_ids=file_ids or None,
            archive_slugs=archive_slugs or None,
            top_k=top_k,
            candidate_k=candidate_k,
            min_pages_per_selected_doc=min_pages_per_selected_doc,
            summary_mode=summary_mode,
            question_class=question_class,
            scope_origin=scope_origin,
        )
        return json.dumps(
            [
                {
                    "source_number": item.source_number,
                    "file_id": item.file_id,
                    "file_name": item.file_name,
                    "archive_slug": item.archive_slug,
                    "file_code": item.file_code,
                    "page_id": item.page_id,
                    "page_number": item.page_number,
                    "score": item.score,
                    "text_score": item.text_score,
                    "image_score": item.image_score,
                    "lexical_score": item.lexical_score,
                    "fused_score": item.fused_score,
                    "needs_visual_check": item.needs_visual_check,
                    "summary_text": item.summary_text,
                    "image_path_local": item.image_path_local,
                    "object_name_page": item.object_name_page,
                }
                for item in results.evidence
            ],
            ensure_ascii=False,
        )

    def retrieve(
        self,
        *,
        question: str,
        user_id: int | None,
        file_ids: list[int] | None,
        archive_slugs: list[str] | None,
        top_k: int,
        candidate_k: int | None = None,
        min_pages_per_selected_doc: int = 0,
        summary_mode: str = "default",
        question_class: str = "extractive",
        scope_origin: str = "global",
    ) -> RetrievalResult:
        return self._retrieval_pipeline_service.retrieve(
            question=question,
            user_id=user_id,
            file_ids=file_ids,
            archive_slugs=archive_slugs,
            top_k=top_k,
            candidate_k=candidate_k,
            min_pages_per_selected_doc=min_pages_per_selected_doc,
            summary_mode=summary_mode,
            question_class=question_class,
            scope_origin=scope_origin,
        )

    def warmup(self) -> None:
        self._retrieval_pipeline_service.warmup()

