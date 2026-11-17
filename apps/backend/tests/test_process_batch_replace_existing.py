from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from apps.backend.app.api.contracts.files import FileProcessBatchRequest, FileProcessPlanItem
from apps.backend.app.api.routes import documents


class _StubRepository:
    def __init__(self) -> None:
        self.deleted_batches: list[tuple[list[int], int | None]] = []

    def delete_files(self, *, file_ids: list[int], user_id: int | None = None) -> int:
        self.deleted_batches.append((list(file_ids), user_id))
        return len(file_ids)


class _StubJobRegistry:
    def __init__(self) -> None:
        self.created_payloads: list[dict[str, object]] = []
        self.started_job_ids: list[str] = []

    def create_plan_job(
        self,
        *,
        process_items: list[dict[str, object]],
        user_id: int,
        metadata_upload_id: str | None = None,
    ) -> SimpleNamespace:
        self.created_payloads.append(
            {
                "process_items": process_items,
                "user_id": user_id,
                "metadata_upload_id": metadata_upload_id,
            }
        )
        now = datetime.now(timezone.utc)
        return SimpleNamespace(
            job_id="job-123",
            status="registered",
            created_at=now,
            updated_at=now,
            error=None,
            processed=[],
        )

    def start(self, job_id: str) -> None:
        self.started_job_ids.append(job_id)


def test_process_files_batch_replaces_existing_documents_in_backend(
    monkeypatch,
) -> None:
    repository = _StubRepository()
    job_registry = _StubJobRegistry()

    monkeypatch.setattr(documents, "_get_repository", lambda: repository)
    monkeypatch.setattr(documents, "get_ingest_job_registry", lambda: job_registry)

    request = FileProcessBatchRequest(
        metadata_upload_id="upload-123",
        replace_file_ids=[42, 0, 42, -1, 84],
        items=[
            FileProcessPlanItem(
                source_path="D:/tmp/sample.pdf",
                file_name="sample.pdf",
                archive_slug="sample_archive",
                enabled=True,
            )
        ],
    )

    response = documents.process_files_batch(
        request=request,
        current_user={"user_id": 7},
    )

    assert repository.deleted_batches == [([42, 84], 7)]
    assert job_registry.created_payloads == [
        {
            "process_items": [
                {
                    "source_path": "D:/tmp/sample.pdf",
                    "archive_slug": "sample_archive",
                    "file_name": "sample.pdf",
                    "enabled": True,
                }
            ],
            "user_id": 7,
            "metadata_upload_id": "upload-123",
        }
    ]
    assert job_registry.started_job_ids == ["job-123"]
    assert response.job.job_id == "job-123"
    assert response.queued_files == 1
