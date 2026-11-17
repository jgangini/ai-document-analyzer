"""Lightweight text helpers shared by ingestion and RAG modules."""

from __future__ import annotations

from datetime import date, datetime
import re
import unicodedata

SPANISH_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()


def compact_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def normalize_rut(value: str) -> str:
    digits = re.sub(r"[^0-9kK]", "", value or "")
    if len(digits) < 2:
        return ""
    return f"{digits[:-1]}-{digits[-1].upper()}"


def extract_ruts(value: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in re.finditer(r"\b\d{1,2}\.?\d{3}\.?\d{3}-[\dkK]\b", value or ""):
        normalized = normalize_rut(match.group(0))
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def parse_date_value(value: str | None) -> date | None:
    text = compact_whitespace(str(value or ""))
    if not text:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    tokens = [fragment.strip() for fragment in normalize_text(text).split() if fragment.strip()]
    if len(tokens) == 4 and tokens[1] == "de" and tokens[3].isdigit():
        month = SPANISH_MONTHS.get(tokens[2])
        if month is not None:
            return date(int(tokens[3]), month, int(tokens[0]))
    if len(tokens) == 5 and tokens[1] == "de" and tokens[3] == "de" and tokens[4].isdigit():
        month = SPANISH_MONTHS.get(tokens[2])
        if month is not None:
            return date(int(tokens[4]), month, int(tokens[0]))
    return None


def build_page_search_text(
    *,
    file_name: str,
    document_code: str | None,
    document_type: str | None,
    page_number: int,
    ocr_text: str,
    visual_summary: str,
    visual_flags: list[str],
) -> str:
    parts = [
        f"file_name: {file_name}",
        f"document_code: {document_code or ''}",
        f"document_type: {document_type or ''}",
        f"page_number: {page_number}",
        f"ocr_text: {compact_whitespace(ocr_text)}",
        f"visual_summary: {compact_whitespace(visual_summary)}",
        f"visual_flags: {' '.join(visual_flags)}",
        f"ruts: {' '.join(extract_ruts(ocr_text))}",
    ]
    return " | ".join(part for part in parts if compact_whitespace(part))


def build_document_search_text(
    *,
    file_name: str,
    document_code: str | None,
    document_type: str | None,
    summary_text: str,
    excerpts: list[str],
    labels: list[str],
    primary_identifier: str | None,
    secondary_identifier: str | None,
) -> str:
    parts = [
        f"file_name: {file_name}",
        f"document_code: {document_code or ''}",
        f"document_type: {document_type or ''}",
        f"primary_identifier: {primary_identifier or ''}",
        f"secondary_identifier: {secondary_identifier or ''}",
        f"summary: {compact_whitespace(summary_text)}",
        f"labels: {' | '.join(compact_whitespace(label) for label in labels if compact_whitespace(label))}",
        f"excerpts: {' '.join(compact_whitespace(text) for text in excerpts if compact_whitespace(text))}",
    ]
    return " | ".join(part for part in parts if compact_whitespace(part))
