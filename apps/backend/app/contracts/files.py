"""Schemas for file ingestion and file browsing APIs."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from apps.backend.app.contracts.common import APIModel


class FileProcessRequest(BaseModel):
    source_path: str | None = None
    include_archives: bool = True
    limit: int | None = Field(default=None, ge=1)
    user_id: int | None = Field(default=None, ge=0)
    document_language: str | None = Field(default=None, min_length=2, max_length=16)
    source_zip_path: str | None = None
    document_code: str | None = Field(default=None, max_length=64)
    document_code_source: str | None = Field(default=None, max_length=32)
    access_profile: str | None = Field(default=None, max_length=32)


class FilePrepareRequest(BaseModel):
    saved_files: list[str] = Field(default_factory=list, min_length=1)
    default_document_language: str | None = Field(default=None, min_length=2, max_length=16)
    default_access: str | None = Field(default=None, max_length=32)


class FilePrepareItem(APIModel):
    source_path: str
    source_zip_path: str | None = None
    group_source_path: str
    group_name: str
    group_kind: str
    archive_slug: str
    file_name: str
    display_name: str
    document_code: str | None = None
    document_code_source: str = "none"
    document_language: str = "es"
    access: str = "private"
    order: int = 0
    enabled: bool = True


class FilePrepareGroup(APIModel):
    group_source_path: str
    group_name: str
    group_kind: str
    archive_slug: str
    item_count: int
    items: list[FilePrepareItem]


class FilePrepareError(APIModel):
    source_path: str
    source_name: str
    error: str


class FilePrepareResponse(APIModel):
    groups: list[FilePrepareGroup]
    errors: list[FilePrepareError] = Field(default_factory=list)


class FileProcessPlanItem(BaseModel):
    source_path: str
    source_zip_path: str | None = None
    archive_slug: str | None = None
    file_name: str
    group_name: str | None = None
    display_name: str | None = None
    document_language: str | None = Field(default=None, min_length=2, max_length=16)
    access: str | None = Field(default=None, max_length=32)
    document_code: str | None = Field(default=None, max_length=64)
    document_code_source: str | None = Field(default=None, max_length=32)
    enabled: bool = True


class FileProcessBatchRequest(BaseModel):
    metadata_upload_id: str | None = Field(default=None, max_length=64)
    replace_file_ids: list[int] = Field(default_factory=list)
    items: list[FileProcessPlanItem] = Field(default_factory=list, min_length=1)


class FileAccessUpdateRequest(BaseModel):
    access_profiles: list[str] = Field(default_factory=list, min_length=1)


class FileBulkAccessUpdateRequest(BaseModel):
    file_ids: list[int] = Field(default_factory=list, min_length=1)
    access_profiles: list[str] = Field(default_factory=list, min_length=1)


class FileBulkDeleteRequest(BaseModel):
    file_ids: list[int] = Field(default_factory=list, min_length=1)


class FileSummary(APIModel):
    file_id: int
    user_id: int
    file_name: str
    file_input_obj_name: str
    file_output_obj_name: str
    archive_slug: str | None = None
    document_code: str | None = None
    document_code_source: str = "none"
    access_profiles: list[str] = Field(default_factory=lambda: ["private"])
    page_count: int
    status: str
    created_at: datetime
    updated_at: datetime


class FilePageSummary(APIModel):
    file_pages_id: int
    file_id: int
    user_id: int
    page_number: int
    image_path_local: str
    file_pages_output_obj_name: str
    file_pages_ocr_obj_name: str = ""
    file_pages_ocr_confidence: float | None = None
    file_pages_ocr_method: str = ""
    width: int
    height: int
    ocr_text: str
    created_at: datetime


class FileListResponse(APIModel):
    items: list[FileSummary]


class FileDetailResponse(APIModel):
    file: FileSummary
    pages: list[FilePageSummary]


class FileProcessItem(APIModel):
    file_id: int
    file_name: str
    status: str
    page_count: int
    object_name: str
    telemetry: dict[str, object] | None = None
    error: str | None = None


class FileProcessResponse(APIModel):
    processed: list[FileProcessItem]


class UploadResponse(APIModel):
    saved_files: list[str]


class IngestJobSummary(APIModel):
    job_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    error: str | None = None


class IngestJobCreateResponse(APIModel):
    job: IngestJobSummary


class IngestPlanCreateResponse(APIModel):
    job: IngestJobSummary
    queued_files: int


class IngestJobStatusResponse(APIModel):
    job: IngestJobSummary
    processed: list[FileProcessItem]


class FileBulkMutationResponse(APIModel):
    success: bool = True
    requested: int
    affected: int
