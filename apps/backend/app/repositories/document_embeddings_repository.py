"""SQL repository for the `page_embeddings` table."""

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


class PageEmbeddingsRepository:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    def add_embedding(
        self,
        *,
        user_id: int,
        file_id: int,
        page_id: int,
        archive_slug: str | None,
        embedding_model: str,
        embedding_dimension: int,
        embedding_vector: list[float],
        modality: str,
        summary_text: str,
    ) -> None:
        vector_payload = json.dumps(embedding_vector)

        def _insert_embedding() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    INSERT INTO page_embeddings (
                        user_id,
                        file_id,
                        file_pages_id,
                        archive_slug,
                        page_embeddings_model,
                        page_embeddings_dimension,
                        page_embeddings_vector,
                        page_embeddings_modality,
                        page_embeddings_summary
                    ) VALUES (
                        :user_id,
                        :file_id,
                        :file_pages_id,
                        :archive_slug,
                        :page_embeddings_model,
                        :page_embeddings_dimension,
                        TO_VECTOR(:page_embeddings_vector, *, FLOAT32),
                        :page_embeddings_modality,
                        :page_embeddings_summary
                    )
                    """,
                    user_id=int(user_id),
                    file_id=int(file_id),
                    file_pages_id=int(page_id),
                    archive_slug=(str(archive_slug or "").strip()[:256] or None),
                    page_embeddings_model=embedding_model,
                    page_embeddings_dimension=int(embedding_dimension),
                    page_embeddings_vector=vector_payload,
                    page_embeddings_modality=modality,
                    page_embeddings_summary=str(summary_text or ""),
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
            operation=_insert_embedding,
        )

    def list_embeddings(
        self,
        file_ids: list[int] | None = None,
        *,
        user_id: int | None = None,
        include_vectors: bool = False,
        modalities: list[str] | None = None,
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
            if file_ids:
                placeholders = []
                for index, file_id in enumerate(file_ids):
                    key = f"file_id_{index}"
                    params[key] = int(file_id)
                    placeholders.append(f":{key}")
                where_parts.append(f"pe.file_id IN ({', '.join(placeholders)})")
            safe_modalities = [str(item or "").strip().lower() for item in list(modalities or []) if str(item or "").strip()]
            if safe_modalities:
                placeholders = []
                for index, modality in enumerate(safe_modalities):
                    key = f"modality_{index}"
                    params[key] = modality
                    placeholders.append(f":{key}")
                where_parts.append(f"LOWER(pe.page_embeddings_modality) IN ({', '.join(placeholders)})")
            where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
            cursor.execute(
                f"""
                SELECT pe.file_id,
                       pe.file_pages_id,
                       pe.page_embeddings_summary,
                       pe.page_embeddings_vector,
                       pe.page_embeddings_dimension,
                       pe.page_embeddings_modality,
                       pe.archive_slug,
                       fp.file_pages_number,
                       fp.file_pages_image_path_local,
                       fp.file_pages_output_obj_name,
                       fp.file_pages_ocr_obj_name,
                       fp.file_pages_ocr_confidence,
                       fp.file_pages_ocr_method,
                       fp.file_pages_ocr_text,
                       f.file_input_file_name
                FROM page_embeddings pe
                JOIN file_pages fp ON fp.file_pages_id = pe.file_pages_id
                JOIN files f ON f.file_id = pe.file_id
                {where_sql}
                """,
                params,
            )
            results: list[dict[str, Any]] = []
            for row in cursor.fetchall():
                item = row_to_dict(cursor, row)
                if include_vectors:
                    item["page_embeddings_vector"] = normalize_embedding_vector(item.get("page_embeddings_vector"))
                else:
                    item.pop("page_embeddings_vector", None)
                results.append(item)
            return results
        finally:
            cursor.close()
            connection.close()
