from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import time

from apps.backend.app.rag import embedding_service


def test_nomic_provider_is_initialized_once_across_threads(monkeypatch) -> None:
    embedding_service.reset_nomic_local_provider_cache()

    created: list[object] = []

    class StubProvider:
        def __init__(self) -> None:
            time.sleep(0.05)
            created.append(self)

    monkeypatch.setattr(embedding_service, "NomicLocalMultimodalProvider", StubProvider)

    with ThreadPoolExecutor(max_workers=6) as executor:
        providers = list(executor.map(lambda _: embedding_service.get_nomic_local_provider(), range(12)))

    assert len(created) == 1
    assert all(provider is created[0] for provider in providers)

    embedding_service.reset_nomic_local_provider_cache()
