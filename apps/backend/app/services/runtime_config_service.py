"""Persistencia de configuracion en tabla `config`."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from apps.backend.app.core.database import DatabaseManager


class ConfigService:
    DEFAULT_GENAI_MODEL = "google.gemini-2.5-flash"

    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    @staticmethod
    def _normalize_value(value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return ""
        return str(value)

    def table_exists(self) -> bool:
        return self.db_manager.table_exists("config")

    def get_value(self, key: str, default: Any = "") -> str:
        if not self.table_exists():
            return self._normalize_value(default)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT config_value
                FROM config
                WHERE config_key = :config_key
                """,
                config_key=key,
            )
            row = cursor.fetchone()
            if not row:
                return self._normalize_value(default)
            value = row[0]
            if hasattr(value, "read"):
                value = value.read()
            return self._normalize_value(value)
        finally:
            cursor.close()
            connection.close()

    def get_oci_compartment_id(self) -> str:
        return self.get_value("oci.compartment_id", "").strip()

    def get_genai_inference_url(self) -> str:
        return self.get_value("genai.inference_url", "").strip()

    def get_genai_model(self, default: str | None = None) -> str:
        resolved_default = (default or self.DEFAULT_GENAI_MODEL).strip()
        value = self.get_value("genai.model", resolved_default).strip()
        return value or resolved_default

    def upsert_value(
        self,
        *,
        key: str,
        value: Any,
        category: str = "general",
        config_type: str = "string",
        description: str = "",
    ) -> None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                MERGE INTO config c
                USING (SELECT :config_key AS config_key FROM dual) src
                ON (c.config_key = src.config_key)
                WHEN MATCHED THEN
                    UPDATE SET
                        c.config_value = :config_value,
                        c.config_type = :config_type,
                        c.config_category = :config_category,
                        c.config_description = :config_description,
                        c.config_updated = SYSDATE
                WHEN NOT MATCHED THEN
                    INSERT (
                        config_key,
                        config_value,
                        config_type,
                        config_category,
                        config_description
                    )
                    VALUES (
                        :config_key,
                        :config_value,
                        :config_type,
                        :config_category,
                        :config_description
                    )
                """,
                config_key=key,
                config_value=self._normalize_value(value),
                config_type=config_type,
                config_category=category,
                config_description=description,
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def upsert_many(self, entries: list[dict[str, Any]]) -> None:
        for entry in entries:
            self.upsert_value(
                key=entry["key"],
                value=entry.get("value", ""),
                category=entry.get("category", "general"),
                config_type=entry.get("type", "string"),
                description=entry.get("description", ""),
            )

    def delete_keys(self, keys: list[str]) -> None:
        safe_keys = [str(key or "").strip() for key in list(keys or []) if str(key or "").strip()]
        if not safe_keys or not self.table_exists():
            return
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {}
            placeholders: list[str] = []
            for index, key in enumerate(safe_keys):
                param_name = f"config_key_{index}"
                params[param_name] = key
                placeholders.append(f":{param_name}")
            cursor.execute(
                f"""
                DELETE FROM config
                WHERE config_key IN ({', '.join(placeholders)})
                """,
                params,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def list_grouped(self) -> dict[str, list[dict[str, str]]]:
        if not self.table_exists():
            return {}
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
        try:
            cursor.execute(
                """
                SELECT config_key, config_value, config_type, config_category, config_description
                FROM config
                ORDER BY NVL(config_category, 'general'), config_key
                """
            )
            for key, value, config_type, category, description in cursor.fetchall():
                if hasattr(value, "read"):
                    value = value.read()
                grouped[category or "general"].append(
                    {
                        "key": key,
                        "value": self._normalize_value(value),
                        "type": config_type or "string",
                        "category": category or "general",
                        "description": description or "",
                    }
                )
            return dict(grouped)
        finally:
            cursor.close()
            connection.close()

    def get_install_state(self) -> dict[str, bool]:
        return {
            "wizard_completed": self.get_value("wizard.completed", "false") == "true",
            "db_validated": self.get_value("install.db.validated", "false") == "true",
            "bucket_validated": self.get_value("install.bucket.validated", "false") == "true",
            "genai_validated": self.get_value("install.genai.validated", "false") == "true",
            "app_ready": self.get_value("app.ready", "false") == "true",
        }
