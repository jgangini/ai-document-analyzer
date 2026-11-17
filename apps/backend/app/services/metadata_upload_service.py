"""Canonical CSV metadata ingestion keyed by the required `file` column."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import csv
import json
from pathlib import Path
import uuid

from apps.backend.app.core.config import Settings
from apps.backend.app.repositories.archive_metadata_repository import ArchiveMetadataRepository
from apps.backend.app.services.metadata_keys import (
    build_metadata_search_text,
    canonicalize_file_key,
    coerce_metadata_scalar,
    normalize_metadata_attribute_key,
    normalize_metadata_header,
)


@dataclass(slots=True)
class CanonicalMetadataRow:
    file: str
    fields: dict[str, str | int | float | bool | None]


@dataclass(slots=True)
class ParsedMetadataUpload:
    columns: list[str]
    rows: list[CanonicalMetadataRow]
    duplicate_files: list[str]


@dataclass(slots=True)
class MetadataUploadResult:
    metadata_upload_id: str
    source_file_name: str
    display_name: str
    description: str
    access_scope: str
    metadata_status: str
    created_at: datetime
    columns: list[str]
    total_rows: int
    matched_files: list[str]
    unmatched_files: list[str]
    duplicate_files: list[str]


class MetadataUploadValidationError(ValueError):
    """Raised when the uploaded metadata CSV is invalid."""


class MetadataUploadService:
    def __init__(
        self,
        *,
        settings: Settings,
        repository: ArchiveMetadataRepository,
    ) -> None:
        self.settings = settings
        self.repository = repository

    def _discover_known_archive_slugs(self, *, user_id: int) -> set[str]:
        known = {
            canonicalize_file_key(value).lower()
            for value in self.repository.list_known_archive_slugs_for_user(
                user_id=user_id,
                include_shared=True,
            )
            if canonicalize_file_key(value)
        }
        for base_dir in (self.settings.upload_path, self.settings.extracted_path, self.settings.staging_path):
            if not base_dir.exists():
                continue
            for suffix in ("*.zip", "*.pdf"):
                for path in base_dir.rglob(suffix):
                    key = canonicalize_file_key(path.stem)
                    if key:
                        known.add(key.lower())
        return known

    def parse_csv(self, *, csv_path: Path) -> ParsedMetadataUpload:
        with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.reader(handle)
            try:
                raw_headers = next(reader)
            except StopIteration as exc:
                raise MetadataUploadValidationError("The metadata CSV is empty.") from exc

            headers = [normalize_metadata_header(item) for item in raw_headers]
            if not headers or headers[0] != "file":
                raise MetadataUploadValidationError(
                    "The metadata CSV must start with an exact first column named `file`."
                )
            if any(not header for header in headers):
                raise MetadataUploadValidationError("The metadata CSV contains empty header names.")

            normalized_headers = [header.lower() for header in headers]
            if len(normalized_headers) != len(set(normalized_headers)):
                raise MetadataUploadValidationError("The metadata CSV contains duplicate header names.")

            rows: list[CanonicalMetadataRow] = []
            seen_files: set[str] = set()
            duplicate_files: list[str] = []
            for row_number, values in enumerate(reader, start=2):
                if not any(str(item or "").strip() for item in values):
                    continue
                padded = list(values) + [""] * max(0, len(headers) - len(values))
                raw_file_value = padded[0] if padded else ""
                file_key = canonicalize_file_key(raw_file_value)
                if not file_key:
                    raise MetadataUploadValidationError(
                        f"Row {row_number} is missing the required `file` value."
                    )
                if file_key.lower() in seen_files:
                    duplicate_files.append(file_key)
                    continue
                seen_files.add(file_key.lower())
                fields: dict[str, str | bool | None] = {}
                for index, header in enumerate(headers[1:], start=1):
                    fields[header] = coerce_metadata_scalar(padded[index] if index < len(padded) else "")
                rows.append(CanonicalMetadataRow(file=file_key, fields=fields))

        return ParsedMetadataUpload(
            columns=headers,
            rows=rows,
            duplicate_files=sorted(set(duplicate_files), key=str.lower),
        )

    @staticmethod
    def _build_row_payloads(parsed: ParsedMetadataUpload) -> list[dict[str, str]]:
        return [
            {
                "file_key": item.file,
                "row_json": json.dumps(
                    {
                        "file": item.file,
                        "fields": item.fields,
                    },
                    ensure_ascii=False,
                ),
                "search_text": build_metadata_search_text(file_key=item.file, fields=item.fields),
            }
            for item in parsed.rows
        ]

    def _build_result(
        self,
        *,
        metadata_upload_id: str,
        source_file_name: str,
        parsed: ParsedMetadataUpload,
        upload_record: dict[str, object],
        known_files: set[str],
    ) -> MetadataUploadResult:
        matched_files = sorted(
            [item.file for item in parsed.rows if item.file.lower() in known_files],
            key=str.lower,
        )
        unmatched_files = sorted(
            [item.file for item in parsed.rows if item.file.lower() not in known_files],
            key=str.lower,
        )
        created_at = upload_record.get("metadata_upload_created")
        if created_at is None:
            created_at = datetime.now(timezone.utc)
        return MetadataUploadResult(
            metadata_upload_id=metadata_upload_id,
            source_file_name=str(source_file_name or "").strip(),
            display_name=str(upload_record.get("display_name") or source_file_name or "").strip(),
            description=str(upload_record.get("description") or "").strip(),
            access_scope=str(upload_record.get("access_scope") or "private").strip() or "private",
            metadata_status=str(upload_record.get("metadata_status") or "active").strip() or "active",
            created_at=created_at,
            columns=list(parsed.columns),
            total_rows=len(parsed.rows),
            matched_files=matched_files,
            unmatched_files=unmatched_files,
            duplicate_files=list(parsed.duplicate_files),
        )

    def upload_csv(
        self,
        *,
        user_id: int,
        csv_path: Path,
        source_file_name: str,
        display_name: str | None = None,
        description: str | None = None,
        access_scope: str | None = None,
    ) -> MetadataUploadResult:
        parsed = self.parse_csv(csv_path=csv_path)
        if parsed.duplicate_files:
            joined = ", ".join(parsed.duplicate_files)
            raise MetadataUploadValidationError(
                f"Duplicate `file` values are not allowed in metadata CSV: {joined}."
            )
        metadata_upload_id = uuid.uuid4().hex
        upload_record = self.repository.create_upload(
            metadata_upload_id=metadata_upload_id,
            user_id=user_id,
            source_file_name=source_file_name,
            columns=parsed.columns,
            total_rows=len(parsed.rows),
            display_name=display_name,
            description=description,
            access_scope=access_scope,
        )
        self.repository.replace_upload_rows(
            metadata_upload_id=metadata_upload_id,
            user_id=user_id,
            rows=self._build_row_payloads(parsed),
        )
        known_files = self._discover_known_archive_slugs(user_id=user_id)
        return self._build_result(
            metadata_upload_id=metadata_upload_id,
            source_file_name=str(source_file_name or "").strip(),
            parsed=parsed,
            upload_record=upload_record,
            known_files=known_files,
        )

    def replace_csv(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        csv_path: Path,
        source_file_name: str,
    ) -> MetadataUploadResult:
        parsed = self.parse_csv(csv_path=csv_path)
        if parsed.duplicate_files:
            joined = ", ".join(parsed.duplicate_files)
            raise MetadataUploadValidationError(
                f"Duplicate `file` values are not allowed in metadata CSV: {joined}."
            )
        upload_record = self.repository.update_upload_content(
            metadata_upload_id=metadata_upload_id,
            user_id=user_id,
            source_file_name=source_file_name,
            columns=parsed.columns,
            total_rows=len(parsed.rows),
        )
        if upload_record is None:
            raise MetadataUploadValidationError("Metadata dataset not found.")
        self.repository.replace_upload_rows(
            metadata_upload_id=metadata_upload_id,
            user_id=user_id,
            rows=self._build_row_payloads(parsed),
        )
        refresh = getattr(self.repository, "refresh_linked_archive_metadata_from_upload", None)
        if callable(refresh):
            refresh(metadata_upload_id=metadata_upload_id, user_id=user_id)
        known_files = self._discover_known_archive_slugs(user_id=user_id)
        return self._build_result(
            metadata_upload_id=metadata_upload_id,
            source_file_name=str(source_file_name or "").strip(),
            parsed=parsed,
            upload_record=upload_record,
            known_files=known_files,
        )
