from __future__ import annotations

from fastapi import HTTPException

from apps.backend.app.core.session import get_db_manager
from apps.backend.app.services.bootstrap_service import SetupService


def require_setup_completed() -> None:
    """Bloquea operaciones de runtime hasta completar el wizard."""
    setup_service = SetupService(get_db_manager())
    if not setup_service.check_setup_status():
        raise HTTPException(
            status_code=503,
            detail="Setup wizard not completed. Complete installation before running tests.",
        )

