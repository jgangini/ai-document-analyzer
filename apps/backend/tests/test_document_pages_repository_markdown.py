from __future__ import annotations

import pytest

from apps.backend.app.repositories.document_pages_repository import FilePagesRepository


class _StubLob:
    def __init__(self, value: str) -> None:
        self.value = value

    def read(self) -> str:
        return self.value


class _StubCursor:
    def __init__(self, rows: list[tuple[object, object]]) -> None:
        self.rows = rows
        self.executed_sql: list[str] = []
        self.closed = False

    def execute(self, sql: str, *args, **kwargs) -> None:
        del args, kwargs
        self.executed_sql.append(" ".join(str(sql).split()).upper())

    def fetchall(self) -> list[tuple[object, object]]:
        return list(self.rows)

    def close(self) -> None:
        self.closed = True


class _StubConnection:
    def __init__(self, cursor: _StubCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _StubCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


class _StubDbManager:
    def __init__(self, connection: _StubConnection) -> None:
        self._connection = connection

    def get_connection(self) -> _StubConnection:
        return self._connection


def test_file_markdown_reads_markdown_column_instead_of_ocr_text() -> None:
    cursor = _StubCursor(
        rows=[
            (1, _StubLob("# Extracted title\n\n| A | B |\n| - | - |\n| 1 | 2 |")),
            (2, "Second page paragraph"),
        ]
    )
    connection = _StubConnection(cursor)
    repository = FilePagesRepository(_StubDbManager(connection))

    markdown = repository.get_file_markdown(file_id=7)

    assert "## Page 1\n\n# Extracted title" in markdown
    assert "## Page 2\n\nSecond page paragraph" in markdown
    assert any("FILE_PAGES_MARKDOWN_TEXT" in sql for sql in cursor.executed_sql)
    assert not any("SELECT FILE_PAGES_NUMBER, FILE_PAGES_OCR_TEXT" in sql for sql in cursor.executed_sql)
    assert cursor.closed is True
    assert connection.closed is True


def test_file_markdown_raises_when_markdown_artifact_is_missing() -> None:
    cursor = _StubCursor(rows=[(1, None)])
    connection = _StubConnection(cursor)
    repository = FilePagesRepository(_StubDbManager(connection))

    with pytest.raises(RuntimeError, match="Markdown extraction is missing"):
        repository.get_file_markdown(file_id=7)

    assert cursor.closed is True
    assert connection.closed is True
