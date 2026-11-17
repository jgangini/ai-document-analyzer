"""Schemas for metadata upload and canonical CSV ingestion."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from apps.backend.app.contracts.common import APIModel


class MetadataUploadUpdateRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=300)
    description: str | None = Field(default=None, max_length=1000)
    metadata_status: str | None = Field(default=None, max_length=32)
    access_scope: str | None = Field(default=None, max_length=32)


class MetadataUploadMatchSummary(APIModel):
    matched_files: list[str] = Field(default_factory=list)
    unmatched_files: list[str] = Field(default_factory=list)
    duplicate_files: list[str] = Field(default_factory=list)


class MetadataUploadSummary(APIModel):
    metadata_upload_id: str
    owner_user_id: int = 0
    source_file_name: str
    display_name: str = ""
    description: str = ""
    access_scope: str = "private"
    metadata_status: str = "active"
    columns: list[str] = Field(default_factory=list)
    total_rows: int = 0
    row_count: int = 0
    matched_files_count: int = 0
    unmatched_files_count: int = 0
    linked_documents_count: int = 0
    created_at: datetime
    updated_at: datetime


class MetadataUploadRowPreview(APIModel):
    file: str
    fields: dict[str, object] = Field(default_factory=dict)


class MetadataUploadListResponse(APIModel):
    items: list[MetadataUploadSummary] = Field(default_factory=list)


class MetadataUploadDetailResponse(MetadataUploadSummary):
    rows: list[MetadataUploadRowPreview] = Field(default_factory=list)


class MetadataUploadResponse(APIModel):
    metadata_upload_id: str
    source_file_name: str
    display_name: str = ""
    description: str = ""
    access_scope: str = "private"
    metadata_status: str = "active"
    created_at: datetime
    columns: list[str] = Field(default_factory=list)
    total_rows: int = 0
    match_summary: MetadataUploadMatchSummary
