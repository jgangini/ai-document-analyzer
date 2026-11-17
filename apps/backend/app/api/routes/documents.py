"""Routes for document upload, preparation, processing, and browsing."""

from __future__ import annotations

import base64
from datetime import date, datetime, timezone
from decimal import Decimal
import mimetypes
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from apps.backend.app.contracts.files import (
    FileAccessUpdateRequest,
    FileBulkAccessUpdateRequest,
    FileBulkDeleteRequest,
    FileBulkMutationResponse,
    FileDetailResponse,
    FileListResponse,
    FilePageSummary,
    FilePrepareError,
    FilePrepareGroup,
    FilePrepareItem,
    FilePrepareRequest,
    FilePrepareResponse,
    FileProcessBatchRequest,
    FileProcessItem,
    FileProcessRequest,
    FileSummary,
    IngestJobCreateResponse,
    IngestJobStatusResponse,
    IngestJobSummary,
    IngestPlanCreateResponse,
    UploadResponse,
)
from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.config import BACKEND_ROOT, get_settings
from apps.backend.app.core.security import get_current_user, get_optional_current_user
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.ingest.archive_service import ArchiveService
from apps.backend.app.ingest.ingest_runner import get_ingest_job_registry
from apps.backend.app.ingest.upload_preparation_service import UploadPreparationService
from apps.backend.app.repositories.file_repository import FileRepository
from apps.backend.app.storage.object_storage_service import ObjectStorageService

router = APIRouter(
    prefix="/files",
    tags=["files"],
    dependencies=[Depends(require_setup_completed)],
)


def _get_repository() -> FileRepository:
    return FileRepository(get_db_manager())


def _read_local_image_data_uri(image_path: object | None) -> str | None:
    raw_path = str(image_path or "").strip()
    if not raw_path:
        return None

    path = Path(raw_path)
    settings = get_settings()
    if not path.is_absolute():
        candidates = [BACKEND_ROOT / path, settings.page_image_path / path]
    else:
        candidates = [path]

    image_file = next((candidate for candidate in candidates if candidate.exists() and candidate.is_file()), None)
    if image_file is None:
        return None

    mime = mimetypes.guess_type(image_file.name)[0] or "image/png"
    encoded = base64.b64encode(image_file.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _coerce_int(value: object | None, default: int = 0) -> int:
    """Oracle NUMBER values may arrive as Decimal objects."""
    try:
        if value is None:
            return default
        if isinstance(value, bool):
            return default
        if isinstance(value, Decimal):
            return int(value)
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return default


def _as_datetime(value: object | None) -> datetime:
    """Ensure a datetime value for API serialization."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date) and not isinstance(value, datetime):
        return datetime.combine(value, datetime.min.time(), tzinfo=timezone.utc)
    return datetime.now(timezone.utc)


def _status_from_code(value: object | None) -> str:
    mapping = {1: "registered", 2: "processing", 3: "completed", -1: "failed", 0: "disabled"}
    return mapping.get(_coerce_int(value, 1), "registered")


def _dedupe_positive_ints(values: list[int] | None) -> list[int]:
    seen: set[int] = set()
    ordered: list[int] = []
    for raw_value in list(values or []):
        value = _coerce_int(raw_value, 0)
        if value <= 0 or value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


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
    request_user_id: int | None,
) -> int:
    resolved_user_id: int | None = None
    if current_user is not None:
        resolved_user_id = _safe_user_id_from_jwt(current_user)
        if resolved_user_id is None:
            token_username = str(
                current_user.get("username")
                or current_user.get("sub")
                or ""
            ).strip()
            if token_username:
                resolved_user_id = repository.find_user_id_by_username(username=token_username)
    if resolved_user_id is None and request_user_id is not None:
        resolved_user_id = int(request_user_id)
    if resolved_user_id is None or resolved_user_id < 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required to process documents (valid user_id).",
        )
    return resolved_user_id


def _normalize_access_profiles(value: object) -> list[str]:
    raw_profiles = value if isinstance(value, list) else [value]
    normalized: list[str] = []
    for raw_value in raw_profiles:
        candidate = str(raw_value or "").strip().lower()
        if not candidate:
            continue
        if candidate not in {"private", "all"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported access profile: {candidate}",
            )
        if candidate not in normalized:
            normalized.append(candidate)
    if not normalized:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least one access profile is required.",
        )
    if "all" in normalized:
        return ["all"]
    return ["private"]


def _access_scope_from_profiles(value: object) -> str:
    normalized_profiles = _normalize_access_profiles(value)
    return "all" if "all" in normalized_profiles else "private"


def _access_profiles_from_scope(value: object | None) -> list[str]:
    normalized_scope = str(value or "").strip().lower()
    if normalized_scope == "all":
        return ["all"]
    return ["private"]


def _get_owned_file_record(
    *,
    repository: FileRepository,
    file_id: int,
    user_id: int,
) -> dict:
    file_record = repository.get_file(file_id)
    if not file_record or _coerce_int(file_record.get("user_id"), -1) != int(user_id):
        raise HTTPException(status_code=404, detail="File not found")
    return file_record


def _get_accessible_file_record(
    *,
    repository: FileRepository,
    file_id: int,
    user_id: int,
) -> dict:
    file_record = repository.get_file(file_id)
    if not file_record:
        raise HTTPException(status_code=404, detail="File not found")
    owner_user_id = _coerce_int(file_record.get("user_id"), -1)
    access_scope = str(file_record.get("access_scope") or "private").strip().lower()
    if owner_user_id == int(user_id):
        return file_record
    if int(user_id) > 0 and access_scope == "all":
        return file_record
    raise HTTPException(status_code=404, detail="File not found")


def _map_file_summary(item: dict) -> FileSummary:
    return FileSummary(
        file_id=_coerce_int(item.get("file_id"), 0),
        user_id=_coerce_int(item.get("user_id"), 0),
        file_name=str(item.get("file_input_file_name") or ""),
        file_input_obj_name=str(item.get("file_input_obj_name") or ""),
        file_output_obj_name=str(item.get("file_output_obj_name") or ""),
        archive_slug=(str(item.get("archive_slug") or "").strip() or None),
        document_code=(str(item.get("file_code") or "").strip() or None),
        document_code_source=str(item.get("file_code_source") or "none"),
        access_profiles=_access_profiles_from_scope(item.get("access_scope")),
        page_count=_coerce_int(item.get("file_page_count"), 0),
        status=_status_from_code(item.get("file_state")),
        created_at=_as_datetime(item.get("file_created")),
        updated_at=_as_datetime(item.get("file_updated")),
    )


def _map_page_summary(item: dict) -> FilePageSummary:
    return FilePageSummary(
        file_pages_id=_coerce_int(item.get("file_pages_id"), 0),
        file_id=_coerce_int(item.get("file_id"), 0),
        user_id=_coerce_int(item.get("user_id"), 0),
        page_number=_coerce_int(item.get("file_pages_number"), 0),
        image_path_local=str(item.get("file_pages_image_path_local") or ""),
        file_pages_output_obj_name=str(item.get("file_pages_output_obj_name") or ""),
        file_pages_ocr_obj_name=str(item.get("file_pages_ocr_obj_name") or ""),
        file_pages_ocr_confidence=(
            float(item["file_pages_ocr_confidence"])
            if item.get("file_pages_ocr_confidence") is not None
            else None
        ),
        file_pages_ocr_method=str(item.get("file_pages_ocr_method") or ""),
        width=_coerce_int(item.get("file_pages_width"), 0),
        height=_coerce_int(item.get("file_pages_height"), 0),
        ocr_text=str(item.get("file_pages_ocr_text") or ""),
        created_at=_as_datetime(item.get("file_pages_created")),
    )


def _resolve_retry_source_path(*, file_record: dict) -> Path:
    settings = get_settings()
    file_name = str(file_record.get("file_input_file_name") or "").strip() or "document.pdf"
    source_hint = str(file_record.get("file_input_obj_name") or "").strip()

    if source_hint:
        source_path = Path(source_hint)
        if source_path.exists():
            return source_path

    object_name = source_hint
    if not object_name:
        raise RuntimeError("No object name available to retry document ingestion.")
    safe_name = Path(file_name).name
    target_path = settings.staging_path / "retry" / uuid.uuid4().hex[:12] / safe_name
    object_storage = ObjectStorageService(settings)
    return object_storage.download_file(object_name=object_name, local_path=target_path)


def _extract_archive_slug_from_object_name(object_name: str) -> str | None:
    normalized = str(object_name or "").strip().strip("/")
    if not normalized:
        return None
    parts = normalized.split("/")
    if len(parts) < 4:
        return None
    if parts[2].lower() != "source":
        return None
    slug = parts[1].strip()
    return slug or None


def _to_job_summary(job) -> IngestJobSummary:
    return IngestJobSummary(
        job_id=str(job.job_id),
        status=str(job.status),
        created_at=job.created_at if isinstance(job.created_at, datetime) else _as_datetime(job.created_at),
        updated_at=job.updated_at if isinstance(job.updated_at, datetime) else _as_datetime(job.updated_at),
        error=None if job.error is None else str(job.error),
    )


def _normalize_process_items(processed: list) -> list[FileProcessItem]:
    """Normalize ingestion items so API responses stay JSON-serializable."""
    out: list[FileProcessItem] = []
    for item in processed:
        if isinstance(item, FileProcessItem):
            out.append(
                FileProcessItem(
                    file_id=_coerce_int(item.file_id, 0),
                    file_name=str(item.file_name or ""),
                    status=str(item.status or ""),
                    page_count=_coerce_int(item.page_count, 0),
                    object_name=str(item.object_name or ""),
                    telemetry=dict(item.telemetry or {}) if item.telemetry else None,
                    error=None if item.error is None else str(item.error),
                )
            )
            continue
        if isinstance(item, dict):
            out.append(
                FileProcessItem(
                    file_id=_coerce_int(item.get("file_id"), 0),
                    file_name=str(item.get("file_name") or ""),
                    status=str(item.get("status") or ""),
                    page_count=_coerce_int(item.get("page_count"), 0),
                    object_name=str(item.get("object_name") or ""),
                    telemetry=(
                        dict(item.get("telemetry") or {})
                        if isinstance(item.get("telemetry"), dict)
                        else None
                    ),
                    error=(str(item.get("error")) if item.get("error") is not None else None),
                )
            )
            continue
        out.append(FileProcessItem.model_validate(item))
    return out


@router.post("/upload", response_model=UploadResponse)
async def upload_files(files: list[UploadFile] = File(...)) -> UploadResponse:
    settings = get_settings()
    settings.upload_path.mkdir(parents=True, exist_ok=True)
    saved_files: list[str] = []
    for upload in files:
        file_name = upload.filename or "upload.bin"
        upload_dir = settings.upload_path / uuid.uuid4().hex[:12]
        upload_dir.mkdir(parents=True, exist_ok=True)
        target = upload_dir / Path(file_name).name
        content = await upload.read()
        target.write_bytes(content)
        saved_files.append(str(target))
    return UploadResponse(saved_files=saved_files)


@router.post("/prepare", response_model=FilePrepareResponse)
def prepare_files(request: FilePrepareRequest) -> FilePrepareResponse:
    settings = get_settings()
    service = UploadPreparationService(
        settings=settings,
        archive_service=ArchiveService(settings),
        db_manager=get_db_manager(),
    )
    result = service.prepare_saved_files(
        saved_files=list(request.saved_files),
        default_document_language=request.default_document_language,
        default_access=request.default_access,
    )
    return FilePrepareResponse(
        groups=[
            FilePrepareGroup(
                group_source_path=group.group_source_path,
                group_name=group.group_name,
                group_kind=group.group_kind,
                archive_slug=group.archive_slug,
                item_count=group.item_count,
                items=[
                    FilePrepareItem(
                        source_path=item.source_path,
                        source_zip_path=item.source_zip_path,
                        group_source_path=item.group_source_path,
                        group_name=item.group_name,
                        group_kind=item.group_kind,
                        archive_slug=item.archive_slug,
                        file_name=item.file_name,
                        display_name=item.display_name,
                        document_code=item.document_code,
                        document_code_source=item.document_code_source,
                        document_language=item.document_language,
                        access=item.access,
                        order=item.order,
                        enabled=item.enabled,
                    )
                    for item in group.items
                ],
            )
            for group in result.groups
        ],
        errors=[
            FilePrepareError(
                source_path=error.source_path,
                source_name=error.source_name,
                error=error.error,
            )
            for error in result.errors
        ],
    )


@router.post("/process", response_model=IngestJobCreateResponse)
def process_files(
    request: FileProcessRequest,
    current_user: dict | None = Depends(get_optional_current_user),
) -> IngestJobCreateResponse:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=request.user_id,
    )

    metadata_override: dict[str, object] = {}
    if "document_code" in request.model_fields_set:
        metadata_override["document_code"] = request.document_code
    if "document_code_source" in request.model_fields_set:
        metadata_override["document_code_source"] = request.document_code_source

    job_registry = get_ingest_job_registry()
    job = job_registry.create_job(
        source_path=request.source_path,
        include_archives=request.include_archives,
        limit=request.limit,
        user_id=resolved_user_id,
        document_language=request.document_language,
        access_scope=_access_scope_from_profiles(request.access_profile or "private"),
        forced_archive_slug=None,
        forced_object_name=None,
        source_zip_path=request.source_zip_path,
        metadata_override=metadata_override,
    )
    job_registry.start(job.job_id)
    return IngestJobCreateResponse(job=_to_job_summary(job))


@router.post("/process-batch", response_model=IngestPlanCreateResponse)
def process_files_batch(
    request: FileProcessBatchRequest,
    current_user: dict | None = Depends(get_optional_current_user),
) -> IngestPlanCreateResponse:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )

    process_items = [item.model_dump(exclude_none=True) for item in request.items if item.enabled]
    if not process_items:
        raise HTTPException(status_code=400, detail="At least one enabled file is required.")

    replace_file_ids = _dedupe_positive_ints(request.replace_file_ids)
    if replace_file_ids:
        repository.delete_files(file_ids=replace_file_ids, user_id=resolved_user_id)

    job_registry = get_ingest_job_registry()
    job = job_registry.create_plan_job(
        process_items=process_items,
        user_id=resolved_user_id,
        metadata_upload_id=(str(request.metadata_upload_id or "").strip() or None),
    )
    job_registry.start(job.job_id)
    return IngestPlanCreateResponse(job=_to_job_summary(job), queued_files=len(process_items))


@router.get("/jobs/{job_id}", response_model=IngestJobStatusResponse)
def get_process_job(job_id: str) -> IngestJobStatusResponse:
    job_registry = get_ingest_job_registry()
    job = job_registry.get(job_id)
    if job is None:
        now = datetime.now(timezone.utc)
        return IngestJobStatusResponse(
            job=IngestJobSummary(
                job_id=job_id,
                status="completed",
                created_at=now,
                updated_at=now,
                error="Ingest job not found (likely backend restart/reload).",
            ),
            processed=[],
        )
    return IngestJobStatusResponse(job=_to_job_summary(job), processed=_normalize_process_items(list(job.processed)))


@router.get("", response_model=FileListResponse)
def list_files(current_user: dict = Depends(get_current_user)) -> FileListResponse:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    items = repository.list_files_for_user(user_id=resolved_user_id, include_shared=True)
    return FileListResponse(items=[_map_file_summary(item) for item in items])


@router.put("/bulk/access", response_model=FileBulkMutationResponse)
def bulk_update_files_access(
    request: FileBulkAccessUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> FileBulkMutationResponse:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    file_ids = _dedupe_positive_ints(request.file_ids)
    if not file_ids:
        raise HTTPException(status_code=400, detail="At least one file_id is required.")
    affected = repository.update_files_access_scope(
        file_ids=file_ids,
        user_id=resolved_user_id,
        access_scope=_access_scope_from_profiles(request.access_profiles),
    )
    return FileBulkMutationResponse(
        success=True,
        requested=len(file_ids),
        affected=affected,
    )


@router.post("/bulk/delete", response_model=FileBulkMutationResponse)
def bulk_delete_files(
    request: FileBulkDeleteRequest,
    current_user: dict = Depends(get_current_user),
) -> FileBulkMutationResponse:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    file_ids = _dedupe_positive_ints(request.file_ids)
    if not file_ids:
        raise HTTPException(status_code=400, detail="At least one file_id is required.")
    affected = repository.delete_files(file_ids=file_ids, user_id=resolved_user_id)
    return FileBulkMutationResponse(
        success=True,
        requested=len(file_ids),
        affected=affected,
    )


@router.get("/{file_id}", response_model=FileDetailResponse)
def get_file(file_id: int, current_user: dict = Depends(get_current_user)) -> FileDetailResponse:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    file_record = _get_accessible_file_record(
        repository=repository,
        file_id=file_id,
        user_id=resolved_user_id,
    )
    pages = repository.get_pages_by_file(file_id)
    return FileDetailResponse(
        file=_map_file_summary(file_record),
        pages=[_map_page_summary(page) for page in pages],
    )


@router.get("/{file_id}/pages", response_model=list[FilePageSummary])
def get_file_pages(file_id: int, current_user: dict = Depends(get_current_user)) -> list[FilePageSummary]:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    _get_accessible_file_record(repository=repository, file_id=file_id, user_id=resolved_user_id)
    return [_map_page_summary(page) for page in repository.get_pages_by_file(file_id)]


@router.put("/{file_id}", response_model=FileBulkMutationResponse)
def update_file(
    file_id: int,
    payload: FileAccessUpdateRequest,
    current_user: dict = Depends(get_current_user),
) -> FileBulkMutationResponse:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    updated = repository.update_file_access_scope(
        file_id=int(file_id),
        user_id=resolved_user_id,
        access_scope=_access_scope_from_profiles(payload.access_profiles),
    )
    if not updated:
        raise HTTPException(status_code=404, detail="File not found")
    return FileBulkMutationResponse(success=True, requested=1, affected=1)


@router.delete("/{file_id}", response_model=FileBulkMutationResponse)
def delete_file(file_id: int, current_user: dict = Depends(get_current_user)) -> FileBulkMutationResponse:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    if not repository.delete_file(file_id=file_id, user_id=resolved_user_id):
        raise HTTPException(status_code=404, detail="File not found")
    return FileBulkMutationResponse(success=True, requested=1, affected=1)


@router.post("/{file_id}/retry")
def retry_file(file_id: int, current_user: dict = Depends(get_current_user)) -> dict:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    file_record = _get_owned_file_record(
        repository=repository,
        file_id=file_id,
        user_id=resolved_user_id,
    )
    try:
        source_path = _resolve_retry_source_path(file_record=file_record)
    except Exception as exc:
        repository.update_file_status(file_id=int(file_id), status="failed")
        raise HTTPException(status_code=503, detail=f"Retry source preparation failed: {exc}") from exc

    job_registry = get_ingest_job_registry()
    job = job_registry.create_job(
        source_path=str(source_path),
        include_archives=True,
        limit=1,
        user_id=int(file_record.get("user_id") or 0),
        document_language=None,
        access_scope=str(file_record.get("access_scope") or "private"),
        forced_archive_slug=_extract_archive_slug_from_object_name(str(file_record.get("file_input_obj_name") or "")),
        forced_object_name=str(file_record.get("file_input_obj_name") or ""),
        source_zip_path=None,
        metadata_override=None,
    )
    job_registry.start(job.job_id)
    return {"success": True, "job_id": job.job_id, "status": job.status}


@router.get("/{file_id}/markdown")
def get_file_markdown(file_id: int, current_user: dict = Depends(get_current_user)) -> dict:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    _get_accessible_file_record(repository=repository, file_id=file_id, user_id=resolved_user_id)
    try:
        markdown = repository.get_file_markdown(file_id=file_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"markdown": markdown}


@router.get("/{file_id}/pages/{page_number}/image")
def get_file_page_image(
    file_id: int,
    page_number: int,
    current_user: dict = Depends(get_current_user),
) -> dict:
    repository = _get_repository()
    resolved_user_id = _resolve_authenticated_user_id(
        repository=repository,
        current_user=current_user,
        request_user_id=None,
    )
    _get_accessible_file_record(repository=repository, file_id=file_id, user_id=resolved_user_id)

    selected_page = repository.get_page_image_record(file_id=file_id, page_number=page_number)
    if selected_page is None:
        raise HTTPException(status_code=404, detail="Page not found")

    local_data_uri = _read_local_image_data_uri(selected_page.get("file_pages_image_path_local"))
    if local_data_uri:
        return {
            "file_id": int(file_id),
            "page_number": int(page_number),
            "object_name_page": str(selected_page.get("file_pages_output_obj_name") or "").strip(),
            "data_uri": local_data_uri,
            "source": "local",
        }

    object_name_page = str(selected_page.get("file_pages_output_obj_name") or "").strip()
    if not object_name_page:
        raise HTTPException(status_code=404, detail="Page image object is not available")

    object_storage = ObjectStorageService(get_settings())
    try:
        data_uri = object_storage.get_object_data_uri(object_name_page)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not data_uri:
        raise HTTPException(status_code=404, detail="Could not load page image")

    return {
        "file_id": int(file_id),
        "page_number": int(page_number),
        "object_name_page": object_name_page,
        "data_uri": data_uri,
        "source": "object_storage",
    }
