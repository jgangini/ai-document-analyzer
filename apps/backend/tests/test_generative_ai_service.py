from __future__ import annotations

from pydantic import BaseModel
import pytest

from apps.backend.app.core.config import get_settings
from apps.backend.app.integrations import generative_ai
from apps.backend.app.integrations.generative_ai import (
    OCIGenerativeAIService,
    OCIResolvedConfig,
)


class _DummyStructuredSchema(BaseModel):
    value: str


class _DummyMultimodalSchema(BaseModel):
    summary: str


def test_resolve_structured_output_method_prefers_json_schema_for_gemini() -> None:
    service = OCIGenerativeAIService(settings=get_settings())

    assert (
        service._resolve_structured_output_method(effective_model_id="google.gemini-2.5-flash")
        == "json_schema"
    )
    assert (
        service._resolve_structured_output_method(effective_model_id="cohere.command-r-plus")
        == "function_calling"
    )


def test_invoke_structured_uses_json_schema_for_gemini_without_raw_default_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: dict[str, int | str] = {}

    class _StubChain:
        def invoke(self, _prompt: str) -> dict[str, str]:
            records["chain_invocations"] = int(records.get("chain_invocations", 0)) + 1
            return {"value": "ok"}

    class _StubChat:
        def __init__(self, **_kwargs) -> None:
            pass

        def with_structured_output(self, _schema, *, method: str = "function_calling", **_kwargs):
            records["method"] = method
            return _StubChain()

        def invoke(self, *_args, **_kwargs):
            records["raw_invocations"] = int(records.get("raw_invocations", 0)) + 1
            return {"value": "raw"}

    monkeypatch.setattr(generative_ai, "ChatOCIGenAI", _StubChat)

    service = OCIGenerativeAIService(settings=get_settings())
    monkeypatch.setattr(
        service,
        "resolve_config",
        lambda: OCIResolvedConfig(
            compartment_id="compartment",
            model_id="google.gemini-2.5-flash",
            service_endpoint="https://example.invalid",
            auth_profile="DEFAULT",
        ),
    )
    monkeypatch.setattr(
        service,
        "_coerce_structured_result",
        lambda **_kwargs: {"value": "ok"},
    )

    result = service.invoke_structured(
        schema_model=_DummyStructuredSchema,
        prompt="Return a structured value.",
    )

    assert result == {"value": "ok"}
    assert records["method"] == "json_schema"
    assert records.get("raw_invocations", 0) == 0


def test_invoke_structured_raises_after_invalid_payload_without_raw_default_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: dict[str, int | str] = {}

    class _StubChain:
        def invoke(self, _prompt: str) -> dict[str, str]:
            records["chain_invocations"] = int(records.get("chain_invocations", 0)) + 1
            return {"value": "bad"}

    class _StubChat:
        def __init__(self, **_kwargs) -> None:
            pass

        def with_structured_output(self, _schema, *, method: str = "function_calling", **_kwargs):
            records["method"] = method
            return _StubChain()

        def invoke(self, *_args, **_kwargs):
            records["raw_invocations"] = int(records.get("raw_invocations", 0)) + 1
            return {"value": "raw"}

    monkeypatch.setattr(generative_ai, "ChatOCIGenAI", _StubChat)

    service = OCIGenerativeAIService(settings=get_settings())
    service.STRUCTURED_MAX_RETRIES = 2
    monkeypatch.setattr(
        service,
        "resolve_config",
        lambda: OCIResolvedConfig(
            compartment_id="compartment",
            model_id="google.gemini-2.5-flash",
            service_endpoint="https://example.invalid",
            auth_profile="DEFAULT",
        ),
    )

    def _raise_invalid_payload(**_kwargs):
        raise RuntimeError("Respuesta estructurada invalida desde LangChain OCI.")

    monkeypatch.setattr(service, "_coerce_structured_result", _raise_invalid_payload)

    with pytest.raises(RuntimeError, match="Respuesta estructurada invalida"):
        service.invoke_structured(
            schema_model=_DummyStructuredSchema,
            prompt="Return a structured value.",
        )

    assert records["method"] == "json_schema"
    assert records["chain_invocations"] == 2
    assert records.get("raw_invocations", 0) == 0


def test_invoke_multimodal_structured_uses_json_schema_without_raw_default_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    records: dict[str, int | str] = {}

    class _StubHumanMessage:
        def __init__(self, content) -> None:
            self.content = content

    class _StubChain:
        def invoke(self, _messages) -> dict[str, str]:
            records["chain_invocations"] = int(records.get("chain_invocations", 0)) + 1
            return {"summary": "ok"}

    class _StubChat:
        def __init__(self, **_kwargs) -> None:
            pass

        def with_structured_output(self, _schema, *, method: str = "function_calling", **_kwargs):
            records["method"] = method
            return _StubChain()

        def invoke(self, *_args, **_kwargs):
            records["raw_invocations"] = int(records.get("raw_invocations", 0)) + 1
            return {"summary": "raw"}

    monkeypatch.setattr(generative_ai, "ChatOCIGenAI", _StubChat)
    monkeypatch.setattr(generative_ai, "HumanMessage", _StubHumanMessage)

    service = OCIGenerativeAIService(settings=get_settings())
    monkeypatch.setattr(
        service,
        "resolve_config",
        lambda: OCIResolvedConfig(
            compartment_id="compartment",
            model_id="google.gemini-2.5-flash",
            service_endpoint="https://example.invalid",
            auth_profile="DEFAULT",
        ),
    )
    monkeypatch.setattr(
        service,
        "_coerce_structured_result",
        lambda **_kwargs: {"summary": "ok"},
    )

    result = service.invoke_multimodal_structured(
        schema_model=_DummyMultimodalSchema,
        prompt="Summarize the image.",
        image_data_uri="data:image/png;base64,AAA",
    )

    assert result == {"summary": "ok"}
    assert records["method"] == "json_schema"
    assert records.get("raw_invocations", 0) == 0
