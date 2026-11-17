import os

from fastapi import APIRouter

from apps.backend.app.core.config import get_settings
from apps.backend.app.core.oci_db_config import get_oci_bucket_name, get_oci_namespace
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.services.runtime_config_service import ConfigService
from apps.backend.app.rag.reranker_service import HybridLocalOnnxRerankService

router = APIRouter(tags=["config"])


def env_flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@router.get("/config/status")
def config_status() -> dict:
    settings = get_settings()
    db_manager = get_db_manager()
    config_service = ConfigService(db_manager)
    compartment_id = config_service.get_oci_compartment_id()
    namespace = str(get_oci_namespace(db_manager) or "").strip()
    bucket_name = str(get_oci_bucket_name(db_manager) or "").strip()
    generative_model = config_service.get_genai_model(default=settings.oci_genai_model)
    hybrid_local_onnx_ready = HybridLocalOnnxRerankService(settings).is_ready()
    document_understanding_live_enabled = settings.document_understanding_live_enabled
    return {
        "database_backend": settings.database_backend,
        "wallet_present": settings.wallet_dir.exists(),
        "oci_config_present": settings.oci_config_file.exists(),
        "oci_genai_configured": bool(compartment_id and generative_model),
        "oci_genai_model": generative_model,
        "hybrid_local_onnx_ready": hybrid_local_onnx_ready,
        "document_understanding_configured": bool(document_understanding_live_enabled and compartment_id),
        "document_understanding_live_enabled": document_understanding_live_enabled,
        "ocr_provider": settings.document_understanding_provider,
        "ocr_engine": "rapidocr",
        "ocr_orchestrator": "docling",
        "object_storage_live_enabled": bool(settings.oci_config_file.exists() and namespace and bucket_name),
        "embedding_live_enabled": settings.embedding_live_enabled,
        "install_state": {},
    }
