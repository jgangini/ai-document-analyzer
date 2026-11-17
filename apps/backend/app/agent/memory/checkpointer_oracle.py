"""Checkpointer LangGraph con persistencia Oracle en la estructura nueva."""

from __future__ import annotations

import base64
from collections import ChainMap
import json
import logging
from typing import Any, Iterator, Sequence

from langgraph.checkpoint.base import (
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
)
from langgraph.checkpoint.memory import InMemorySaver

from apps.backend.app.core.database import DatabaseManager

logger = logging.getLogger(__name__)
DEFAULT_CHECKPOINT_NAMESPACE = "default"


def _encode_typed(value: tuple[str, bytes]) -> str:
    return json.dumps(
        {
            "type": value[0],
            "data_b64": base64.b64encode(value[1]).decode("ascii"),
        },
        ensure_ascii=False,
    )


def _decode_typed(raw: str) -> tuple[str, bytes]:
    payload = json.loads(raw or "{}")
    return (
        str(payload.get("type", "json")),
        base64.b64decode(str(payload.get("data_b64", "")).encode("ascii")),
    )


def _normalize_checkpoint_ns(config: dict[str, Any]) -> str:
    configurable = config.get("configurable", {}) if isinstance(config, dict) else {}
    raw_value = configurable.get("checkpoint_ns", DEFAULT_CHECKPOINT_NAMESPACE)
    normalized = str(raw_value or "").strip()
    return normalized or DEFAULT_CHECKPOINT_NAMESPACE


def _json_default(value: Any) -> Any:
    if isinstance(value, ChainMap):
        merged: dict[str, Any] = {}
        for mapping in reversed(value.maps):
            merged.update(dict(mapping))
        return merged
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class OracleLangGraphCheckpointer(InMemorySaver):
    """Persist checkpoints en Oracle y mantiene cache in-memory para velocidad."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        super().__init__()
        self._db_manager = db_manager

    def _tables_ready(self) -> bool:
        return self._db_manager.table_exists("agent_checkpoints")

    def _insert_thread(self, *, thread_id: str) -> None:
        if not self._db_manager.table_exists("agent_threads"):
            return
        connection = self._db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                MERGE INTO agent_threads tgt
                USING (SELECT :thread_id AS thread_id FROM dual) src
                ON (tgt.agent_threads_thread_id = src.thread_id)
                WHEN MATCHED THEN
                  UPDATE SET agent_threads_updated = SYSTIMESTAMP
                WHEN NOT MATCHED THEN
                  INSERT (agent_threads_thread_id)
                  VALUES (src.thread_id)
                """,
                thread_id=thread_id,
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def put(self, config, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions):
        next_config = super().put(config, checkpoint, metadata, new_versions)
        if not self._tables_ready():
            return next_config
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = _normalize_checkpoint_ns(config)
        checkpoint_id = str(get_checkpoint_id(next_config))
        parent_checkpoint_id = str(get_checkpoint_id(config) or "")
        self._insert_thread(thread_id=thread_id)
        connection = self._db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO agent_checkpoints (
                    agent_threads_thread_id,
                    agent_checkpoints_namespace,
                    agent_checkpoints_checkpoint_id,
                    agent_checkpoints_parent_id,
                    agent_checkpoints_config_json,
                    agent_checkpoints_checkpoint_typed,
                    agent_checkpoints_metadata_typed,
                    agent_checkpoints_versions_json
                ) VALUES (
                    :thread_id,
                    :checkpoint_ns,
                    :checkpoint_id,
                    :parent_id,
                    :config_json,
                    :checkpoint_typed,
                    :metadata_typed,
                    :versions_json
                )
                """,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=checkpoint_id,
                parent_id=parent_checkpoint_id or None,
                config_json=json.dumps(config, ensure_ascii=False, default=_json_default),
                checkpoint_typed=_encode_typed(self.serde.dumps_typed(checkpoint)),
                metadata_typed=_encode_typed(self.serde.dumps_typed(metadata)),
                versions_json=json.dumps(new_versions, ensure_ascii=False, default=_json_default),
            )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            logger.warning("Checkpoint persistence failed: %s", exc)
        finally:
            cursor.close()
            connection.close()
        return next_config

    def put_writes(
        self,
        config,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        super().put_writes(config, writes, task_id, task_path)
        if not self._db_manager.table_exists("agent_checkpoint_writes"):
            return
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = _normalize_checkpoint_ns(config)
        checkpoint_id = str(get_checkpoint_id(config))
        connection = self._db_manager.get_connection()
        cursor = connection.cursor()
        try:
            for idx, (channel_name, value) in enumerate(writes):
                cursor.execute(
                    """
                    INSERT INTO agent_checkpoint_writes (
                        agent_threads_thread_id,
                        agent_checkpoints_namespace,
                        agent_checkpoints_checkpoint_id,
                        agent_checkpoint_writes_task_id,
                        agent_checkpoint_writes_task_path,
                        agent_checkpoint_writes_write_idx,
                        agent_checkpoint_writes_channel_name,
                        agent_checkpoint_writes_value_typed
                    ) VALUES (
                        :thread_id,
                        :checkpoint_ns,
                        :checkpoint_id,
                        :task_id,
                        :task_path,
                        :write_idx,
                        :channel_name,
                        :value_typed
                    )
                    """,
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=checkpoint_id,
                    task_id=task_id,
                    task_path=task_path or "",
                    write_idx=int(idx),
                    channel_name=str(channel_name),
                    value_typed=_encode_typed(self.serde.dumps_typed(value)),
                )
            connection.commit()
        except Exception as exc:
            connection.rollback()
            logger.warning("Checkpoint writes persistence failed: %s", exc)
        finally:
            cursor.close()
            connection.close()

    def get_tuple(self, config) -> CheckpointTuple | None:
        in_memory = super().get_tuple(config)
        if in_memory is not None:
            return in_memory
        if not self._tables_ready():
            return None
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = _normalize_checkpoint_ns(config)
        requested_checkpoint_id = get_checkpoint_id(config)
        connection = self._db_manager.get_connection()
        cursor = connection.cursor()
        try:
            if requested_checkpoint_id:
                cursor.execute(
                    """
                    SELECT agent_checkpoints_checkpoint_id,
                           agent_checkpoints_parent_id,
                           agent_checkpoints_checkpoint_typed,
                           agent_checkpoints_metadata_typed
                    FROM agent_checkpoints
                    WHERE agent_threads_thread_id = :thread_id
                      AND agent_checkpoints_namespace = :checkpoint_ns
                      AND agent_checkpoints_checkpoint_id = :checkpoint_id
                    FETCH FIRST 1 ROWS ONLY
                    """,
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                    checkpoint_id=str(requested_checkpoint_id),
                )
            else:
                cursor.execute(
                    """
                    SELECT agent_checkpoints_checkpoint_id,
                           agent_checkpoints_parent_id,
                           agent_checkpoints_checkpoint_typed,
                           agent_checkpoints_metadata_typed
                    FROM agent_checkpoints
                    WHERE agent_threads_thread_id = :thread_id
                      AND agent_checkpoints_namespace = :checkpoint_ns
                    ORDER BY agent_checkpoints_created DESC
                    FETCH FIRST 1 ROWS ONLY
                    """,
                    thread_id=thread_id,
                    checkpoint_ns=checkpoint_ns,
                )
            row = cursor.fetchone()
            if not row:
                return None
            checkpoint_id, parent_id, checkpoint_typed, metadata_typed = row
            checkpoint_value = self.serde.loads_typed(
                _decode_typed(str(checkpoint_typed.read() if hasattr(checkpoint_typed, "read") else checkpoint_typed))
            )
            metadata_value = self.serde.loads_typed(
                _decode_typed(str(metadata_typed.read() if hasattr(metadata_typed, "read") else metadata_typed))
            )
            cursor.execute(
                """
                SELECT agent_checkpoint_writes_task_id,
                       agent_checkpoint_writes_channel_name,
                       agent_checkpoint_writes_value_typed
                FROM agent_checkpoint_writes
                WHERE agent_threads_thread_id = :thread_id
                  AND agent_checkpoints_namespace = :checkpoint_ns
                  AND agent_checkpoints_checkpoint_id = :checkpoint_id
                ORDER BY agent_checkpoint_writes_write_idx ASC
                """,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
                checkpoint_id=str(checkpoint_id),
            )
            pending_writes = []
            for task_id, channel_name, value_typed in cursor.fetchall() or []:
                raw_typed = str(value_typed.read() if hasattr(value_typed, "read") else value_typed)
                pending_writes.append(
                    (
                        str(task_id),
                        str(channel_name),
                        self.serde.loads_typed(_decode_typed(raw_typed)),
                    )
                )
            checkpoint_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": str(checkpoint_id),
                }
            }
            parent_config = (
                {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": str(parent_id),
                    }
                }
                if parent_id
                else None
            )
            return CheckpointTuple(
                config=checkpoint_config,
                checkpoint=checkpoint_value,
                metadata=metadata_value,
                pending_writes=pending_writes,
                parent_config=parent_config,
            )
        finally:
            cursor.close()
            connection.close()

    def list(
        self,
        config,
        *,
        filter: dict[str, Any] | None = None,
        before=None,
        limit: int | None = None,
    ) -> Iterator[CheckpointTuple]:
        del filter, before
        in_memory = list(super().list(config, limit=limit))
        if in_memory:
            for item in in_memory:
                yield item
            return
        if not self._tables_ready() or config is None:
            return
        thread_id = str(config["configurable"]["thread_id"])
        checkpoint_ns = _normalize_checkpoint_ns(config)
        connection = self._db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT agent_checkpoints_checkpoint_id
                FROM agent_checkpoints
                WHERE agent_threads_thread_id = :thread_id
                  AND agent_checkpoints_namespace = :checkpoint_ns
                ORDER BY agent_checkpoints_created DESC
                """,
                thread_id=thread_id,
                checkpoint_ns=checkpoint_ns,
            )
            count = 0
            for (checkpoint_id,) in cursor.fetchall() or []:
                tuple_config = {
                    "configurable": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": str(checkpoint_id),
                    }
                }
                loaded = self.get_tuple(tuple_config)
                if loaded is not None:
                    yield loaded
                    count += 1
                    if limit is not None and count >= int(limit):
                        return
        finally:
            cursor.close()
            connection.close()


OracleInMemoryCheckpointer = OracleLangGraphCheckpointer
