from __future__ import annotations

from datetime import datetime

from apps.backend.app.repositories.chat_conversations_repository import QAConversationsRepository


class _StubCursor:
    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self._rows = rows
        self.executed: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def execute(self, sql: str, /, **kwargs) -> None:
        normalized_sql = " ".join(str(sql).split())
        self.executed.append((normalized_sql, kwargs))

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._rows)

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

    def table_exists(self, table_name: str) -> bool:
        return str(table_name or "").strip().lower() in {"qa_conversations", "qa_sessions"}

    def get_connection(self) -> _StubConnection:
        return self._connection


def test_list_conversations_orders_by_last_turn_activity(monkeypatch) -> None:
    activity_at = datetime(2026, 4, 24, 9, 30, 0)
    rows = [
        (
            12,
            "chat reciente",
            datetime(2026, 4, 20, 8, 0, 0),
            activity_at,
            3,
            "ultima respuesta",
        )
    ]
    cursor = _StubCursor(rows)
    connection = _StubConnection(cursor)
    repository = QAConversationsRepository(_StubDbManager(connection))
    monkeypatch.setattr(repository, "_supports_session_link", lambda: True)

    result = repository.list_conversations(user_id=7)

    assert result == [
        {
            "qa_conversations_id": 12,
            "qa_conversations_title": "chat reciente",
            "qa_conversations_created": datetime(2026, 4, 20, 8, 0, 0),
            "qa_conversations_updated": activity_at,
            "turns": 3,
            "last_message_preview": "ultima respuesta",
        }
    ]
    executed_sql, params = cursor.executed[-1]
    assert "SELECT MAX(s.qa_sessions_created)" in executed_sql
    assert "ORDER BY qa_conversations_last_activity DESC" in executed_sql
    assert params == {"user_id": 7, "search_filter": None}
    assert cursor.closed is True
    assert connection.closed is True
