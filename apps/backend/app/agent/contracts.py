"""Tipos y utilidades compartidas para respuestas QA."""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from apps.backend.app.contracts.questions import EvidenceItem


@dataclass(slots=True)
class LLMResult:
    answer_text: str
    executive_summary: str
    key_points: list[str]
    obligations: list[str]
    citation_source_numbers: list[int]
    model_used: str


@dataclass(slots=True)
class VisualInspectionResult:
    used: bool
    analyzed_pages: list[int]
    visual_context: str
    confidence_notes: list[str]
    ocr_vs_visual_discrepancies: list[str]


@dataclass(slots=True)
class HybridAnswerResult:
    llm_result: LLMResult
    answer_mode: str
    visual_confirmation_used: bool
    analyzed_pages: list[int]
    confidence_notes: list[str]
    ocr_vs_visual_discrepancies: list[str]


@dataclass(slots=True)
class QueryExecutionResult:
    strategy: str
    selected_provider: str
    evidence: list[EvidenceItem]
    answer: LLMResult
    answer_mode: str
    visual_confirmation_used: bool
    analyzed_pages: list[int]
    confidence_notes: list[str]
    ocr_vs_visual_discrepancies: list[str]
    thread_id: str = ""
    telemetry: dict[str, object] = field(default_factory=dict)


def serialize_evidence(evidence: list[EvidenceItem]) -> str:
    lines: list[str] = []
    for index, item in enumerate(evidence, start=1):
        archive_part = f" archive={item.archive_slug}" if str(item.archive_slug or "").strip() else ""
        lines.append(
            (
                f"[Source {index}]{archive_part} file={item.file_name} page={item.page_number} "
                f"score={item.score:.4f} summary={item.summary_text}"
            )
        )
    return "\n".join(lines)


def extract_text_from_oci_chat_result(chat_result) -> str:
    choices = getattr(chat_result.chat_response, "choices", []) or []
    if not choices:
        return ""
    message = choices[0].message
    contents = getattr(message, "content", None) or []
    text_parts = [content.text for content in contents if getattr(content, "text", None)]
    if text_parts:
        return "\n".join(text_parts).strip()
    refusal = getattr(message, "refusal", None)
    return refusal or ""


def parse_structured_answer(payload_text: str, evidence_count: int) -> dict:
    payload = json.loads(payload_text or "{}")
    source_numbers = [
        int(item)
        for item in payload.get("citation_source_numbers", [])
        if isinstance(item, int) and 1 <= int(item) <= evidence_count
    ]
    return {
        "answer_text": str(payload.get("answer_text", "")).strip(),
        "executive_summary": str(payload.get("executive_summary", "")).strip(),
        "key_points": [
            str(item).strip()
            for item in payload.get("key_points", [])
            if str(item).strip()
        ],
        "obligations": [
            str(item).strip()
            for item in payload.get("obligations", [])
            if str(item).strip()
        ],
        "citation_source_numbers": sorted(set(source_numbers)),
    }

