"""
Configuracion extraida de la tabla config para las rutas API.
Todas las funciones reciben db_manager (inyectado desde main), leen de config
y lanzan HTTPException(400) con mensaje claro si la config no esta disponible.
"""

from typing import Any, Dict, Tuple

from fastapi import HTTPException

from apps.backend.app.core.oci_db_config import (
    get_oci_bucket_name,
    get_oci_compartment_id,
    get_oci_namespace,
    load_oci_config,
)


def get_oci_config_required(db_manager: Any) -> Dict:
    """Config OCI para clientes. Lanza 400 si no existe."""
    oci_config = load_oci_config(db_manager)
    if not oci_config:
        raise HTTPException(400, "OCI configuration not found")
    return oci_config


def get_compartment_id_required(db_manager: Any) -> str:
    """Compartment ID de OCI. Lanza 400 si no esta configurado."""
    compartment_id = get_oci_compartment_id(db_manager)
    if not compartment_id:
        raise HTTPException(400, "Compartment ID not found in configuration")
    return compartment_id


def get_oci_namespace_required(db_manager: Any) -> str:
    """Namespace de Object Storage. Lanza 400 si no esta configurado."""
    namespace = get_oci_namespace(db_manager)
    if not namespace:
        raise HTTPException(400, "OCI namespace not found in configuration")
    return namespace


def get_oci_bucket_required(db_manager: Any) -> str:
    """Bucket unico de Object Storage. Lanza 400 si no esta configurado."""
    bucket_name = get_oci_bucket_name(db_manager)
    if not bucket_name:
        raise HTTPException(400, "OCI bucket_name not found in configuration")
    return bucket_name


def get_oci_namespace_and_bucket_required(db_manager: Any) -> Tuple[str, str]:
    """Namespace y bucket unico en una sola llamada. Lanza 400 si falta algo."""
    namespace = get_oci_namespace_required(db_manager)
    bucket_name = get_oci_bucket_required(db_manager)
    return namespace, bucket_name

