from fastapi import APIRouter

from apps.backend.app.core.config import get_settings
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.services.runtime_config_service import ConfigService

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict:
    settings = get_settings()
    config_service = ConfigService(get_db_manager())
    return {
        "status": "ok",
        "app": settings.app_name,
        "model": config_service.get_genai_model(default=settings.oci_genai_model),
        "database_backend": settings.database_backend,
        "install_state": {},
    }

