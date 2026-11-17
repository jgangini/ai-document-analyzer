"""Compat shim: use `storage.object_storage_service`."""

from apps.backend.app.storage.object_storage_service import ObjectStorageService

__all__ = ["ObjectStorageService"]

