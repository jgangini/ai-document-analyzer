"""Shared OCR result types for the Docling ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class PageOCRResult:
    raw_ocr_text: str
    normalized_text: str
    markdown_text: str
    detected_blocks_json: str
    table_extraction_json: str
    ocr_confidence: float
    extraction_method: str
