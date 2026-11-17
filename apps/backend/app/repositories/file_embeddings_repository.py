"""SQL repository for the `file_embeddings` table."""

from __future__ import annotations

import json
from typing import Any

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.core.db_types import normalize_embedding_vector
from apps.backend.app.repositories.repository_utils import (
    build_file_access_scope_condition,
    execute_with_retryable_database_operation,
    row_to_dict,
)


class FileEmbeddingsRepository:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    def add_or_replace_embedding(
        self,
        *,
        user_id: int,
        file_id: int,
        archive_slug: str | None,
        embedding_model: str,
        embedding_dimension: int,
        embedding_vector: list[float],
        summary_text: str,
        search_text: str,
    ) -> None:
        vector_payload = json.dumps(embedding_vector)

        def _write_embedding() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute("DELETE FROM file_embeddings WHERE file_id = :file_id", file_id=int(file_id))
                cursor.execute(
                    """
                    INSERT INTO file_embeddings (
                        user_id,
                        file_id,
                        archive_slug,
                        file_embeddings_model,
                        file_embeddings_dimension,
                        file_embeddings_vector,
                        file_embeddings_summary,
                        file_embeddings_search_text
                    ) VALUES (
                        :user_id,
                        :file_id,
                        :archive_slug,
                        :file_embeddings_model,
                        :file_embeddings_dimension,
                        TO_VECTOR(:file_embeddings_vector, *, FLOAT32),
                        :file_embeddings_summary,
                        :file_embeddings_search_text
                    )
                    """,
                    user_id=int(user_id),
                    file_id=int(file_id),
                    archive_slug=(str(archive_slug or "").strip()[:256] or None),
                    file_embeddings_model=str(embedding_model or "").strip(),
                    file_embeddings_dimension=int(embedding_dimension),
                    file_embeddings_vector=vector_payload,
                    file_embeddings_summary=str(summary_text or ""),
                    file_embeddings_search_text=str(search_text or ""),
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
            operation=_write_embedding,
            candidate_index_names=("IDX_FILE_EMBEDDINGS_SEARCH_TEXT",),
        )

    def list_embeddings(
        self,
        *,
        user_id: int | None = None,
        file_ids: list[int] | None = None,
        include_vectors: bool = False,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {}
            where_parts: list[str] = []
            if user_id is not None:
                params["user_id"] = int(user_id)
                where_parts.append(
                    build_file_access_scope_condition(
                        alias="f",
                        user_param="user_id",
                        include_shared=include_shared,
                    )
                )
            safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
            if safe_file_ids:
                placeholders: list[str] = []
                for index, file_id in enumerate(safe_file_ids):
                    key = f"file_id_{index}"
                    params[key] = int(file_id)
                    placeholders.append(f":{key}")
                where_parts.append(f"fe.file_id IN ({', '.join(placeholders)})")
            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
            cursor.execute(
                f"""
                SELECT fe.file_id,
                       fe.user_id,
                       fe.file_embeddings_model,
                       fe.file_embeddings_dimension,
                       fe.file_embeddings_vector,
                       fe.file_embeddings_summary,
                       fe.file_embeddings_search_text,
                       fe.archive_slug,
                       f.file_input_file_name,
                       f.file_code
                FROM file_embeddings fe
                JOIN files f ON f.file_id = fe.file_id
                {where_sql}
                ORDER BY fe.file_id
                """,
                params,
            )
            rows: list[dict[str, Any]] = []
            for row in cursor.fetchall():
                item = row_to_dict(cursor, row)
                if include_vectors:
                    item["file_embeddings_vector"] = normalize_embedding_vector(item.get("file_embeddings_vector"))
                else:
                    item.pop("file_embeddings_vector", None)
                rows.append(item)
            return rows
        finally:
            cursor.close()
            connection.close()
