"""Document ingestion orchestration: ZIP/PDF -> OCR -> storage -> RAG artifacts."""

from __future__ import annotations

from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib import import_module
import json
from pathlib import Path
from threading import Lock
import time
from typing import Any, Callable, Iterator, TypeVar

from apps.backend.app.contracts.files import FileProcessItem
from apps.backend.app.core.hashing import sha256_file
from apps.backend.app.ingest.document_metadata import (
    FileMetadata,
    FileMetadataClassifier,
    extract_document_code_from_filename,
    normalize_document_code_value,
)
from apps.backend.app.ingest.text_utils import (
    build_document_search_text,
    build_page_search_text,
    compact_whitespace,
)
from apps.backend.app.services.metadata_keys import (
    build_metadata_search_text,
    canonicalize_file_key,
    normalize_metadata_attribute_key,
)
from apps.backend.app.storage.object_keys import (
    build_archive_prefix,
    build_page_ocr_json_key,
    build_page_png_key,
    build_pdf_source_key,
    build_zip_source_key,
)

T = TypeVar("T")


def _load_attr(module_name: str, attr_name: str):
    return getattr(import_module(module_name), attr_name)


@dataclass(slots=True)
class IngestionPlanResult:
    processed: list[FileProcessItem] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class IngestionService:
    def __init__(
        self,
        *,
        settings: Any,
        db_manager: Any | None = None,
        archive_service: Any,
        pdf_service: Any,
        docling_document_service: DoclingDocumentService | None = None,
        embedding_service: Any,
        object_storage: Any,
    ) -> None:
        DoclingDocumentService = _load_attr(
            "apps.backend.app.ingest.docling_document_service",
            "DoclingDocumentService",
        )
        PageVisualEnricher = _load_attr("apps.backend.app.ingest.rag_enrichment", "PageVisualEnricher")
        DocumentFactExtractor = _load_attr(
            "apps.backend.app.ingest.rag_enrichment",
            "DocumentFactExtractor",
        )
        self.settings = settings
        self.db_manager = db_manager
        self.archive_service = archive_service
        self.pdf_service = pdf_service
        self.docling_document_service = docling_document_service or DoclingDocumentService(settings)
        self.embedding_service = embedding_service
        self.object_storage = object_storage
        self.repository = None
        if db_manager is not None:
            FileRepository = _load_attr("apps.backend.app.repositories.file_repository", "FileRepository")
            self.repository = FileRepository(db_manager)
        self.file_metadata_classifier = FileMetadataClassifier(
            settings=settings,
            db_manager=db_manager,
        )
        self.page_visual_enricher = PageVisualEnricher(
            settings=settings,
            db_manager=db_manager,
        )
        self.document_fact_extractor = DocumentFactExtractor(
            settings=settings,
            db_manager=db_manager,
        )
        self._archive_execution_slots: dict[tuple[int, str], Lock] = {}
        self._archive_execution_slots_guard = Lock()
        self._file_registration_guard = Lock()
        self._uploaded_zip_keys: set[str] = set()
        self._uploaded_zip_keys_lock = Lock()

    @staticmethod
    def _normalize_parallel_bucket_key(*values: object) -> str:
        for value in values:
            normalized = str(value or "").strip().lower()
            if normalized:
                return normalized
        return "__default__"

    @staticmethod
    def _round_robin_bucket_values(*, buckets: dict[str, deque[T]], bucket_order: list[str]) -> list[T]:
        ordered: list[T] = []
        remaining = list(bucket_order)
        while remaining:
            next_remaining: list[str] = []
            for key in remaining:
                queue = buckets.get(key)
                if not queue:
                    continue
                ordered.append(queue.popleft())
                if queue:
                    next_remaining.append(key)
            remaining = next_remaining
        return ordered

    @classmethod
    def _interleave_plan_items_by_archive(
        cls,
        *,
        process_items: list[dict[str, object]],
    ) -> list[dict[str, object]]:
        buckets: dict[str, deque[dict[str, object]]] = {}
        bucket_order: list[str] = []
        for raw_item in process_items:
            key = cls._normalize_parallel_bucket_key(
                raw_item.get("archive_slug"),
                raw_item.get("source_zip_path"),
                raw_item.get("source_path"),
                raw_item.get("file_name"),
            )
            if key not in buckets:
                buckets[key] = deque()
                bucket_order.append(key)
            buckets[key].append(raw_item)
        return cls._round_robin_bucket_values(buckets=buckets, bucket_order=bucket_order)

    @classmethod
    def _interleave_pdf_tasks_by_archive(
        cls,
        *,
        pdf_tasks: list[tuple[int, object]],
        forced_archive_slug: str | None,
    ) -> list[tuple[int, object]]:
        buckets: dict[str, deque[tuple[int, object]]] = {}
        bucket_order: list[str] = []
        for indexed_task in pdf_tasks:
            _, pdf_source = indexed_task
            key = cls._normalize_parallel_bucket_key(
                forced_archive_slug,
                getattr(pdf_source, "archive_slug", None),
                getattr(pdf_source, "source_zip_path", None),
                getattr(pdf_source, "pdf_path", None),
            )
            if key not in buckets:
                buckets[key] = deque()
                bucket_order.append(key)
            buckets[key].append(indexed_task)
        return cls._round_robin_bucket_values(buckets=buckets, bucket_order=bucket_order)

    def _resolve_max_parallel_documents(self) -> int:
        try:
            from apps.backend.app.services.runtime_config_service import ConfigService

            config_service = ConfigService(get_db_manager())
            raw_value = config_service.get_value("rag.ingest.max_parallel_documents", "3").strip()
            parsed = int(raw_value)
            return max(1, parsed)
        except Exception:
            return 1

    def _resolve_boolean_runtime_config(self, key: str, *, default: bool = False) -> bool:
        try:
            from apps.backend.app.services.runtime_config_service import ConfigService

            config_service = ConfigService(get_db_manager())
            raw_value = config_service.get_value(
                key,
                "true" if default else "false",
            ).strip().lower()
        except Exception:
            return bool(default)
        return raw_value in {"1", "true", "yes", "on"}

    def _visual_enrichment_enabled(self) -> bool:
        return self._resolve_boolean_runtime_config(
            "rag.ingest.visual_enrichment_enabled",
            default=False,
        )

    def _page_image_embeddings_enabled(self) -> bool:
        return self._resolve_boolean_runtime_config(
            "rag.ingest.page_image_embeddings_enabled",
            default=True,
        )

    def _structured_facts_enabled(self) -> bool:
        return self._resolve_boolean_runtime_config(
            "rag.ingest.structured_facts_enabled",
            default=False,
        )

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @staticmethod
    def _resolve_page_analysis(
        *,
        page_number: int,
        page_analysis_by_number: dict[int, DoclingPageResult],
    ) -> DoclingPageResult:
        page_analysis = page_analysis_by_number.get(int(page_number))
        if page_analysis is None:
            raise RuntimeError(f"Docling did not return page {page_number}.")
        return page_analysis

    @staticmethod
    def _decode_json_payload(value: object | None, *, default_value: dict[str, object] | None = None) -> dict[str, object]:
        if isinstance(value, dict):
            return dict(value)
        if value is None:
            return dict(default_value or {})
        raw_value = value.read() if hasattr(value, "read") else value
        try:
            parsed = json.loads(str(raw_value or "{}"))
        except Exception:
            return dict(default_value or {})
        if isinstance(parsed, dict):
            return dict(parsed)
        return dict(default_value or {})

    @staticmethod
    def _parse_json_value(value: object | None, *, default_value: object) -> object:
        if value is None:
            return default_value
        if isinstance(value, (dict, list)):
            return value
        raw_value = value.read() if hasattr(value, "read") else value
        try:
            return json.loads(str(raw_value))
        except Exception:
            return default_value

    @staticmethod
    def _normalize_archive_metadata_fields(
        fields: dict[str, object] | None,
    ) -> dict[str, str | int | float | bool | None]:
        normalized_fields: dict[str, str | int | float | bool | None] = {}
        for raw_key, raw_value in dict(fields or {}).items():
            key = str(raw_key or "").strip()
            if not key or key.lower() == "file":
                continue
            if raw_value is None or isinstance(raw_value, (str, int, float, bool)):
                normalized_fields[key] = raw_value
                continue
            normalized_fields[key] = compact_whitespace(str(raw_value))
        return normalized_fields

    def _load_archive_metadata_context(
        self,
        *,
        metadata_upload_id: str | None,
        user_id: int,
        archive_slug: str,
    ) -> dict[str, object] | None:
        if not metadata_upload_id:
            return None
        metadata_row = self.repository.archive_metadata.get_upload_row(
            metadata_upload_id=metadata_upload_id,
            user_id=user_id,
            file_key=archive_slug,
        )
        if metadata_row is None:
            return None
        payload = self._decode_json_payload(metadata_row.get("row_json"))
        file_key = canonicalize_file_key(str(payload.get("file") or archive_slug))
        fields = self._normalize_archive_metadata_fields(
            dict(payload.get("fields") or {}) if isinstance(payload.get("fields"), dict) else {}
        )
        return {
            "file": file_key or canonicalize_file_key(archive_slug),
            "fields": fields,
            "metadata_upload_id": str(metadata_upload_id).strip(),
            "search_text": build_metadata_search_text(
                file_key=file_key or canonicalize_file_key(archive_slug),
                fields=fields,
            ),
        }

    @staticmethod
    def _build_metadata_attribute_rows(
        *,
        metadata_context: dict[str, object] | None,
    ) -> list[dict[str, object]]:
        if not metadata_context:
            return []
        metadata_upload_id = str(metadata_context.get("metadata_upload_id") or "").strip()
        fields = dict(metadata_context.get("fields") or {})
        attribute_rows: list[dict[str, object]] = []
        for header, raw_value in fields.items():
            if raw_value is None:
                continue
            attribute_key = normalize_metadata_attribute_key(header)
            value_text = compact_whitespace(str(raw_value))
            attribute_rows.append(
                {
                    "page_id": None,
                    "attribute_key": attribute_key,
                    "attribute_value_text": value_text[:4000],
                    "attribute_value_number": (
                        float(raw_value)
                        if isinstance(raw_value, (int, float)) and not isinstance(raw_value, bool)
                        else None
                    ),
                    "attribute_value_date": None,
                    "attribute_value_bool": (
                        1
                        if raw_value is True
                        else (0 if raw_value is False else None)
                    ),
                    "source_type": "metadata_csv",
                    "metadata_json": json.dumps(
                        {
                            "source": "metadata_csv",
                            "column_name": str(header),
                            "metadata_upload_id": metadata_upload_id,
                        },
                        ensure_ascii=False,
                    ),
                    "confidence": 1.0,
                }
            )
        return attribute_rows

    @staticmethod
    def _should_index_page_image_embedding(
        *,
        visual_flags: list[str],
        visual_summary: str,
    ) -> bool:
        interesting_flags = {
            "low_ocr_confidence",
            "contains_picture",
            "possible_table",
            "possible_signature",
            "possible_stamp",
            "contains_signature",
            "contains_table",
            "contains_stamp",
            "contains_handwriting",
        }
        return bool(
            compact_whitespace(visual_summary)
            or any(flag in interesting_flags for flag in list(visual_flags or []))
        )

    def process_documents(
        self,
        *,
        source_path: Path | None = None,
        include_archives: bool = True,
        limit: int | None = None,
        user_id: int | None = None,
        document_language: str | None = None,
        access_scope: str | None = None,
        forced_archive_slug: str | None = None,
        forced_object_name: str | None = None,
        source_zip_path: Path | None = None,
        metadata_override: dict[str, object] | None = None,
        metadata_upload_id: str | None = None,
    ) -> list[FileProcessItem]:
        effective_user_id = int(user_id) if user_id is not None else 0
        sources = self.archive_service.discover_sources(
            source_path=source_path,
            include_archives=include_archives,
        )
        if limit:
            sources = sources[:limit]

        pdf_contexts = self.archive_service.resolve_pdf_contexts(sources)
        self._pre_register_pdf_contexts(
            pdf_contexts=pdf_contexts,
            user_id=effective_user_id,
            access_scope=access_scope,
            forced_archive_slug=forced_archive_slug,
            forced_object_name=forced_object_name,
        )

        max_parallel_documents = self._resolve_max_parallel_documents()
        if len(pdf_contexts) <= 1 or max_parallel_documents <= 1:
            processed: list[FileProcessItem] = []
            for pdf_source in pdf_contexts:
                effective_archive_slug = str(forced_archive_slug or pdf_source.archive_slug)
                processed.append(
                    self._process_pdf_with_archive_slot(
                        pdf_path=pdf_source.pdf_path,
                        user_id=effective_user_id,
                        archive_slug=effective_archive_slug,
                        archive_id=pdf_source.archive_id,
                        source_zip_path=source_zip_path or pdf_source.source_zip_path,
                        document_language=document_language,
                        access_scope=access_scope,
                        forced_object_name=forced_object_name,
                        metadata_override=metadata_override,
                        metadata_upload_id=metadata_upload_id,
                    )
                )
            return processed

        ordered_results: list[FileProcessItem | None] = [None] * len(pdf_contexts)
        first_error: Exception | None = None
        max_workers = min(max_parallel_documents, len(pdf_contexts))
        scheduled_pdf_tasks = self._interleave_pdf_tasks_by_archive(
            pdf_tasks=list(enumerate(pdf_contexts)),
            forced_archive_slug=forced_archive_slug,
        )
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="ingest-pdf") as executor:
            futures: list[tuple[int, object]] = []
            for idx, pdf_source in scheduled_pdf_tasks:
                effective_archive_slug = str(forced_archive_slug or pdf_source.archive_slug)
                future = executor.submit(
                    self._process_pdf_with_archive_slot,
                    pdf_path=pdf_source.pdf_path,
                    user_id=effective_user_id,
                    archive_slug=effective_archive_slug,
                    archive_id=pdf_source.archive_id,
                    source_zip_path=source_zip_path or pdf_source.source_zip_path,
                    document_language=document_language,
                    access_scope=access_scope,
                    forced_object_name=forced_object_name,
                    metadata_override=metadata_override,
                    metadata_upload_id=metadata_upload_id,
                )
                futures.append((idx, future))

            for idx, future in futures:
                try:
                    ordered_results[idx] = future.result()
                except Exception as exc:
                    if first_error is None:
                        first_error = exc

        if first_error is not None:
            raise first_error
        return [item for item in ordered_results if item is not None]

    @staticmethod
    def _normalize_archive_execution_key(*, user_id: int, archive_slug: str | None, pdf_path: Path) -> tuple[int, str]:
        normalized_archive_slug = compact_whitespace(str(archive_slug or "")).lower()
        normalized_pdf_path = compact_whitespace(str(pdf_path)).lower()
        if normalized_archive_slug:
            return int(user_id), f"{normalized_archive_slug}::{normalized_pdf_path}"
        return int(user_id), normalized_pdf_path

    def _get_archive_execution_lock(self, *, user_id: int, archive_slug: str | None, pdf_path: Path) -> Lock:
        guard = getattr(self, "_archive_execution_slots_guard", None)
        if guard is None:
            guard = Lock()
            self._archive_execution_slots_guard = guard
        slots = getattr(self, "_archive_execution_slots", None)
        if slots is None:
            slots = {}
            self._archive_execution_slots = slots
        key = self._normalize_archive_execution_key(
            user_id=user_id,
            archive_slug=archive_slug,
            pdf_path=pdf_path,
        )
        with guard:
            archive_lock = slots.get(key)
            if archive_lock is None:
                archive_lock = Lock()
                slots[key] = archive_lock
            return archive_lock

    @contextmanager
    def _archive_execution_slot(self, *, user_id: int, archive_slug: str | None, pdf_path: Path) -> Iterator[None]:
        archive_lock = self._get_archive_execution_lock(
            user_id=user_id,
            archive_slug=archive_slug,
            pdf_path=pdf_path,
        )
        archive_lock.acquire()
        try:
            yield
        finally:
            archive_lock.release()

    def _process_pdf_with_archive_slot(
        self,
        *,
        pdf_path: Path,
        user_id: int,
        archive_slug: str,
        archive_id: str,
        source_zip_path: Path | None,
        document_language: str | None,
        access_scope: str | None,
        forced_object_name: str | None = None,
        metadata_override: dict[str, object] | None = None,
        metadata_upload_id: str | None = None,
    ) -> FileProcessItem:
        with self._archive_execution_slot(
            user_id=user_id,
            archive_slug=archive_slug,
            pdf_path=pdf_path,
        ):
            process_kwargs = {
                "user_id": user_id,
                "archive_slug": archive_slug,
                "archive_id": archive_id,
                "source_zip_path": source_zip_path,
                "document_language": document_language,
                "forced_object_name": forced_object_name,
                "metadata_override": metadata_override,
                "metadata_upload_id": metadata_upload_id,
            }
            if access_scope is not None:
                process_kwargs["access_scope"] = access_scope
            return self._process_pdf(
                pdf_path,
                **process_kwargs,
            )

    def _pre_register_pdf_contexts(
        self,
        *,
        pdf_contexts: list,
        user_id: int,
        access_scope: str | None,
        forced_archive_slug: str | None,
        forced_object_name: str | None,
    ) -> None:
        """Create `files` rows up front so the ingestion queue is visible immediately."""
        user_storage_name = self.repository.get_user_storage_name(user_id=user_id)
        use_forced_object_name = bool(forced_object_name) and len(pdf_contexts) == 1
        for pdf_source in pdf_contexts:
            effective_archive_slug = str(forced_archive_slug or pdf_source.archive_slug)
            archive_prefix = build_archive_prefix(
                username=user_storage_name,
                archive_slug=effective_archive_slug,
                archive_id=pdf_source.archive_id,
            )
            object_name = (
                str(forced_object_name).strip()
                if use_forced_object_name
                else build_pdf_source_key(archive_prefix=archive_prefix, doc_name=pdf_source.pdf_path.name)
            )
            self.repository.get_or_create_file(
                user_id=user_id,
                file_name=pdf_source.pdf_path.name,
                original_local_path=str(pdf_source.pdf_path),
                bucket_object_name=object_name,
                file_input_size=pdf_source.pdf_path.stat().st_size,
                archive_slug=effective_archive_slug,
                access_scope=access_scope,
            )

    def _pre_register_process_plan_items(
        self,
        *,
        process_items: list[dict[str, object]],
        user_id: int,
    ) -> None:
        if self.repository is None:
            return
        user_storage_name = self.repository.get_user_storage_name(user_id=user_id)
        archive_id_cache: dict[str, str] = {}
        for raw_item in process_items:
            if not bool(raw_item.get("enabled", True)):
                continue
            source_path_raw = str(raw_item.get("source_path") or "").strip()
            if not source_path_raw:
                continue
            try:
                source_path = Path(source_path_raw)
                if not source_path.exists() or not source_path.is_file() or source_path.suffix.lower() != ".pdf":
                    continue
                archive_slug = str(raw_item.get("archive_slug") or source_path.stem).strip()
                if not archive_slug:
                    continue
                source_zip_raw = str(raw_item.get("source_zip_path") or "").strip()
                archive_id_source = source_zip_raw or str(source_path)
                archive_id = archive_id_cache.get(archive_id_source)
                if archive_id is None:
                    archive_id = sha256_file(Path(archive_id_source))
                    archive_id_cache[archive_id_source] = archive_id
                archive_prefix = build_archive_prefix(
                    username=user_storage_name,
                    archive_slug=archive_slug,
                    archive_id=archive_id,
                )
                object_name = build_pdf_source_key(
                    archive_prefix=archive_prefix,
                    doc_name=source_path.name,
                )
                self.repository.get_or_create_file(
                    user_id=user_id,
                    file_name=source_path.name,
                    original_local_path=str(source_path),
                    bucket_object_name=object_name,
                    file_input_size=source_path.stat().st_size,
                    archive_slug=archive_slug,
                    access_scope=str(raw_item.get("access") or "").strip() or None,
                )
            except Exception:
                # Visibility in the queue should not block the real ingestion path.
                continue

    def _process_pdf(
        self,
        pdf_path: Path,
        *,
        user_id: int,
        archive_slug: str,
        archive_id: str,
        source_zip_path: Path | None,
        document_language: str | None,
        access_scope: str | None = None,
        forced_object_name: str | None = None,
        metadata_override: dict[str, object] | None = None,
        metadata_upload_id: str | None = None,
    ) -> FileProcessItem:
        total_started_at = time.perf_counter()
        visual_enrichment_enabled = self._visual_enrichment_enabled()
        page_image_embeddings_enabled = self._page_image_embeddings_enabled()
        structured_facts_enabled = self._structured_facts_enabled()
        telemetry: dict[str, object] = {
            "archive_slug": archive_slug,
            "metadata_upload_id": str(metadata_upload_id or "").strip() or None,
            "metadata_attached": False,
            "metadata_missing_for_archive": False,
            "metadata_field_count": 0,
            "visual_enrichment_enabled": visual_enrichment_enabled,
            "page_image_embeddings_enabled": page_image_embeddings_enabled,
            "structured_facts_enabled": structured_facts_enabled,
        }
        self._ensure_valid_pdf(pdf_path)
        file_hash = sha256_file(pdf_path)
        user_storage_name = self.repository.get_user_storage_name(user_id=user_id)
        user_scope = user_storage_name or f"user-{user_id}"
        archive_prefix = build_archive_prefix(
            username=user_storage_name,
            archive_slug=archive_slug,
            archive_id=archive_id,
        )
        object_name = (
            str(forced_object_name).strip()
            if forced_object_name
            else build_pdf_source_key(archive_prefix=archive_prefix, doc_name=pdf_path.name)
        )
        with self._file_registration_guard:
            record = self.repository.get_or_create_file(
                user_id=user_id,
                file_name=pdf_path.name,
                original_local_path=str(pdf_path),
                bucket_object_name=object_name,
                file_input_size=pdf_path.stat().st_size,
                archive_slug=archive_slug,
                access_scope=access_scope,
            )
            file_id = int(record["file_id"])
            self.repository.reset_file_derivatives(file_id=file_id)
            self.repository.update_file_status(file_id, status="processing", page_count=0)
        metadata_context: dict[str, object] | None = None
        rendered_pages: list[dict] = []
        upload_result = {"object_name": object_name}

        try:
            metadata_lookup_started = time.perf_counter()
            metadata_context = self._load_archive_metadata_context(
                metadata_upload_id=metadata_upload_id,
                user_id=user_id,
                archive_slug=archive_slug,
            )
            telemetry["metadata_lookup_ms"] = self._elapsed_ms(metadata_lookup_started)
            if metadata_context is not None:
                metadata_persist_started = time.perf_counter()
                persisted_metadata = {
                    "file": str(metadata_context.get("file") or archive_slug),
                    "fields": dict(metadata_context.get("fields") or {}),
                }
                self.repository.archive_metadata.upsert_archive_metadata(
                    user_id=user_id,
                    archive_slug=archive_slug,
                    metadata_upload_id=str(metadata_context.get("metadata_upload_id") or "").strip() or None,
                    metadata_json=json.dumps(persisted_metadata, ensure_ascii=False),
                    metadata_search_text=str(metadata_context.get("search_text") or ""),
                )
                telemetry["metadata_persist_ms"] = self._elapsed_ms(metadata_persist_started)
                telemetry["metadata_attached"] = True
                telemetry["metadata_field_count"] = len(
                    dict(metadata_context.get("fields") or {})
                )
            elif metadata_upload_id:
                telemetry["metadata_missing_for_archive"] = True

            upload_started = time.perf_counter()
            upload_result = self._upload_source_pdf_and_zip(
                pdf_path,
                object_name=object_name,
                file_id=file_id,
                archive_prefix=archive_prefix,
                source_zip_path=source_zip_path,
            )
            telemetry["source_upload_ms"] = self._elapsed_ms(upload_started)

            render_started = time.perf_counter()
            rendered_pages = self.pdf_service.render_pages(pdf_path)
            telemetry["render_pages_ms"] = self._elapsed_ms(render_started)

            docling_started = time.perf_counter()
            docling_result = self.docling_document_service.analyze_document(
                pdf_path=pdf_path,
                document_language=document_language,
            )
            telemetry["docling_ms"] = self._elapsed_ms(docling_started)
            telemetry.update(dict(docling_result.telemetry))
            if len(docling_result.pages) != len(rendered_pages):
                raise RuntimeError(
                    f"Docling/page render mismatch for '{pdf_path.name}': "
                    f"{len(docling_result.pages)} parsed vs {len(rendered_pages)} rendered pages."
                )

            self.repository.update_file_status(file_id, status="processing", page_count=len(rendered_pages))
            leading_page_texts, page_telemetry = self._process_rendered_pages(
                rendered_pages=rendered_pages,
                page_analysis_by_number=docling_result.pages,
                pdf_path=pdf_path,
                file_id=file_id,
                user_id=user_id,
                file_hash=file_hash,
                user_scope=user_scope,
                archive_prefix=archive_prefix,
                archive_slug=archive_slug,
                metadata_override=metadata_override,
                enable_page_image_embeddings=page_image_embeddings_enabled,
            )
            telemetry.update(page_telemetry)

            classifier_started = time.perf_counter()
            detected_metadata = self.file_metadata_classifier.classify(
                file_name=pdf_path.name,
                file_path=pdf_path,
                text_samples=leading_page_texts,
                document_language=document_language,
            )
            telemetry["document_classification_ms"] = self._elapsed_ms(classifier_started)

            resolved_metadata_started = time.perf_counter()
            document_metadata = self._resolve_document_metadata_with_override(
                detected_metadata=detected_metadata,
                metadata_override=metadata_override,
            )
            telemetry["document_metadata_resolution_ms"] = self._elapsed_ms(resolved_metadata_started)

            file_metadata_write_started = time.perf_counter()
            self.repository.update_file_document_metadata(
                file_id=file_id,
                document_code=document_metadata.document_code,
                document_code_source=document_metadata.document_code_source,
                archive_slug=archive_slug,
            )
            telemetry["file_metadata_write_ms"] = self._elapsed_ms(file_metadata_write_started)

            rag_finalize_started = time.perf_counter()
            self._finalize_document_rag(
                file_id=file_id,
                user_id=user_id,
                file_name=pdf_path.name,
                archive_slug=archive_slug,
                document_metadata=document_metadata,
                metadata_context=metadata_context,
                structured_facts_enabled=structured_facts_enabled,
            )
            telemetry["rag_finalize_ms"] = self._elapsed_ms(rag_finalize_started)

            status_update_started = time.perf_counter()
            self.repository.update_file_status(
                file_id,
                status="completed",
                page_count=len(rendered_pages),
                processing_notes="Processed successfully.",
            )
            telemetry["final_status_write_ms"] = self._elapsed_ms(status_update_started)
        except Exception as exc:
            self.repository.update_file_status(
                file_id,
                status="failed",
                processing_notes=str(exc),
            )
            telemetry["error"] = str(exc)
            telemetry["total_ms"] = self._elapsed_ms(total_started_at)
            raise

        telemetry["page_count"] = len(rendered_pages)
        telemetry["total_ms"] = self._elapsed_ms(total_started_at)
        return FileProcessItem(
            file_id=file_id,
            file_name=str(record["file_input_file_name"]),
            status="completed",
            page_count=len(rendered_pages),
            object_name=str(upload_result["object_name"]),
            telemetry=telemetry,
        )

    def _upload_source_pdf_and_zip(
        self,
        pdf_path: Path,
        *,
        object_name: str,
        file_id: int,
        archive_prefix: str,
        source_zip_path: Path | None,
    ) -> dict[str, str]:
        upload_result = self.object_storage.upload_file(
            pdf_path,
            object_name=object_name,
            content_type="application/pdf",
        )
        self.repository.update_file_storage(file_id, bucket_object_name=upload_result["object_name"])
        if source_zip_path is not None:
            self._upload_zip_once(source_zip_path=source_zip_path, archive_prefix=archive_prefix)
        return upload_result

    def _upload_zip_once(self, *, source_zip_path: Path, archive_prefix: str) -> None:
        zip_object_name = build_zip_source_key(archive_prefix=archive_prefix, zip_name=source_zip_path.name)
        with self._uploaded_zip_keys_lock:
            if zip_object_name in self._uploaded_zip_keys:
                return
            self._uploaded_zip_keys.add(zip_object_name)
        try:
            self.object_storage.upload_file(
                source_zip_path,
                object_name=zip_object_name,
                content_type="application/zip",
            )
        except Exception:
            with self._uploaded_zip_keys_lock:
                self._uploaded_zip_keys.discard(zip_object_name)
            raise

    def _process_rendered_pages(
        self,
        *,
        rendered_pages: list[dict],
        page_analysis_by_number: dict[int, DoclingPageResult],
        pdf_path: Path,
        file_id: int,
        user_id: int,
        file_hash: str,
        user_scope: str,
        archive_prefix: str,
        archive_slug: str,
        metadata_override: dict[str, object] | None,
        enable_page_image_embeddings: bool,
    ) -> tuple[list[str], dict[str, object]]:
        leading_page_texts: list[str] = []
        telemetry: dict[str, object] = {
            "ocr_pages_count": len(rendered_pages),
            "page_db_write_ms": 0,
            "page_storage_ms": 0,
            "ocr_ms": 0,
            "native_text_pages_count": 0,
            "ocr_provider_pages_count": 0,
            "blank_ocr_pages_count": 0,
            "page_enrichment_ms": 0,
            "embedding_ms": 0,
            "page_text_embeddings_written": 0,
            "page_image_embeddings_written": 0,
        }
        preliminary_document_code, _ = extract_document_code_from_filename(pdf_path.name)
        resolved_document_code, resolved_document_type = self._resolve_preliminary_metadata(
            preliminary_document_code=preliminary_document_code,
            metadata_override=metadata_override,
        )
        total_pages = max(1, len(rendered_pages))
        for page_info in rendered_pages:
            page_number = int(page_info["page_number"])
            page_object_name = build_page_png_key(
                archive_prefix=archive_prefix,
                doc_name=pdf_path.name,
                page_number=page_number,
            )
            page_ocr_object_name = build_page_ocr_json_key(
                archive_prefix=archive_prefix,
                doc_name=pdf_path.name,
                page_number=page_number,
            )
            storage_started = time.perf_counter()
            page_upload = self.object_storage.upload_file(
                page_info["image_path"],
                object_name=page_object_name,
                content_type="image/png",
            )
            telemetry["page_storage_ms"] = int(telemetry["page_storage_ms"]) + self._elapsed_ms(storage_started)

            ocr_started = time.perf_counter()
            page_analysis = self._resolve_page_analysis(
                page_number=page_number,
                page_analysis_by_number=page_analysis_by_number,
            )
            ocr_artifact = page_analysis.ocr_result
            telemetry["ocr_provider_pages_count"] = int(telemetry["ocr_provider_pages_count"]) + 1
            telemetry["ocr_ms"] = int(telemetry["ocr_ms"]) + self._elapsed_ms(ocr_started)
            embedding_text = (ocr_artifact.normalized_text or "").strip()
            markdown_text = str(ocr_artifact.markdown_text).strip()
            if embedding_text and len(leading_page_texts) < 2:
                leading_page_texts.append(embedding_text)
            if not embedding_text:
                telemetry["blank_ocr_pages_count"] = int(telemetry["blank_ocr_pages_count"]) + 1
            enrichment_started = time.perf_counter()
            page_enrichment = self.page_visual_enricher.enrich_page(
                image_path=page_info["image_path"],
                file_name=pdf_path.name,
                document_code=resolved_document_code,
                document_type=resolved_document_type,
                page_number=page_number,
                total_pages=total_pages,
                ocr_text=embedding_text,
                ocr_confidence=float(ocr_artifact.ocr_confidence),
                base_visual_summary=page_analysis.visual_summary,
                base_layout_payload=self._decode_json_payload(
                    page_analysis.layout_json,
                    default_value={"labels": list(page_analysis.visual_flags)},
                ),
                base_visual_flags=list(page_analysis.visual_flags),
            )
            telemetry["page_enrichment_ms"] = int(telemetry["page_enrichment_ms"]) + self._elapsed_ms(enrichment_started)

            ocr_payload = {
                "file_name": pdf_path.name,
                "page_number": page_number,
                "normalized_text": embedding_text,
                "raw_text": ocr_artifact.raw_ocr_text,
                "markdown_text": markdown_text,
                "ocr_confidence": float(ocr_artifact.ocr_confidence),
                "extraction_method": ocr_artifact.extraction_method,
                "detected_blocks": self._parse_json_value(
                    ocr_artifact.detected_blocks_json,
                    default_value=[],
                ),
                "table_extraction": self._parse_json_value(
                    ocr_artifact.table_extraction_json,
                    default_value=[],
                ),
                "layout": self._parse_json_value(
                    page_enrichment.layout_json,
                    default_value={},
                ),
            }
            ocr_json_local_path = (
                self.settings.data_dir / "users" / user_scope / "ocr_json" / f"{file_hash}-{page_number:03d}.json"
            )
            ocr_json_local_path.parent.mkdir(parents=True, exist_ok=True)
            ocr_json_local_path.write_text(json.dumps(ocr_payload, ensure_ascii=False), encoding="utf-8")
            storage_started = time.perf_counter()
            ocr_upload = self.object_storage.upload_file(
                ocr_json_local_path,
                object_name=page_ocr_object_name,
                content_type="application/json",
            )
            telemetry["page_storage_ms"] = int(telemetry["page_storage_ms"]) + self._elapsed_ms(storage_started)

            db_write_started = time.perf_counter()
            page_record = self.repository.add_page(
                user_id=user_id,
                file_id=file_id,
                page_number=page_number,
                image_path_local=str(page_info["image_path"]),
                width=page_info["width"],
                height=page_info["height"],
                ocr_text=embedding_text,
                markdown_text=markdown_text,
                file_pages_output_obj_name=page_upload["object_name"],
                file_pages_ocr_obj_name=ocr_upload["object_name"],
                file_pages_ocr_confidence=float(ocr_artifact.ocr_confidence),
                file_pages_ocr_method=ocr_artifact.extraction_method,
                file_pages_visual_summary=page_enrichment.visual_summary,
                file_pages_layout_json=page_enrichment.layout_json,
                file_pages_search_text=page_enrichment.search_text,
                file_pages_visual_flags=" ".join(page_enrichment.visual_flags),
                file_pages_text_quality=float(page_enrichment.text_quality),
            )
            telemetry["page_db_write_ms"] = int(telemetry["page_db_write_ms"]) + self._elapsed_ms(db_write_started)

            embedding_started_at: float | None = None
            if embedding_text:
                embedding_started_at = time.perf_counter()
                text_embedding = self.embedding_service.embed_document_text(text=embedding_text)
                self.repository.add_embedding(
                    user_id=user_id,
                    file_id=file_id,
                    page_id=int(page_record["file_pages_id"]),
                    archive_slug=archive_slug,
                    embedding_model=self.settings.embedding_model_name,
                    embedding_dimension=len(text_embedding),
                    embedding_vector=text_embedding,
                    modality="ocr_text",
                    summary_text=embedding_text[:4000],
                )
                telemetry["page_text_embeddings_written"] = int(telemetry["page_text_embeddings_written"]) + 1
            if enable_page_image_embeddings and self._should_index_page_image_embedding(
                visual_flags=list(page_enrichment.visual_flags),
                visual_summary=page_enrichment.visual_summary,
            ):
                if embedding_started_at is None:
                    embedding_started_at = time.perf_counter()
                image_embedding, visual_summary = self.embedding_service.embed_image(
                    image_path=page_info["image_path"],
                    context_text=page_enrichment.visual_summary or embedding_text[:1200] or f"{pdf_path.name} page {page_number}",
                )
                self.repository.add_embedding(
                    user_id=user_id,
                    file_id=file_id,
                    page_id=int(page_record["file_pages_id"]),
                    archive_slug=archive_slug,
                    embedding_model=self.settings.embedding_model_name,
                    embedding_dimension=len(image_embedding),
                    embedding_vector=image_embedding,
                    modality="page_image",
                    summary_text=compact_whitespace(
                        page_enrichment.visual_summary or visual_summary or embedding_text
                    )[:4000],
                )
                telemetry["page_image_embeddings_written"] = int(
                    telemetry["page_image_embeddings_written"]
                ) + 1
            if embedding_started_at is not None:
                telemetry["embedding_ms"] = int(telemetry["embedding_ms"]) + self._elapsed_ms(embedding_started_at)
        return leading_page_texts, telemetry

    @staticmethod
    def _resolve_preliminary_metadata(
        *,
        preliminary_document_code: str | None,
        metadata_override: dict[str, object] | None,
    ) -> tuple[str | None, str | None]:
        override = dict(metadata_override or {})
        resolved_code = preliminary_document_code
        if "document_code" in override:
            resolved_code = normalize_document_code_value(str(override.get("document_code") or ""))
        return resolved_code, None

    def _resolve_document_metadata_with_override(
        self,
        *,
        detected_metadata: FileMetadata,
        metadata_override: dict[str, object] | None,
    ) -> FileMetadata:
        override = dict(metadata_override or {})
        resolved_document_code = detected_metadata.document_code
        resolved_document_code_source = detected_metadata.document_code_source

        if "document_code" in override:
            resolved_document_code = normalize_document_code_value(str(override.get("document_code") or ""))
            resolved_document_code_source = (
                str(override.get("document_code_source") or "").strip().lower() or "manual"
            )

        return FileMetadata(
            document_code=resolved_document_code,
            document_code_source=resolved_document_code_source,
        )

    def process_document_plan(
        self,
        *,
        process_items: list[dict[str, object]],
        user_id: int,
        metadata_upload_id: str | None = None,
        progress_callback: Callable[[FileProcessItem], None] | None = None,
    ) -> IngestionPlanResult:
        result = IngestionPlanResult()
        self._pre_register_process_plan_items(process_items=process_items, user_id=user_id)
        valid_items: list[dict[str, object]] = []
        for raw_item in process_items:
            if not bool(raw_item.get("enabled", True)):
                continue
            source_path_raw = str(raw_item.get("source_path") or "").strip()
            file_name = str(raw_item.get("file_name") or Path(source_path_raw).name or "document.pdf").strip()
            if not source_path_raw:
                result.errors.append(f"{file_name}: source_path is required.")
                result.processed.append(
                    FileProcessItem(
                        file_id=0,
                        file_name=file_name,
                        status="failed",
                        page_count=0,
                        object_name="",
                        error="source_path is required.",
                    )
                )
                continue
            valid_items.append(dict(raw_item))

        scheduled_items = self._interleave_plan_items_by_archive(process_items=valid_items)
        max_parallel_documents = min(self._resolve_max_parallel_documents(), len(valid_items))
        if max_parallel_documents <= 1:
            for raw_item in valid_items:
                try:
                    processed_items = self._process_plan_item(
                        raw_item=raw_item,
                        user_id=user_id,
                        metadata_upload_id=metadata_upload_id,
                    )
                    result.processed.extend(processed_items)
                    if progress_callback is not None:
                        for processed_item in processed_items:
                            progress_callback(processed_item)
                except Exception as exc:
                    file_name = str(
                        raw_item.get("file_name") or Path(str(raw_item.get("source_path") or "")).name or "document.pdf"
                    ).strip()
                    result.errors.append(f"{file_name}: {exc}")
                    failed_item = FileProcessItem(
                        file_id=0,
                        file_name=file_name,
                        status="failed",
                        page_count=0,
                        object_name="",
                        error=str(exc),
                    )
                    result.processed.append(failed_item)
                    if progress_callback is not None:
                        progress_callback(failed_item)
            return result

        with ThreadPoolExecutor(
            max_workers=max_parallel_documents,
            thread_name_prefix="ingest-plan",
        ) as executor:
            futures = {
                executor.submit(
                    self._process_plan_item,
                    raw_item=dict(raw_item),
                    user_id=user_id,
                    metadata_upload_id=metadata_upload_id,
                ): dict(raw_item)
                for raw_item in scheduled_items
            }
            for future in as_completed(futures):
                raw_item = futures[future]
                try:
                    processed_items = future.result()
                    result.processed.extend(processed_items)
                    if progress_callback is not None:
                        for processed_item in processed_items:
                            progress_callback(processed_item)
                except Exception as exc:
                    file_name = str(
                        raw_item.get("file_name") or Path(str(raw_item.get("source_path") or "")).name or "document.pdf"
                    ).strip()
                    result.errors.append(f"{file_name}: {exc}")
                    failed_item = FileProcessItem(
                        file_id=0,
                        file_name=file_name,
                        status="failed",
                        page_count=0,
                        object_name="",
                        error=str(exc),
                    )
                    result.processed.append(failed_item)
                    if progress_callback is not None:
                        progress_callback(failed_item)
        return result

    def _process_plan_item(
        self,
        *,
        raw_item: dict[str, object],
        user_id: int,
        metadata_upload_id: str | None,
    ) -> list[FileProcessItem]:
        source_path_raw = str(raw_item.get("source_path") or "").strip()
        file_name = str(raw_item.get("file_name") or Path(source_path_raw).name or "document.pdf").strip()
        if not source_path_raw:
            raise RuntimeError(f"{file_name}: source_path is required.")

        metadata_override: dict[str, object] = {}
        if "document_code" in raw_item:
            metadata_override["document_code"] = raw_item.get("document_code")
        if "document_code_source" in raw_item:
            metadata_override["document_code_source"] = raw_item.get("document_code_source")

        process_kwargs = {
            "source_path": Path(source_path_raw),
            "include_archives": False,
            "limit": 1,
            "user_id": user_id,
            "document_language": str(raw_item.get("document_language") or "").strip() or None,
            "forced_archive_slug": str(raw_item.get("archive_slug") or "").strip() or None,
            "source_zip_path": (
                Path(str(raw_item.get("source_zip_path") or "").strip())
                if str(raw_item.get("source_zip_path") or "").strip()
                else None
            ),
            "metadata_override": metadata_override,
            "metadata_upload_id": metadata_upload_id,
        }
        access_scope = str(raw_item.get("access") or "").strip() or None
        if access_scope is not None:
            process_kwargs["access_scope"] = access_scope
        return self.process_documents(**process_kwargs)

    def _finalize_document_rag(
        self,
        *,
        file_id: int,
        user_id: int,
        file_name: str,
        archive_slug: str,
        document_metadata: FileMetadata,
        metadata_context: dict[str, object] | None = None,
        structured_facts_enabled: bool = False,
    ) -> None:
        page_rows = self.repository.get_pages_by_file(file_id)
        if not page_rows:
            raise RuntimeError(f"No persisted pages were found for file_id={file_id}.")

        metadata_search_text = compact_whitespace(str(metadata_context.get("search_text") or "")) if metadata_context else ""
        refreshed_page_rows: list[dict] = []
        for row in page_rows:
            visual_flags = [
                token.strip()
                for token in str(row.get("file_pages_visual_flags") or "").split()
                if token.strip()
            ]
            search_text = build_page_search_text(
                file_name=file_name,
                document_code=document_metadata.document_code,
                document_type=None,
                page_number=int(row.get("file_pages_number") or 0),
                ocr_text=str(row.get("file_pages_ocr_text") or ""),
                visual_summary=str(row.get("file_pages_visual_summary") or ""),
                visual_flags=visual_flags,
            )
            if metadata_search_text:
                search_text = compact_whitespace(f"{search_text} | {metadata_search_text}")
            self.repository.file_pages.update_page_rag_enrichment(
                page_id=int(row.get("file_pages_id") or 0),
                visual_summary=str(row.get("file_pages_visual_summary") or ""),
                layout_json=str(row.get("file_pages_layout_json") or "{}"),
                search_text=search_text,
                visual_flags=str(row.get("file_pages_visual_flags") or ""),
                text_quality=float(row.get("file_pages_text_quality") or 0.0),
            )
            refreshed_row = dict(row)
            refreshed_row["file_pages_search_text"] = search_text
            refreshed_page_rows.append(refreshed_row)

        leading_excerpts: list[str] = []
        for row in refreshed_page_rows[:3]:
            ocr_excerpt = compact_whitespace(str(row.get("file_pages_ocr_text") or ""))[:900]
            visual_excerpt = compact_whitespace(str(row.get("file_pages_visual_summary") or ""))[:350]
            if ocr_excerpt:
                leading_excerpts.append(ocr_excerpt)
            if visual_excerpt:
                leading_excerpts.append(visual_excerpt)

        summary_hint = ""
        entity_labels: list[str] = []
        primary_identifier: str | None = None
        secondary_identifier: str | None = None
        if structured_facts_enabled:
            document_facts = self.document_fact_extractor.extract(
                file_name=file_name,
                document_code=document_metadata.document_code,
                document_type=None,
                page_rows=refreshed_page_rows,
            )
            file_group_id: int | None = None
            if document_facts.group_key:
                file_group_id = self.repository.document_facts.upsert_file_group(
                    user_id=user_id,
                    group_key=document_facts.group_key,
                    group_type=document_facts.group_type,
                    primary_identifier=document_facts.primary_identifier,
                    secondary_identifier=document_facts.secondary_identifier,
                    primary_subject=document_facts.primary_subject,
                    secondary_subject=document_facts.secondary_subject,
                    metadata_json=document_facts.metadata_json,
                )

            self.repository.document_facts.upsert_file_profile(
                user_id=user_id,
                file_group_id=file_group_id,
                file_id=file_id,
                profile_type="generic",
                file_role=document_facts.file_role,
                primary_identifier=document_facts.primary_identifier,
                secondary_identifier=document_facts.secondary_identifier,
                primary_subject=document_facts.primary_subject,
                secondary_subject=document_facts.secondary_subject,
                signed_at=document_facts.signed_at,
                effective_from=document_facts.effective_from,
                effective_to=document_facts.effective_to,
                fact_confidence=document_facts.confidence,
                fact_summary=document_facts.summary_text,
                metadata_json=document_facts.metadata_json,
            )
            self.repository.document_facts.replace_file_entities(
                user_id=user_id,
                file_id=file_id,
                file_group_id=file_group_id,
                entities=document_facts.entities,
            )
            self.repository.document_facts.replace_file_attributes(
                user_id=user_id,
                file_id=file_id,
                file_group_id=file_group_id,
                attributes=list(document_facts.attributes) + self._build_metadata_attribute_rows(
                    metadata_context=metadata_context
                ),
            )
            self.repository.document_facts.replace_file_links(
                user_id=user_id,
                file_id=file_id,
                file_group_id=file_group_id,
                links=document_facts.links,
            )
            summary_hint = document_facts.summary_text
            primary_identifier = document_facts.primary_identifier
            secondary_identifier = document_facts.secondary_identifier
            entity_labels = [
                compact_whitespace(str(item.get("entity_name") or item.get("person_name") or ""))
                for item in list(document_facts.entities)
                if compact_whitespace(str(item.get("entity_name") or item.get("person_name") or ""))
            ]
        summary_fragments = [
            f"file_name={file_name}",
            f"archive_slug={archive_slug}",
            f"document_code={document_metadata.document_code or ''}",
            summary_hint,
        ]
        summary_text = compact_whitespace(" | ".join(fragment for fragment in summary_fragments if fragment))
        if not summary_text:
            summary_text = compact_whitespace(" ".join([file_name, *leading_excerpts[:2]]))
        document_search_text = build_document_search_text(
            file_name=file_name,
            document_code=document_metadata.document_code,
            document_type=None,
            summary_text=summary_text,
            excerpts=leading_excerpts,
            labels=entity_labels,
            primary_identifier=primary_identifier,
            secondary_identifier=secondary_identifier,
        )
        if metadata_search_text:
            document_search_text = compact_whitespace(f"{document_search_text} | {metadata_search_text}")
        embedding_input = document_search_text or summary_text or compact_whitespace(file_name)
        document_embedding = self.embedding_service.embed_document_text(text=embedding_input)
        self.repository.file_embeddings.add_or_replace_embedding(
            user_id=user_id,
            file_id=file_id,
            archive_slug=archive_slug,
            embedding_model=self.settings.embedding_model_name,
            embedding_dimension=len(document_embedding),
            embedding_vector=document_embedding,
            summary_text=summary_text,
            search_text=document_search_text,
        )

    @staticmethod
    def _ensure_valid_pdf(pdf_path: Path) -> None:
        header = pdf_path.read_bytes()[:5]
        if header != b"%PDF-":
            raise ValueError(f"Invalid PDF header for '{pdf_path.name}'")


def get_ingestion_service() -> IngestionService:
    factory = import_module("apps.backend.app.ingest.ingestion_factory")
    return factory.get_ingestion_service()
