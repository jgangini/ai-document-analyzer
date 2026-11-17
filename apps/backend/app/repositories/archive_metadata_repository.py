"""SQL repository for canonical archive metadata uploads and persisted archive metadata."""

from __future__ import annotations

import json
from typing import Any

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.repositories.repository_utils import (
    build_file_access_scope_condition,
    build_oracle_text_contains_query,
    execute_with_retryable_database_operation,
    execute_with_oracle_text_repair,
    read_lob,
    row_to_dict,
)


class ArchiveMetadataRepository:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    @staticmethod
    def _read_lob(value: Any) -> Any:
        return read_lob(value)

    @staticmethod
    def _row_to_dict(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
        return row_to_dict(cursor, row)

    @staticmethod
    def _normalized_archive_slug(value: str | None) -> str:
        normalized = str(value or "").strip()
        return normalized[:256]

    @staticmethod
    def _normalized_upload_id(value: str | None) -> str:
        normalized = str(value or "").strip()
        return normalized[:64]

    @staticmethod
    def _normalize_access_scope(value: str | None, *, default_value: str = "private") -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "all":
            return "all"
        return default_value

    @staticmethod
    def _file_access_condition(
        *,
        alias: str = "",
        user_param: str = "user_id",
        include_shared: bool = False,
    ) -> str:
        return build_file_access_scope_condition(
            alias=alias,
            user_param=user_param,
            include_shared=include_shared,
        )

    @staticmethod
    def _metadata_upload_access_condition(
        *,
        alias: str = "u",
        user_param: str = "user_id",
        include_shared: bool = False,
    ) -> str:
        prefix = f"{alias}." if alias else ""
        owner_condition = f"{prefix}user_id = :{user_param}"
        if not include_shared:
            return owner_condition
        return (
            f"({owner_condition} OR "
            f"(:{user_param} > 0 AND LOWER(NVL({prefix}access_scope, 'private')) = 'all'))"
        )

    def create_upload(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        source_file_name: str,
        columns: list[str],
        total_rows: int,
        display_name: str | None = None,
        description: str | None = None,
        access_scope: str | None = None,
    ) -> dict[str, Any]:
        normalized_access_scope = self._normalize_access_scope(access_scope)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO archive_metadata_uploads (
                    metadata_upload_id,
                    user_id,
                    source_file_name,
                    display_name,
                    description,
                    access_scope,
                    metadata_status,
                    column_names_json,
                    total_rows
                ) VALUES (
                    :metadata_upload_id,
                    :user_id,
                    :source_file_name,
                    :display_name,
                    :description,
                    :access_scope,
                    'active',
                    :column_names_json,
                    :total_rows
                )
                """,
                metadata_upload_id=self._normalized_upload_id(metadata_upload_id),
                user_id=int(user_id),
                source_file_name=str(source_file_name or "").strip()[:500],
                display_name=str(display_name or source_file_name or "").strip()[:300],
                description=str(description or "").strip()[:1000] or None,
                access_scope=normalized_access_scope,
                column_names_json=json.dumps(list(columns or []), ensure_ascii=False),
                total_rows=int(total_rows or 0),
            )
            connection.commit()
            return self.get_upload(metadata_upload_id=metadata_upload_id, user_id=user_id) or {
                "metadata_upload_id": self._normalized_upload_id(metadata_upload_id),
                "user_id": int(user_id),
                "source_file_name": str(source_file_name or "").strip()[:500],
                "display_name": str(display_name or source_file_name or "").strip()[:300],
                "description": str(description or "").strip()[:1000],
                "access_scope": normalized_access_scope,
                "metadata_status": "active",
                "column_names_json": json.dumps(list(columns or []), ensure_ascii=False),
                "total_rows": int(total_rows or 0),
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def replace_upload_rows(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        rows: list[dict[str, Any]],
    ) -> None:
        def _write_rows() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    DELETE FROM archive_metadata_upload_rows
                    WHERE metadata_upload_id = :metadata_upload_id
                      AND user_id = :user_id
                    """,
                    metadata_upload_id=self._normalized_upload_id(metadata_upload_id),
                    user_id=int(user_id),
                )
                for row in list(rows or []):
                    cursor.execute(
                        """
                        INSERT INTO archive_metadata_upload_rows (
                            metadata_upload_id,
                            user_id,
                            file_key,
                            row_json,
                            search_text
                        ) VALUES (
                            :metadata_upload_id,
                            :user_id,
                            :file_key,
                            :row_json,
                            :search_text
                        )
                        """,
                        metadata_upload_id=self._normalized_upload_id(metadata_upload_id),
                        user_id=int(user_id),
                        file_key=self._normalized_archive_slug(str(row.get("file_key") or "")),
                        row_json=str(row.get("row_json") or "{}"),
                        search_text=str(row.get("search_text") or ""),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        execute_with_retryable_database_operation(
            db_manager=self.db_manager,
            operation=_write_rows,
            candidate_index_names=("IDX_ARCHIVE_METADATA_UPLOAD_ROWS_TEXT",),
        )

    def list_uploads_for_user(
        self,
        *,
        user_id: int,
        include_archived: bool = True,
        search_text: str | None = None,
        include_shared: bool = True,
    ) -> list[dict[str, Any]]:
        where_parts = [
            self._metadata_upload_access_condition(alias="u", include_shared=include_shared)
        ]
        params: dict[str, Any] = {"user_id": int(user_id)}
        if not include_archived:
            where_parts.append("LOWER(u.metadata_status) = 'active'")
        normalized_search = str(search_text or "").strip().lower()
        if normalized_search:
            where_parts.append(
                "("
                "LOWER(u.source_file_name) LIKE :search_text OR "
                "LOWER(NVL(u.display_name, '')) LIKE :search_text OR "
                "LOWER(NVL(u.description, '')) LIKE :search_text"
                ")"
            )
            params["search_text"] = f"%{normalized_search}%"

        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                       u.metadata_upload_id,
                       u.user_id,
                       u.source_file_name,
                       u.display_name,
                       u.description,
                       u.access_scope,
                       u.metadata_status,
                       u.column_names_json,
                       u.total_rows,
                       u.metadata_upload_created,
                       u.metadata_upload_updated,
                       NVL(row_counts.row_count, 0) AS row_count,
                       NVL(match_counts.matched_files_count, 0) AS matched_files_count,
                       GREATEST(NVL(row_counts.row_count, 0) - NVL(match_counts.matched_files_count, 0), 0)
                           AS unmatched_files_count,
                       NVL(link_counts.linked_documents_count, 0) AS linked_documents_count
                FROM archive_metadata_uploads u
                LEFT JOIN (
                    SELECT user_id, metadata_upload_id, COUNT(*) AS row_count
                    FROM archive_metadata_upload_rows
                    GROUP BY user_id, metadata_upload_id
                ) row_counts
                  ON row_counts.user_id = u.user_id
                 AND row_counts.metadata_upload_id = u.metadata_upload_id
                LEFT JOIN (
                    SELECT r.user_id, r.metadata_upload_id, COUNT(DISTINCT r.file_key) AS matched_files_count
                    FROM archive_metadata_upload_rows r
                    JOIN files f
                      ON LOWER(f.archive_slug) = LOWER(r.file_key)
                    WHERE {self._file_access_condition(alias="f", include_shared=True)}
                    GROUP BY r.user_id, r.metadata_upload_id
                ) match_counts
                  ON match_counts.user_id = u.user_id
                 AND match_counts.metadata_upload_id = u.metadata_upload_id
                LEFT JOIN (
                    SELECT am.metadata_upload_id, COUNT(DISTINCT f.file_id) AS linked_documents_count
                    FROM archive_metadata am
                    JOIN files f
                      ON f.user_id = am.user_id
                     AND LOWER(f.archive_slug) = LOWER(am.archive_slug)
                    WHERE am.metadata_upload_id IS NOT NULL
                      AND {self._file_access_condition(alias="f", include_shared=True)}
                    GROUP BY am.metadata_upload_id
                ) link_counts
                  ON link_counts.metadata_upload_id = u.metadata_upload_id
                WHERE {' AND '.join(where_parts)}
                ORDER BY u.metadata_upload_updated DESC, u.metadata_upload_created DESC
                """,
                params,
            )
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def update_upload_catalog(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        display_name: str | None | object = None,
        description: str | None | object = None,
        metadata_status: str | None | object = None,
        access_scope: str | None | object = None,
        update_display_name: bool = False,
        update_description: bool = False,
        update_metadata_status: bool = False,
        update_access_scope: bool = False,
    ) -> dict[str, Any] | None:
        assignments: list[str] = []
        params: dict[str, Any] = {
            "metadata_upload_id": self._normalized_upload_id(metadata_upload_id),
            "user_id": int(user_id),
        }
        if update_display_name:
            assignments.append("display_name = :display_name")
            params["display_name"] = str(display_name or "").strip()[:300] or None
        if update_description:
            assignments.append("description = :description")
            params["description"] = str(description or "").strip()[:1000] or None
        if update_metadata_status:
            normalized_status = str(metadata_status or "").strip().lower()
            if normalized_status not in {"active", "archived"}:
                raise ValueError("metadata_status must be active or archived")
            assignments.append("metadata_status = :metadata_status")
            params["metadata_status"] = normalized_status
        if update_access_scope:
            normalized_access_scope = self._normalize_access_scope(str(access_scope or None))
            assignments.append("access_scope = :access_scope")
            params["access_scope"] = normalized_access_scope
        if not assignments:
            return self.get_upload(metadata_upload_id=metadata_upload_id, user_id=user_id)

        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                UPDATE archive_metadata_uploads
                SET {', '.join(assignments)}
                WHERE metadata_upload_id = :metadata_upload_id
                  AND user_id = :user_id
                """,
                params,
            )
            updated = int(getattr(cursor, "rowcount", 0) or 0)
            connection.commit()
            if updated <= 0:
                return None
            return self.get_upload(metadata_upload_id=metadata_upload_id, user_id=user_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def update_upload_content(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        source_file_name: str,
        columns: list[str],
        total_rows: int,
    ) -> dict[str, Any] | None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE archive_metadata_uploads
                SET source_file_name = :source_file_name,
                    column_names_json = :column_names_json,
                    total_rows = :total_rows
                WHERE metadata_upload_id = :metadata_upload_id
                  AND user_id = :user_id
                """,
                metadata_upload_id=self._normalized_upload_id(metadata_upload_id),
                user_id=int(user_id),
                source_file_name=str(source_file_name or "").strip()[:500],
                column_names_json=json.dumps(list(columns or []), ensure_ascii=False),
                total_rows=int(total_rows or 0),
            )
            updated = int(getattr(cursor, "rowcount", 0) or 0)
            connection.commit()
            if updated <= 0:
                return None
            return self.get_upload(metadata_upload_id=metadata_upload_id, user_id=user_id)
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def list_upload_rows(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit or 200), 1000))
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT metadata_upload_row_id,
                       metadata_upload_id,
                       user_id,
                       file_key,
                       row_json,
                       search_text,
                       metadata_upload_row_created,
                       metadata_upload_row_updated
                FROM archive_metadata_upload_rows
                WHERE metadata_upload_id = :metadata_upload_id
                  AND user_id = :user_id
                ORDER BY metadata_upload_row_id
                FETCH FIRST {safe_limit} ROWS ONLY
                """,
                metadata_upload_id=self._normalized_upload_id(metadata_upload_id),
                user_id=int(user_id),
            )
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def delete_upload(self, *, metadata_upload_id: str, user_id: int) -> bool:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                DELETE FROM archive_metadata_uploads
                WHERE metadata_upload_id = :metadata_upload_id
                  AND user_id = :user_id
                """,
                metadata_upload_id=self._normalized_upload_id(metadata_upload_id),
                user_id=int(user_id),
            )
            deleted = int(getattr(cursor, "rowcount", 0) or 0) > 0
            connection.commit()
            return deleted
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def refresh_linked_archive_metadata_from_upload(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
    ) -> int:
        linked_slugs = {
            str(row.get("archive_slug") or "").strip().casefold()
            for row in self.list_archive_metadata_for_user(user_id=user_id, include_shared=False)
            if str(row.get("metadata_upload_id") or "").strip() == self._normalized_upload_id(metadata_upload_id)
            and str(row.get("archive_slug") or "").strip()
        }
        if not linked_slugs:
            return 0
        refreshed = 0
        for row in self.list_upload_rows(metadata_upload_id=metadata_upload_id, user_id=user_id, limit=1000):
            file_key = self._normalized_archive_slug(str(row.get("file_key") or ""))
            if not file_key or file_key.casefold() not in linked_slugs:
                continue
            raw_payload = self._read_lob(row.get("row_json"))
            try:
                payload = json.loads(str(raw_payload or "{}"))
            except Exception:
                payload = {"file": file_key, "fields": {}}
            persisted_metadata = {
                "file": str(payload.get("file") or file_key),
                "fields": dict(payload.get("fields") or {}),
            }
            self.upsert_archive_metadata(
                user_id=user_id,
                archive_slug=file_key,
                metadata_upload_id=metadata_upload_id,
                metadata_json=json.dumps(persisted_metadata, ensure_ascii=False),
                metadata_search_text=str(self._read_lob(row.get("search_text")) or ""),
            )
            refreshed += 1
        return refreshed

    def get_upload(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        include_shared: bool = False,
    ) -> dict[str, Any] | None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT metadata_upload_id,
                       user_id,
                       source_file_name,
                       display_name,
                       description,
                       access_scope,
                       metadata_status,
                       column_names_json,
                       total_rows,
                       metadata_upload_created,
                       metadata_upload_updated
                FROM archive_metadata_uploads
                WHERE metadata_upload_id = :metadata_upload_id
                  AND {self._metadata_upload_access_condition(alias="", include_shared=include_shared)}
                FETCH FIRST 1 ROWS ONLY
                """,
                metadata_upload_id=self._normalized_upload_id(metadata_upload_id),
                user_id=int(user_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(cursor, row)
        finally:
            cursor.close()
            connection.close()

    def get_upload_row(
        self,
        *,
        metadata_upload_id: str,
        user_id: int,
        file_key: str,
        include_shared: bool = True,
    ) -> dict[str, Any] | None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT r.metadata_upload_row_id,
                       r.metadata_upload_id,
                       r.user_id,
                       r.file_key,
                       r.row_json,
                       r.search_text,
                       r.metadata_upload_row_created,
                       r.metadata_upload_row_updated
                FROM archive_metadata_upload_rows r
                JOIN archive_metadata_uploads u
                  ON u.metadata_upload_id = r.metadata_upload_id
                 AND u.user_id = r.user_id
                WHERE r.metadata_upload_id = :metadata_upload_id
                  AND {self._metadata_upload_access_condition(alias="u", include_shared=include_shared)}
                  AND LOWER(r.file_key) = LOWER(:file_key)
                FETCH FIRST 1 ROWS ONLY
                """,
                metadata_upload_id=self._normalized_upload_id(metadata_upload_id),
                user_id=int(user_id),
                file_key=self._normalized_archive_slug(file_key),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(cursor, row)
        finally:
            cursor.close()
            connection.close()

    def list_known_archive_slugs_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[str]:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT DISTINCT archive_slug
                FROM files
                WHERE {self._file_access_condition(include_shared=include_shared)}
                  AND archive_slug IS NOT NULL
                ORDER BY archive_slug
                """,
                user_id=int(user_id),
            )
            return [
                str(self._read_lob(row[0]) or "").strip()
                for row in cursor.fetchall()
                if str(self._read_lob(row[0]) or "").strip()
            ]
        finally:
            cursor.close()
            connection.close()

    def upsert_archive_metadata(
        self,
        *,
        user_id: int,
        archive_slug: str,
        metadata_upload_id: str | None,
        metadata_json: str,
        metadata_search_text: str,
    ) -> None:
        normalized_user_id = int(user_id)
        normalized_archive_slug = self._normalized_archive_slug(archive_slug)
        normalized_upload_id = self._normalized_upload_id(metadata_upload_id) or None
        normalized_metadata_json = str(metadata_json or "{}")
        normalized_metadata_search_text = str(metadata_search_text or "")

        def _update_after_unique_race() -> bool:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE archive_metadata
                    SET metadata_upload_id = :metadata_upload_id,
                        metadata_source = 'metadata_csv',
                        metadata_json = :metadata_json,
                        metadata_search_text = :metadata_search_text
                    WHERE user_id = :user_id
                      AND LOWER(archive_slug) = LOWER(:archive_slug)
                    """,
                    user_id=normalized_user_id,
                    archive_slug=normalized_archive_slug,
                    metadata_upload_id=normalized_upload_id,
                    metadata_json=normalized_metadata_json,
                    metadata_search_text=normalized_metadata_search_text,
                )
                updated = int(getattr(cursor, "rowcount", 0) or 0) > 0
                connection.commit()
                return updated
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        def _upsert() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    MERGE INTO archive_metadata target
                    USING (
                        SELECT :user_id AS user_id,
                               :archive_slug AS archive_slug
                        FROM dual
                    ) source
                    ON (
                        target.user_id = source.user_id
                        AND LOWER(target.archive_slug) = LOWER(source.archive_slug)
                    )
                    WHEN MATCHED THEN UPDATE SET
                        metadata_upload_id = :metadata_upload_id,
                        metadata_source = 'metadata_csv',
                        metadata_json = :metadata_json,
                        metadata_search_text = :metadata_search_text
                    WHEN NOT MATCHED THEN INSERT (
                        user_id,
                        archive_slug,
                        metadata_upload_id,
                        metadata_source,
                        metadata_json,
                        metadata_search_text
                    ) VALUES (
                        :user_id,
                        :archive_slug,
                        :metadata_upload_id,
                        'metadata_csv',
                        :metadata_json,
                        :metadata_search_text
                    )
                    """,
                    user_id=normalized_user_id,
                    archive_slug=normalized_archive_slug,
                    metadata_upload_id=normalized_upload_id,
                    metadata_json=normalized_metadata_json,
                    metadata_search_text=normalized_metadata_search_text,
                )
                connection.commit()
            except Exception as exc:
                connection.rollback()
                if "ORA-00001" in str(exc) and _update_after_unique_race():
                    return
                raise
            finally:
                cursor.close()
                connection.close()

        execute_with_retryable_database_operation(
            db_manager=self.db_manager,
            operation=_upsert,
            candidate_index_names=("IDX_ARCHIVE_METADATA_TEXT",),
        )

    def get_archive_metadata_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        if not safe_file_ids:
            return []
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            placeholders: list[str] = []
            for index, file_id in enumerate(safe_file_ids):
                key = f"file_id_{index}"
                params[key] = int(file_id)
                placeholders.append(f":{key}")
            cursor.execute(
                f"""
                SELECT
                       f.file_id,
                       f.archive_slug,
                       am.metadata_upload_id,
                       amu.column_names_json,
                       am.metadata_json,
                       am.metadata_search_text
                FROM files f
                LEFT JOIN archive_metadata am
                  ON am.user_id = f.user_id
                 AND LOWER(am.archive_slug) = LOWER(f.archive_slug)
                LEFT JOIN archive_metadata_uploads amu
                  ON amu.metadata_upload_id = am.metadata_upload_id
                WHERE {self._file_access_condition(alias="f", include_shared=include_shared)}
                  AND f.file_id IN ({', '.join(placeholders)})
                ORDER BY f.file_id
                """,
                params,
            )
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def list_archive_metadata_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                       scoped.file_id,
                       scoped.archive_slug,
                       am.metadata_upload_id,
                       amu.column_names_json,
                       am.metadata_json,
                       am.metadata_search_text
                FROM (
                    SELECT
                           MIN(f.file_id) AS file_id,
                           f.user_id,
                           f.archive_slug
                    FROM files f
                    WHERE {self._file_access_condition(alias='f', include_shared=include_shared)}
                      AND f.archive_slug IS NOT NULL
                    GROUP BY f.user_id,
                             f.archive_slug
                ) scoped
                LEFT JOIN archive_metadata am
                  ON am.user_id = scoped.user_id
                 AND LOWER(am.archive_slug) = LOWER(scoped.archive_slug)
                LEFT JOIN archive_metadata_uploads amu
                  ON amu.metadata_upload_id = am.metadata_upload_id
                ORDER BY scoped.archive_slug
                """,
                user_id=int(user_id),
            )
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def search_file_ids_by_metadata_query(
        self,
        *,
        user_id: int,
        query_text: str,
        file_ids: list[int] | None = None,
        limit: int = 20,
        include_shared: bool = False,
    ) -> list[int]:
        safe_limit = max(1, min(int(limit), 100))
        contains_query = build_oracle_text_contains_query(query_text)
        if not contains_query:
            return []

        def _run_query() -> list[int]:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                params: dict[str, Any] = {
                    "user_id": int(user_id),
                    "contains_query": contains_query,
                }
                where_parts = [
                    self._file_access_condition(alias="f", include_shared=include_shared),
                    "CONTAINS(am.metadata_search_text, :contains_query, 1) > 0",
                ]
                safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
                if safe_file_ids:
                    placeholders: list[str] = []
                    for index, file_id in enumerate(safe_file_ids):
                        key = f"file_id_{index}"
                        params[key] = int(file_id)
                        placeholders.append(f":{key}")
                    where_parts.append(f"f.file_id IN ({', '.join(placeholders)})")
                cursor.execute(
                    f"""
                    SELECT DISTINCT f.file_id
                    FROM archive_metadata am
                    JOIN files f
                      ON f.user_id = am.user_id
                     AND LOWER(f.archive_slug) = LOWER(am.archive_slug)
                    WHERE {' AND '.join(where_parts)}
                    ORDER BY f.file_id
                    FETCH FIRST {safe_limit} ROWS ONLY
                    """,
                    params,
                )
                return [int(row[0]) for row in cursor.fetchall()]
            finally:
                cursor.close()
                connection.close()

        return execute_with_oracle_text_repair(
            db_manager=self.db_manager,
            operation=_run_query,
            candidate_index_names=("IDX_ARCHIVE_METADATA_TEXT",),
        )
