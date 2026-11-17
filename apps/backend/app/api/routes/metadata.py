"""Metadata catalog routes for canonical CSV ingestion keyed by archive slug."""

from __future__ import annotations

from datetime import date, datetime, time, timezone
import json
from pathlib import Path
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status

from apps.backend.app.contracts.metadata import (
    MetadataUploadDetailResponse,
    MetadataUploadListResponse,
    MetadataUploadMatchSummary,
    MetadataUploadResponse,
    MetadataUploadRowPreview,
    MetadataUploadSummary,
    MetadataUploadUpdateRequest,
)
from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.security import get_optional_current_user
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.repositories.archive_metadata_repository import ArchiveMetadataRepository
from apps.backend.app.repositories.file_repository import FileRepository
from apps.backend.app.services.metadata_upload_service import (
    MetadataUploadService,
    MetadataUploadValidationError,
)

router = APIRouter(
    prefix="/metadata",
    tags=["metadata"],
    dependencies=[Depends(require_setup_completed)],
)


def _read_lob_value(value: Any) -> Any:
    if hasattr(value, "read"):
        try:
            return value.read()
        except Exception:
            return value
    return value


def _coerce_datetime(value: Any) -> datetime:
    value = _read_lob_value(value)
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, time.min).replace(tzinfo=timezone.utc)
    if value:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            return parsed
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def _parse_columns(raw_value: Any) -> list[str]:
    raw_value = _read_lob_value(raw_value)
    if isinstance(raw_value, (list, tuple)):
        candidates = list(raw_value)
    else:
        try:
            parsed = json.loads(str(raw_value or "[]"))
        except Exception:
            parsed = []
        candidates = parsed if isinstance(parsed, list) else []
    return [str(item or "").strip() for item in candidates if str(item or "").strip()]


def _normalize_access_scope(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not normalized:
        return "private"
    if normalized in {"private", "all"}:
        return normalized
    raise HTTPException(status_code=400, detail="Metadata access_scope must be private or all.")


def _parse_row_preview(row: dict[str, Any]) -> MetadataUploadRowPreview:
    raw_payload = _read_lob_value(row.get("row_json"))
    payload: dict[str, Any]
    try:
        parsed = json.loads(str(raw_payload or "{}"))
        payload = parsed if isinstance(parsed, dict) else {}
    except Exception:
        payload = {}
    file_key = str(payload.get("file") or row.get("file_key") or "").strip()
    fields = payload.get("fields")
    return MetadataUploadRowPreview(
        file=file_key,
        fields=dict(fields) if isinstance(fields, dict) else {},
    )


def _map_upload_summary(row: dict[str, Any]) -> MetadataUploadSummary:
    created_at = _coerce_datetime(row.get("metadata_upload_created") or row.get("created_at"))
    updated_at = _coerce_datetime(
        row.get("metadata_upload_updated")
        or row.get("updated_at")
        or row.get("metadata_upload_created")
        or row.get("created_at")
    )
    total_rows = int(row.get("total_rows") or row.get("row_count") or 0)
    row_count = int(row.get("row_count") or total_rows)
    return MetadataUploadSummary(
        metadata_upload_id=str(row.get("metadata_upload_id") or "").strip(),
        owner_user_id=int(row.get("user_id") or 0),
        source_file_name=str(row.get("source_file_name") or "").strip(),
        display_name=str(row.get("display_name") or row.get("source_file_name") or "").strip(),
        description=str(_read_lob_value(row.get("description")) or "").strip(),
        access_scope=_normalize_access_scope(str(row.get("access_scope") or "private")),
        metadata_status=str(row.get("metadata_status") or "active").strip() or "active",
        columns=_parse_columns(row.get("column_names_json")),
        total_rows=total_rows,
        row_count=row_count,
        matched_files_count=int(row.get("matched_files_count") or 0),
        unmatched_files_count=int(row.get("unmatched_files_count") or max(total_rows - int(row.get("matched_files_count") or 0), 0)),
        linked_documents_count=int(row.get("linked_documents_count") or 0),
        created_at=created_at,
        updated_at=updated_at,
    )


def _upload_response_from_result(result: Any) -> MetadataUploadResponse:
    return MetadataUploadResponse(
        metadata_upload_id=result.metadata_upload_id,
        source_file_name=result.source_file_name,
        display_name=result.display_name,
        description=result.description,
        access_scope=result.access_scope,
        metadata_status=result.metadata_status,
        created_at=result.created_at,
        columns=result.columns,
        total_rows=result.total_rows,
        match_summary=MetadataUploadMatchSummary(
            matched_files=result.matched_files,
            unmatched_files=result.unmatched_files,
            duplicate_files=result.duplicate_files,
        ),
    )


def _safe_user_id_from_jwt(current_user: dict) -> int | None:
    raw = current_user.get("user_id")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        uid = int(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return uid if uid >= 0 else None


def _resolve_authenticated_user_id(
    *,
    repository: FileRepository,
    current_user: dict | None,
) -> int:
    resolved_user_id: int | None = None
    if current_user is not None:
        resolved_user_id = _safe_user_id_from_jwt(current_user)
        if resolved_user_id is None:
            token_username = str(current_user.get("username") or current_user.get("sub") or "").strip()
            if token_username:
                resolved_user_id = repository.find_user_id_by_username(username=token_username)
    if resolved_user_id is None or resolved_user_id < 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to upload metadata CSV.",
        )
    return resolved_user_id


def _metadata_repository() -> ArchiveMetadataRepository:
    return ArchiveMetadataRepository(get_db_manager())


def _metadata_service(*, repository: ArchiveMetadataRepository | None = None) -> MetadataUploadService:
    return MetadataUploadService(
        settings=get_settings(),
        repository=repository or _metadata_repository(),
    )


def _save_upload_file(file: UploadFile) -> tuple[Path, str]:
    file_name = str(file.filename or "").strip() or "metadata.csv"
    if not file_name.lower().endswith(".csv"):
        raise HTTPException(status_code=400, detail="Only CSV metadata files are supported.")

    settings = get_settings()
    metadata_dir = settings.upload_path / "metadata" / uuid.uuid4().hex[:12]
    metadata_dir.mkdir(parents=True, exist_ok=True)
    return metadata_dir / Path(file_name).name, file_name


async def _persist_uploaded_csv(file: UploadFile) -> tuple[Path, str]:
    saved_path, file_name = _save_upload_file(file)
    content = await file.read()
    saved_path.write_bytes(content)
    return saved_path, file_name


@router.post("/upload", response_model=MetadataUploadResponse)
async def upload_metadata_csv(
    file: UploadFile = File(...),
    display_name: str | None = Form(default=None),
    description: str | None = Form(default=None),
    access_scope: str = Form(default="private"),
    current_user: dict | None = Depends(get_optional_current_user),
) -> MetadataUploadResponse:
    repository = FileRepository(get_db_manager())
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
    )
    saved_path, file_name = await _persist_uploaded_csv(file)

    service = _metadata_service()
    try:
        result = service.upload_csv(
            user_id=resolved_user_id,
            csv_path=saved_path,
            source_file_name=file_name,
            display_name=display_name,
            description=description,
            access_scope=_normalize_access_scope(access_scope),
        )
    except MetadataUploadValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _upload_response_from_result(result)


@router.get("/uploads", response_model=MetadataUploadListResponse)
def list_metadata_uploads(
    include_archived: bool = Query(default=True),
    search: str | None = Query(default=None, max_length=200),
    current_user: dict | None = Depends(get_optional_current_user),
) -> MetadataUploadListResponse:
    file_repository = FileRepository(get_db_manager())
    resolved_user_id = _resolve_authenticated_user_id(
        repository=file_repository,
        current_user=current_user,
    )
    repository = _metadata_repository()
    rows = repository.list_uploads_for_user(
        user_id=resolved_user_id,
        include_archived=include_archived,
        search_text=search,
    )
    return MetadataUploadListResponse(items=[_map_upload_summary(row) for row in rows])


@router.get("/uploads/{metadata_upload_id}", response_model=MetadataUploadDetailResponse)
def get_metadata_upload(
    metadata_upload_id: str,
    row_limit: int = Query(default=100, ge=1, le=1000),
    current_user: dict | None = Depends(get_optional_current_user),
) -> MetadataUploadDetailResponse:
    file_repository = FileRepository(get_db_manager())
    resolved_user_id = _resolve_authenticated_user_id(
        repository=file_repository,
        current_user=current_user,
    )
    repository = _metadata_repository()
    summaries = repository.list_uploads_for_user(
        user_id=resolved_user_id,
        include_archived=True,
        search_text=None,
    )
    summary_row = next(
        (
            row
            for row in summaries
            if str(row.get("metadata_upload_id") or "").strip() == str(metadata_upload_id or "").strip()
        ),
        None,
    )
    if summary_row is None:
        raise HTTPException(status_code=404, detail="Metadata dataset not found.")

    rows = repository.list_upload_rows(
        metadata_upload_id=metadata_upload_id,
        user_id=int(summary_row.get("user_id") or resolved_user_id),
        limit=row_limit,
    )
    summary = _map_upload_summary(summary_row)
    return MetadataUploadDetailResponse(
        **summary.model_dump(),
        rows=[_parse_row_preview(row) for row in rows],
    )


@router.patch("/uploads/{metadata_upload_id}", response_model=MetadataUploadSummary)
def update_metadata_upload(
    metadata_upload_id: str,
    request: MetadataUploadUpdateRequest,
    current_user: dict | None = Depends(get_optional_current_user),
) -> MetadataUploadSummary:
    file_repository = FileRepository(get_db_manager())
    resolved_user_id = _resolve_authenticated_user_id(
        repository=file_repository,
        current_user=current_user,
    )
    repository = _metadata_repository()
    try:
        updated = repository.update_upload_catalog(
            metadata_upload_id=metadata_upload_id,
            user_id=resolved_user_id,
            display_name=request.display_name,
            description=request.description,
            metadata_status=request.metadata_status,
            access_scope=(
                _normalize_access_scope(request.access_scope)
                if "access_scope" in request.model_fields_set
                else None
            ),
            update_display_name="display_name" in request.model_fields_set,
            update_description="description" in request.model_fields_set,
            update_metadata_status="metadata_status" in request.model_fields_set,
            update_access_scope="access_scope" in request.model_fields_set,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if updated is None:
        raise HTTPException(status_code=404, detail="Metadata dataset not found.")

    rows = repository.list_uploads_for_user(
        user_id=resolved_user_id,
        include_archived=True,
        search_text=None,
    )
    summary_row = next(
        (
            row
            for row in rows
            if str(row.get("metadata_upload_id") or "").strip() == str(metadata_upload_id or "").strip()
        ),
        updated,
    )
    return _map_upload_summary(summary_row)


@router.put("/uploads/{metadata_upload_id}/file", response_model=MetadataUploadResponse)
async def replace_metadata_upload_csv(
    metadata_upload_id: str,
    file: UploadFile = File(...),
    current_user: dict | None = Depends(get_optional_current_user),
) -> MetadataUploadResponse:
    file_repository = FileRepository(get_db_manager())
    resolved_user_id = _resolve_authenticated_user_id(
        repository=file_repository,
        current_user=current_user,
    )
    saved_path, file_name = await _persist_uploaded_csv(file)

    service = _metadata_service()
    try:
        result = service.replace_csv(
            metadata_upload_id=metadata_upload_id,
            user_id=resolved_user_id,
            csv_path=saved_path,
            source_file_name=file_name,
        )
    except MetadataUploadValidationError as exc:
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 400
        raise HTTPException(status_code=status_code, detail=detail) from exc

    return _upload_response_from_result(result)


@router.delete("/uploads/{metadata_upload_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_metadata_upload(
    metadata_upload_id: str,
    current_user: dict | None = Depends(get_optional_current_user),
) -> Response:
    file_repository = FileRepository(get_db_manager())
    resolved_user_id = _resolve_authenticated_user_id(
        repository=file_repository,
        current_user=current_user,
    )
    repository = _metadata_repository()
    deleted = repository.delete_upload(metadata_upload_id=metadata_upload_id, user_id=resolved_user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Metadata dataset not found.")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
