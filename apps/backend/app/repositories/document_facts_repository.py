"""SQL repository for generic file facts and grouping."""

from __future__ import annotations

from datetime import date
from typing import Any

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.repositories.repository_utils import (
    build_file_access_scope_condition,
    execute_with_retryable_database_operation,
    row_to_dict,
)


def _normalized_text(value: str | None, *, max_len: int | None = None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    return normalized[:max_len] if max_len is not None else normalized


def _required_text(value: str | None, *, max_len: int, default: str = "") -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return default
    return normalized[:max_len]


def _truncate_utf8_bytes(value: str | None, *, max_bytes: int) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    encoded = normalized.encode("utf-8")
    if len(encoded) <= int(max_bytes):
        return normalized
    truncated = encoded[: int(max_bytes)]
    while truncated:
        try:
            return truncated.decode("utf-8")
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return None


def _optional_positive_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _bounded_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return float(max(0.0, min(1.0, parsed)))


class DocumentFactsRepository:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    @staticmethod
    def _file_access_condition(
        *,
        alias: str = "f",
        user_param: str = "user_id",
        include_shared: bool = False,
    ) -> str:
        return build_file_access_scope_condition(
            alias=alias,
            user_param=user_param,
            include_shared=include_shared,
        )

    def _execute_retryable_write(self, *, operation: Any) -> Any:
        return execute_with_retryable_database_operation(
            db_manager=self.db_manager,
            operation=operation,
        )

    def reset_file_facts(self, *, file_id: int) -> None:
        """Delete file-scoped fact rows without touching global group cleanup.

        Re-ingestion can reset multiple PDFs from the same archive in parallel.
        Purging orphaned `file_groups` inside every reset introduces cross-file
        contention and can trigger Oracle sibling row lock deadlocks.
        """
        def _reset() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute("DELETE FROM file_links WHERE file_id = :file_id", file_id=int(file_id))
                cursor.execute("DELETE FROM file_attributes WHERE file_id = :file_id", file_id=int(file_id))
                cursor.execute("DELETE FROM file_entities WHERE file_id = :file_id", file_id=int(file_id))
                cursor.execute("DELETE FROM file_profiles WHERE file_id = :file_id", file_id=int(file_id))
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        self._execute_retryable_write(operation=_reset)

    def delete_orphaned_groups(self) -> int:
        """Best-effort cleanup for unreferenced `file_groups` rows."""
        def _delete_orphans() -> int:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    DELETE FROM file_groups
                    WHERE file_group_id NOT IN (
                        SELECT DISTINCT file_group_id
                        FROM file_profiles
                        WHERE file_group_id IS NOT NULL
                    )
                    """
                )
                deleted = int(cursor.rowcount or 0)
                connection.commit()
                return deleted
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        return int(self._execute_retryable_write(operation=_delete_orphans) or 0)

    def upsert_file_group(
        self,
        *,
        user_id: int,
        group_key: str,
        group_type: str,
        primary_identifier: str | None,
        secondary_identifier: str | None,
        primary_subject: str | None,
        secondary_subject: str | None,
        metadata_json: str = "{}",
    ) -> int:
        def _upsert_group() -> int:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                normalized_group_key = _truncate_utf8_bytes(group_key, max_bytes=256) or ""
                cursor.execute(
                    """
                    SELECT file_group_id
                    FROM file_groups
                    WHERE user_id = :user_id
                      AND group_key = :group_key
                    FETCH FIRST 1 ROWS ONLY
                    """,
                    user_id=int(user_id),
                    group_key=normalized_group_key,
                )
                row = cursor.fetchone()
                if row:
                    group_id = int(row[0])
                    cursor.execute(
                        """
                        UPDATE file_groups
                        SET group_type = :group_type,
                            primary_identifier = :primary_identifier,
                            secondary_identifier = :secondary_identifier,
                            primary_subject = :primary_subject,
                            secondary_subject = :secondary_subject,
                            metadata_json = :metadata_json
                        WHERE file_group_id = :file_group_id
                        """,
                        group_type=_normalized_text(group_type, max_len=64) or "generic",
                        primary_identifier=_normalized_text(primary_identifier, max_len=128),
                        secondary_identifier=_normalized_text(secondary_identifier, max_len=128),
                        primary_subject=_normalized_text(primary_subject, max_len=512),
                        secondary_subject=_normalized_text(secondary_subject, max_len=512),
                        metadata_json=str(metadata_json or "{}")[:4000],
                        file_group_id=group_id,
                    )
                    connection.commit()
                    return group_id

                group_id_var = cursor.var(int)
                cursor.execute(
                    """
                    INSERT INTO file_groups (
                        user_id,
                        group_key,
                        group_type,
                        primary_identifier,
                        secondary_identifier,
                        primary_subject,
                        secondary_subject,
                        metadata_json
                    ) VALUES (
                        :user_id,
                        :group_key,
                        :group_type,
                        :primary_identifier,
                        :secondary_identifier,
                        :primary_subject,
                        :secondary_subject,
                        :metadata_json
                    )
                    RETURNING file_group_id INTO :file_group_id
                    """,
                    user_id=int(user_id),
                    group_key=normalized_group_key,
                    group_type=_normalized_text(group_type, max_len=64) or "generic",
                    primary_identifier=_normalized_text(primary_identifier, max_len=128),
                    secondary_identifier=_normalized_text(secondary_identifier, max_len=128),
                    primary_subject=_normalized_text(primary_subject, max_len=512),
                    secondary_subject=_normalized_text(secondary_subject, max_len=512),
                    metadata_json=str(metadata_json or "{}")[:4000],
                    file_group_id=group_id_var,
                )
                connection.commit()
                return int(group_id_var.getvalue()[0])
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        return int(self._execute_retryable_write(operation=_upsert_group))

    def upsert_file_profile(
        self,
        *,
        user_id: int,
        file_group_id: int | None,
        file_id: int,
        profile_type: str,
        file_role: str,
        primary_identifier: str | None,
        secondary_identifier: str | None,
        primary_subject: str | None,
        secondary_subject: str | None,
        signed_at: date | None,
        effective_from: date | None,
        effective_to: date | None,
        fact_confidence: float | None,
        fact_summary: str,
        metadata_json: str = "{}",
    ) -> None:
        def _upsert_profile() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    MERGE INTO file_profiles target
                    USING (SELECT :file_id AS file_id FROM dual) source
                    ON (target.file_id = source.file_id)
                    WHEN MATCHED THEN UPDATE SET
                        user_id = :user_id,
                        file_group_id = :file_group_id,
                        profile_type = :profile_type,
                        file_role = :file_role,
                        primary_identifier = :primary_identifier,
                        secondary_identifier = :secondary_identifier,
                        primary_subject = :primary_subject,
                        secondary_subject = :secondary_subject,
                        signed_at = :signed_at,
                        effective_from = :effective_from,
                        effective_to = :effective_to,
                        fact_confidence = :fact_confidence,
                        fact_summary = :fact_summary,
                        metadata_json = :metadata_json
                    WHEN NOT MATCHED THEN INSERT (
                        user_id,
                        file_group_id,
                        file_id,
                        profile_type,
                        file_role,
                        primary_identifier,
                        secondary_identifier,
                        primary_subject,
                        secondary_subject,
                        signed_at,
                        effective_from,
                        effective_to,
                        fact_confidence,
                        fact_summary,
                        metadata_json
                    ) VALUES (
                        :user_id,
                        :file_group_id,
                        :file_id,
                        :profile_type,
                        :file_role,
                        :primary_identifier,
                        :secondary_identifier,
                        :primary_subject,
                        :secondary_subject,
                        :signed_at,
                        :effective_from,
                        :effective_to,
                        :fact_confidence,
                        :fact_summary,
                        :metadata_json
                    )
                    """,
                    user_id=int(user_id),
                    file_group_id=int(file_group_id) if file_group_id is not None else None,
                    file_id=int(file_id),
                    profile_type=_normalized_text(profile_type, max_len=64) or "generic",
                    file_role=_normalized_text(file_role, max_len=64) or "other",
                    primary_identifier=_normalized_text(primary_identifier, max_len=128),
                    secondary_identifier=_normalized_text(secondary_identifier, max_len=128),
                    primary_subject=_normalized_text(primary_subject, max_len=512),
                    secondary_subject=_normalized_text(secondary_subject, max_len=512),
                    signed_at=signed_at,
                    effective_from=effective_from,
                    effective_to=effective_to,
                    fact_confidence=float(max(0.0, min(1.0, fact_confidence))) if fact_confidence is not None else None,
                    fact_summary=str(fact_summary or "")[:4000],
                    metadata_json=str(metadata_json or "{}")[:4000],
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        self._execute_retryable_write(operation=_upsert_profile)
        if file_group_id is not None:
            self.refresh_current_profile_flags(file_group_id=int(file_group_id))

    def replace_file_entities(self, *, user_id: int, file_id: int, file_group_id: int | None, entities: list[dict[str, Any]]) -> None:
        self._replace_rows("DELETE FROM file_entities WHERE file_id = :file_id", """
            INSERT INTO file_entities (
                user_id, file_group_id, file_id, page_id, entity_role, entity_type,
                entity_name, person_name, identifier_value, has_visible_signature,
                bbox_json, metadata_json, confidence
            ) VALUES (
                :user_id, :file_group_id, :file_id, :page_id, :entity_role, :entity_type,
                :entity_name, :person_name, :identifier_value, :has_visible_signature,
                :bbox_json, :metadata_json, :confidence
            )
        """, rows=[self._normalize_entity_row(item) for item in entities], user_id=user_id, file_id=file_id, file_group_id=file_group_id)

    def replace_file_attributes(self, *, user_id: int, file_id: int, file_group_id: int | None, attributes: list[dict[str, Any]]) -> None:
        self._replace_rows("DELETE FROM file_attributes WHERE file_id = :file_id", """
            INSERT INTO file_attributes (
                user_id, file_group_id, file_id, page_id, attribute_key,
                attribute_value_text, attribute_value_number, attribute_value_date,
                attribute_value_bool, source_type, metadata_json, confidence
            ) VALUES (
                :user_id, :file_group_id, :file_id, :page_id, :attribute_key,
                :attribute_value_text, :attribute_value_number, :attribute_value_date,
                :attribute_value_bool, :source_type, :metadata_json, :confidence
            )
        """, rows=[self._normalize_attribute_row(item) for item in attributes], user_id=user_id, file_id=file_id, file_group_id=file_group_id)

    def replace_file_links(self, *, user_id: int, file_id: int, file_group_id: int | None, links: list[dict[str, Any]]) -> None:
        self._replace_rows("DELETE FROM file_links WHERE file_id = :file_id", """
            INSERT INTO file_links (
                user_id, file_group_id, file_id, page_id, link_type,
                source_label, target_label, link_key, metadata_json, confidence
            ) VALUES (
                :user_id, :file_group_id, :file_id, :page_id, :link_type,
                :source_label, :target_label, :link_key, :metadata_json, :confidence
            )
        """, rows=[self._normalize_link_row(item) for item in links], user_id=user_id, file_id=file_id, file_group_id=file_group_id)

    def refresh_current_profile_flags(self, *, file_group_id: int) -> None:
        def _refresh_flags() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute("UPDATE file_profiles SET is_current = 0 WHERE file_group_id = :file_group_id", file_group_id=int(file_group_id))
                cursor.execute(
                    """
                    UPDATE file_profiles
                    SET is_current = 1
                    WHERE file_profile_id IN (
                        SELECT file_profile_id
                        FROM (
                            SELECT file_profile_id,
                                   ROW_NUMBER() OVER (
                                       ORDER BY NVL(effective_from, DATE '1900-01-01') DESC,
                                                NVL(signed_at, DATE '1900-01-01') DESC,
                                                file_profile_id DESC
                                   ) AS rn
                            FROM file_profiles
                            WHERE file_group_id = :file_group_id
                              AND file_role <> 'termination'
                        )
                        WHERE rn = 1
                    )
                    """,
                    file_group_id=int(file_group_id),
                )
                cursor.execute(
                    """
                    MERGE INTO file_groups target
                    USING (
                        SELECT dg.file_group_id,
                               SUM(CASE WHEN dp.is_current = 1 THEN 1 ELSE 0 END) AS current_profile_count,
                               MAX(CASE WHEN dp.is_current = 1 THEN dp.effective_from END) AS current_effective_from,
                               MAX(CASE WHEN dp.is_current = 1 THEN dp.effective_to END) AS current_effective_to
                        FROM file_groups dg
                        LEFT JOIN file_profiles dp ON dp.file_group_id = dg.file_group_id
                        WHERE dg.file_group_id = :file_group_id
                        GROUP BY dg.file_group_id
                    ) source
                    ON (target.file_group_id = source.file_group_id)
                    WHEN MATCHED THEN UPDATE SET
                        current_profile_count = NVL(source.current_profile_count, 0),
                        current_effective_from = source.current_effective_from,
                        current_effective_to = source.current_effective_to
                    """,
                    file_group_id=int(file_group_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        self._execute_retryable_write(operation=_refresh_flags)

    def list_group_ids_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[int]:
        safe_file_ids = [int(value) for value in list(file_ids or []) if int(value) > 0]
        if not safe_file_ids:
            return []
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            placeholders: list[str] = []
            for index, value in enumerate(safe_file_ids):
                key = f"file_id_{index}"
                params[key] = int(value)
                placeholders.append(f":{key}")
            cursor.execute(
                f"""
                SELECT DISTINCT dp.file_group_id
                FROM file_profiles dp
                JOIN files f ON f.file_id = dp.file_id
                WHERE {self._file_access_condition(include_shared=include_shared)}
                  AND dp.file_group_id IS NOT NULL
                  AND dp.file_id IN ({', '.join(placeholders)})
                ORDER BY dp.file_group_id
                """,
                params,
            )
            return [int(row[0]) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def list_file_ids_for_group_ids(
        self,
        *,
        user_id: int,
        group_ids: list[int],
        current_only: bool = False,
        include_shared: bool = False,
    ) -> list[int]:
        safe_group_ids = [int(value) for value in list(group_ids or []) if int(value) > 0]
        if not safe_group_ids:
            return []
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            placeholders: list[str] = []
            for index, value in enumerate(safe_group_ids):
                key = f"group_id_{index}"
                params[key] = int(value)
                placeholders.append(f":{key}")
            current_clause = " AND dp.is_current = 1" if current_only else ""
            cursor.execute(
                f"""
                SELECT dp.file_id
                FROM file_profiles dp
                JOIN files f ON f.file_id = dp.file_id
                WHERE {self._file_access_condition(include_shared=include_shared)}
                  AND dp.file_group_id IN ({', '.join(placeholders)}){current_clause}
                ORDER BY dp.is_current DESC, dp.file_id ASC
                """,
                params,
            )
            return [int(row[0]) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def list_current_profiles(
        self,
        *,
        user_id: int,
        file_ids: list[int] | None = None,
        as_of_date: date | None = None,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            where_parts = [self._file_access_condition(include_shared=include_shared), "dp.is_current = 1"]
            if as_of_date is not None:
                params["as_of_date"] = as_of_date
                where_parts.append("(dp.effective_to IS NULL OR dp.effective_to >= :as_of_date)")
            if file_ids:
                placeholders = []
                for index, file_id in enumerate([int(v) for v in file_ids if int(v) > 0]):
                    key = f"file_id_{index}"
                    params[key] = int(file_id)
                    placeholders.append(f":{key}")
                if placeholders:
                    where_parts.append(f"dp.file_id IN ({', '.join(placeholders)})")
            cursor.execute(
                f"""
                SELECT dp.*, dg.group_key, dg.group_type
                FROM file_profiles dp
                JOIN files f ON f.file_id = dp.file_id
                LEFT JOIN file_groups dg ON dg.file_group_id = dp.file_group_id
                WHERE {' AND '.join(where_parts)}
                ORDER BY dp.effective_from DESC NULLS LAST, dp.signed_at DESC NULLS LAST, dp.file_id DESC
                """,
                params,
            )
            return [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def count_groups_by_subject_name(
        self,
        *,
        user_id: int,
        subject_name: str,
        file_ids: list[int] | None = None,
        current_only: bool = True,
        include_shared: bool = False,
    ) -> int:
        params: dict[str, Any] = {"user_id": int(user_id), "subject_name": f"%{str(subject_name or '').strip().upper()}%"}
        where_parts = [
            self._file_access_condition(include_shared=include_shared),
            "(UPPER(NVL(dp.primary_subject, '')) LIKE :subject_name OR UPPER(NVL(dp.secondary_subject, '')) LIKE :subject_name)",
        ]
        if current_only:
            where_parts.append("dp.is_current = 1")
        return self._count_distinct_groups(where_parts=where_parts, params=params, file_ids=file_ids)

    def count_expired_groups(
        self,
        *,
        user_id: int,
        as_of_date: date,
        file_ids: list[int] | None = None,
        include_shared: bool = False,
    ) -> int:
        params: dict[str, Any] = {"user_id": int(user_id), "as_of_date": as_of_date}
        where_parts = [
            self._file_access_condition(include_shared=include_shared),
            "dp.is_current = 1",
            "dp.effective_to IS NOT NULL",
            "dp.effective_to < :as_of_date",
        ]
        return self._count_distinct_groups(where_parts=where_parts, params=params, file_ids=file_ids)

    def list_secondary_identifiers_with_multiple_primary_identifiers(
        self,
        *,
        user_id: int,
        file_ids: list[int] | None = None,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            where_parts = [
                self._file_access_condition(include_shared=include_shared),
                "NVL(TRIM(dp.secondary_identifier), '') <> ''",
                "NVL(TRIM(dp.primary_identifier), '') <> ''",
            ]
            if file_ids:
                placeholders = []
                for index, file_id in enumerate([int(v) for v in file_ids if int(v) > 0]):
                    key = f"file_id_{index}"
                    params[key] = int(file_id)
                    placeholders.append(f":{key}")
                if placeholders:
                    where_parts.append(f"dp.file_id IN ({', '.join(placeholders)})")
            cursor.execute(
                f"""
                SELECT dp.secondary_identifier AS secondary_identifier,
                       COUNT(DISTINCT dp.primary_identifier) AS primary_identifier_count,
                       LISTAGG(DISTINCT dp.primary_identifier, ', ') WITHIN GROUP (ORDER BY dp.primary_identifier) AS primary_identifiers
                FROM file_profiles dp
                JOIN files f ON f.file_id = dp.file_id
                WHERE {' AND '.join(where_parts)}
                GROUP BY dp.secondary_identifier
                HAVING COUNT(DISTINCT dp.primary_identifier) > 1
                ORDER BY COUNT(DISTINCT dp.primary_identifier) DESC, dp.secondary_identifier ASC
                """,
                params,
            )
            return [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def _count_distinct_groups(self, *, where_parts: list[str], params: dict[str, Any], file_ids: list[int] | None) -> int:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            if file_ids:
                placeholders = []
                for index, file_id in enumerate([int(v) for v in file_ids if int(v) > 0]):
                    key = f"file_id_{index}"
                    params[key] = int(file_id)
                    placeholders.append(f":{key}")
                if placeholders:
                    where_parts.append(f"dp.file_id IN ({', '.join(placeholders)})")
            cursor.execute(
                f"""
                SELECT COUNT(DISTINCT dp.file_group_id)
                FROM file_profiles dp
                JOIN files f ON f.file_id = dp.file_id
                WHERE {' AND '.join(where_parts)}
                """,
                params,
            )
            return int(cursor.fetchone()[0] or 0)
        finally:
            cursor.close()
            connection.close()

    def _list_ids(self, sql_template: str, *, user_id: int, values: list[int], key_prefix: str) -> list[int]:
        safe_values = [int(value) for value in list(values or []) if int(value) > 0]
        if not safe_values:
            return []
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            placeholders: list[str] = []
            for index, value in enumerate(safe_values):
                key = f"{key_prefix}_{index}"
                params[key] = int(value)
                placeholders.append(f":{key}")
            cursor.execute(sql_template.format(placeholders=", ".join(placeholders)), params)
            return [int(row[0]) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def _normalize_entity_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "page_id": _optional_positive_int(row.get("page_id")),
            "entity_role": _required_text(row.get("entity_role"), max_len=64),
            "entity_type": _required_text(row.get("entity_type"), max_len=64, default="organization"),
            "entity_name": _normalized_text(row.get("entity_name"), max_len=512),
            "person_name": _normalized_text(row.get("person_name"), max_len=512),
            "identifier_value": _normalized_text(row.get("identifier_value"), max_len=128),
            "has_visible_signature": 1 if bool(row.get("has_visible_signature")) else 0,
            "bbox_json": _required_text(row.get("bbox_json"), max_len=4000, default="{}"),
            "metadata_json": _required_text(row.get("metadata_json"), max_len=4000, default="{}"),
            "confidence": _bounded_confidence(row.get("confidence")),
        }

    @staticmethod
    def _normalize_attribute_row(row: dict[str, Any]) -> dict[str, Any]:
        bool_value = row.get("attribute_value_bool")
        if bool_value is not None:
            bool_value = 1 if bool(bool_value) else 0
        return {
            "page_id": _optional_positive_int(row.get("page_id")),
            "attribute_key": _required_text(row.get("attribute_key"), max_len=128),
            "attribute_value_text": _normalized_text(row.get("attribute_value_text"), max_len=4000),
            "attribute_value_number": row.get("attribute_value_number"),
            "attribute_value_date": row.get("attribute_value_date"),
            "attribute_value_bool": bool_value,
            "source_type": _required_text(row.get("source_type"), max_len=64, default="ocr"),
            "metadata_json": _required_text(row.get("metadata_json"), max_len=4000, default="{}"),
            "confidence": _bounded_confidence(row.get("confidence")),
        }

    @staticmethod
    def _normalize_link_row(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "page_id": _optional_positive_int(row.get("page_id")),
            "link_type": _required_text(row.get("link_type"), max_len=64),
            "source_label": _normalized_text(row.get("source_label"), max_len=512),
            "target_label": _normalized_text(row.get("target_label"), max_len=512),
            "link_key": _normalized_text(row.get("link_key"), max_len=128),
            "metadata_json": _required_text(row.get("metadata_json"), max_len=4000, default="{}"),
            "confidence": _bounded_confidence(row.get("confidence")),
        }

    def _replace_rows(self, delete_sql: str, insert_sql: str, *, rows: list[dict[str, Any]], user_id: int, file_id: int, file_group_id: int | None) -> None:
        def _replace() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(delete_sql, file_id=int(file_id))
                for row in rows:
                    payload = dict(row)
                    payload["user_id"] = int(user_id)
                    payload["file_id"] = int(file_id)
                    payload["file_group_id"] = int(file_group_id) if file_group_id is not None else None
                    cursor.execute(insert_sql, payload)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        self._execute_retryable_write(operation=_replace)
