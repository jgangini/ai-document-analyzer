"""Inline selector parsing for metadata-first chat queries."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from typing import Literal

from apps.backend.app.services.metadata_keys import canonicalize_file_key

_FILE_EXTENSION_PATTERN = re.compile(r"\.(?:zip|pdf)\b", re.IGNORECASE)
_WHITESPACE_PATTERN = re.compile(r"\s+")


@dataclass(slots=True)
class ParsedQuestionSelectors:
    cleaned_question: str
    metadata_mode: Literal["auto", "metadata_first"] = "auto"
    archive_slugs: list[str] | None = None
    metadata_fields: list[str] | None = None


def _normalize_selector_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.casefold()
    return " ".join(normalized.split())


def normalize_selector_archive_slugs(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_value in list(values or []):
        normalized = canonicalize_file_key(str(raw_value or "").strip().strip(",.;:"))
        normalized_key = normalized.lower()
        if not normalized or normalized_key in seen:
            continue
        seen.add(normalized_key)
        ordered.append(normalized)
    return ordered


def normalize_selector_metadata_fields(values: list[str] | None) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_value in list(values or []):
        normalized = str(raw_value or "").strip()
        normalized_key = _normalize_selector_text(normalized)
        if not normalized or normalized_key in seen:
            continue
        seen.add(normalized_key)
        ordered.append(normalized)
    return ordered


def _has_selector_boundary(text: str, index: int) -> bool:
    return index <= 0 or text[index - 1].isspace()


def _consume_separator(text: str, index: int) -> int:
    cursor = int(index)
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    if cursor < len(text) and text[cursor] in ",;":
        cursor += 1
        while cursor < len(text) and text[cursor].isspace():
            cursor += 1
    return cursor


def _consume_quoted_value(text: str, start: int) -> tuple[str, int] | None:
    if start >= len(text) or text[start] not in {'"', "'"}:
        return None
    quote = text[start]
    cursor = start + 1
    while cursor < len(text):
        if text[cursor] == quote:
            return text[start + 1 : cursor], cursor + 1
        cursor += 1
    return None


def _resolve_archive_slug_catalog(value: str, catalog: list[str]) -> str | None:
    canonical_value = canonicalize_file_key(_FILE_EXTENSION_PATTERN.sub("", str(value or "").strip()))
    normalized_value = canonical_value.lower()
    for candidate in catalog:
        if canonicalize_file_key(candidate).lower() == normalized_value:
            return candidate
    return None


def _match_catalog_archive_slug(text: str, start: int, catalog: list[str]) -> tuple[str, int] | None:
    segment = text[start:]
    if not segment:
        return None
    lowered_segment = segment.lower()
    candidates = sorted(
        normalize_selector_archive_slugs(catalog),
        key=lambda item: len(item),
        reverse=True,
    )
    for candidate in candidates:
        lowered_candidate = candidate.lower()
        for suffix in ("", ".zip", ".pdf"):
            rendered = lowered_candidate + suffix
            if not lowered_segment.startswith(rendered):
                continue
            end = start + len(rendered)
            if end < len(text) and not text[end].isspace() and text[end] not in ",;":
                continue
            return candidate, end
    return None


def _match_catalog_metadata_field(text: str, start: int, catalog: list[str]) -> tuple[str, int] | None:
    segment = text[start:]
    if not segment:
        return None
    candidates = sorted(
        normalize_selector_metadata_fields(catalog),
        key=lambda item: len(item),
        reverse=True,
    )
    lowered_segment = segment.casefold()
    for candidate in candidates:
        lowered_candidate = candidate.casefold()
        if not lowered_segment.startswith(lowered_candidate):
            continue
        end = start + len(candidate)
        if end < len(text) and not text[end].isspace() and text[end] not in ",;":
            continue
        return candidate, end
    return None


def _consume_unquoted_file_value(text: str, start: int, catalog: list[str] | None) -> tuple[str, int] | None:
    cursor = start
    while cursor < len(text) and not text[cursor].isspace() and text[cursor] not in ",;":
        cursor += 1
    raw_value = text[start:cursor].strip()
    if not raw_value:
        return None
    if catalog:
        resolved = _resolve_archive_slug_catalog(raw_value, catalog)
        if resolved:
            return resolved, cursor
    canonical = canonicalize_file_key(_FILE_EXTENSION_PATTERN.sub("", raw_value))
    if not canonical:
        return None
    return canonical, cursor


def _consume_unquoted_field_value(text: str, start: int, catalog: list[str] | None) -> tuple[str, int] | None:
    if catalog:
        matched = _match_catalog_metadata_field(text, start, catalog)
        if matched is not None:
            return matched
    cursor = start
    while cursor < len(text):
        if text[cursor] in ",;":
            break
        if text[cursor].isspace():
            lookahead = cursor
            while lookahead < len(text) and text[lookahead].isspace():
                lookahead += 1
            if lookahead >= len(text):
                break
            if text.startswith("@metadata", lookahead) or text.startswith("/file:", lookahead) or text.startswith("/col:", lookahead):
                break
        cursor += 1
    raw_value = text[start:cursor].strip()
    if not raw_value:
        return None
    return raw_value, cursor


def parse_question_selectors(
    *,
    question: str,
    available_archive_slugs: list[str] | None = None,
    available_metadata_fields: list[str] | None = None,
) -> ParsedQuestionSelectors:
    text = str(question or "")
    archive_catalog = normalize_selector_archive_slugs(available_archive_slugs)
    field_catalog = normalize_selector_metadata_fields(available_metadata_fields)

    metadata_requested = False
    archive_slugs: list[str] = []
    metadata_fields: list[str] = []
    consumed_ranges: list[tuple[int, int]] = []

    cursor = 0
    while cursor < len(text):
        if text[cursor] == "@" and _has_selector_boundary(text, cursor):
            if text[cursor : cursor + 9].lower() == "@metadata":
                metadata_requested = True
                consumed_ranges.append((cursor, _consume_separator(text, cursor + 9)))
                cursor = consumed_ranges[-1][1]
                continue
        if text[cursor] == "/" and _has_selector_boundary(text, cursor):
            if text[cursor : cursor + 6].lower() == "/file:":
                value_start = cursor + 6
                while value_start < len(text) and text[value_start].isspace():
                    value_start += 1
                matched = None
                quoted = _consume_quoted_value(text, value_start)
                if quoted is not None:
                    raw_value, end = quoted
                    resolved = _resolve_archive_slug_catalog(raw_value, archive_catalog) if archive_catalog else None
                    matched = (resolved or canonicalize_file_key(raw_value), end)
                elif archive_catalog:
                    matched = _match_catalog_archive_slug(text, value_start, archive_catalog)
                    if matched is None:
                        matched = _consume_unquoted_file_value(text, value_start, archive_catalog)
                else:
                    matched = _consume_unquoted_file_value(text, value_start, None)
                if matched is not None and matched[0]:
                    archive_slugs.append(str(matched[0]))
                    consumed_ranges.append((cursor, _consume_separator(text, matched[1])))
                    cursor = consumed_ranges[-1][1]
                    continue
            if text[cursor : cursor + 5].lower() == "/col:":
                value_start = cursor + 5
                while value_start < len(text) and text[value_start].isspace():
                    value_start += 1
                matched = None
                quoted = _consume_quoted_value(text, value_start)
                if quoted is not None:
                    matched = quoted
                else:
                    matched = _consume_unquoted_field_value(text, value_start, field_catalog or None)
                if matched is not None and str(matched[0]).strip():
                    metadata_fields.append(str(matched[0]).strip())
                    consumed_ranges.append((cursor, _consume_separator(text, matched[1])))
                    cursor = consumed_ranges[-1][1]
                    continue
        cursor += 1

    if not consumed_ranges:
        cleaned_question = " ".join(text.split())
    else:
        parts: list[str] = []
        start = 0
        for range_start, range_end in consumed_ranges:
            if range_start > start:
                parts.append(text[start:range_start])
            start = max(start, range_end)
        if start < len(text):
            parts.append(text[start:])
        cleaned_question = _WHITESPACE_PATTERN.sub(" ", "".join(parts)).strip()

    return ParsedQuestionSelectors(
        cleaned_question=cleaned_question,
        metadata_mode="metadata_first" if metadata_requested else "auto",
        archive_slugs=normalize_selector_archive_slugs(archive_slugs),
        metadata_fields=normalize_selector_metadata_fields(metadata_fields),
    )


def merge_question_selectors(
    *,
    question: str,
    request_metadata_mode: str | None = None,
    request_archive_slugs: list[str] | None = None,
    request_metadata_fields: list[str] | None = None,
    available_archive_slugs: list[str] | None = None,
    available_metadata_fields: list[str] | None = None,
) -> ParsedQuestionSelectors:
    parsed = parse_question_selectors(
        question=question,
        available_archive_slugs=available_archive_slugs,
        available_metadata_fields=available_metadata_fields,
    )
    archive_slugs = normalize_selector_archive_slugs(
        list(request_archive_slugs or []) + list(parsed.archive_slugs or [])
    )
    metadata_fields = normalize_selector_metadata_fields(
        list(request_metadata_fields or []) + list(parsed.metadata_fields or [])
    )
    metadata_mode = "metadata_first" if (
        str(request_metadata_mode or "").strip().lower() == "metadata_first"
        or parsed.metadata_mode == "metadata_first"
        or metadata_fields
    ) else "auto"
    return ParsedQuestionSelectors(
        cleaned_question=parsed.cleaned_question,
        metadata_mode=metadata_mode,
        archive_slugs=archive_slugs,
        metadata_fields=metadata_fields,
    )


def build_effective_selector_question(selectors: ParsedQuestionSelectors) -> str:
    cleaned_question = str(selectors.cleaned_question or "").strip()
    if len(cleaned_question) >= 3:
        return cleaned_question

    archive_slugs = normalize_selector_archive_slugs(selectors.archive_slugs)
    metadata_fields = normalize_selector_metadata_fields(selectors.metadata_fields)
    metadata_requested = str(selectors.metadata_mode or "").strip().lower() == "metadata_first"

    if metadata_fields and archive_slugs:
        return "Muestra los valores de metadata seleccionados para los archivos seleccionados."
    if metadata_fields:
        return "Muestra los valores de metadata seleccionados."
    if metadata_requested and archive_slugs:
        return "Muestra la metadata disponible para los archivos seleccionados."
    if metadata_requested:
        return "Muestra la metadata disponible."
    if archive_slugs:
        return "Muestra el inventario documental de los archivos seleccionados."
    return ""
