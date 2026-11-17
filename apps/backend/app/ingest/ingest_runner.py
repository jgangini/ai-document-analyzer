"""Background job runner for document ingestion requests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock, Thread
import time
import uuid

from apps.backend.app.contracts.files import FileProcessItem
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.ingest.ingestion_factory import get_ingestion_service
from apps.backend.app.repositories.file_repository import FileRepository
from apps.backend.app.services.runtime_config_service import ConfigService


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class IngestJobRecord:
    job_id: str
    status: str
    created_at: datetime
    updated_at: datetime
    request_payload: dict[str, object]
    processed: list[FileProcessItem] = field(default_factory=list)
    error: str | None = None


class IngestJobRegistry:
    """Registro in-memory de jobs de ingesta bajo la estructura nueva."""

    def __init__(self) -> None:
        self._jobs: dict[str, IngestJobRecord] = {}
        self._lock = Lock()
        self._active_jobs = 0
        self._recover_orphaned_file_states()

    def _recover_orphaned_file_states(self) -> None:
        try:
            repository = FileRepository(get_db_manager())
            repository.mark_incomplete_files_as_failed()
        except Exception:
            # Do not block API startup if reconciliation fails.
            pass

    def create_job(
        self,
        *,
        source_path: str | None,
        include_archives: bool,
        limit: int | None,
        user_id: int | None,
        document_language: str | None,
        access_scope: str | None = None,
        forced_archive_slug: str | None = None,
        forced_object_name: str | None = None,
        source_zip_path: str | None = None,
        metadata_override: dict[str, object] | None = None,
        metadata_upload_id: str | None = None,
    ) -> IngestJobRecord:
        job_id = str(uuid.uuid4())
        now = _utc_now()
        record = IngestJobRecord(
            job_id=job_id,
            status="registered",
            created_at=now,
            updated_at=now,
            request_payload={
                "source_path": source_path,
                "include_archives": include_archives,
                "limit": limit,
                "user_id": user_id,
                "document_language": document_language,
                "access_scope": access_scope,
                "forced_archive_slug": forced_archive_slug,
                "forced_object_name": forced_object_name,
                "source_zip_path": source_zip_path,
                "metadata_override": dict(metadata_override or {}),
                "metadata_upload_id": metadata_upload_id,
            },
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def create_plan_job(
        self,
        *,
        process_items: list[dict[str, object]],
        user_id: int,
        metadata_upload_id: str | None = None,
    ) -> IngestJobRecord:
        job_id = str(uuid.uuid4())
        now = _utc_now()
        record = IngestJobRecord(
            job_id=job_id,
            status="registered",
            created_at=now,
            updated_at=now,
            request_payload={
                "process_items": [dict(item) for item in process_items],
                "user_id": int(user_id),
                "metadata_upload_id": metadata_upload_id,
            },
        )
        with self._lock:
            self._jobs[job_id] = record
        return record

    def start(self, job_id: str) -> None:
        with self._lock:
            if job_id not in self._jobs:
                return
        worker = Thread(
            target=self._run_job,
            args=(job_id,),
            daemon=True,
            name=f"ingest-job-{job_id[:8]}",
        )
        worker.start()

    def get(self, job_id: str) -> IngestJobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def _resolve_max_parallel_jobs(self) -> int:
        try:
            config_service = ConfigService(get_db_manager())
            raw_value = config_service.get_value("rag.ingest.max_parallel_jobs", "2").strip()
            parsed = int(raw_value)
            return max(1, parsed)
        except Exception:
            return 1

    def _acquire_execution_slot(self, *, max_parallel_jobs: int) -> None:
        while True:
            with self._lock:
                if self._active_jobs < max_parallel_jobs:
                    self._active_jobs += 1
                    return
            time.sleep(0.2)

    def _release_execution_slot(self) -> None:
        with self._lock:
            if self._active_jobs > 0:
                self._active_jobs -= 1

    @staticmethod
    def _normalize_progress_item(item: FileProcessItem) -> FileProcessItem:
        return FileProcessItem(
            file_id=int(item.file_id or 0),
            file_name=str(item.file_name or ""),
            status=str(item.status or ""),
            page_count=int(item.page_count or 0),
            object_name=str(item.object_name or ""),
            telemetry=dict(item.telemetry or {}) if item.telemetry else None,
            error=None if item.error is None else str(item.error),
        )

    def _record_plan_progress(self, *, job_id: str, item: FileProcessItem) -> None:
        normalized = self._normalize_progress_item(item)
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return
            replaced = False
            normalized_file_name = str(normalized.file_name or "").strip().lower()
            for index, existing in enumerate(record.processed):
                existing_file_name = str(existing.file_name or "").strip().lower()
                if int(existing.file_id or 0) > 0 and int(normalized.file_id or 0) > 0:
                    if int(existing.file_id or 0) == int(normalized.file_id or 0):
                        record.processed[index] = normalized
                        replaced = True
                        break
                elif normalized_file_name and normalized_file_name == existing_file_name:
                    record.processed[index] = normalized
                    replaced = True
                    break
            if not replaced:
                record.processed.append(normalized)
            record.updated_at = _utc_now()

    def _run_job(self, job_id: str) -> None:
        max_parallel_jobs = self._resolve_max_parallel_jobs()
        self._acquire_execution_slot(max_parallel_jobs=max_parallel_jobs)
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                self._release_execution_slot()
                return
            record.status = "running"
            record.updated_at = _utc_now()

        service = get_ingestion_service()
        payload = record.request_payload
        try:
            if payload.get("process_items") is not None:
                plan_result = service.process_document_plan(
                    process_items=list(payload.get("process_items") or []),
                    user_id=int(payload["user_id"]),
                    metadata_upload_id=(
                        str(payload.get("metadata_upload_id") or "").strip() or None
                    ),
                    progress_callback=lambda item: self._record_plan_progress(job_id=job_id, item=item),
                )
                with self._lock:
                    record.processed = list(plan_result.processed)
                    record.updated_at = _utc_now()
                    if plan_result.errors:
                        record.error = "\n".join(plan_result.errors[:10])
                        if len(plan_result.errors) > 10:
                            record.error += f"\n...and {len(plan_result.errors) - 10} more error(s)."
                        record.status = "failed"
                    else:
                        record.status = "completed"
                return

            processed = service.process_documents(
                source_path=Path(payload["source_path"]) if payload.get("source_path") else None,
                include_archives=bool(payload.get("include_archives", True)),
                limit=int(payload["limit"]) if payload.get("limit") is not None else None,
                user_id=int(payload["user_id"]) if payload.get("user_id") is not None else None,
                document_language=str(payload["document_language"]) if payload.get("document_language") else None,
                access_scope=str(payload["access_scope"]) if payload.get("access_scope") else None,
                forced_archive_slug=str(payload["forced_archive_slug"]) if payload.get("forced_archive_slug") else None,
                forced_object_name=str(payload["forced_object_name"]) if payload.get("forced_object_name") else None,
                source_zip_path=(
                    Path(str(payload["source_zip_path"]))
                    if payload.get("source_zip_path")
                    else None
                ),
                metadata_override=dict(payload.get("metadata_override") or {}),
                metadata_upload_id=(
                    str(payload.get("metadata_upload_id") or "").strip() or None
                ),
            )
            with self._lock:
                record.processed = list(processed)
                record.status = "completed"
                record.updated_at = _utc_now()
        except Exception as exc:
            with self._lock:
                record.error = str(exc)
                record.status = "failed"
                record.updated_at = _utc_now()
        finally:
            self._release_execution_slot()


_REGISTRY = IngestJobRegistry()


def get_ingest_job_registry() -> IngestJobRegistry:
    return _REGISTRY
