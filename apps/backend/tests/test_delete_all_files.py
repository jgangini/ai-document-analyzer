from __future__ import annotations

from scripts.delete_all_files import TRUNCATE_ORDER


def test_truncate_order_covers_current_document_tables() -> None:
    expected_tables = {
        "page_embeddings",
        "file_links",
        "file_attributes",
        "file_entities",
        "file_profiles",
        "file_embeddings",
        "file_pages",
        "archive_metadata_upload_rows",
        "archive_metadata",
        "archive_metadata_uploads",
        "qa_sessions",
        "ingest_job_files",
        "files",
        "file_groups",
        "ingest_jobs",
        "qa_conversations",
    }
    assert expected_tables.issubset(set(TRUNCATE_ORDER))


def test_truncate_order_respects_foreign_key_dependencies() -> None:
    index = {name: TRUNCATE_ORDER.index(name) for name in TRUNCATE_ORDER}
    assert index["page_embeddings"] < index["file_pages"]
    assert index["page_embeddings"] < index["files"]
    assert index["file_embeddings"] < index["files"]
    assert index["file_links"] < index["file_pages"]
    assert index["file_links"] < index["file_groups"]
    assert index["file_attributes"] < index["file_pages"]
    assert index["file_attributes"] < index["file_groups"]
    assert index["file_entities"] < index["file_pages"]
    assert index["file_entities"] < index["file_groups"]
    assert index["file_profiles"] < index["files"]
    assert index["file_profiles"] < index["file_groups"]
    assert index["archive_metadata_upload_rows"] < index["archive_metadata_uploads"]
    assert index["archive_metadata"] < index["archive_metadata_uploads"]
    assert index["qa_sessions"] < index["files"]
    assert index["qa_sessions"] < index["qa_conversations"]
    assert index["ingest_job_files"] < index["files"]
    assert index["ingest_job_files"] < index["ingest_jobs"]
