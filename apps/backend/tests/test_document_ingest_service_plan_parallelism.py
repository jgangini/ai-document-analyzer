from __future__ import annotations

from pathlib import Path
from threading import Lock
import time
from types import SimpleNamespace

from apps.backend.app.api.contracts.files import FileProcessItem
from apps.backend.app.ingest.document_ingest_service import IngestionService
from apps.backend.app.storage.object_keys import build_archive_prefix, build_pdf_source_key


def test_process_document_plan_runs_items_in_parallel_when_enabled() -> None:
    service = object.__new__(IngestionService)
    service._pre_register_process_plan_items = lambda *, process_items, user_id: None
    service._resolve_max_parallel_documents = lambda: 3

    def stub_process_documents(
        *,
        source_path,
        include_archives,
        limit,
        user_id,
        document_language,
        forced_archive_slug,
        source_zip_path,
        metadata_override,
        metadata_upload_id,
    ):
        time.sleep(0.2)
        return [
            FileProcessItem(
                file_id=1,
                file_name=Path(str(source_path)).name,
                status="completed",
                page_count=1,
                object_name=str(source_path),
                telemetry={"archive_slug": forced_archive_slug, "metadata_upload_id": metadata_upload_id},
            )
        ]

    service.process_documents = stub_process_documents

    progress: list[str] = []
    process_items = [
        {
            "source_path": f"D:/tmp/doc-{index}.pdf",
            "file_name": f"doc-{index}.pdf",
            "archive_slug": f"archive-{index}",
            "enabled": True,
        }
        for index in range(3)
    ]

    started = time.perf_counter()
    result = IngestionService.process_document_plan(
        service,
        process_items=process_items,
        user_id=7,
        metadata_upload_id="metadata-123",
        progress_callback=lambda item: progress.append(str(item.file_name)),
    )
    elapsed = time.perf_counter() - started

    assert result.errors == []
    assert len(result.processed) == 3
    assert sorted(progress) == ["doc-0.pdf", "doc-1.pdf", "doc-2.pdf"]
    # Three 200ms tasks should finish well below the 600ms sequential baseline.
    assert elapsed < 0.45


def test_process_document_plan_interleaves_archives_to_avoid_worker_starvation() -> None:
    service = object.__new__(IngestionService)
    service._pre_register_process_plan_items = lambda *, process_items, user_id: None
    service._resolve_max_parallel_documents = lambda: 2

    archive_locks = {
        "archive-a": Lock(),
        "archive-b": Lock(),
    }
    start_order: list[str] = []

    def stub_process_plan_item(*, raw_item, user_id, metadata_upload_id):
        del user_id, metadata_upload_id
        archive_slug = str(raw_item.get("archive_slug") or "")
        with archive_locks[archive_slug]:
            start_order.append(archive_slug)
            time.sleep(0.2)
            return [
                FileProcessItem(
                    file_id=1,
                    file_name=str(raw_item.get("file_name") or ""),
                    status="completed",
                    page_count=1,
                    object_name=str(raw_item.get("source_path") or ""),
                )
            ]

    service._process_plan_item = stub_process_plan_item

    process_items = [
        {
            "source_path": "D:/tmp/archive-a-1.pdf",
            "file_name": "archive-a-1.pdf",
            "archive_slug": "archive-a",
            "enabled": True,
        },
        {
            "source_path": "D:/tmp/archive-a-2.pdf",
            "file_name": "archive-a-2.pdf",
            "archive_slug": "archive-a",
            "enabled": True,
        },
        {
            "source_path": "D:/tmp/archive-a-3.pdf",
            "file_name": "archive-a-3.pdf",
            "archive_slug": "archive-a",
            "enabled": True,
        },
        {
            "source_path": "D:/tmp/archive-b-1.pdf",
            "file_name": "archive-b-1.pdf",
            "archive_slug": "archive-b",
            "enabled": True,
        },
    ]

    result = IngestionService.process_document_plan(
        service,
        process_items=process_items,
        user_id=7,
        metadata_upload_id=None,
    )

    assert result.errors == []
    assert len(result.processed) == 4
    assert len(start_order) == 4
    assert set(start_order[:2]) == {"archive-a", "archive-b"}


def test_process_documents_runs_archive_pdfs_in_parallel_when_enabled(tmp_path: Path) -> None:
    service = object.__new__(IngestionService)
    pdf_contexts = []
    for index in range(3):
        pdf_path = tmp_path / f"archive-doc-{index}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        pdf_contexts.append(
            SimpleNamespace(
                pdf_path=pdf_path,
                archive_slug=f"archive-{index}",
                archive_id=f"archive-id-{index}",
                source_zip_path=None,
            )
        )

    service.archive_service = SimpleNamespace(
        discover_sources=lambda *, source_path, include_archives: [str(source_path)],
        resolve_pdf_contexts=lambda sources: list(pdf_contexts),
    )
    service._pre_register_pdf_contexts = lambda **kwargs: None
    service._resolve_max_parallel_documents = lambda: 3

    def stub_process_pdf(
        pdf_path,
        *,
        user_id,
        archive_slug,
        archive_id,
        source_zip_path,
        document_language,
        forced_object_name,
        metadata_override,
        metadata_upload_id,
    ):
        del user_id, archive_slug, archive_id, source_zip_path, document_language, forced_object_name, metadata_override, metadata_upload_id
        time.sleep(0.2)
        return FileProcessItem(
            file_id=1,
            file_name=Path(str(pdf_path)).name,
            status="completed",
            page_count=1,
            object_name=str(pdf_path),
        )

    service._process_pdf = stub_process_pdf

    started = time.perf_counter()
    result = IngestionService.process_documents(
        service,
        source_path=tmp_path,
        include_archives=True,
        user_id=7,
    )
    elapsed = time.perf_counter() - started

    assert len(result) == 3
    assert sorted(item.file_name for item in result) == [
        "archive-doc-0.pdf",
        "archive-doc-1.pdf",
        "archive-doc-2.pdf",
    ]
    # Three 200ms tasks should finish well below the 600ms sequential baseline.
    assert elapsed < 0.45


def test_process_documents_runs_same_archive_pdfs_in_parallel_when_enabled(
    tmp_path: Path,
) -> None:
    service = object.__new__(IngestionService)
    pdf_contexts = []
    for index, archive_slug in enumerate(("archive-a", "archive-a", "archive-b")):
        pdf_path = tmp_path / f"{archive_slug}-doc-{index}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        pdf_contexts.append(
            SimpleNamespace(
                pdf_path=pdf_path,
                archive_slug=archive_slug,
                archive_id=f"archive-id-{index}",
                source_zip_path=None,
            )
        )

    service.archive_service = SimpleNamespace(
        discover_sources=lambda *, source_path, include_archives: [str(source_path)],
        resolve_pdf_contexts=lambda sources: list(pdf_contexts),
    )
    service._pre_register_pdf_contexts = lambda **kwargs: None
    service._resolve_max_parallel_documents = lambda: 3

    stats_lock = Lock()
    active_total = 0
    max_total = 0
    active_by_archive: dict[str, int] = {}
    max_by_archive: dict[str, int] = {}

    def stub_process_pdf(
        pdf_path,
        *,
        user_id,
        archive_slug,
        archive_id,
        source_zip_path,
        document_language,
        forced_object_name,
        metadata_override,
        metadata_upload_id,
    ):
        del user_id, archive_id, source_zip_path, document_language, forced_object_name, metadata_override, metadata_upload_id
        nonlocal active_total, max_total
        with stats_lock:
            active_total += 1
            max_total = max(max_total, active_total)
            active_by_archive[archive_slug] = active_by_archive.get(archive_slug, 0) + 1
            max_by_archive[archive_slug] = max(
                max_by_archive.get(archive_slug, 0),
                active_by_archive[archive_slug],
            )
        time.sleep(0.2)
        with stats_lock:
            active_total -= 1
            active_by_archive[archive_slug] -= 1
        return FileProcessItem(
            file_id=1,
            file_name=Path(str(pdf_path)).name,
            status="completed",
            page_count=1,
            object_name=str(pdf_path),
        )

    service._process_pdf = stub_process_pdf

    started = time.perf_counter()
    result = IngestionService.process_documents(
        service,
        source_path=tmp_path,
        include_archives=True,
        user_id=7,
    )
    elapsed = time.perf_counter() - started

    assert len(result) == 3
    assert max_by_archive["archive-a"] >= 2
    assert max_by_archive["archive-b"] == 1
    assert max_total >= 3
    # Same-archive PDFs should no longer serialize; ZIP upload dedupe is guarded separately.
    assert elapsed < 0.45


def test_process_documents_interleaves_archives_when_workers_are_limited(tmp_path: Path) -> None:
    service = object.__new__(IngestionService)
    pdf_contexts = []
    for index, archive_slug in enumerate(("archive-a", "archive-a", "archive-a", "archive-b")):
        pdf_path = tmp_path / f"{archive_slug}-doc-{index}.pdf"
        pdf_path.write_bytes(b"%PDF-1.4\n")
        pdf_contexts.append(
            SimpleNamespace(
                pdf_path=pdf_path,
                archive_slug=archive_slug,
                archive_id=f"archive-id-{index}",
                source_zip_path=None,
            )
        )

    service.archive_service = SimpleNamespace(
        discover_sources=lambda *, source_path, include_archives: [str(source_path)],
        resolve_pdf_contexts=lambda sources: list(pdf_contexts),
    )
    service._pre_register_pdf_contexts = lambda **kwargs: None
    service._resolve_max_parallel_documents = lambda: 2

    start_order: list[str] = []

    def stub_process_pdf(
        pdf_path,
        *,
        user_id,
        archive_slug,
        archive_id,
        source_zip_path,
        document_language,
        forced_object_name,
        metadata_override,
        metadata_upload_id,
    ):
        del user_id, archive_id, source_zip_path, document_language, forced_object_name, metadata_override, metadata_upload_id
        start_order.append(archive_slug)
        time.sleep(0.2)
        return FileProcessItem(
            file_id=1,
            file_name=Path(str(pdf_path)).name,
            status="completed",
            page_count=1,
            object_name=str(pdf_path),
        )

    service._process_pdf = stub_process_pdf

    result = IngestionService.process_documents(
        service,
        source_path=tmp_path,
        include_archives=True,
        user_id=7,
    )

    assert len(result) == 4
    assert len(start_order) == 4
    assert set(start_order[:2]) == {"archive-a", "archive-b"}


def test_pre_register_process_plan_items_uses_plan_paths_without_rediscovering_sources(
    tmp_path: Path,
    monkeypatch,
) -> None:
    service = object.__new__(IngestionService)

    pdf_a = tmp_path / "doc-a.pdf"
    pdf_b = tmp_path / "doc-b.pdf"
    pdf_a.write_bytes(b"%PDF-1.4\na")
    pdf_b.write_bytes(b"%PDF-1.4\nb")
    archive_zip = tmp_path / "archive-a.zip"
    archive_zip.write_bytes(b"zip-bytes")

    registered_calls: list[dict[str, object]] = []
    hash_calls: list[str] = []

    service.archive_service = SimpleNamespace(
        discover_sources=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("plan pre-registration should not rediscover sources")
        ),
        resolve_pdf_contexts=lambda sources: (_ for _ in ()).throw(
            AssertionError("plan pre-registration should not resolve pdf contexts")
        ),
    )
    service.repository = SimpleNamespace(
        get_user_storage_name=lambda user_id: "tester@example.com",
        get_or_create_file=lambda **kwargs: registered_calls.append(dict(kwargs)),
    )

    def stub_sha256_file(path: Path) -> str:
        normalized = str(Path(path))
        hash_calls.append(normalized)
        if normalized == str(archive_zip):
            return "zip-hash-123"
        raise AssertionError(f"Unexpected hash target during pre-registration: {normalized}")

    monkeypatch.setattr(
        "apps.backend.app.ingest.document_ingest_service.sha256_file",
        stub_sha256_file,
    )

    IngestionService._pre_register_process_plan_items(
        service,
        process_items=[
            {
                "source_path": str(pdf_a),
                "source_zip_path": str(archive_zip),
                "archive_slug": "ARCHIVE_A",
                "enabled": True,
            },
            {
                "source_path": str(pdf_b),
                "source_zip_path": str(archive_zip),
                "archive_slug": "ARCHIVE_A",
                "enabled": True,
            },
        ],
        user_id=7,
    )

    assert hash_calls == [str(archive_zip)]
    assert len(registered_calls) == 2

    expected_prefix = build_archive_prefix(
        username="tester@example.com",
        archive_slug="ARCHIVE_A",
        archive_id="zip-hash-123",
    )
    assert registered_calls[0]["bucket_object_name"] == build_pdf_source_key(
        archive_prefix=expected_prefix,
        doc_name=pdf_a.name,
    )
    assert registered_calls[1]["bucket_object_name"] == build_pdf_source_key(
        archive_prefix=expected_prefix,
        doc_name=pdf_b.name,
    )
