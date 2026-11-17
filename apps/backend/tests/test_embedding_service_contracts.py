from __future__ import annotations

from types import MethodType

import pytest

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_nomic_provider_uses_document_and_query_prefixes() -> None:
    provider = object.__new__(NomicLocalMultimodalProvider)
    calls: list[tuple[str, str]] = []

    def _stub_embed_prefixed_text(self, *, text: str, prefix: str) -> list[float]:
        calls.append((prefix, text))
        return [float(len(calls))]

    provider._embed_prefixed_text = MethodType(_stub_embed_prefixed_text, provider)

    assert provider.embed_document_text(text="documento") == [1.0]
    assert provider.embed_query_text(text="consulta") == [2.0]
    assert calls == [
        ("search_document", "documento"),
        ("search_query", "consulta"),
    ]

def test_embedding_service_routes_document_and_query_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    class _StubProvider:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def embed_document_text(self, *, text: str) -> list[float]:
            self.calls.append(("document", text))
            return [1.0]

        def embed_query_text(self, *, text: str) -> list[float]:
            self.calls.append(("query", text))
            return [2.0]

        def embed_image(self, *, image_path: Path, context_text: str = "") -> tuple[list[float], str]:
            raise AssertionError("image embeddings are not part of this unit test")

    stub_provider = _StubProvider()
    monkeypatch.setattr(
        "apps.backend.app.rag.embedding_service.get_nomic_local_provider",
        lambda: stub_provider,
    )
    service = EmbeddingService(_build_settings())

    assert service.embed_document_text(text="archivo") == [1.0]
    assert service.embed_query_text(text="pregunta") == [2.0]
    assert service.embed_text(text="otra pregunta", input_type="query") == [2.0]
    assert stub_provider.calls == [
        ("document", "archivo"),
        ("query", "pregunta"),
        ("query", "otra pregunta"),
    ]
