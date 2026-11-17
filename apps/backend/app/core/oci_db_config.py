"""Read OCI-related configuration from config table."""

import logging
from pathlib import Path, PureWindowsPath
from typing import Optional, Dict

from apps.backend.app.core.config import get_settings

from .database import DatabaseManager

logger = logging.getLogger(__name__)


def _resolve_oci_key_file_path(key_file_value: object) -> Optional[Path]:
    raw_value = str(key_file_value or "").strip()
    if not raw_value:
        return None

    settings = get_settings()
    posix_candidate = Path(raw_value)
    windows_candidate = PureWindowsPath(raw_value)
    candidates: list[Path] = []

    if posix_candidate.is_absolute():
        candidates.append(posix_candidate)
    elif not windows_candidate.drive:
        candidates.append((settings.root_dir / posix_candidate).resolve())

    key_name = windows_candidate.name or posix_candidate.name
    if key_name:
        candidates.append((settings.keys_dir / key_name).resolve())

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def load_oci_config(db_manager: DatabaseManager) -> Optional[Dict]:
    """
    Load OCI configuration from config table.
    Returns dict in OCI config format or None if not configured.
    """
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT config_key, config_value
            FROM config
            WHERE config_category = 'oci'
        """)

        oci_data = {}
        for row in cursor.fetchall():
            key = row[0].replace('oci.', '')
            value = row[1]
            if hasattr(value, 'read'):
                value = value.read()
            oci_data[key] = value

        cursor.close()
        conn.close()

        required_fields = ['user', 'fingerprint', 'tenancy', 'region', 'key_file']
        if not all(field in oci_data and oci_data[field] for field in required_fields):
            return None
        resolved_key_file = _resolve_oci_key_file_path(oci_data["key_file"])
        if resolved_key_file is None:
            logger.error("OCI key file could not be resolved from config value: %s", oci_data["key_file"])
            return None

        with open(resolved_key_file, 'r') as f:
            key_content = f.read()

        return {
            "user": oci_data['user'],
            "key_content": key_content,
            "fingerprint": oci_data['fingerprint'],
            "tenancy": oci_data['tenancy'],
            "region": oci_data['region']
        }

    except Exception as e:
        logger.error("Error loading OCI config from DB: %s", e)
        return None


def get_oci_compartment_id(db_manager: DatabaseManager) -> Optional[str]:
    """Get OCI compartment_id from config table (oci.compartment_id)."""
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT config_value FROM config WHERE config_key = 'oci.compartment_id'")
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row and row[0]:
            val = row[0]
            if hasattr(val, "read"):
                val = val.read()
            return val
        return None
    except Exception as e:
        logger.error("Error loading OCI compartment_id: %s", e)
        return None


def get_oci_namespace(db_manager: DatabaseManager) -> Optional[str]:
    """Get OCI namespace from config table."""
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT config_value
            FROM config
            WHERE config_key = 'oci.namespace'
        """)

        row = cursor.fetchone()
        cursor.close()
        conn.close()

        if row and row[0]:
            value = row[0]
            if hasattr(value, 'read'):
                value = value.read()
            return value
        return None

    except Exception as e:
        logger.error("Error loading OCI namespace: %s", e)
        return None


def get_oci_bucket_name(db_manager: DatabaseManager) -> Optional[str]:
    """Get single Object Storage bucket name from config table."""
    try:
        conn = db_manager.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT config_key, config_value
            FROM config
            WHERE config_key = 'oci.bucket_name'
        """)

        values: Dict[str, str] = {}
        for row in cursor.fetchall():
            key = row[0]
            value = row[1]
            if hasattr(value, 'read'):
                value = value.read()
            values[key] = str(value or "").strip()

        cursor.close()
        conn.close()

        return values.get("oci.bucket_name", "") or None

    except Exception as e:
        logger.error("Error loading OCI bucket name: %s", e)
        return None
