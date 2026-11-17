"""SQL repository for `file_pages` and OCR artifacts."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.repositories.repository_utils import (
    execute_with_retryable_database_operation,
    non_empty_string,
    read_lob,
    row_to_dict,
)


class FilePagesRepository:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager

    def add_page(
        self,
        *,
        user_id: int,
        file_id: int,
        page_number: int,
        image_path_local: str,
        width: int,
        height: int,
        ocr_text: str,
        markdown_text: str,
        file_pages_output_obj_name: str = "",
        file_pages_ocr_obj_name: str = "",
        file_pages_ocr_confidence: float = 0.0,
        file_pages_ocr_method: str = "docling_rapidocr",
        file_pages_visual_summary: str = "",
        file_pages_layout_json: str = "{}",
        file_pages_search_text: str = "",
        file_pages_visual_flags: str = "",
        file_pages_text_quality: float = 0.0,
    ) -> dict[str, Any]:
        def _insert_page() -> dict[str, Any]:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                page_id_var = cursor.var(int)
                created_var = cursor.var(datetime)
                cursor.execute(
                    """
                    INSERT INTO file_pages (
                        user_id,
                        file_id,
                        file_pages_number,
                        file_pages_image_path_local,
                        file_pages_output_obj_name,
                        file_pages_ocr_obj_name,
                        file_pages_ocr_confidence,
                        file_pages_ocr_method,
                        file_pages_ocr_text,
                        file_pages_markdown_text,
                        file_pages_visual_summary,
                        file_pages_layout_json,
                        file_pages_search_text,
                        file_pages_visual_flags,
                        file_pages_text_quality,
                        file_pages_width,
                        file_pages_height,
                        file_pages_state
                    ) VALUES (
                        :user_id,
                        :file_id,
                        :file_pages_number,
                        :file_pages_image_path_local,
                        :file_pages_output_obj_name,
                        :file_pages_ocr_obj_name,
                        :file_pages_ocr_confidence,
                        :file_pages_ocr_method,
                        :file_pages_ocr_text,
                        :file_pages_markdown_text,
                        :file_pages_visual_summary,
                        :file_pages_layout_json,
                        :file_pages_search_text,
                        :file_pages_visual_flags,
                        :file_pages_text_quality,
                        :file_pages_width,
                        :file_pages_height,
                        1
                    )
                    RETURNING file_pages_id, file_pages_created
                    INTO :file_pages_id, :file_pages_created
                    """,
                    user_id=int(user_id),
                    file_id=int(file_id),
                    file_pages_number=int(page_number),
                    file_pages_image_path_local=image_path_local or "",
                    file_pages_output_obj_name=non_empty_string(file_pages_output_obj_name, default_value="local-page-only"),
                    file_pages_ocr_obj_name=non_empty_string(file_pages_ocr_obj_name, default_value=""),
                    file_pages_ocr_confidence=float(max(0.0, min(1.0, file_pages_ocr_confidence))),
                    file_pages_ocr_method=non_empty_string(file_pages_ocr_method, default_value="docling_rapidocr"),
                    file_pages_ocr_text=non_empty_string(ocr_text, default_value="No OCR text extracted."),
                    file_pages_markdown_text=str(markdown_text),
                    file_pages_visual_summary=str(file_pages_visual_summary or ""),
                    file_pages_layout_json=str(file_pages_layout_json or "{}"),
                    file_pages_search_text=str(file_pages_search_text or ""),
                    file_pages_visual_flags=str(file_pages_visual_flags or ""),
                    file_pages_text_quality=float(max(0.0, min(1.0, file_pages_text_quality))),
                    file_pages_width=int(width or 0),
                    file_pages_height=int(height or 0),
                    file_pages_id=page_id_var,
                    file_pages_created=created_var,
                )
                connection.commit()
                page_id = int(page_id_var.getvalue()[0])
                created_at = created_var.getvalue()[0]
                return {
                    "file_pages_id": page_id,
                    "file_id": int(file_id),
                    "user_id": int(user_id),
                    "file_pages_number": int(page_number),
                    "file_pages_image_path_local": image_path_local or "",
                    "file_pages_output_obj_name": non_empty_string(
                        file_pages_output_obj_name,
                        default_value="local-page-only",
                    ),
                    "file_pages_ocr_obj_name": non_empty_string(file_pages_ocr_obj_name, default_value=""),
                    "file_pages_ocr_confidence": float(max(0.0, min(1.0, file_pages_ocr_confidence))),
                    "file_pages_ocr_method": non_empty_string(
                        file_pages_ocr_method,
                        default_value="docling_rapidocr",
                    ),
                    "file_pages_width": int(width or 0),
                    "file_pages_height": int(height or 0),
                    "file_pages_ocr_text": non_empty_string(ocr_text, default_value="No OCR text extracted."),
                    "file_pages_markdown_text": str(markdown_text),
                    "file_pages_visual_summary": str(file_pages_visual_summary or ""),
                    "file_pages_layout_json": str(file_pages_layout_json or "{}"),
                    "file_pages_search_text": str(file_pages_search_text or ""),
                    "file_pages_visual_flags": str(file_pages_visual_flags or ""),
                    "file_pages_text_quality": float(max(0.0, min(1.0, file_pages_text_quality))),
                    "file_pages_created": created_at,
                }
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        return execute_with_retryable_database_operation(
            db_manager=self.db_manager,
            operation=_insert_page,
            candidate_index_names=("IDX_FILE_PAGES_SEARCH_TEXT",),
        )

    def update_page_ocr_text(self, *, page_id: int, ocr_text: str) -> None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE file_pages
                SET file_pages_ocr_text = :ocr_text
                WHERE file_pages_id = :page_id
                """,
                ocr_text=non_empty_string(ocr_text, default_value="No OCR text extracted."),
                page_id=int(page_id),
            )
            connection.commit()
        finally:
            cursor.close()
            connection.close()

    def update_page_rag_enrichment(
        self,
        *,
        page_id: int,
        visual_summary: str,
        layout_json: str,
        search_text: str,
        visual_flags: str,
        text_quality: float,
    ) -> None:
        def _update_page() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE file_pages
                    SET file_pages_visual_summary = :visual_summary,
                        file_pages_layout_json = :layout_json,
                        file_pages_search_text = :search_text,
                        file_pages_visual_flags = :visual_flags,
                        file_pages_text_quality = :text_quality
                    WHERE file_pages_id = :page_id
                    """,
                    visual_summary=str(visual_summary or ""),
                    layout_json=str(layout_json or "{}"),
                    search_text=str(search_text or ""),
                    visual_flags=str(visual_flags or ""),
                    text_quality=float(max(0.0, min(1.0, text_quality))),
                    page_id=int(page_id),
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
            operation=_update_page,
            candidate_index_names=("IDX_FILE_PAGES_SEARCH_TEXT",),
        )

    def get_pages_by_file(self, file_id: int) -> list[dict[str, Any]]:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT file_pages_id, file_id, user_id, file_pages_number, file_pages_image_path_local,
                       file_pages_output_obj_name, file_pages_ocr_obj_name, file_pages_ocr_confidence,
                       file_pages_ocr_method, file_pages_width, file_pages_height, file_pages_ocr_text,
                       file_pages_markdown_text, file_pages_visual_summary, file_pages_layout_json, file_pages_search_text,
                       file_pages_visual_flags, file_pages_text_quality, file_pages_created
                FROM file_pages
                WHERE file_id = :file_id
                ORDER BY file_pages_number ASC
                """,
                file_id=int(file_id),
            )
            return [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def get_page_image_record(self, *, file_id: int, page_number: int) -> dict[str, Any] | None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT file_pages_id, file_id, user_id, file_pages_number,
                       file_pages_image_path_local, file_pages_output_obj_name
                FROM file_pages
                WHERE file_id = :file_id
                  AND file_pages_number = :page_number
                """,
                file_id=int(file_id),
                page_number=int(page_number),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return row_to_dict(cursor, row)
        finally:
            cursor.close()
            connection.close()

    def get_file_markdown(self, *, file_id: int) -> str:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT file_pages_number, file_pages_markdown_text
                FROM file_pages
                WHERE file_id = :file_id
                ORDER BY file_pages_number
                """,
                file_id=int(file_id),
            )
            rows = cursor.fetchall()
            if not rows:
                raise RuntimeError(f"Markdown extraction is missing for file {file_id}.")
            sections: list[str] = []
            for row in rows:
                page_no = int(row[0] or 0)
                markdown_value = read_lob(row[1])
                if markdown_value is None:
                    raise RuntimeError(f"Markdown extraction is missing for file {file_id} page {page_no}.")
                sections.append(f"## Page {page_no}\n\n{str(markdown_value).strip()}")
            return "\n\n".join(sections).strip()
        finally:
            cursor.close()
            connection.close()
