from __future__ import annotations

from apps.backend.app.ingest.ingest_runner import IngestJobRegistry


def test_ingest_job_registry_reads_parallel_jobs_from_runtime_config(monkeypatch) -> None:
    class _StubConfigService:
        def __init__(self, db_manager) -> None:
            self.db_manager = db_manager

        def get_value(self, key: str, default: str = "") -> str:
            assert key == "rag.ingest.max_parallel_jobs"
            assert default == "2"
            return "4"

    registry = object.__new__(IngestJobRegistry)

    monkeypatch.setattr("apps.backend.app.ingest.ingest_runner.ConfigService", _StubConfigService)
    monkeypatch.setattr("apps.backend.app.ingest.ingest_runner.get_db_manager", lambda: object())

    assert IngestJobRegistry._resolve_max_parallel_jobs(registry) == 4
