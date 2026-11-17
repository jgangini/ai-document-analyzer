from __future__ import annotations

from apps.backend.app.repositories import repository_utils


def test_execute_with_retryable_database_operation_retries_deadlock(monkeypatch) -> None:
    sleep_calls: list[float] = []
    monkeypatch.setattr(repository_utils.time, "sleep", lambda seconds: sleep_calls.append(float(seconds)))

    attempts = {"count": 0}

    def _operation() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("ORA-00060: deadlock detected while waiting for resource")
        return "ok"

    result = repository_utils.execute_with_retryable_database_operation(
        db_manager=object(),  # type: ignore[arg-type]
        operation=_operation,
    )

    assert result == "ok"
    assert attempts["count"] == 2
    assert sleep_calls == [1.0]


def test_execute_with_retryable_database_operation_repairs_oracle_text_before_retry(monkeypatch) -> None:
    sleep_calls: list[float] = []
    repair_calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(repository_utils.time, "sleep", lambda seconds: sleep_calls.append(float(seconds)))
    monkeypatch.setattr(
        repository_utils,
        "repair_oracle_text_indexes",
        lambda **kwargs: repair_calls.append(tuple(kwargs.get("candidate_index_names") or ())),
    )

    attempts = {"count": 0}

    def _operation() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("ORA-29861: domain index is marked LOADING and currently not usable")
        return "ok"

    result = repository_utils.execute_with_retryable_database_operation(
        db_manager=object(),  # type: ignore[arg-type]
        operation=_operation,
        candidate_index_names=("IDX_FILE_PAGES_SEARCH_TEXT",),
    )

    assert result == "ok"
    assert attempts["count"] == 2
    assert repair_calls == [("IDX_FILE_PAGES_SEARCH_TEXT",)]
    assert sleep_calls == [0.25]
