from __future__ import annotations

from apps.backend.app.api.routes import settings as settings_route


def test_default_payload_omits_retired_file_types_block() -> None:
    payload = settings_route._default_payload()

    assert "file_types" not in payload
    assert payload["rag"]["retrieval.doc_shortlist_scoped"] == 12
    assert payload["app"]["name"] == "AI Document Analyzer"
    assert payload["app"]["agent_name"] == "Nadia Assist"


def test_build_payload_ignores_retired_keys(monkeypatch) -> None:
    class _StubConfigService:
        def list_grouped(self) -> dict[str, list[dict[str, str]]]:
            return {
                "rag": [
                    {"key": "rag.retrieval.doc_shortlist_scoped", "value": "7"},
                    {"key": "rag.retrieval.rerank_max_pool", "value": "99"},
                ],
                "app": [
                    {"key": "app.name", "value": "Test App"},
                    {"key": "app.agent_name", "value": "Test Agent"},
                    {"key": "app.avatar_url", "value": "/should-not-survive"},
                ],
            }

    monkeypatch.setattr(settings_route, "_resolve_avatar_file", lambda: None)

    payload = settings_route._build_payload(_StubConfigService())

    assert "file_types" not in payload
    assert payload["rag"]["retrieval.doc_shortlist_scoped"] == 7
    assert "retrieval.rerank_max_pool" not in payload["rag"]
    assert payload["app"]["name"] == "Test App"
    assert payload["app"]["agent_name"] == "Test Agent"
    assert payload["app"]["avatar_url"] == ""


def test_build_payload_keeps_configured_application_name(monkeypatch) -> None:
    class _StubConfigService:
        def list_grouped(self) -> dict[str, list[dict[str, str]]]:
            return {
                "app": [
                    {"key": "app.name", "value": "Nadia Assist"},
                ],
            }

    monkeypatch.setattr(settings_route, "_resolve_avatar_file", lambda: None)

    payload = settings_route._build_payload(_StubConfigService())

    assert payload["app"]["name"] == "Nadia Assist"
    assert payload["app"]["agent_name"] == "Nadia Assist"
