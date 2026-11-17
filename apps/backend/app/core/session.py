"""Helpers de sesion/conexion para FastAPI."""

from __future__ import annotations

from collections.abc import Generator

from apps.backend.app.core.database import DatabaseManager


def get_db_manager() -> DatabaseManager:
    """Retorna singleton de DatabaseManager."""
    from apps.backend.app.core.config import get_settings

    return DatabaseManager.get_instance(get_settings())


def get_db_connection() -> Generator:
    """Dependency que entrega una conexion Oracle abierta."""
    connection = get_db_manager().get_connection()
    try:
        yield connection
    finally:
        connection.close()
