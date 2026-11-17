"""Schemas for QA retrieval and responses."""

from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel, Field

from apps.backend.app.contracts.common import APIModel


class AskQuestionRequest(BaseModel):
    question: str = Field(default="")
    file_ids: list[int] = Field(default_factory=list)
    allow_inferred_scope: bool = True
    top_k: int = Field(default=5, ge=1, le=12000)
    candidate_k: int | None = Field(default=None, ge=1, le=24000)
    min_pages_per_selected_doc: int = Field(default=0, ge=0, le=3)
    summary_mode: Literal["default", "per_document"] = "default"
    metadata_mode: Literal["auto", "metadata_first"] = "auto"
    archive_slugs: list[str] = Field(default_factory=list)
    metadata_fields: list[str] = Field(default_factory=list)
    conversation_id: int | None = Field(default=None, ge=1)
    user_id: int | None = Field(default=None, ge=0)
    current_date: date | None = None
    history: list["HistoryMessage"] = Field(default_factory=list)


class HistoryMessage(BaseModel):
    role: str = Field(min_length=1)
    content: str = Field(default="")


class EvidenceItem(APIModel):
    source_number: int
    file_id: int
    file_name: str
    archive_slug: str = ""
    file_code: str | None = None
    page_id: int
    page_number: int
    score: float
    text_score: float | None = None
    image_score: float | None = None
    lexical_score: float | None = None
    fused_score: float | None = None
    needs_visual_check: bool = False
    summary_text: str
    image_path_local: str
    object_name_page: str = ""
    extraction_method: str = ""
    ocr_confidence: float | None = None


class CitationItem(APIModel):
    source_number: int
    file_name: str
    page_number: int
    score: float
    snippet: str


class SourceItem(APIModel):
    doc_id: str
    name: str
    source_number: int
    file_id: int
    page_number: int
    object_name_page: str = ""
    snippet: str = ""


class AskQuestionResponse(APIModel):
    answer: str
    answer_text: str
    executive_summary: str
    key_points: list[str]
    obligations: list[str]
    citations: list[CitationItem]
    cited_sources: list[SourceItem] = Field(default_factory=list)
    model_used: str
    strategy: str
    answer_mode: str
    visual_confirmation_used: bool
    analyzed_pages: list[int]
    confidence_notes: list[str]
    ocr_vs_visual_discrepancies: list[str]
    evidence: list[EvidenceItem]
    thread_id: str | None = None
    telemetry: dict[str, object] = Field(default_factory=dict)


class ReasoningStageItem(APIModel):
    key: str
    label: str
    starts_at_seconds: int = Field(default=0, ge=0)


class ReasoningStagesResponse(APIModel):
    search: list[ReasoningStageItem]
    document: list[ReasoningStageItem]


class GraphNodeItem(APIModel):
    key: str
    label: str
    kind: str


class GraphEdgeItem(APIModel):
    source: str
    target: str
    condition: str = ""


class GraphDefinitionResponse(APIModel):
    nodes: list[GraphNodeItem]
    edges: list[GraphEdgeItem]
    start_node: str
    end_node: str


class ScopeOptionsResponse(APIModel):
    files: list[str] = Field(default_factory=list)
    metadata_fields: list[str] = Field(default_factory=list)
    has_metadata: bool = False
