"""Shared API response types."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class APIModel(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())


class HealthResponse(APIModel):
    status: str
    app: str
    model: str
    database_backend: str


class ConfigStatusResponse(APIModel):
    database_backend: str
    wallet_present: bool
    oci_config_present: bool
    oci_genai_configured: bool
    oci_genai_model: str
    hybrid_local_onnx_ready: bool
    document_understanding_configured: bool
    document_understanding_live_enabled: bool
    ocr_provider: str = "docling_rapidocr"
    ocr_engine: str = "rapidocr"
    ocr_orchestrator: str = "docling"
    object_storage_live_enabled: bool
    embedding_live_enabled: bool


class ErrorResponse(APIModel):
    detail: str


class TimestampedResponse(APIModel):
    created_at: datetime
