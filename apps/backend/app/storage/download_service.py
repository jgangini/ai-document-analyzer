"""File download service: resolve file from files table and Object Storage."""

from __future__ import annotations

import logging
from typing import Tuple

import oci

from apps.backend.app.api.config import get_oci_config_required, get_oci_namespace_and_bucket_required
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.database import DatabaseManager

logger = logging.getLogger(__name__)


class FileDownloadService:
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    def get_download(self, user_id: int, file_id: int) -> Tuple[str, bytes, str]:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    file_input_file_name,
                    file_input_obj_name,
                    user_id,
                    access_scope
                FROM files
                WHERE file_id = :1
                """,
                [file_id],
            )
            row = cursor.fetchone()
            if not row:
                raise FileNotFoundError("File not found")
            filename = row[0]
            input_obj_name = row[1] if len(row) > 1 and row[1] else None
            owner_user_id = int(row[2] or 0) if len(row) > 2 and row[2] is not None else 0
            access_scope = str(row[3] or "private").strip().lower() if len(row) > 3 else "private"
            resolved_user_id = int(user_id or 0)
            if owner_user_id != resolved_user_id and not (resolved_user_id > 0 and access_scope == "all"):
                raise FileNotFoundError("File not found")
            if not input_obj_name:
                input_obj_name = filename
        finally:
            cursor.close()
            conn.close()
        try:
            oci_config = get_oci_config_required(self.db_manager)
            namespace, bucket_name = get_oci_namespace_and_bucket_required(self.db_manager)
            os_client = oci.object_storage.ObjectStorageClient(oci_config)
            response = os_client.get_object(
                namespace_name=namespace,
                bucket_name=bucket_name,
                object_name=input_obj_name,
            )
            content = response.data.content
            content_type = response.headers.get("Content-Type", "application/octet-stream")
            return (filename, content, content_type)
        except Exception:
            local_candidate = (get_settings().root_dir / input_obj_name).resolve()
            if local_candidate.exists():
                return (
                    filename,
                    local_candidate.read_bytes(),
                    "application/pdf",
                )
            raise

