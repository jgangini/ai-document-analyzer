"""Servicio de Object Storage obligatorio contra OCI."""

from __future__ import annotations

import base64
import mimetypes
from pathlib import Path

import oci

from apps.backend.app.core.config import Settings
from apps.backend.app.core.oci_db_config import get_oci_bucket_name, get_oci_namespace
from apps.backend.app.core.session import get_db_manager


class ObjectStorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = None
        self._namespace: str | None = None
        self._bucket_name: str | None = None

    def _resolve_bucket_target(self) -> tuple[str, str]:
        if self._namespace and self._bucket_name:
            return self._namespace, self._bucket_name
        db_manager = get_db_manager()
        namespace = str(get_oci_namespace(db_manager) or "").strip()
        bucket_name = str(get_oci_bucket_name(db_manager) or "").strip()
        if not namespace or not bucket_name:
            raise RuntimeError("Object Storage requiere oci.namespace y oci.bucket_name en tabla config.")
        self._namespace = namespace
        self._bucket_name = bucket_name
        return namespace, bucket_name

    def is_available(self) -> bool:
        if not self.settings.oci_config_file.exists():
            return False
        try:
            self._resolve_bucket_target()
            return True
        except Exception:
            return False

    def _get_client(self):
        if self._client is None:
            if not self.is_available():
                raise RuntimeError("Object Storage OCI no esta disponible por configuracion incompleta.")
            config = oci.config.from_file(
                file_location=str(self.settings.oci_config_file),
                profile_name=self.settings.oci_profile,
            )
            self._client = oci.object_storage.ObjectStorageClient(config)
        return self._client

    def upload_file(
        self,
        local_path: Path,
        *,
        object_name: str,
        content_type: str = "application/octet-stream",
    ) -> dict[str, str]:
        if not self.is_available():
            raise RuntimeError("Object Storage OCI es mandatorio y no esta disponible.")
        namespace, bucket_name = self._resolve_bucket_target()
        client = self._get_client()
        if client is None:
            raise RuntimeError("ObjectStorage client is not available.")
        with local_path.open("rb") as stream:
            client.put_object(
                namespace_name=namespace,
                bucket_name=bucket_name,
                object_name=object_name,
                put_object_body=stream,
                content_type=content_type,
            )
        return {
            "namespace": namespace,
            "bucket_name": bucket_name,
            "object_name": object_name,
            "uri": f"oci://{namespace}/{bucket_name}/{object_name}",
        }

    def download_file(self, *, object_name: str, local_path: Path) -> Path:
        if not object_name:
            raise RuntimeError("Object name is required to download from Object Storage.")
        if not self.is_available():
            raise RuntimeError("Object Storage OCI es mandatorio y no esta disponible.")
        namespace, bucket_name = self._resolve_bucket_target()
        client = self._get_client()
        if client is None:
            raise RuntimeError("ObjectStorage client is not available.")
        response = client.get_object(
            namespace_name=namespace,
            bucket_name=bucket_name,
            object_name=object_name,
        )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(response.data.content)
        return local_path

    def get_object_data_uri(self, object_name: str) -> str | None:
        if not object_name:
            return None
        if not self.is_available():
            raise RuntimeError("Object Storage OCI es mandatorio y no esta disponible.")
        namespace, bucket_name = self._resolve_bucket_target()
        client = self._get_client()
        if client is None:
            return None
        response = client.get_object(
            namespace_name=namespace,
            bucket_name=bucket_name,
            object_name=object_name,
        )
        raw = response.data.content
        mime = mimetypes.guess_type(object_name)[0] or "image/png"
        encoded = base64.b64encode(raw).decode("ascii")
        return f"data:{mime};base64,{encoded}"

