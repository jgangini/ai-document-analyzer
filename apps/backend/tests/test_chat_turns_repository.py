from __future__ import annotations

from apps.backend.app.repositories.chat_turns_repository import QASessionsRepository


class _StubVar:
    def __init__(self, value: int) -> None:
        self._value = int(value)

    def getvalue(self) -> list[int]:
        return [self._value]


class _StubCursor:
    def __init__(self) -> None:
        self.executed: list[tuple[str, dict[str, object]]] = []
        self.closed = False
        self.fetchone_results: list[tuple[object, ...]] = [(1,)]

    def execute(self, sql: str, /, **kwargs) -> None:
        normalized_sql = " ".join(str(sql).split())
        self.executed.append((normalized_sql, kwargs))

    def fetchone(self) -> tuple[object, ...]:
        if self.fetchone_results:
            return self.fetchone_results.pop(0)
        return (1,)

    def var(self, _kind) -> _StubVar:
        return _StubVar(321)

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

    def table_exists(self, table_name: str) -> bool:
        return str(table_name or "").strip().lower() == "qa_sessions"

    def get_connection(self) -> _StubConnection:
        return self._connection


def test_save_qa_session_persists_full_answer_clob(monkeypatch) -> None:
    cursor = _StubCursor()
    connection = _StubConnection(cursor)
    repository = QASessionsRepository(_StubDbManager(connection))
    monkeypatch.setattr(repository, "_supports_conversation_columns", lambda: False)
    long_answer = "\n".join(f"| {index} | fila {index} |" for index in range(1, 121))

    result = repository.save_qa_session(
        user_id=7,
        file_id=None,
        conversation_id=None,
        question="dame el inventario",
        retrieval_metadata={"strategy": "facts-first"},
        answer=long_answer,
        model_used="facts-layer:inventory",
    )

    assert result == {
        "qa_sessions_id": 321,
        "qa_sessions_turn_index": 0,
        "qa_conversations_id": None,
    }
    assert connection.commit_calls == 1
    assert connection.rollback_calls == 0
    assert connection.closed is True
    assert cursor.closed is True

    _, params = cursor.executed[-1]
    assert params["answer"] == long_answer
    assert len(str(params["answer"])) == len(long_answer)


def test_save_qa_session_refreshes_conversation_updated_at(monkeypatch) -> None:
    cursor = _StubCursor()
    connection = _StubConnection(cursor)
    repository = QASessionsRepository(_StubDbManager(connection))
    monkeypatch.setattr(repository, "_supports_conversation_columns", lambda: True)

    result = repository.save_qa_session(
        user_id=9,
        file_id=17,
        conversation_id=44,
        question="hola",
        retrieval_metadata={"strategy": "chat"},
        answer="respuesta",
        model_used="gemini",
    )

    assert result == {
        "qa_sessions_id": 321,
        "qa_sessions_turn_index": 1,
        "qa_conversations_id": 44,
    }
    assert any("UPDATE qa_conversations" in sql for sql, _ in cursor.executed)
    update_calls = [params for sql, params in cursor.executed if "UPDATE qa_conversations" in sql]
    assert update_calls == [{"conversation_id": 44, "user_id": 9}]
