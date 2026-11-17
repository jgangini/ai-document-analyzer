"""File metadata helpers and classification flow."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from apps.backend.app.core.config import Settings
from apps.backend.app.core.database import DatabaseManager

DOCUMENT_CODE_SEPARATOR = "_-_"
DOCUMENT_CODE_PREFIX_PATTERN = re.compile(r"^([A-Za-z]{1,10}\d{2,}[A-Za-z0-9]*)\s*(?=[_-])")


@dataclass(slots=True)
class FileMetadata:
    document_code: str | None
    document_code_source: str


def _normalize_document_code_candidate(value: str | None) -> str | None:
    normalized = str(value or "").strip().upper()
    if not normalized:
        return None
    if not re.fullmatch(r"[A-Z]{1,10}\d{2,}[A-Z0-9]*", normalized):
        return None
    return normalized[:64]


def normalize_document_code_value(value: str | None) -> str | None:
    return _normalize_document_code_candidate(value)


def extract_document_code_from_filename(file_name: str) -> tuple[str | None, str]:
    stem = Path(str(file_name or "").strip()).stem
    if DOCUMENT_CODE_SEPARATOR in stem:
        prefix = _normalize_document_code_candidate(stem.split(DOCUMENT_CODE_SEPARATOR, 1)[0])
        if prefix:
            return prefix, "filename_rule"
    prefix_match = DOCUMENT_CODE_PREFIX_PATTERN.match(stem)
    if prefix_match:
        prefix = _normalize_document_code_candidate(prefix_match.group(1))
        if prefix:
            return prefix, "filename_rule"
    return None, "none"


class FileMetadataClassifier:
    def __init__(
        self,
        *,
        settings: Settings,
        db_manager: DatabaseManager | None = None,
    ) -> None:
        del db_manager
        self.settings = settings

    def classify(
        self,
        *,
        file_name: str,
        file_path: Path | None = None,
        relative_path: str | None = None,
        text_samples: list[str] | None = None,
        document_language: str | None = None,
    ) -> FileMetadata:
        del file_path, relative_path, text_samples, document_language
        document_code, document_code_source = extract_document_code_from_filename(file_name)
        return FileMetadata(
            document_code=document_code,
            document_code_source=document_code_source,
        )
