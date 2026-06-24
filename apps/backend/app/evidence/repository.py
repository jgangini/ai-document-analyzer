"""Oracle repository for the document evidence ledger."""

from __future__ import annotations

import json
from typing import Any

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.evidence.ledger import DocumentUnit


class EvidenceLedgerRepository:
    """Durable source/unit/evidence registry backed by Autonomous Database."""

    def __init__(self, db_manager: DatabaseManager) -> None:
        self._db_manager = db_manager

    def tables_ready(self) -> bool:
        return (
            self._db_manager.table_exists("document_sources")
            and self._db_manager.table_exists("document_units")
        )

    def upsert_source(
        self,
        *,
        source_id: str,
        source_uri: str,
        source_sha256: str,
        title: str = "",
        mime_type: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.tables_ready():
            return
        connection = self._db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                MERGE INTO document_sources tgt
                USING (SELECT :source_id AS source_id FROM dual) src
                ON (tgt.document_sources_source_id = src.source_id)
                WHEN MATCHED THEN
                  UPDATE SET
                    document_sources_source_uri = :source_uri,
                    document_sources_source_sha256 = :source_sha256,
                    document_sources_title = :title,
                    document_sources_mime_type = :mime_type,
                    document_sources_metadata_json = :metadata_json,
                    document_sources_updated = SYSTIMESTAMP
                WHEN NOT MATCHED THEN
                  INSERT (
                    document_sources_source_id,
                    document_sources_source_uri,
                    document_sources_source_sha256,
                    document_sources_title,
                    document_sources_mime_type,
                    document_sources_metadata_json
                  ) VALUES (
                    :source_id,
                    :source_uri,
                    :source_sha256,
                    :title,
                    :mime_type,
                    :metadata_json
                  )
                """,
                source_id=str(source_id),
                source_uri=str(source_uri),
                source_sha256=str(source_sha256),
                title=str(title or ""),
                mime_type=str(mime_type or ""),
                metadata_json=json.dumps(dict(metadata or {}), ensure_ascii=False),
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def upsert_unit(self, unit: DocumentUnit) -> None:
        if not self.tables_ready():
            return
        connection = self._db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                MERGE INTO document_units tgt
                USING (
                    SELECT :source_id AS source_id, :unit_id AS unit_id FROM dual
                ) src
                ON (
                    tgt.document_sources_source_id = src.source_id
                    AND tgt.document_units_unit_id = src.unit_id
                )
                WHEN MATCHED THEN
                  UPDATE SET
                    document_units_citation_label = :citation_label,
                    document_units_char_start = :char_start,
                    document_units_char_end = :char_end,
                    document_units_unit_text = :unit_text,
                    document_units_unit_text_sha256 = :unit_text_sha256,
                    document_units_evidence_id = :evidence_id,
                    document_units_hash_verified = :hash_verified,
                    document_units_metadata_json = :metadata_json,
                    document_units_updated = SYSTIMESTAMP
                WHEN NOT MATCHED THEN
                  INSERT (
                    document_sources_source_id,
                    document_units_unit_id,
                    document_units_citation_label,
                    document_units_char_start,
                    document_units_char_end,
                    document_units_unit_text,
                    document_units_unit_text_sha256,
                    document_units_evidence_id,
                    document_units_hash_verified,
                    document_units_metadata_json
                  ) VALUES (
                    :source_id,
                    :unit_id,
                    :citation_label,
                    :char_start,
                    :char_end,
                    :unit_text,
                    :unit_text_sha256,
                    :evidence_id,
                    :hash_verified,
                    :metadata_json
                  )
                """,
                source_id=unit.source_id,
                unit_id=unit.unit_id,
                citation_label=unit.citation_label,
                char_start=int(unit.char_start),
                char_end=int(unit.char_end),
                unit_text=unit.text,
                unit_text_sha256=unit.unit_text_sha256,
                evidence_id=unit.evidence_id,
                hash_verified=1 if unit.hash_verified else 0,
                metadata_json=json.dumps(dict(unit.metadata or {}), ensure_ascii=False),
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def get_verified_unit(self, *, source_id: str, unit_id: str) -> DocumentUnit | None:
        if not self.tables_ready():
            return None
        connection = self._db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    u.document_sources_source_id,
                    u.document_units_unit_id,
                    u.document_units_unit_text,
                    u.document_units_citation_label,
                    u.document_units_char_start,
                    u.document_units_char_end,
                    s.document_sources_source_sha256,
                    u.document_units_unit_text_sha256,
                    u.document_units_evidence_id,
                    u.document_units_hash_verified,
                    u.document_units_metadata_json
                FROM document_units u
                JOIN document_sources s
                  ON s.document_sources_source_id = u.document_sources_source_id
                WHERE u.document_sources_source_id = :source_id
                  AND u.document_units_unit_id = :unit_id
                  AND u.document_units_hash_verified = 1
                """,
                source_id=str(source_id),
                unit_id=str(unit_id),
            )
            row = cursor.fetchone()
            return self._row_to_unit(row) if row else None
        finally:
            cursor.close()
            connection.close()

    def _row_to_unit(self, row: Any) -> DocumentUnit:
        raw_text = row[2].read() if hasattr(row[2], "read") else row[2]
        raw_metadata = row[10].read() if hasattr(row[10], "read") else row[10]
        try:
            metadata = json.loads(str(raw_metadata or "{}"))
        except Exception:
            metadata = {}
        return DocumentUnit(
            source_id=str(row[0]),
            unit_id=str(row[1]),
            text=str(raw_text or ""),
            citation_label=str(row[3] or ""),
            char_start=int(row[4] or 0),
            char_end=int(row[5] or 0),
            source_sha256=str(row[6] or ""),
            unit_text_sha256=str(row[7] or ""),
            evidence_id=str(row[8] or ""),
            hash_verified=bool(row[9]),
            metadata=dict(metadata or {}),
        )
