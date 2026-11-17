from __future__ import annotations

from typing import Any

from apps.backend.app.repositories.document_facts_repository import DocumentFactsRepository


class _RecordingCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, Any]]] = []
        self.rowcount = 0
        self.closed = False

    def execute(self, statement: str, **params: Any) -> None:
        self.executed.append((statement.strip(), dict(params)))

    def close(self) -> None:
        self.closed = True


class _RecordingConnection:
    def __init__(self, cursor: _RecordingCursor) -> None:
        self._cursor = cursor
        self.committed = False
        self.closed = False

    def cursor(self) -> _RecordingCursor:
        return self._cursor

    def commit(self) -> None:
        self.committed = True

    def close(self) -> None:
        self.closed = True


class _RecordingDbManager:
    def __init__(self, connection: _RecordingConnection) -> None:
        self._connection = connection

    def get_connection(self) -> _RecordingConnection:
        return self._connection


def test_reset_file_facts_only_deletes_file_scoped_rows() -> None:
    cursor = _RecordingCursor()
    connection = _RecordingConnection(cursor)
    repository = DocumentFactsRepository(_RecordingDbManager(connection))

    repository.reset_file_facts(file_id=77)

    assert connection.committed is True
    assert connection.closed is True
    assert cursor.closed is True
    statements = [statement for statement, _ in cursor.executed]
    assert statements == [
        "DELETE FROM file_links WHERE file_id = :file_id",
        "DELETE FROM file_attributes WHERE file_id = :file_id",
        "DELETE FROM file_entities WHERE file_id = :file_id",
        "DELETE FROM file_profiles WHERE file_id = :file_id",
    ]
    assert all(params == {"file_id": 77} for _, params in cursor.executed)


def test_normalize_entity_row_replaces_none_in_required_columns() -> None:
    normalized = DocumentFactsRepository._normalize_entity_row(
        {
            "page_id": 0,
            "entity_role": None,
            "entity_type": None,
            "entity_name": None,
            "person_name": None,
            "identifier_value": None,
            "has_visible_signature": None,
            "bbox_json": None,
            "metadata_json": None,
            "confidence": 1.5,
        }
    )
    assert normalized == {
        "page_id": None,
        "entity_role": "",
        "entity_type": "organization",
        "entity_name": None,
        "person_name": None,
        "identifier_value": None,
        "has_visible_signature": 0,
        "bbox_json": "{}",
        "metadata_json": "{}",
        "confidence": 1.0,
    }


def test_normalize_attribute_row_clamps_and_defaults_values() -> None:
    normalized = DocumentFactsRepository._normalize_attribute_row(
        {
            "page_id": "7",
            "attribute_key": None,
            "attribute_value_text": None,
            "attribute_value_number": 12.5,
            "attribute_value_date": None,
            "attribute_value_bool": "yes",
            "source_type": None,
            "metadata_json": None,
            "confidence": -3,
        }
    )
    assert normalized == {
        "page_id": 7,
        "attribute_key": "",
        "attribute_value_text": None,
        "attribute_value_number": 12.5,
        "attribute_value_date": None,
        "attribute_value_bool": 1,
        "source_type": "ocr",
        "metadata_json": "{}",
        "confidence": 0.0,
    }


def test_normalize_link_row_replaces_missing_required_text_fields() -> None:
    normalized = DocumentFactsRepository._normalize_link_row(
        {
            "page_id": None,
            "link_type": None,
            "source_label": None,
            "target_label": None,
            "link_key": None,
            "metadata_json": None,
            "confidence": 0.42,
        }
    )
    assert normalized == {
        "page_id": None,
        "link_type": "",
        "source_label": None,
        "target_label": None,
        "link_key": None,
        "metadata_json": "{}",
        "confidence": 0.42,
    }
