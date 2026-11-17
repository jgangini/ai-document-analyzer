"""Vector search helpers for Oracle AI Database."""

from __future__ import annotations

import json
from dataclasses import dataclass

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.repositories.repository_utils import build_file_access_scope_condition


@dataclass(slots=True)
class OracleVectorSearchResult:
    file_id: int
    file_name: str
    archive_slug: str
    file_code: str | None
    page_id: int
    page_number: int
    score: float
    summary_text: str
    image_path_local: str
    object_name_page: str
    modality: str
    extraction_method: str
    ocr_confidence: float | None


@dataclass(slots=True)
class OracleDocumentSearchResult:
    file_id: int
    file_name: str
    file_code: str | None
    score: float
    summary_text: str
    search_text: str


class OracleVectorStore:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    def similarity_search(
        self,
        *,
        query_vector: list[float],
        user_id: int | None = None,
        file_ids: list[int] | None = None,
        modality: str | None = None,
        top_k: int = 5,
        include_shared: bool = False,
    ) -> list[OracleVectorSearchResult]:
        safe_top_k = max(1, min(int(top_k), 24000))
        params: dict[str, object] = {"query_vector": json.dumps(query_vector)}
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
                placeholders.append(f":{key}")
                params[key] = int(file_id)
            where_parts.append(f"pe.file_id IN ({', '.join(placeholders)})")
        if modality:
            params["modality"] = str(modality).strip().lower()
            where_parts.append("LOWER(pe.page_embeddings_modality) = :modality")
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    pe.file_id AS file_id,
                    f.file_input_file_name AS file_name,
                    f.archive_slug AS archive_slug,
                    f.file_code AS file_code,
                    pe.file_pages_id AS page_id,
                    fp.file_pages_number AS page_number,
                    1 - VECTOR_DISTANCE(
                        pe.page_embeddings_vector,
                        TO_VECTOR(:query_vector, *, FLOAT32),
                        COSINE
                    ) AS score,
                    pe.page_embeddings_summary AS summary_text,
                    fp.file_pages_image_path_local AS image_path_local,
                    fp.file_pages_output_obj_name AS object_name_page,
                    pe.page_embeddings_modality AS modality,
                    fp.file_pages_ocr_method AS extraction_method,
                    fp.file_pages_ocr_confidence AS ocr_confidence
                FROM page_embeddings pe
                JOIN file_pages fp ON fp.file_pages_id = pe.file_pages_id
                JOIN files f ON f.file_id = pe.file_id
                {where_clause}
                ORDER BY VECTOR_DISTANCE(
                    pe.page_embeddings_vector,
                    TO_VECTOR(:query_vector, *, FLOAT32),
                    COSINE
                )
                FETCH APPROX FIRST {safe_top_k} ROWS ONLY
                """,
                params,
            )
            rows = cursor.fetchall()
            results: list[OracleVectorSearchResult] = []
            for row in rows:
                summary = row[7]
                if hasattr(summary, "read"):
                    summary = summary.read()
                results.append(
                    OracleVectorSearchResult(
                        file_id=int(row[0]),
                        file_name=str(row[1]),
                        archive_slug=str(row[2] or ""),
                        file_code=(str(row[3]).strip().upper() if row[3] is not None and str(row[3]).strip() else None),
                        page_id=int(row[4]),
                        page_number=int(row[5]),
                        score=float(row[6] or 0.0),
                        summary_text=str(summary or ""),
                        image_path_local=str(row[8] or ""),
                        object_name_page=str(row[9] or ""),
                        modality=str(row[10] or ""),
                        extraction_method=str(row[11] or ""),
                        ocr_confidence=float(row[12]) if row[12] is not None else None,
                    )
                )
            return results
        finally:
            cursor.close()
            connection.close()

    def document_similarity_search(
        self,
        *,
        query_vector: list[float],
        user_id: int | None = None,
        file_ids: list[int] | None = None,
        top_k: int = 10,
        include_shared: bool = False,
    ) -> list[OracleDocumentSearchResult]:
        safe_top_k = max(1, min(int(top_k), 24000))
        params: dict[str, object] = {"query_vector": json.dumps(query_vector)}
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
                placeholders.append(f":{key}")
                params[key] = int(file_id)
            where_parts.append(f"fe.file_id IN ({', '.join(placeholders)})")
        where_clause = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    fe.file_id AS file_id,
                    f.file_input_file_name AS file_name,
                    f.file_code AS file_code,
                    1 - VECTOR_DISTANCE(
                        fe.file_embeddings_vector,
                        TO_VECTOR(:query_vector, *, FLOAT32),
                        COSINE
                    ) AS score,
                    fe.file_embeddings_summary AS summary_text,
                    fe.file_embeddings_search_text AS search_text
                FROM file_embeddings fe
                JOIN files f ON f.file_id = fe.file_id
                {where_clause}
                ORDER BY VECTOR_DISTANCE(
                    fe.file_embeddings_vector,
                    TO_VECTOR(:query_vector, *, FLOAT32),
                    COSINE
                )
                FETCH APPROX FIRST {safe_top_k} ROWS ONLY
                """,
                params,
            )
            rows = cursor.fetchall()
            results: list[OracleDocumentSearchResult] = []
            for row in rows:
                summary = row[4]
                search_text = row[5]
                if hasattr(summary, "read"):
                    summary = summary.read()
                if hasattr(search_text, "read"):
                    search_text = search_text.read()
                results.append(
                    OracleDocumentSearchResult(
                        file_id=int(row[0]),
                        file_name=str(row[1]),
                        file_code=(str(row[2]).strip().upper() if row[2] is not None and str(row[2]).strip() else None),
                        score=float(row[3] or 0.0),
                        summary_text=str(summary or ""),
                        search_text=str(search_text or ""),
                    )
                )
            return results
        finally:
            cursor.close()
            connection.close()
