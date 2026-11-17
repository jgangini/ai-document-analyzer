"""Oracle JSON store for long-term agent memory."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.app.agent.memory.serde import dumps_payload, loads_payload


class OracleMemoryStore:
    def __init__(self, db_manager) -> None:
        self.db_manager = db_manager

    def put(self, *, namespace: str, key: str, value: dict[str, Any]) -> None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                MERGE INTO agent_store_items target
                USING (
                    SELECT :namespace AS namespace, :item_key AS item_key FROM dual
                ) source
                ON (
                    target.namespace = source.namespace
                    AND target.item_key = source.item_key
                )
                WHEN MATCHED THEN UPDATE
                    SET agent_store_value_json = :value_json,
                        agent_store_updated = SYSTIMESTAMP
                WHEN NOT MATCHED THEN INSERT (
                    agent_store_namespace,
                    agent_store_item_key,
                    agent_store_value_json,
                    agent_store_created,
                    agent_store_updated
                ) VALUES (
                    :namespace, :item_key, :value_json, SYSTIMESTAMP, SYSTIMESTAMP
                )
                """,
                namespace=namespace,
                item_key=key,
                value_json=dumps_payload(value),
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def get(self, *, namespace: str, key: str) -> dict[str, Any] | None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT agent_store_value_json
                FROM agent_store_items
                WHERE agent_store_namespace = :namespace
                  AND agent_store_item_key = :item_key
                FETCH FIRST 1 ROWS ONLY
                """,
                namespace=namespace,
                item_key=key,
            )
            row = cursor.fetchone()
            if not row:
                return None
            payload = row[0].read() if hasattr(row[0], "read") else row[0]
            decoded = loads_payload(payload)
            return decoded if isinstance(decoded, dict) else None
        finally:
            cursor.close()
            connection.close()

    def list_namespace(self, *, namespace: str, limit: int = 100) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 500))
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    agent_store_item_key,
                    agent_store_value_json,
                    agent_store_updated
                FROM agent_store_items
                WHERE agent_store_namespace = :namespace
                ORDER BY agent_store_updated DESC
                FETCH FIRST {safe_limit} ROWS ONLY
                """,
                namespace=namespace,
            )
            results: list[dict[str, Any]] = []
            for row in cursor.fetchall():
                value_raw = row[1].read() if hasattr(row[1], "read") else row[1]
                results.append(
                    {
                        "key": str(row[0]),
                        "value": loads_payload(value_raw),
                        "updated_at": row[2] if isinstance(row[2], datetime) else None,
                    }
                )
            return results
        finally:
            cursor.close()
            connection.close()

