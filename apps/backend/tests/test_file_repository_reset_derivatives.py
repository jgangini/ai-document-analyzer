from __future__ import annotations

from apps.backend.app.repositories import file_repository as file_repository_module
from apps.backend.app.repositories.file_repository import FileRepository


class _StubCursor:
    def __init__(self) -> None:
        self.executed_sql: list[str] = []
        self.rowcount = 7
        self.closed = False

    def execute(self, sql: str, *args, **kwargs) -> None:
        del args, kwargs
        self.executed_sql.append(" ".join(str(sql).split()).upper())

    def close(self) -> None:
        self.closed = True


class _StubConnection:
    def __init__(self, cursor: _StubCursor) -> None:
        self._cursor = cursor
        self.commit_calls = 0
        self.rollback_calls = 0
        self.closed = False

    def cursor(self) -> _StubCursor:
        return self._cursor

    def commit(self) -> None:
        self.commit_calls += 1

    def rollback(self) -> None:
        self.rollback_calls += 1

    def close(self) -> None:
        self.closed = True


class _StubDbManager:
    def __init__(self, connection: _StubConnection) -> None:
        self._connection = connection

    def get_connection(self) -> _StubConnection:
        return self._connection


class _StubDocumentFactsRepository:
    def __init__(self) -> None:
        self.reset_calls: list[int] = []

    def reset_file_facts(self, *, file_id: int) -> None:
        self.reset_calls.append(int(file_id))


def test_reset_file_derivatives_relies_on_file_pages_cascade_for_page_embeddings() -> None:
    cursor = _StubCursor()
    connection = _StubConnection(cursor)
    repository = FileRepository(_StubDbManager(connection))
    stub_document_facts = _StubDocumentFactsRepository()
    repository.document_facts = stub_document_facts

    repository.reset_file_derivatives(file_id=346)

    assert stub_document_facts.reset_calls == [346]
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0
    assert connection.closed is True
    assert cursor.closed is True
    assert any("DELETE FROM FILE_EMBEDDINGS" in sql for sql in cursor.executed_sql)
    assert any("DELETE FROM FILE_PAGES" in sql for sql in cursor.executed_sql)
    assert not any("DELETE FROM PAGE_EMBEDDINGS" in sql for sql in cursor.executed_sql)


def test_update_file_status_uses_retryable_database_operation(monkeypatch) -> None:
    cursor = _StubCursor()
    connection = _StubConnection(cursor)
    repository = FileRepository(_StubDbManager(connection))
    captured_calls: list[tuple[str, ...]] = []

    def _stub_retryable_write(*, db_manager, operation, candidate_index_names=()):
        del db_manager
        captured_calls.append(tuple(candidate_index_names))
        return operation()

    monkeypatch.setattr(
        file_repository_module,
        "execute_with_retryable_database_operation",
        _stub_retryable_write,
    )

    repository.update_file_status(file_id=346, status="completed", page_count=12)

    assert captured_calls == [()]
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0
    assert any("UPDATE FILES" in sql for sql in cursor.executed_sql)


def test_mark_incomplete_files_as_failed_only_targets_processing_rows() -> None:
    cursor = _StubCursor()
    connection = _StubConnection(cursor)
    repository = FileRepository(_StubDbManager(connection))

    changed = repository.mark_incomplete_files_as_failed()

    assert changed == 7
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0
    assert connection.closed is True
    assert cursor.closed is True
    assert any("WHERE FILE_STATE = :PROCESSING_STATE" in sql for sql in cursor.executed_sql)
    assert not any("REGISTERED_STATE" in sql for sql in cursor.executed_sql)
