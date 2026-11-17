"""SQL repository for `files` and related file artifacts."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from importlib import import_module
from pathlib import Path
import re
import time
from typing import Any, TypeVar

from apps.backend.app.repositories.file_repository_keys import (
    build_lexical_scan_terms,
    file_lookup_primary_keys,
    file_lookup_signature,
)
from apps.backend.app.repositories.repository_utils import (
    build_file_access_scope_condition,
    build_oracle_text_contains_query,
    code_to_status,
    execute_with_retryable_database_operation,
    execute_with_oracle_text_repair,
    is_oracle_text_loading_error,
    is_retryable_database_error,
    non_empty_string,
    repair_oracle_text_indexes,
    read_lob,
    row_to_dict,
    status_to_code,
)

T = TypeVar("T")


def _load_attr(module_name: str, attr_name: str):
    return getattr(import_module(module_name), attr_name)


class FileRepository:
    def __init__(self, db_manager: Any) -> None:
        FilePagesRepository = _load_attr(
            "apps.backend.app.repositories.document_pages_repository",
            "FilePagesRepository",
        )
        PageEmbeddingsRepository = _load_attr(
            "apps.backend.app.repositories.document_embeddings_repository",
            "PageEmbeddingsRepository",
        )
        FileEmbeddingsRepository = _load_attr(
            "apps.backend.app.repositories.file_embeddings_repository",
            "FileEmbeddingsRepository",
        )
        DocumentFactsRepository = _load_attr(
            "apps.backend.app.repositories.document_facts_repository",
            "DocumentFactsRepository",
        )
        ArchiveMetadataRepository = _load_attr(
            "apps.backend.app.repositories.archive_metadata_repository",
            "ArchiveMetadataRepository",
        )
        QAConversationsRepository = _load_attr(
            "apps.backend.app.repositories.chat_conversations_repository",
            "QAConversationsRepository",
        )
        QASessionsRepository = _load_attr(
            "apps.backend.app.repositories.chat_turns_repository",
            "QASessionsRepository",
        )
        self.db_manager = db_manager
        self.file_pages = FilePagesRepository(db_manager)
        self.page_embeddings = PageEmbeddingsRepository(db_manager)
        self.file_embeddings = FileEmbeddingsRepository(db_manager)
        self.document_facts = DocumentFactsRepository(db_manager)
        self.archive_metadata = ArchiveMetadataRepository(db_manager)
        self.qa_conversations = QAConversationsRepository(db_manager)
        self.qa_sessions = QASessionsRepository(db_manager)

    @staticmethod
    def _non_empty_string(value: str | None, *, default_value: str) -> str:
        return non_empty_string(value, default_value=default_value)

    @staticmethod
    def _normalize_access_scope(value: str | None, *, default_value: str = "private") -> str:
        normalized = str(value or "").strip().lower()
        if normalized == "all":
            return "all"
        return default_value

    @staticmethod
    def _status_to_code(status: str) -> int:
        return status_to_code(status)

    @staticmethod
    def _code_to_status(state_code: int | None) -> str:
        return code_to_status(state_code)

    @staticmethod
    def _local_pdf_is_encrypted(*, archive_slug: str, file_name: str) -> bool:
        archive = str(archive_slug or "").strip()
        name = str(file_name or "").strip()
        if not archive or not name or not name.lower().endswith(".pdf"):
            return False
        try:
            from pypdf import PdfReader
        except Exception:
            return False
        try:
            get_settings = _load_attr("apps.backend.app.core.config", "get_settings")
            extracted_root = get_settings().extracted_path
        except Exception:
            return False
        candidates: list[Path] = []
        try:
            for archive_dir in sorted(extracted_root.glob(f"{archive}-*")):
                candidate = archive_dir / name
                if candidate.is_file():
                    candidates.append(candidate)
        except Exception:
            candidates = []
        for candidate in candidates[:3]:
            try:
                reader = PdfReader(str(candidate), strict=False)
                if bool(reader.is_encrypted):
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _read_lob(value: Any) -> Any:
        return read_lob(value)

    @staticmethod
    def _row_to_dict(cursor, row: tuple[Any, ...]) -> dict[str, Any]:
        return row_to_dict(cursor, row)

    def _file_metadata_projection(self, *, alias: str = "") -> list[str]:
        prefix = f"{alias}." if alias else ""
        return [
            f"{prefix}file_code",
            f"{prefix}file_code_source",
            f"{prefix}access_scope",
        ]

    def _file_select_columns(self, *, alias: str = "") -> str:
        prefix = f"{alias}." if alias else ""
        columns = [
            f"{prefix}file_id",
            f"{prefix}user_id",
            f"{prefix}file_input_file_name",
            f"{prefix}file_input_obj_name",
            f"{prefix}file_output_obj_name",
            f"{prefix}archive_slug",
            f"{prefix}file_page_count",
            f"{prefix}file_state",
            f"{prefix}file_created",
            f"{prefix}file_updated",
            *self._file_metadata_projection(alias=alias),
        ]
        return ",\n                       ".join(columns)

    @staticmethod
    def _file_metadata_defaults() -> dict[str, Any]:
        return {
            "archive_slug": None,
            "file_code": None,
            "file_code_source": "none",
            "access_scope": "private",
        }

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
    def _dedupe_positive_ids(file_ids: list[int] | None) -> list[int]:
        seen: set[int] = set()
        ordered: list[int] = []
        for raw_value in list(file_ids or []):
            value = int(raw_value)
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    def _execute_retryable_write(
        self,
        *,
        operation: Callable[[], T],
        candidate_index_names: tuple[str, ...] = (),
    ) -> T:
        return execute_with_retryable_database_operation(
            db_manager=self.db_manager,
            operation=operation,
            candidate_index_names=candidate_index_names,
        )

    def get_or_create_file(
        self,
        *,
        user_id: int,
        file_name: str,
        original_local_path: str,
        bucket_object_name: str,
        file_input_size: int = 0,
        archive_slug: str | None = None,
        access_scope: str | None = None,
    ) -> dict[str, Any]:
        input_object_name = self._non_empty_string(bucket_object_name, default_value=original_local_path)
        normalized_archive_slug = (str(archive_slug or "").strip()[:256] or None)
        normalized_access_scope = (
            self._normalize_access_scope(access_scope)
            if access_scope is not None
            else None
        )
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT {self._file_select_columns()}
                FROM files
                WHERE user_id = :user_id
                  AND file_input_file_name = :file_name
                  AND NVL(file_input_obj_name, '') = :input_obj_name
                FETCH FIRST 1 ROWS ONLY
                """,
                user_id=user_id,
                file_name=file_name,
                input_obj_name=input_object_name,
            )
            row = cursor.fetchone()
            if row:
                payload = self._row_to_dict(cursor, row)
                existing_archive_slug = str(payload.get("archive_slug") or "").strip() or None
                existing_access_scope = self._normalize_access_scope(
                    str(payload.get("access_scope") or None),
                    default_value="private",
                )
                next_archive_slug = normalized_archive_slug if normalized_archive_slug else existing_archive_slug
                next_access_scope = normalized_access_scope if normalized_access_scope else existing_access_scope
                if next_archive_slug != existing_archive_slug or next_access_scope != existing_access_scope:
                    cursor.execute(
                        """
                        UPDATE files
                        SET archive_slug = :archive_slug,
                            access_scope = :access_scope
                        WHERE file_id = :file_id
                        """,
                        archive_slug=next_archive_slug,
                        access_scope=next_access_scope,
                        file_id=int(payload["file_id"]),
                    )
                    connection.commit()
                    payload["archive_slug"] = next_archive_slug
                    payload["access_scope"] = next_access_scope
                return payload

            file_id_var = cursor.var(int)
            created_var = cursor.var(datetime)
            updated_var = cursor.var(datetime)
            cursor.execute(
                """
                INSERT INTO files (
                    user_id,
                    file_input_file_name,
                    file_input_size,
                    file_input_obj_name,
                    file_output_obj_name,
                    archive_slug,
                    access_scope,
                    file_page_count,
                    file_state
                ) VALUES (
                    :user_id,
                    :file_input_file_name,
                    :file_input_size,
                    :file_input_obj_name,
                    :file_output_obj_name,
                    :archive_slug,
                    :access_scope,
                    :file_page_count,
                    :file_state
                )
                RETURNING file_id, file_created, file_updated
                INTO :file_id, :file_created, :file_updated
                """,
                user_id=user_id,
                file_input_file_name=file_name,
                file_input_size=int(file_input_size or 0),
                file_input_obj_name=input_object_name,
                file_output_obj_name=self._non_empty_string(bucket_object_name, default_value=f"pending/{file_name}"),
                archive_slug=normalized_archive_slug,
                access_scope=self._normalize_access_scope(normalized_access_scope, default_value="private"),
                file_page_count=0,
                file_state=self._status_to_code("registered"),
                file_id=file_id_var,
                file_created=created_var,
                file_updated=updated_var,
            )
            returned_file_id = int(file_id_var.getvalue()[0])
            created_at = created_var.getvalue()[0]
            updated_at = updated_var.getvalue()[0]
            connection.commit()
            return {
                "file_id": returned_file_id,
                "user_id": user_id,
                "file_input_file_name": file_name,
                "file_input_obj_name": input_object_name,
                "file_output_obj_name": self._non_empty_string(bucket_object_name, default_value=f"pending/{file_name}"),
                "archive_slug": normalized_archive_slug,
                "access_scope": self._normalize_access_scope(normalized_access_scope, default_value="private"),
                "file_page_count": 0,
                "file_state": self._status_to_code("registered"),
                "file_created": created_at,
                "file_updated": updated_at,
                **self._file_metadata_defaults(),
            }
        finally:
            cursor.close()
            connection.close()

    def get_user_storage_name(self, *, user_id: int) -> str:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT user_username
                FROM users
                WHERE user_id = :user_id
                FETCH FIRST 1 ROWS ONLY
                """,
                user_id=int(user_id),
            )
            row = cursor.fetchone()
            if row and row[0]:
                value = self._read_lob(row[0])
                normalized = str(value or "").strip()
                if normalized:
                    return normalized
            return f"user-{int(user_id)}"
        finally:
            cursor.close()
            connection.close()

    def find_user_id_by_username(self, *, username: str) -> int | None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            normalized = str(username or "").strip()
            if not normalized:
                return None
            cursor.execute(
                """
                SELECT user_id
                FROM users
                WHERE LOWER(user_username) = LOWER(:username)
                FETCH FIRST 1 ROWS ONLY
                """,
                username=normalized,
            )
            row = cursor.fetchone()
            if not row:
                return None
            value = self._read_lob(row[0])
            return int(value)
        finally:
            cursor.close()
            connection.close()

    def update_file_storage(self, file_id: int, *, bucket_object_name: str) -> None:
        def _update_storage() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE files
                    SET file_output_obj_name = :file_output_obj_name
                    WHERE file_id = :file_id
                    """,
                    file_output_obj_name=self._non_empty_string(bucket_object_name, default_value="pending/object"),
                    file_id=int(file_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        self._execute_retryable_write(operation=_update_storage)

    def update_file_document_metadata(
        self,
        *,
        file_id: int,
        document_code: str | None,
        document_code_source: str = "none",
        archive_slug: str | None = None,
    ) -> None:
        def _update_metadata() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    """
                    UPDATE files
                    SET file_code = :file_code,
                        file_code_source = :file_code_source,
                        archive_slug = COALESCE(:archive_slug, archive_slug)
                    WHERE file_id = :file_id
                    """,
                    file_code=(str(document_code).strip().upper()[:64] if document_code else None),
                    file_code_source=self._non_empty_string(document_code_source, default_value="none")[:32],
                    archive_slug=(str(archive_slug or "").strip()[:256] or None),
                    file_id=int(file_id),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        self._execute_retryable_write(operation=_update_metadata)

    def update_file_status(
        self,
        file_id: int,
        *,
        status: str,
        page_count: int | None = None,
        processing_notes: str | None = None,
    ) -> None:
        del processing_notes
        def _update_status() -> None:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                if page_count is None:
                    cursor.execute(
                        """
                        UPDATE files
                        SET file_state = :file_state
                        WHERE file_id = :file_id
                        """,
                        file_state=self._status_to_code(status),
                        file_id=int(file_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE files
                        SET file_state = :file_state,
                            file_page_count = :file_page_count
                        WHERE file_id = :file_id
                        """,
                        file_state=self._status_to_code(status),
                        file_page_count=int(page_count),
                        file_id=int(file_id),
                    )
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                cursor.close()
                connection.close()

        self._execute_retryable_write(operation=_update_status)

    def reset_file_derivatives(self, *, file_id: int) -> None:
        max_attempts = 3
        last_error: Exception | None = None
        for attempt in range(1, max_attempts + 1):
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                self.document_facts.reset_file_facts(file_id=file_id)
                cursor.execute("DELETE FROM file_embeddings WHERE file_id = :file_id", file_id=file_id)
                # `page_embeddings.file_pages_id` already cascades from `file_pages`.
                # Deleting child rows explicitly before the parent can deadlock Oracle
                # vector/text index maintenance with ORA-12860 sibling row locks.
                cursor.execute("DELETE FROM file_pages WHERE file_id = :file_id", file_id=file_id)
                cursor.execute(
                    """
                    UPDATE files
                    SET file_page_count = 0,
                        file_state = :file_state
                    WHERE file_id = :file_id
                    """,
                    file_state=self._status_to_code("registered"),
                    file_id=file_id,
                )
                connection.commit()
                return
            except Exception as exc:
                last_error = exc
                try:
                    connection.rollback()
                except Exception:
                    pass
                if is_oracle_text_loading_error(exc):
                    repair_oracle_text_indexes(
                        db_manager=self.db_manager,
                        candidate_index_names=(
                            "IDX_FILE_EMBEDDINGS_SEARCH_TEXT",
                            "IDX_FILE_PAGES_SEARCH_TEXT",
                        ),
                        error=exc,
                    )
                    if attempt >= max_attempts:
                        raise
                    time.sleep(0.25 * attempt)
                    continue
                if not is_retryable_database_error(exc) or attempt >= max_attempts:
                    raise
                time.sleep(float(attempt))
            finally:
                try:
                    cursor.close()
                except Exception:
                    pass
                try:
                    connection.close()
                except Exception:
                    pass
        if last_error is not None:
            raise last_error

    def list_files(self) -> list[dict[str, Any]]:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT {self._file_select_columns()}
                FROM files
                ORDER BY file_updated DESC
                """
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(cursor, row) for row in rows]
        finally:
            cursor.close()
            connection.close()

    def list_files_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        """List documents visible to a single user."""
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT {self._file_select_columns()}
                FROM files
                WHERE {self._file_access_condition(include_shared=include_shared)}
                ORDER BY file_updated DESC
                """,
                user_id=int(user_id),
            )
            rows = cursor.fetchall()
            return [self._row_to_dict(cursor, row) for row in rows]
        finally:
            cursor.close()
            connection.close()

    def list_page_quality_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        """Return Docling OCR quality rollups for selected files."""
        safe_file_ids = self._dedupe_positive_ids(file_ids)
        if not safe_file_ids:
            return []
        params: dict[str, Any] = {"user_id": int(user_id)}
        placeholders: list[str] = []
        for index, file_id in enumerate(safe_file_ids):
            key = f"file_id_{index}"
            params[key] = int(file_id)
            placeholders.append(f":{key}")

        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT f.file_id,
                       f.archive_slug,
                       f.file_input_file_name,
                       f.file_page_count,
                       f.file_state,
                       fp.file_pages_id,
                       fp.file_pages_number,
                       fp.file_pages_ocr_confidence,
                       fp.file_pages_ocr_method,
                       fp.file_pages_visual_flags,
                       fp.file_pages_text_quality,
                       DBMS_LOB.GETLENGTH(fp.file_pages_ocr_text) AS ocr_text_length
                FROM files f
                LEFT JOIN file_pages fp ON fp.file_id = f.file_id
                WHERE {self._file_access_condition(alias="f", include_shared=include_shared)}
                  AND f.file_id IN ({", ".join(placeholders)})
                ORDER BY f.file_id ASC, fp.file_pages_number ASC
                """,
                params,
            )
            rows = [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

        grouped: dict[int, dict[str, Any]] = {}
        for row in rows:
            file_id = int(row.get("file_id") or 0)
            if file_id <= 0:
                continue
            item = grouped.setdefault(
                file_id,
                {
                    "file_id": file_id,
                    "archive_slug": str(row.get("archive_slug") or ""),
                    "file_name": str(row.get("file_input_file_name") or f"file-{file_id}"),
                    "file_page_count": int(row.get("file_page_count") or 0),
                    "status": code_to_status(row.get("file_state")),
                    "indexed_pages_count": 0,
                    "low_ocr_pages_count": 0,
                    "blank_pages_count": 0,
                    "encrypted_or_unreadable_pages_count": 0,
                    "avg_ocr_confidence": 0.0,
                    "min_ocr_confidence": 0.0,
                    "avg_text_quality": 0.0,
                    "ocr_methods": [],
                    "visual_flags": [],
                    "_confidence_values": [],
                    "_quality_values": [],
                },
            )
            if row.get("file_pages_id") is None:
                continue
            item["indexed_pages_count"] = int(item["indexed_pages_count"]) + 1
            confidence = float(row.get("file_pages_ocr_confidence") or 0.0)
            text_quality = float(row.get("file_pages_text_quality") or 0.0)
            item["_confidence_values"].append(confidence)
            item["_quality_values"].append(text_quality)
            method = str(row.get("file_pages_ocr_method") or "").strip()
            if method and method not in item["ocr_methods"]:
                item["ocr_methods"].append(method)
            flags = [
                flag.strip()
                for flag in re.split(r"[,;|]\s*", str(row.get("file_pages_visual_flags") or ""))
                if flag.strip()
            ]
            for flag in flags:
                if flag not in item["visual_flags"]:
                    item["visual_flags"].append(flag)
            if confidence and confidence < 0.78 or "low_ocr_confidence" in flags:
                item["low_ocr_pages_count"] = int(item["low_ocr_pages_count"]) + 1
            if int(row.get("ocr_text_length") or 0) <= 20:
                item["blank_pages_count"] = int(item["blank_pages_count"]) + 1
            normalized_flags = " ".join(flags).lower()
            normalized_method = method.lower()
            if any(token in normalized_flags or token in normalized_method for token in ("encrypted", "cifrado", "password", "locked")):
                item["encrypted_or_unreadable_pages_count"] = int(item["encrypted_or_unreadable_pages_count"]) + 1

        result: list[dict[str, Any]] = []
        for item in grouped.values():
            confidence_values = list(item.pop("_confidence_values", []))
            quality_values = list(item.pop("_quality_values", []))
            if self._local_pdf_is_encrypted(
                archive_slug=str(item.get("archive_slug") or ""),
                file_name=str(item.get("file_name") or ""),
            ):
                item["encrypted_or_unreadable_pages_count"] = max(
                    1,
                    int(item["encrypted_or_unreadable_pages_count"] or 0),
                )
                if "pdf_encrypted" not in item["visual_flags"]:
                    item["visual_flags"].append("pdf_encrypted")
            if confidence_values:
                item["avg_ocr_confidence"] = sum(confidence_values) / len(confidence_values)
                item["min_ocr_confidence"] = min(confidence_values)
            if quality_values:
                item["avg_text_quality"] = sum(quality_values) / len(quality_values)
            if (
                item["status"] == "failed"
                and int(item["file_page_count"] or 0) > 0
                and int(item["indexed_pages_count"] or 0) == 0
            ):
                item["encrypted_or_unreadable_pages_count"] = max(
                    1,
                    int(item["encrypted_or_unreadable_pages_count"] or 0),
                )
            result.append(item)
        return result

    def count_files_for_user(self, *, user_id: int, include_shared: bool = False) -> int:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT COUNT(*)
                FROM files
                WHERE {self._file_access_condition(include_shared=include_shared)}
                """,
                user_id=int(user_id),
            )
            return int(cursor.fetchone()[0] or 0)
        finally:
            cursor.close()
            connection.close()

    def get_file(self, file_id: int) -> dict[str, Any] | None:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT {self._file_select_columns()}
                FROM files
                WHERE file_id = :file_id
                """,
                file_id=int(file_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_dict(cursor, row)
        finally:
            cursor.close()
            connection.close()

    def update_file_access_scope(self, *, file_id: int, user_id: int, access_scope: str) -> bool:
        normalized_access_scope = self._normalize_access_scope(access_scope)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE files
                SET access_scope = :access_scope
                WHERE file_id = :file_id
                  AND user_id = :user_id
                """,
                access_scope=normalized_access_scope,
                file_id=int(file_id),
                user_id=int(user_id),
            )
            updated = cursor.rowcount > 0
            connection.commit()
            return bool(updated)
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def update_files_access_scope(
        self,
        *,
        file_ids: list[int],
        user_id: int,
        access_scope: str,
    ) -> int:
        safe_file_ids = self._dedupe_positive_ids(file_ids)
        if not safe_file_ids:
            return 0

        normalized_access_scope = self._normalize_access_scope(access_scope)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {
                "user_id": int(user_id),
                "access_scope": normalized_access_scope,
            }
            placeholders: list[str] = []
            for index, file_id in enumerate(safe_file_ids):
                key = f"file_id_{index}"
                params[key] = int(file_id)
                placeholders.append(f":{key}")

            cursor.execute(
                f"""
                UPDATE files
                SET access_scope = :access_scope
                WHERE user_id = :user_id
                  AND file_id IN ({', '.join(placeholders)})
                """,
                params,
            )
            updated = int(cursor.rowcount or 0)
            connection.commit()
            return updated
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def filter_file_ids_for_user(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[int]:
        safe_file_ids = self._dedupe_positive_ids(file_ids)
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
                SELECT file_id
                FROM files
                WHERE {self._file_access_condition(include_shared=include_shared)}
                  AND file_id IN ({', '.join(placeholders)})
                ORDER BY file_id
                """,
                params,
            )
            return [int(row[0]) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def list_distinct_document_codes_for_user(
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
                SELECT DISTINCT file_code
                FROM files
                WHERE {self._file_access_condition(include_shared=include_shared)}
                  AND file_code IS NOT NULL
                ORDER BY file_code
                """,
                user_id=int(user_id),
            )
            return [str(row[0]).strip().upper() for row in cursor.fetchall() if str(row[0] or "").strip()]
        finally:
            cursor.close()
            connection.close()

    def list_file_ids_for_document_codes(
        self,
        *,
        user_id: int,
        document_codes: list[str],
        include_shared: bool = False,
    ) -> list[int]:
        safe_codes = [str(code or "").strip().upper() for code in document_codes if str(code or "").strip()]
        if not safe_codes:
            return []
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            placeholders: list[str] = []
            for index, code in enumerate(safe_codes):
                key = f"document_code_{index}"
                params[key] = code
                placeholders.append(f":{key}")
            cursor.execute(
                f"""
                SELECT file_id
                FROM files
                WHERE {self._file_access_condition(include_shared=include_shared)}
                  AND file_code IN ({', '.join(placeholders)})
                ORDER BY file_id
                """,
                params,
            )
            return [int(row[0]) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def list_file_ids_for_input_filenames(
        self,
        *,
        user_id: int,
        file_names: list[str],
        file_ids: list[int] | None = None,
        include_shared: bool = False,
    ) -> list[int]:
        safe_file_names = [
            str(file_name or "").strip()
            for file_name in file_names
            if str(file_name or "").strip()
        ]
        if not safe_file_names:
            return []
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            where_conditions = [
                self._file_access_condition(include_shared=include_shared),
            ]
            safe_file_ids = self._dedupe_positive_ids(file_ids)
            if safe_file_ids:
                file_id_placeholders: list[str] = []
                for index, file_id in enumerate(safe_file_ids):
                    key = f"file_id_{index}"
                    params[key] = int(file_id)
                    file_id_placeholders.append(f":{key}")
                where_conditions.append(f"file_id IN ({', '.join(file_id_placeholders)})")

            cursor.execute(
                f"""
                SELECT file_id, file_input_file_name
                FROM files
                WHERE {' AND '.join(where_conditions)}
                ORDER BY file_id
                """,
                params,
            )
            rows = [
                (int(row[0]), str(self._read_lob(row[1]) or ""))
                for row in cursor.fetchall()
                if int(row[0]) > 0
            ]
            input_primary_keys: set[str] = set()
            input_signatures: set[str] = set()
            for file_name in safe_file_names:
                input_primary_keys.update(file_lookup_primary_keys(file_name))
                signature = file_lookup_signature(file_name)
                if signature:
                    input_signatures.add(signature)

            matched_ids: set[int] = set()
            for file_id, stored_file_name in rows:
                if input_primary_keys & file_lookup_primary_keys(stored_file_name):
                    matched_ids.add(file_id)

            if input_signatures:
                rows_by_signature: dict[str, list[int]] = {}
                for file_id, stored_file_name in rows:
                    signature = file_lookup_signature(stored_file_name)
                    if not signature:
                        continue
                    rows_by_signature.setdefault(signature, []).append(file_id)
                for signature in input_signatures:
                    signature_file_ids = rows_by_signature.get(signature, [])
                    if len(signature_file_ids) == 1:
                        matched_ids.add(signature_file_ids[0])

            return [file_id for file_id, _ in rows if file_id in matched_ids]
        finally:
            cursor.close()
            connection.close()

    @staticmethod
    def _merge_lexical_rows(
        *,
        primary_rows: list[dict[str, Any]],
        scan_rows: list[dict[str, Any]],
        key_name: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        records: dict[int, dict[str, Any]] = {}
        order: dict[int, int] = {}
        for row in list(primary_rows or []) + list(scan_rows or []):
            key = int(row.get(key_name) or 0)
            if key <= 0:
                continue
            existing = records.get(key)
            if existing is None:
                records[key] = dict(row)
                order[key] = len(order)
                continue
            if float(row.get("lexical_score") or 0.0) > float(existing.get("lexical_score") or 0.0):
                existing["lexical_score"] = row.get("lexical_score")
        ranked = sorted(
            records.values(),
            key=lambda item: (
                float(item.get("lexical_score") or 0.0),
                -order.get(int(item.get(key_name) or 0), 0),
            ),
            reverse=True,
        )
        return ranked[: max(1, int(limit))]

    def _scan_lexical_pages(
        self,
        *,
        user_id: int,
        question: str,
        file_ids: list[int] | None,
        limit: int,
        include_shared: bool,
    ) -> list[dict[str, Any]]:
        terms = build_lexical_scan_terms(question)
        if not terms:
            return []
        params: dict[str, Any] = {"user_id": int(user_id)}
        score_parts: list[str] = []
        term_conditions: list[str] = []
        for index, term in enumerate(terms):
            key = f"scan_term_{index}"
            params[key] = term
            condition = f"INSTR(scanned.scan_text, :{key}) > 0"
            term_conditions.append(condition)
            score_parts.append(f"CASE WHEN {condition} THEN 1 ELSE 0 END")
        inner_where_conditions = [
            self._file_access_condition(alias="f", include_shared=include_shared),
        ]
        safe_file_ids = self._dedupe_positive_ids(file_ids)
        if safe_file_ids:
            placeholders: list[str] = []
            for index, file_id in enumerate(safe_file_ids):
                key = f"file_id_{index}"
                params[key] = int(file_id)
                placeholders.append(f":{key}")
            inner_where_conditions.append(f"f.file_id IN ({', '.join(placeholders)})")

        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            score_expr = " + ".join(score_parts)
            cursor.execute(
                f"""
                SELECT scanned.file_id,
                       scanned.file_pages_id,
                       scanned.file_pages_number,
                       scanned.file_pages_image_path_local,
                       scanned.file_pages_output_obj_name,
                       scanned.file_pages_ocr_confidence,
                       scanned.file_pages_ocr_method,
                       scanned.file_pages_ocr_text,
                       scanned.file_pages_visual_summary,
                       scanned.file_pages_search_text,
                       scanned.file_input_file_name,
                       scanned.archive_slug,
                       scanned.file_code,
                       ({score_expr}) AS lexical_score
                FROM (
                    SELECT fp.file_id,
                           fp.file_pages_id,
                           fp.file_pages_number,
                           fp.file_pages_image_path_local,
                           fp.file_pages_output_obj_name,
                           fp.file_pages_ocr_confidence,
                           fp.file_pages_ocr_method,
                           fp.file_pages_ocr_text,
                           fp.file_pages_visual_summary,
                           fp.file_pages_search_text,
                           f.file_input_file_name,
                           f.archive_slug,
                           f.file_code,
                           LOWER(DBMS_LOB.SUBSTR(fp.file_pages_search_text, 4000, 1)) AS scan_text
                    FROM file_pages fp
                    JOIN files f ON f.file_id = fp.file_id
                    WHERE {' AND '.join(inner_where_conditions)}
                ) scanned
                WHERE {' OR '.join(term_conditions)}
                ORDER BY ({score_expr}) DESC, scanned.file_id ASC, scanned.file_pages_number ASC
                FETCH FIRST {max(1, min(int(limit), 24000))} ROWS ONLY
                """,
                params,
            )
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def _scan_lexical_documents(
        self,
        *,
        user_id: int,
        question: str,
        file_ids: list[int] | None,
        limit: int,
        include_shared: bool,
    ) -> list[dict[str, Any]]:
        terms = build_lexical_scan_terms(question)
        if not terms:
            return []
        params: dict[str, Any] = {"user_id": int(user_id)}
        score_parts: list[str] = []
        term_conditions: list[str] = []
        for index, term in enumerate(terms):
            key = f"scan_term_{index}"
            params[key] = term
            condition = f"INSTR(scanned.scan_text, :{key}) > 0"
            term_conditions.append(condition)
            score_parts.append(f"CASE WHEN {condition} THEN 1 ELSE 0 END")
        inner_where_conditions = [
            self._file_access_condition(alias="f", include_shared=include_shared),
        ]
        safe_file_ids = self._dedupe_positive_ids(file_ids)
        if safe_file_ids:
            placeholders: list[str] = []
            for index, file_id in enumerate(safe_file_ids):
                key = f"file_id_{index}"
                params[key] = int(file_id)
                placeholders.append(f":{key}")
            inner_where_conditions.append(f"fe.file_id IN ({', '.join(placeholders)})")

        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            score_expr = " + ".join(score_parts)
            cursor.execute(
                f"""
                SELECT scanned.file_id,
                       scanned.file_embeddings_summary,
                       scanned.file_embeddings_search_text,
                       scanned.file_input_file_name,
                       scanned.archive_slug,
                       scanned.file_code,
                       ({score_expr}) AS lexical_score
                FROM (
                    SELECT fe.file_id,
                           fe.file_embeddings_summary,
                           fe.file_embeddings_search_text,
                           f.file_input_file_name,
                           f.archive_slug,
                           f.file_code,
                           LOWER(DBMS_LOB.SUBSTR(fe.file_embeddings_search_text, 4000, 1)) AS scan_text
                    FROM file_embeddings fe
                    JOIN files f ON f.file_id = fe.file_id
                    WHERE {' AND '.join(inner_where_conditions)}
                ) scanned
                WHERE {' OR '.join(term_conditions)}
                ORDER BY ({score_expr}) DESC, scanned.file_id ASC
                FETCH FIRST {max(1, min(int(limit), 24000))} ROWS ONLY
                """,
                params,
            )
            return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def search_lexical_pages(
        self,
        *,
        user_id: int,
        question: str,
        file_ids: list[int] | None = None,
        limit: int = 20,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 24000))
        contains_query = build_oracle_text_contains_query(question)
        text_rows: list[dict[str, Any]] = []

        def _run_query() -> list[dict[str, Any]]:
            params: dict[str, Any] = {
                "user_id": int(user_id),
                "contains_query": contains_query,
            }
            where_conditions = [
                self._file_access_condition(alias="f", include_shared=include_shared),
                "CONTAINS(fp.file_pages_search_text, :contains_query, 1) > 0",
            ]
            safe_file_ids = self._dedupe_positive_ids(file_ids)
            if safe_file_ids:
                placeholders: list[str] = []
                for index, file_id in enumerate(safe_file_ids):
                    key = f"file_id_{index}"
                    params[key] = int(file_id)
                    placeholders.append(f":{key}")
                where_conditions.append(f"f.file_id IN ({', '.join(placeholders)})")

            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                cursor.execute(
                    f"""
                    SELECT fp.file_id,
                           fp.file_pages_id,
                           fp.file_pages_number,
                           fp.file_pages_image_path_local,
                           fp.file_pages_output_obj_name,
                           fp.file_pages_ocr_confidence,
                           fp.file_pages_ocr_method,
                           fp.file_pages_ocr_text,
                           fp.file_pages_visual_summary,
                           fp.file_pages_search_text,
                           f.file_input_file_name,
                           f.archive_slug,
                           f.file_code,
                           SCORE(1) AS lexical_score
                    FROM file_pages fp
                    JOIN files f ON f.file_id = fp.file_id
                    WHERE {' AND '.join(where_conditions)}
                    ORDER BY SCORE(1) DESC, fp.file_id ASC, fp.file_pages_number ASC
                    FETCH FIRST {safe_limit} ROWS ONLY
                    """,
                    params,
                )
                return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
            finally:
                cursor.close()
                connection.close()

        if contains_query:
            text_rows = execute_with_oracle_text_repair(
                db_manager=self.db_manager,
                operation=_run_query,
                candidate_index_names=("IDX_FILE_PAGES_SEARCH_TEXT",),
            )
        scan_rows = self._scan_lexical_pages(
            user_id=user_id,
            question=question,
            file_ids=file_ids,
            limit=safe_limit,
            include_shared=include_shared,
        )
        return self._merge_lexical_rows(
            primary_rows=text_rows,
            scan_rows=scan_rows,
            key_name="file_pages_id",
            limit=safe_limit,
        )

    def search_lexical_documents(
        self,
        *,
        user_id: int,
        question: str,
        file_ids: list[int] | None = None,
        limit: int = 20,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        safe_limit = max(1, min(int(limit), 24000))
        contains_query = build_oracle_text_contains_query(question)
        text_rows: list[dict[str, Any]] = []

        def _run_query() -> list[dict[str, Any]]:
            connection = self.db_manager.get_connection()
            cursor = connection.cursor()
            try:
                params: dict[str, Any] = {
                    "user_id": int(user_id),
                    "contains_query": contains_query,
                }
                where_conditions = [
                    self._file_access_condition(alias="f", include_shared=include_shared),
                    "CONTAINS(fe.file_embeddings_search_text, :contains_query, 1) > 0",
                ]
                safe_file_ids = self._dedupe_positive_ids(file_ids)
                if safe_file_ids:
                    placeholders: list[str] = []
                    for index, file_id in enumerate(safe_file_ids):
                        key = f"file_id_{index}"
                        params[key] = int(file_id)
                        placeholders.append(f":{key}")
                    where_conditions.append(f"fe.file_id IN ({', '.join(placeholders)})")
                cursor.execute(
                    f"""
                    SELECT fe.file_id,
                           fe.file_embeddings_summary,
                           fe.file_embeddings_search_text,
                           f.file_input_file_name,
                           f.archive_slug,
                           f.file_code,
                           SCORE(1) AS lexical_score
                    FROM file_embeddings fe
                    JOIN files f ON f.file_id = fe.file_id
                    WHERE {' AND '.join(where_conditions)}
                    ORDER BY SCORE(1) DESC, fe.file_id ASC
                    FETCH FIRST {safe_limit} ROWS ONLY
                    """,
                    params,
                )
                return [self._row_to_dict(cursor, row) for row in cursor.fetchall()]
            finally:
                cursor.close()
                connection.close()

        if contains_query:
            text_rows = execute_with_oracle_text_repair(
                db_manager=self.db_manager,
                operation=_run_query,
                candidate_index_names=("IDX_FILE_EMBEDDINGS_SEARCH_TEXT",),
            )
        scan_rows = self._scan_lexical_documents(
            user_id=user_id,
            question=question,
            file_ids=file_ids,
            limit=safe_limit,
            include_shared=include_shared,
        )
        return self._merge_lexical_rows(
            primary_rows=text_rows,
            scan_rows=scan_rows,
            key_name="file_id",
            limit=safe_limit,
        )

    def delete_file(self, *, file_id: int, user_id: int | None = None) -> bool:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"file_id": int(file_id)}
            where_conditions = ["file_id = :file_id"]
            if user_id is not None:
                params["user_id"] = int(user_id)
                where_conditions.append("user_id = :user_id")
            cursor.execute(
                f"DELETE FROM files WHERE {' AND '.join(where_conditions)}",
                params,
            )
            deleted = cursor.rowcount > 0
            connection.commit()
            return bool(deleted)
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def delete_files(self, *, file_ids: list[int], user_id: int | None = None) -> int:
        safe_file_ids = self._dedupe_positive_ids(file_ids)
        if not safe_file_ids:
            return 0

        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {}
            placeholders: list[str] = []
            for index, file_id in enumerate(safe_file_ids):
                key = f"file_id_{index}"
                params[key] = int(file_id)
                placeholders.append(f":{key}")

            where_conditions = [f"file_id IN ({', '.join(placeholders)})"]
            if user_id is not None:
                params["user_id"] = int(user_id)
                where_conditions.append("user_id = :user_id")

            cursor.execute(
                f"""
                DELETE FROM files
                WHERE {' AND '.join(where_conditions)}
                """,
                params,
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

    def retry_file(self, *, file_id: int) -> bool:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE files
                SET file_state = :file_state
                WHERE file_id = :file_id
                """,
                file_state=self._status_to_code("processing"),
                file_id=int(file_id),
            )
            changed = cursor.rowcount > 0
            connection.commit()
            return bool(changed)
        finally:
            cursor.close()
            connection.close()

    def mark_incomplete_files_as_failed(self) -> int:
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE files
                SET file_state = :failed_state
                WHERE file_state = :processing_state
                """,
                failed_state=self._status_to_code("failed"),
                processing_state=self._status_to_code("processing"),
            )
            changed = int(cursor.rowcount or 0)
            connection.commit()
            return changed
        finally:
            cursor.close()
            connection.close()

    def add_page(self, **kwargs) -> dict[str, Any]:
        return self.file_pages.add_page(**kwargs)

    def list_file_ids_for_archive_slugs(
        self,
        *,
        user_id: int,
        archive_slugs: list[str],
        include_shared: bool = False,
    ) -> list[int]:
        safe_archive_slugs = [
            str(value or "").strip()
            for value in archive_slugs
            if str(value or "").strip()
        ]
        if not safe_archive_slugs:
            return []
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params: dict[str, Any] = {"user_id": int(user_id)}
            placeholders: list[str] = []
            for index, archive_slug in enumerate(safe_archive_slugs):
                key = f"archive_slug_{index}"
                params[key] = archive_slug
                placeholders.append(f"LOWER(:{key})")
            cursor.execute(
                f"""
                SELECT file_id
                FROM files
                WHERE {self._file_access_condition(include_shared=include_shared)}
                  AND LOWER(archive_slug) IN ({', '.join(placeholders)})
                ORDER BY file_id
                """,
                params,
            )
            return [int(row[0]) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()

    def get_archive_slug_map_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> dict[int, str]:
        safe_file_ids = self._dedupe_positive_ids(file_ids)
        if not safe_file_ids:
            return {}
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
                SELECT file_id, archive_slug
                FROM files
                WHERE {self._file_access_condition(include_shared=include_shared)}
                  AND file_id IN ({', '.join(placeholders)})
                ORDER BY file_id
                """,
                params,
            )
            return {
                int(row[0]): str(self._read_lob(row[1]) or "").strip()
                for row in cursor.fetchall()
                if int(row[0] or 0) > 0 and str(self._read_lob(row[1]) or "").strip()
            }
        finally:
            cursor.close()
            connection.close()

    def list_known_archive_slugs_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[str]:
        return self.archive_metadata.list_known_archive_slugs_for_user(
            user_id=user_id,
            include_shared=include_shared,
        )

    def search_file_ids_by_metadata_query(
        self,
        *,
        user_id: int,
        query_text: str,
        file_ids: list[int] | None = None,
        limit: int = 20,
        include_shared: bool = False,
    ) -> list[int]:
        return self.archive_metadata.search_file_ids_by_metadata_query(
            user_id=user_id,
            query_text=query_text,
            file_ids=file_ids,
            limit=limit,
            include_shared=include_shared,
        )

    def get_archive_metadata_for_file_ids(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        return self.archive_metadata.get_archive_metadata_for_file_ids(
            user_id=user_id,
            file_ids=file_ids,
            include_shared=include_shared,
        )

    def list_archive_metadata_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        return self.archive_metadata.list_archive_metadata_for_user(
            user_id=user_id,
            include_shared=include_shared,
        )

    def update_page_ocr_text(self, **kwargs) -> None:
        self.file_pages.update_page_ocr_text(**kwargs)

    def get_pages_by_file(self, file_id: int) -> list[dict[str, Any]]:
        return self.file_pages.get_pages_by_file(file_id)

    def get_page_image_record(self, *, file_id: int, page_number: int) -> dict[str, Any] | None:
        return self.file_pages.get_page_image_record(file_id=file_id, page_number=page_number)

    def get_file_markdown(self, *, file_id: int) -> str:
        return self.file_pages.get_file_markdown(file_id=file_id)

    def add_embedding(self, **kwargs) -> None:
        self.page_embeddings.add_embedding(**kwargs)

    def list_embeddings(
        self,
        file_ids: list[int] | None = None,
        *,
        user_id: int | None = None,
        include_vectors: bool = False,
        modalities: list[str] | None = None,
        include_shared: bool = False,
    ) -> list[dict[str, Any]]:
        return self.page_embeddings.list_embeddings(
            file_ids=file_ids,
            user_id=user_id,
            include_vectors=include_vectors,
            modalities=modalities,
            include_shared=include_shared,
        )

    def save_qa_session(self, **kwargs) -> dict[str, Any]:
        return self.qa_sessions.save_qa_session(**kwargs)

    def create_qa_conversation(self, **kwargs) -> dict[str, Any]:
        return self.qa_conversations.create_conversation(**kwargs)

    def list_qa_conversations(self, **kwargs) -> list[dict[str, Any]]:
        return self.qa_conversations.list_conversations(**kwargs)

    def get_qa_conversation(self, **kwargs) -> dict[str, Any] | None:
        return self.qa_conversations.get_conversation(**kwargs)

    def rename_qa_conversation(self, **kwargs) -> bool:
        return self.qa_conversations.rename_conversation(**kwargs)

    def delete_qa_conversation(self, **kwargs) -> bool:
        return self.qa_conversations.delete_conversation(**kwargs)

    def list_qa_conversation_messages(self, **kwargs) -> list[dict[str, Any]]:
        return self.qa_conversations.list_messages(**kwargs)
