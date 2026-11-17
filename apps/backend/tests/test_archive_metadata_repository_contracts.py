from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_file_types_bootstrap_script_is_removed() -> None:
    sql_path = Path("apps/backend/db/bootstrap/sql/04_file_types.sql")
    assert sql_path.exists() is False

def test_archive_metadata_repository_is_bootstrap_only() -> None:
    assert hasattr(ArchiveMetadataRepository, "ensure_schema") is False

def test_archive_metadata_bootstrap_sql_files_exist() -> None:
    sql_dir = Path("apps/backend/db/bootstrap/sql")
    assert (sql_dir / "22_archive_metadata_uploads.sql").exists()
    assert (sql_dir / "23_archive_metadata_upload_rows.sql").exists()
    assert (sql_dir / "24_archive_metadata.sql").exists()

def test_archive_metadata_repository_file_lookup_does_not_use_distinct_with_clob() -> None:
    class _StubCursor:
        def __init__(self) -> None:
            self.executed_sql = ""

        def execute(self, sql: str, params: dict | None = None) -> None:
            del params
            self.executed_sql = sql

        def fetchall(self) -> list[tuple]:
            return []

        def close(self) -> None:
            return None

    class _StubConnection:
        def __init__(self, cursor: _StubCursor) -> None:
            self._cursor = cursor

        def cursor(self) -> _StubCursor:
            return self._cursor

        def close(self) -> None:
            return None

    stub_cursor = _StubCursor()
    repository = object.__new__(ArchiveMetadataRepository)
    repository.db_manager = type(
        "_StubDbManager",
        (),
        {"get_connection": lambda self: _StubConnection(stub_cursor)},
    )()
    rows = repository.get_archive_metadata_for_file_ids(user_id=7, file_ids=[101])

    assert rows == []
    assert "SELECT DISTINCT" not in _normalize_sql_whitespace(stub_cursor.executed_sql).upper()

def test_archive_metadata_repository_user_lookup_does_not_group_by_metadata_clob() -> None:
    class _StubCursor:
        def __init__(self) -> None:
            self.executed_sql = ""

        def execute(self, sql: str, params: dict | None = None, **kwargs) -> None:
            del params, kwargs
            self.executed_sql = sql

        def fetchall(self) -> list[tuple]:
            return []

        def close(self) -> None:
            return None

    class _StubConnection:
        def __init__(self, cursor: _StubCursor) -> None:
            self._cursor = cursor

        def cursor(self) -> _StubCursor:
            return self._cursor

        def close(self) -> None:
            return None

    stub_cursor = _StubCursor()
    repository = object.__new__(ArchiveMetadataRepository)
    repository.db_manager = type(
        "_StubDbManager",
        (),
        {"get_connection": lambda self: _StubConnection(stub_cursor)},
    )()

    rows = repository.list_archive_metadata_for_user(user_id=7, include_shared=True)

    normalized_sql = _normalize_sql_whitespace(stub_cursor.executed_sql).upper()
    group_by_fragment = normalized_sql.split("GROUP BY", 1)[1]
    assert rows == []
    assert "AM.METADATA_JSON" not in group_by_fragment
    assert "AM.METADATA_SEARCH_TEXT" not in group_by_fragment

def test_archive_metadata_repository_lists_shared_metadata_uploads_against_visible_files() -> None:
    class _StubCursor:
        def __init__(self) -> None:
            self.executed_sql = ""
            self.params: dict | None = None

        def execute(self, sql: str, params: dict | None = None, **kwargs) -> None:
            del kwargs
            self.executed_sql = sql
            self.params = params

        def fetchall(self) -> list[tuple]:
            return []

        def close(self) -> None:
            return None

    class _StubConnection:
        def __init__(self, cursor: _StubCursor) -> None:
            self._cursor = cursor

        def cursor(self) -> _StubCursor:
            return self._cursor

        def close(self) -> None:
            return None

    stub_cursor = _StubCursor()
    repository = object.__new__(ArchiveMetadataRepository)
    repository.db_manager = type(
        "_StubDbManager",
        (),
        {"get_connection": lambda self: _StubConnection(stub_cursor)},
    )()

    rows = repository.list_uploads_for_user(user_id=11, include_archived=False, include_shared=True)

    normalized_sql = _normalize_sql_whitespace(stub_cursor.executed_sql).upper()
    assert rows == []
    assert stub_cursor.params == {"user_id": 11}
    assert "U.ACCESS_SCOPE" in normalized_sql
    assert "LOWER(NVL(U.ACCESS_SCOPE, 'PRIVATE')) = 'ALL'" in normalized_sql
    assert "LOWER(NVL(F.ACCESS_SCOPE, 'PRIVATE')) = 'ALL'" in normalized_sql
    assert "F.USER_ID = R.USER_ID" not in normalized_sql

def test_archive_metadata_repository_get_upload_row_can_read_shared_dataset_rows() -> None:
    class _StubCursor:
        def __init__(self) -> None:
            self.executed_sql = ""

        def execute(self, sql: str, params: dict | None = None, **kwargs) -> None:
            del params, kwargs
            self.executed_sql = sql

        def fetchone(self) -> None:
            return None

        def close(self) -> None:
            return None

    class _StubConnection:
        def __init__(self, cursor: _StubCursor) -> None:
            self._cursor = cursor

        def cursor(self) -> _StubCursor:
            return self._cursor

        def close(self) -> None:
            return None

    stub_cursor = _StubCursor()
    repository = object.__new__(ArchiveMetadataRepository)
    repository.db_manager = type(
        "_StubDbManager",
        (),
        {"get_connection": lambda self: _StubConnection(stub_cursor)},
    )()

    row = repository.get_upload_row(metadata_upload_id="meta-1", user_id=22, file_key="LA122")

    normalized_sql = _normalize_sql_whitespace(stub_cursor.executed_sql).upper()
    assert row is None
    assert "JOIN ARCHIVE_METADATA_UPLOADS U" in normalized_sql
    assert "LOWER(NVL(U.ACCESS_SCOPE, 'PRIVATE')) = 'ALL'" in normalized_sql
    assert "R.USER_ID = :USER_ID" not in normalized_sql

def test_archive_metadata_repository_retries_update_after_unique_constraint_race(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubCursor:
        def __init__(self) -> None:
            self.executed_sql: list[str] = []
            self.rowcount = 0

        def execute(self, sql: str, *args, **kwargs) -> None:
            del args, kwargs
            normalized_sql = _normalize_sql_whitespace(sql).upper()
            self.executed_sql.append(normalized_sql)
            if normalized_sql.startswith("MERGE INTO ARCHIVE_METADATA"):
                raise RuntimeError("ORA-00001: unique constraint (APP_DOC.UQ_ARCHIVE_METADATA_SLUG)")
            if normalized_sql.startswith("UPDATE ARCHIVE_METADATA"):
                self.rowcount = 1
                return
            raise AssertionError(f"Unexpected SQL executed: {normalized_sql}")

        def close(self) -> None:
            return None

    class _StubConnection:
        def __init__(self) -> None:
            self.rollback_calls = 0
            self.commit_calls = 0

        def cursor(self) -> _StubCursor:
            return stub_cursor

        def rollback(self) -> None:
            self.rollback_calls += 1

        def commit(self) -> None:
            self.commit_calls += 1

        def close(self) -> None:
            return None

    stub_cursor = _StubCursor()
    stub_connections: list[_StubConnection] = []

    def _get_connection():
        connection = _StubConnection()
        stub_connections.append(connection)
        return connection

    import apps.backend.app.repositories.archive_metadata_repository as archive_metadata_module

    monkeypatch.setattr(
        archive_metadata_module,
        "execute_with_oracle_text_repair",
        lambda *, db_manager, operation, candidate_index_names: operation(),
    )

    repository = object.__new__(ArchiveMetadataRepository)
    repository.db_manager = type("_StubDbManager", (), {"get_connection": staticmethod(_get_connection)})()
    repository.upsert_archive_metadata(
        user_id=7,
        archive_slug="AI041_ID_49",
        metadata_upload_id="upload-123",
        metadata_json='{"file":"AI041_ID_49"}',
        metadata_search_text="file ai041 id 49",
    )

    assert len(stub_connections) == 2
    assert stub_connections[0].rollback_calls == 1
    assert stub_connections[0].commit_calls == 0
    assert stub_connections[1].commit_calls == 1
    assert any(sql.startswith("MERGE INTO ARCHIVE_METADATA") for sql in stub_cursor.executed_sql)
    assert any(sql.startswith("UPDATE ARCHIVE_METADATA") for sql in stub_cursor.executed_sql)

def test_build_oracle_text_contains_query_sanitizes_metadata_question() -> None:
    query = build_oracle_text_contains_query(
        "Usa la metadata para ubicar RM797_ID_1668.zip con Id 1668; "
        "luego confirma el Nombre de Propietario Principal y la Dirección."
    )

    tokens = query.split(" OR ")

    assert "{rm797_id_1668}" in tokens
    assert "{1668}" in tokens
    assert "{propietario}" in tokens
    assert "{dirección}" in tokens
    assert ";" not in query
    assert "." not in query
    assert ":" not in query

def test_build_oracle_text_contains_query_wraps_reserved_terms_as_literals() -> None:
    query = build_oracle_text_contains_query(
        "Busca RM797_ID_1668 and within about NOT owner"
    )

    tokens = query.split(" OR ")

    assert "{rm797_id_1668}" in tokens
    assert "{within}" in tokens
    assert "{about}" in tokens
    assert "{owner}" in tokens
    assert " within " not in query

def test_build_oracle_text_contains_query_returns_empty_for_only_noise() -> None:
    assert build_oracle_text_contains_query("de, la; y. a o") == ""

def test_rag_bootstrap_sql_aligns_archive_slug_and_oracle_text_defaults() -> None:
    files_sql = Path("apps/backend/db/bootstrap/sql/05_files.sql").read_text(encoding="utf-8")
    file_pages_sql = Path("apps/backend/db/bootstrap/sql/06_file_pages.sql").read_text(encoding="utf-8")
    page_embeddings_sql = Path("apps/backend/db/bootstrap/sql/07_page_embeddings.sql").read_text(encoding="utf-8")
    file_embeddings_sql = Path("apps/backend/db/bootstrap/sql/08_file_embeddings.sql").read_text(encoding="utf-8")
    uploads_sql = Path("apps/backend/db/bootstrap/sql/22_archive_metadata_uploads.sql").read_text(encoding="utf-8")
    upload_rows_sql = Path("apps/backend/db/bootstrap/sql/23_archive_metadata_upload_rows.sql").read_text(encoding="utf-8")
    archive_metadata_sql = Path("apps/backend/db/bootstrap/sql/24_archive_metadata.sql").read_text(encoding="utf-8")

    normalized_files_sql = _normalize_sql_whitespace(files_sql.lower())
    normalized_file_pages_sql = _normalize_sql_whitespace(file_pages_sql.lower())
    normalized_page_embeddings_sql = _normalize_sql_whitespace(page_embeddings_sql.lower())
    normalized_file_embeddings_sql = _normalize_sql_whitespace(file_embeddings_sql.lower())
    normalized_uploads_sql = _normalize_sql_whitespace(uploads_sql.lower())
    normalized_upload_rows_sql = _normalize_sql_whitespace(upload_rows_sql.lower())
    normalized_archive_metadata_sql = _normalize_sql_whitespace(archive_metadata_sql.lower())

    assert "archive_slug varchar2(256)" in normalized_files_sql
    assert "create index idx_files_user_archive_slug on files (user_id, archive_slug);" in normalized_files_sql
    assert "file_type_key" not in normalized_files_sql
    assert "parameters ('maintenance auto')" in normalized_file_pages_sql
    assert "archive_slug varchar2(256)" in normalized_page_embeddings_sql
    assert "create index idx_page_embeddings_archive on page_embeddings (user_id, archive_slug, page_embeddings_modality);" in normalized_page_embeddings_sql
    assert "include (user_id, file_id, file_pages_id, archive_slug, page_embeddings_modality)" in normalized_page_embeddings_sql
    assert "create vector index idx_page_embeddings_vector" in normalized_page_embeddings_sql
    assert "organization neighbor partitions" in normalized_page_embeddings_sql
    assert "organization inmemory neighbor graph" not in normalized_page_embeddings_sql
    assert "archive_slug varchar2(256)" in normalized_file_embeddings_sql
    assert "create index idx_file_embeddings_archive on file_embeddings (user_id, archive_slug);" in normalized_file_embeddings_sql
    assert "parameters ('maintenance auto')" in normalized_file_embeddings_sql
    assert "create vector index idx_file_embeddings_vector" in normalized_file_embeddings_sql
    assert "organization neighbor partitions" in normalized_file_embeddings_sql
    assert "organization inmemory neighbor graph" not in normalized_file_embeddings_sql
    assert "include (user_id, file_id, archive_slug)" in normalized_file_embeddings_sql
    assert "create table archive_metadata_uploads" in normalized_uploads_sql
    assert "display_name varchar2(300)" in normalized_uploads_sql
    assert "metadata_status varchar2(32) default 'active' not null" in normalized_uploads_sql
    assert "check (metadata_status in ('active', 'archived'))" in normalized_uploads_sql
    assert "create index idx_archive_metadata_uploads_status" in normalized_uploads_sql
    assert "create table archive_metadata_upload_rows" in normalized_upload_rows_sql
    assert "create index idx_archive_metadata_upload_rows_text on archive_metadata_upload_rows (search_text) indextype is ctxsys.context parameters ('maintenance auto');" in normalized_upload_rows_sql
    assert "create table archive_metadata" in normalized_archive_metadata_sql
    assert "create index idx_archive_metadata_text on archive_metadata (metadata_search_text) indextype is ctxsys.context parameters ('maintenance auto');" in normalized_archive_metadata_sql
