"""Pure helpers for canonical archive metadata keys and values."""

from __future__ import annotations

from typing import Any
import re

_INTEGER_PATTERN = re.compile(r"^[+-]?\d+$")
_DECIMAL_PATTERN = re.compile(r"^[+-]?\d+[.,]\d+$")
_FILE_EXTENSION_PATTERN = re.compile(r"\.(zip|pdf)$", flags=re.IGNORECASE)
_BOOLEAN_TRUE = {"true", "yes", "si", "sí", "1"}
_BOOLEAN_FALSE = {"false", "no", "0"}


def canonicalize_file_key(value: str | None) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    normalized = _FILE_EXTENSION_PATTERN.sub("", normalized)
    return normalized.strip()[:256]


def normalize_metadata_header(value: str | None) -> str:
    return str(value or "").strip()


def normalize_metadata_attribute_key(value: str | None) -> str:
    normalized = normalize_metadata_header(value).lower()
    normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
    normalized = re.sub(r"_+", "_", normalized)
    return f"metadata.{normalized or 'field'}"[:128]


def _should_preserve_numeric_as_text(value: str) -> bool:
    candidate = value.lstrip("+-")
    return len(candidate) > 1 and candidate.startswith("0") and not candidate.startswith("0.")


def coerce_metadata_scalar(value: str | None) -> str | int | float | bool | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    lowered = normalized.lower()
    if lowered in _BOOLEAN_TRUE:
        return True
    if lowered in _BOOLEAN_FALSE:
        return False
    compact_number = normalized.replace(" ", "")
    if _INTEGER_PATTERN.fullmatch(compact_number) and not _should_preserve_numeric_as_text(compact_number):
        try:
            return int(compact_number)
        except ValueError:
            return normalized
    if _DECIMAL_PATTERN.fullmatch(compact_number) and not _should_preserve_numeric_as_text(compact_number):
        try:
            return float(compact_number.replace(",", "."))
        except ValueError:
            return normalized
    return normalized


def build_metadata_search_text(*, file_key: str, fields: dict[str, Any]) -> str:
    parts = [f"file: {file_key}"]
    for key, value in fields.items():
        if value is None:
            continue
        parts.append(f"{normalize_metadata_header(key)}: {value}")
    return " | ".join(part for part in parts if str(part).strip())
