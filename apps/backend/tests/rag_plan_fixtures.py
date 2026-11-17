from __future__ import annotations

from datetime import date
from importlib import import_module
from pathlib import Path

from apps.backend.app.api.contracts.questions import EvidenceItem


def _load_attr(module_name: str, attr_name: str):
    return getattr(import_module(module_name), attr_name)

__all__ = [
    "_RecordingInventoryFileRepository",
    "_RecordingScopeRepository",
    "_StubArchiveMetadataFileRepository",
    "_StubInventoryFileRepository",
    "_StubMetadataRepository",
    "_StubScopeRepository",
    "_build_ingestion_service_for_tests",
    "_build_metadata_upload_service",
    "_build_settings",
    "_make_evidence_item",
    "_normalize_sql_whitespace",
]


class _StubScopeRepository:
    def __init__(self) -> None:
        self._files_by_user = {
            7: [101, 102, 103, 104],
        }
        self._codes_by_user = {
            7: {
                "AI041": [101, 102],
                "RM797": [101, 102],
                "RM798": [103, 104],
            }
        }
        self._archive_slugs_by_user = {
            7: {
                "RM797_ID_1668": [101],
                "RM797_ID_5515": [102],
            }
        }
        self._file_names_by_user = {
            7: {
                "ai041.pdf": [101],
                "ai041_modificacion.pdf": [102],
            }
        }

    def filter_file_ids_for_user(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[int]:
        del include_shared
        allowed = set(self._files_by_user.get(int(user_id), []))
        return [file_id for file_id in file_ids if int(file_id) in allowed]

    def list_distinct_document_codes_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[str]:
        del include_shared
        return sorted(self._codes_by_user.get(int(user_id), {}).keys())

    def list_file_ids_for_document_codes(
        self,
        *,
        user_id: int,
        document_codes: list[str],
        include_shared: bool = False,
    ) -> list[int]:
        del include_shared
        resolved: list[int] = []
        for code in document_codes:
            resolved.extend(self._codes_by_user.get(int(user_id), {}).get(code, []))
        return resolved

    def list_known_archive_slugs_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[str]:
        del include_shared
        return sorted(self._archive_slugs_by_user.get(int(user_id), {}).keys())

    def list_file_ids_for_archive_slugs(
        self,
        *,
        user_id: int,
        archive_slugs: list[str],
        include_shared: bool = False,
    ) -> list[int]:
        del include_shared
        resolved: list[int] = []
        for archive_slug in archive_slugs:
            resolved.extend(self._archive_slugs_by_user.get(int(user_id), {}).get(archive_slug, []))
        return resolved

    def list_file_ids_for_input_filenames(
        self,
        *,
        user_id: int,
        file_names: list[str],
        file_ids: list[int] | None = None,
        include_shared: bool = False,
    ) -> list[int]:
        del include_shared
        allowed = {int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0}
        resolved: list[int] = []
        for file_name in file_names:
            for file_id in self._file_names_by_user.get(int(user_id), {}).get(str(file_name).lower(), []):
                if allowed and int(file_id) not in allowed:
                    continue
                resolved.append(int(file_id))
        return resolved

    def get_archive_slug_map_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> dict[int, str]:
        del include_shared
        allowed = {int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0}
        resolved: dict[int, str] = {}
        for archive_slug, scoped_file_ids in self._archive_slugs_by_user.get(int(user_id), {}).items():
            for file_id in scoped_file_ids:
                if int(file_id) in allowed:
                    resolved[int(file_id)] = str(archive_slug)
        return resolved

    def count_files_for_user(self, *, user_id: int, include_shared: bool = False) -> int:
        del include_shared
        return len(self._files_by_user.get(int(user_id), []))

class _StubMetadataRepository:
    def __init__(self) -> None:
        self.created_uploads: list[dict[str, object]] = []
        self.replaced_rows: list[dict[str, object]] = []
        self.updated_uploads: list[dict[str, object]] = []
        self.refresh_calls: list[dict[str, object]] = []

    def list_known_archive_slugs_for_user(self, *, user_id: int, include_shared: bool = False) -> list[str]:
        del user_id
        del include_shared
        return ["RM797_ID_1668", "RM797_ID_5515"]

    def create_upload(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        source_file_name: str,
        columns: list[str],
        total_rows: int,
        display_name: str | None = None,
        description: str | None = None,
        access_scope: str | None = None,
    ) -> dict[str, object]:
        payload = {
            "metadata_upload_id": metadata_upload_id,
            "user_id": user_id,
            "source_file_name": source_file_name,
            "display_name": display_name or source_file_name,
            "description": description or "",
            "access_scope": access_scope or "private",
            "metadata_status": "active",
            "column_names_json": columns,
            "total_rows": total_rows,
        }
        self.created_uploads.append(payload)
        return {
            **payload,
            "metadata_upload_created": date(2026, 4, 21),
        }

    def replace_upload_rows(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        rows: list[dict[str, object]],
    ) -> None:
        self.replaced_rows.append(
            {
                "metadata_upload_id": metadata_upload_id,
                "user_id": user_id,
                "rows": rows,
            }
        )

    def update_upload_content(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        source_file_name: str,
        columns: list[str],
        total_rows: int,
    ) -> dict[str, object] | None:
        payload = {
            "metadata_upload_id": metadata_upload_id,
            "user_id": user_id,
            "source_file_name": source_file_name,
            "display_name": source_file_name,
            "description": "",
            "metadata_status": "active",
            "column_names_json": columns,
            "total_rows": total_rows,
            "metadata_upload_created": date(2026, 4, 21),
        }
        self.updated_uploads.append(payload)
        return payload

    def refresh_linked_archive_metadata_from_upload(self, *, metadata_upload_id: str, user_id: int) -> int:
        self.refresh_calls.append({"metadata_upload_id": metadata_upload_id, "user_id": user_id})
        return 0

class _StubArchiveMetadataFileRepository:
    def __init__(
        self,
        rows: list[dict[str, object]],
        *,
        file_rows: list[dict[str, object]] | None = None,
        page_quality_rows: list[dict[str, object]] | None = None,
    ) -> None:
        self.rows = [dict(row) for row in rows]
        self.file_rows = [dict(row) for row in list(file_rows or [])]
        self.page_quality_rows = [dict(row) for row in list(page_quality_rows or [])]

    def get_archive_metadata_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[dict[str, object]]:
        del user_id, include_shared
        allowed = {int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0}
        return [
            dict(row)
            for row in self.rows
            if int(row.get("file_id") or 0) in allowed
        ]

    def list_archive_metadata_for_user(self, *, user_id: int, include_shared: bool = False) -> list[dict[str, object]]:
        del user_id, include_shared
        return [dict(row) for row in self.rows]

    def get_archive_slug_map_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> dict[int, str]:
        del user_id, include_shared
        allowed = {int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0}
        return {
            int(row.get("file_id") or 0): str(row.get("archive_slug") or "")
            for row in self.rows
            if int(row.get("file_id") or 0) in allowed and str(row.get("archive_slug") or "").strip()
        }

    def list_files_for_user(self, *, user_id: int, include_shared: bool = False) -> list[dict[str, object]]:
        del user_id, include_shared
        return [dict(row) for row in self.file_rows]

    def list_page_quality_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[dict[str, object]]:
        del user_id, include_shared
        allowed = {int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0}
        return [
            dict(row)
            for row in self.page_quality_rows
            if int(row.get("file_id") or 0) in allowed
        ]

class _StubInventoryFileRepository:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = [dict(row) for row in rows]

    def list_files_for_user(self, *, user_id: int, include_shared: bool = False) -> list[dict[str, object]]:
        del user_id, include_shared
        return [dict(row) for row in self.rows]

class _RecordingScopeRepository(_StubScopeRepository):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, bool]] = []

    def filter_file_ids_for_user(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[int]:
        self.calls.append(("filter_file_ids_for_user", bool(include_shared)))
        return super().filter_file_ids_for_user(
            user_id=user_id,
            file_ids=file_ids,
            include_shared=include_shared,
        )

    def list_distinct_document_codes_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[str]:
        self.calls.append(("list_distinct_document_codes_for_user", bool(include_shared)))
        return super().list_distinct_document_codes_for_user(
            user_id=user_id,
            include_shared=include_shared,
        )

    def list_known_archive_slugs_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[str]:
        self.calls.append(("list_known_archive_slugs_for_user", bool(include_shared)))
        return super().list_known_archive_slugs_for_user(
            user_id=user_id,
            include_shared=include_shared,
        )

class _RecordingInventoryFileRepository(_StubInventoryFileRepository):
    def __init__(self, rows: list[dict[str, object]]) -> None:
        super().__init__(rows)
        self.include_shared_calls: list[bool] = []

    def list_files_for_user(self, *, user_id: int, include_shared: bool = False) -> list[dict[str, object]]:
        self.include_shared_calls.append(bool(include_shared))
        return super().list_files_for_user(user_id=user_id, include_shared=include_shared)

def _build_settings():
    Settings = _load_attr("apps.backend.app.core.config", "Settings")
    return Settings(_env_file=None)

def _make_evidence_item(
    *,
    file_id: int,
    file_name: str,
    page_id: int | None = None,
    source_number: int | None = None,
    page_number: int = 1,
    summary_text: str | None = None,
    score: float = 0.9,
    ocr_confidence: float = 0.95,
) -> EvidenceItem:
    resolved_page_id = int(page_id or file_id)
    return EvidenceItem(
        source_number=int(source_number or resolved_page_id),
        file_id=int(file_id),
        file_name=file_name,
        file_code=None,
        page_id=resolved_page_id,
        page_number=int(page_number),
        score=float(score),
        summary_text=summary_text or f"Evidencia OCR relevante para {file_name}.",
        image_path_local="",
        object_name_page="",
        extraction_method="docling_rapidocr",
        ocr_confidence=float(ocr_confidence),
    )

def _build_ingestion_service_for_tests():
    IngestionService = _load_attr("apps.backend.app.ingest.document_ingest_service", "IngestionService")
    return object.__new__(IngestionService)

def _build_metadata_upload_service(
    *,
    tmp_path: Path,
    repository: _StubMetadataRepository | None = None,
):
    Settings = _load_attr("apps.backend.app.core.config", "Settings")
    MetadataUploadService = _load_attr(
        "apps.backend.app.services.metadata_upload_service",
        "MetadataUploadService",
    )
    uploads_dir = tmp_path / "uploads"
    extracted_dir = tmp_path / "extracted"
    staging_dir = tmp_path / "staging"
    uploads_dir.mkdir()
    extracted_dir.mkdir()
    staging_dir.mkdir()
    settings = Settings(
        _env_file=None,
        UPLOAD_DIR=str(uploads_dir),
        EXTRACTED_DIR=str(extracted_dir),
        STAGING_DIR=str(staging_dir),
    )
    return MetadataUploadService(
        settings=settings,
        repository=repository or _StubMetadataRepository(),
    )

def _normalize_sql_whitespace(value: str) -> str:
    return " ".join(str(value or "").split())
