from __future__ import annotations

from apps.backend.app.repositories.file_repository import FileRepository


class _LookupCursor:
    def __init__(self, rows: list[tuple[int, str]]) -> None:
        self._rows = rows
        self.executed_sql = ""
        self.params: dict[str, object] = {}
        self.closed = False

    def execute(self, sql: str, params: dict[str, object]) -> None:
        self.executed_sql = " ".join(str(sql).split())
        self.params = dict(params)

    def fetchall(self) -> list[tuple[int, str]]:
        return self._rows

    def close(self) -> None:
        self.closed = True


class _LookupConnection:
    def __init__(self, cursor: _LookupCursor) -> None:
        self._cursor = cursor
        self.closed = False

    def cursor(self) -> _LookupCursor:
        return self._cursor

    def close(self) -> None:
        self.closed = True


class _LookupDbManager:
    def __init__(self, connection: _LookupConnection) -> None:
        self._connection = connection

    def get_connection(self) -> _LookupConnection:
        return self._connection


def _repository_with_rows(rows: list[tuple[int, str]]) -> tuple[FileRepository, _LookupCursor, _LookupConnection]:
    cursor = _LookupCursor(rows)
    connection = _LookupConnection(cursor)
    return FileRepository(_LookupDbManager(connection)), cursor, connection


def test_filename_lookup_matches_displayed_name_when_stored_name_loses_a_vowel() -> None:
    repository, cursor, connection = _repository_with_rows(
        [
            (90, "ZV403_-_Contrato.pdf"),
            (91, "ZV403_-_Modificacin_2.pdf"),
        ]
    )

    result = repository.list_file_ids_for_input_filenames(
        user_id=8,
        file_names=["ZV403_-_Modificacion_2.pdf"],
        include_shared=True,
    )

    assert result == [91]
    assert cursor.closed is True
    assert connection.closed is True


def test_filename_lookup_uses_canonical_punctuation_and_extension_keys() -> None:
    repository, _, _ = _repository_with_rows(
        [
            (12, "AC100 - Technical Summary.pdf"),
            (13, "AC100 - Technical Annex.pdf"),
        ]
    )

    result = repository.list_file_ids_for_input_filenames(
        user_id=8,
        file_names=["ac100_technical_summary"],
        include_shared=True,
    )

    assert result == [12]


def test_filename_lookup_does_not_use_ambiguous_signature_matches() -> None:
    repository, _, _ = _repository_with_rows(
        [
            (21, "AB100_-_Version.pdf"),
            (22, "AB100_-_Varsion.pdf"),
        ]
    )

    result = repository.list_file_ids_for_input_filenames(
        user_id=8,
        file_names=["AB100_-_Vorsion.pdf"],
        include_shared=True,
    )

    assert result == []
