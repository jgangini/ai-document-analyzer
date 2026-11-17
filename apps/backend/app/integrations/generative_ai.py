"""Proveedor OCI nativo para LangChain (chat, multimodal y embeddings)."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
import time
from typing import Any

from pydantic import BaseModel  # type: ignore[reportMissingImports]

from apps.backend.app.core.config import Settings
from apps.backend.app.services.runtime_config_service import ConfigService
from langchain_core.messages import HumanMessage  # type: ignore[reportMissingImports]
from langchain_oci import ChatOCIGenAI  # type: ignore[reportMissingImports]

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class OCIResolvedConfig:
    compartment_id: str
    model_id: str
    service_endpoint: str
    auth_profile: str


class OCIGenerativeAIService:
    """Capa de acceso unificada a LangChain OCI."""
    MULTIMODAL_STRUCTURED_MAX_RETRIES = 3
    MULTIMODAL_TEXT_MAX_RETRIES = 2
    STRUCTURED_MAX_RETRIES = 3
    TEXT_MAX_RETRIES = 2

    def __init__(self, *, settings: Settings, config_service: ConfigService | None = None) -> None:
        self.settings = settings
        self.config_service = config_service

    def is_available(self) -> bool:
        resolved = self.resolve_config()
        return bool(
            self.settings.oci_config_file.exists()
            and resolved.compartment_id
            and resolved.model_id
            and not self._is_embedding_model_id(resolved.model_id)
        )

    def _auth_file_location(self) -> str:
        return str(self.settings.oci_config_file)

    def resolve_config(self) -> OCIResolvedConfig:
        compartment_id = (
            self.config_service.get_oci_compartment_id().strip()
            if self.config_service is not None
            else ""
        )
        model_id = (
            self.config_service.get_genai_model(default=self.settings.oci_genai_model).strip()
            if self.config_service is not None
            else self.settings.oci_genai_model
        )
        service_endpoint = (
            self.config_service.get_genai_inference_url().strip()
            if self.config_service is not None
            else ""
        )
        return OCIResolvedConfig(
            compartment_id=compartment_id,
            model_id=model_id,
            service_endpoint=service_endpoint,
            auth_profile=self.settings.oci_profile,
        )

    @staticmethod
    def _is_embedding_model_id(model_id: str) -> bool:
        normalized = str(model_id or "").strip().lower()
        if not normalized:
            return False
        # Bloquea modelos de embedding usados por error en flujo de chat.
        embedding_markers = ("nomic-embed", "embedding", ".embed", "-embed", "_embed", " embed ")
        return any(marker in normalized for marker in embedding_markers)

    def _resolve_chat_model_id(
        self,
        *,
        requested_model_id: str | None,
        resolved_model_id: str,
    ) -> str:
        candidate = str(requested_model_id or resolved_model_id or "").strip()
        if not candidate:
            raise RuntimeError(
                "Configuracion invalida: falta `genai.model` para chat/synthesis en OCI."
            )
        if not self._is_embedding_model_id(candidate):
            return candidate

        raise RuntimeError(
            "Configuracion invalida: `genai.model` apunta a un modelo de embedding "
            f"('{candidate}'). Debe ser un modelo generativo de chat; "
            "los embeddings del proyecto son Nomic local CPU (`nomic_local`)."
        )

    @staticmethod
    def _resolve_structured_output_method(*, effective_model_id: str) -> str:
        normalized = str(effective_model_id or "").strip().lower()
        # LangChain OCI documents the default `function_calling` path as unreliable for
        # Gemini structured outputs; prefer `json_schema` to keep the schema contract strict
        # without falling back to raw free-form chat.
        if "gemini" in normalized or normalized.startswith("google."):
            return "json_schema"
        return "function_calling"

    def invoke_structured(
        self,
        *,
        schema_model: type[BaseModel],
        prompt: str,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        if ChatOCIGenAI is None:
            raise RuntimeError("langchain-oci no esta instalado.")
        resolved = self.resolve_config()
        effective_model_id = self._resolve_chat_model_id(
            requested_model_id=model_id,
            resolved_model_id=resolved.model_id,
        )
        llm = ChatOCIGenAI(
            model_id=effective_model_id,
            service_endpoint=resolved.service_endpoint or None,
            compartment_id=resolved.compartment_id,
            auth_type="API_KEY",
            auth_profile=resolved.auth_profile,
            auth_file_location=self._auth_file_location(),
        )
        structured_method = self._resolve_structured_output_method(
            effective_model_id=effective_model_id,
        )
        chain = llm.with_structured_output(
            schema_model,
            method=structured_method,
        )
        max_retries = max(1, int(self.STRUCTURED_MAX_RETRIES))
        last_invalid_payload_error: RuntimeError | None = None

        for attempt in range(1, max_retries + 1):
            try:
                result = chain.invoke(prompt)
            except Exception as exc:
                raise RuntimeError(
                    self._build_runtime_error_message(
                        operation="structured chat",
                        exc=exc,
                        model_id=effective_model_id,
                        endpoint=(resolved.service_endpoint or ""),
                    )
                ) from exc

            try:
                return self._coerce_structured_result(
                    schema_model=schema_model,
                    result=result,
                    operation="structured chat",
                )
            except RuntimeError as exc:
                is_invalid_payload = "Respuesta estructurada invalida desde LangChain OCI" in str(exc)
                if not is_invalid_payload or attempt >= max_retries:
                    if not is_invalid_payload:
                        raise
                    last_invalid_payload_error = exc
                    break
                last_invalid_payload_error = exc
                logger.warning(
                    "OCI structured output invalido con method=%s (attempt %s/%s). Reintentando.",
                    structured_method,
                    attempt,
                    max_retries,
                )
                time.sleep(0.30 * attempt)

        if last_invalid_payload_error is not None:
            raise last_invalid_payload_error

        raise RuntimeError(
            f"OCI structured chat failed after retries using method={structured_method}."
        )

    def invoke_multimodal_structured(
        self,
        *,
        schema_model: type[BaseModel],
        prompt: str,
        image_data_uri: str,
        model_id: str | None = None,
    ) -> dict[str, Any]:
        if ChatOCIGenAI is None or HumanMessage is None:
            raise RuntimeError("langchain-oci no esta instalado.")
        resolved = self.resolve_config()
        effective_model_id = self._resolve_chat_model_id(
            requested_model_id=model_id,
            resolved_model_id=resolved.model_id,
        )
        llm = ChatOCIGenAI(
            model_id=effective_model_id,
            service_endpoint=resolved.service_endpoint or None,
            compartment_id=resolved.compartment_id,
            auth_type="API_KEY",
            auth_profile=resolved.auth_profile,
            auth_file_location=self._auth_file_location(),
        )
        structured_method = self._resolve_structured_output_method(
            effective_model_id=effective_model_id,
        )
        chain = llm.with_structured_output(
            schema_model,
            method=structured_method,
        )
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_uri}},
            ]
        )
        max_retries = max(1, int(self.MULTIMODAL_STRUCTURED_MAX_RETRIES))
        last_invalid_payload_error: RuntimeError | None = None
        for attempt in range(1, max_retries + 1):
            try:
                result = chain.invoke([message])
            except Exception as exc:
                raise RuntimeError(
                    self._build_runtime_error_message(
                        operation="multimodal structured chat",
                        exc=exc,
                        model_id=effective_model_id,
                        endpoint=(resolved.service_endpoint or ""),
                    )
                ) from exc

            try:
                return self._coerce_structured_result(
                    schema_model=schema_model,
                    result=result,
                    operation="multimodal structured chat",
                )
            except RuntimeError as exc:
                is_invalid_payload = "Respuesta estructurada invalida desde LangChain OCI" in str(exc)
                if not is_invalid_payload or attempt >= max_retries:
                    if not is_invalid_payload:
                        raise
                    last_invalid_payload_error = exc
                    break
                last_invalid_payload_error = exc
                logger.warning(
                    "OCI multimodal structured output invalido con method=%s (attempt %s/%s). Reintentando.",
                    structured_method,
                    attempt,
                    max_retries,
                )
                time.sleep(0.35 * attempt)

        if last_invalid_payload_error is not None:
            raise last_invalid_payload_error

        raise RuntimeError(
            f"OCI multimodal structured chat failed after retries using method={structured_method}."
        )

    def invoke_multimodal_text(
        self,
        *,
        prompt: str,
        image_data_uri: str,
        model_id: str | None = None,
    ) -> str:
        if ChatOCIGenAI is None or HumanMessage is None:
            raise RuntimeError("langchain-oci no esta instalado.")
        resolved = self.resolve_config()
        effective_model_id = self._resolve_chat_model_id(
            requested_model_id=model_id,
            resolved_model_id=resolved.model_id,
        )
        llm = ChatOCIGenAI(
            model_id=effective_model_id,
            service_endpoint=resolved.service_endpoint or None,
            compartment_id=resolved.compartment_id,
            auth_type="API_KEY",
            auth_profile=resolved.auth_profile,
            auth_file_location=self._auth_file_location(),
        )
        message = HumanMessage(
            content=[
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_uri}},
            ]
        )
        max_retries = max(1, int(self.MULTIMODAL_TEXT_MAX_RETRIES))
        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                result = llm.invoke([message])
                text = self._extract_text_content(result).strip()
                if text:
                    return text
                raise RuntimeError("Respuesta vacia desde multimodal raw chat.")
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                logger.warning(
                    "OCI multimodal raw chat retorno error/vacio (attempt %s/%s). Reintentando.",
                    attempt,
                    max_retries,
                )
                time.sleep(0.3 * attempt)

        if last_error is None:
            raise RuntimeError("OCI multimodal raw chat failed without error details.")
        if isinstance(last_error, RuntimeError):
            raise last_error
        raise RuntimeError(
            self._build_runtime_error_message(
                operation="multimodal raw chat",
                exc=last_error,
                model_id=effective_model_id,
                endpoint=(resolved.service_endpoint or ""),
            )
        ) from last_error

    def invoke_text(
        self,
        *,
        prompt: str,
        model_id: str | None = None,
    ) -> str:
        if ChatOCIGenAI is None:
            raise RuntimeError("langchain-oci no esta instalado.")
        resolved = self.resolve_config()
        effective_model_id = self._resolve_chat_model_id(
            requested_model_id=model_id,
            resolved_model_id=resolved.model_id,
        )
        llm = ChatOCIGenAI(
            model_id=effective_model_id,
            service_endpoint=resolved.service_endpoint or None,
            compartment_id=resolved.compartment_id,
            auth_type="API_KEY",
            auth_profile=resolved.auth_profile,
            auth_file_location=self._auth_file_location(),
        )
        max_retries = max(1, int(self.TEXT_MAX_RETRIES))
        last_error: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                result = llm.invoke(prompt)
                text = self._extract_text_content(result).strip()
                if text:
                    return text
                raise RuntimeError("Respuesta vacia desde chat raw.")
            except Exception as exc:
                last_error = exc
                if attempt >= max_retries:
                    break
                logger.warning(
                    "OCI raw chat retorno error/vacio (attempt %s/%s). Reintentando.",
                    attempt,
                    max_retries,
                )
                time.sleep(0.3 * attempt)

        if last_error is None:
            raise RuntimeError("OCI raw chat failed without error details.")
        if isinstance(last_error, RuntimeError):
            raise last_error
        raise RuntimeError(
            self._build_runtime_error_message(
                operation="raw chat",
                exc=last_error,
                model_id=effective_model_id,
                endpoint=(resolved.service_endpoint or ""),
            )
        ) from last_error

    @staticmethod
    def _extract_json_candidates(raw_text: str) -> list[str]:
        text = str(raw_text or "").strip()
        if not text:
            return []
        candidates: list[str] = [text]
        fenced_blocks = re.findall(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
        candidates.extend(block.strip() for block in fenced_blocks if block.strip())
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            candidates.append(text[start : end + 1].strip())
        # Preserve order while removing duplicates.
        unique: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            unique.append(candidate)
        return unique

    @classmethod
    def _parse_json_like(cls, raw_value: Any) -> Any | None:
        if raw_value is None:
            return None
        if isinstance(raw_value, (dict, list)):
            return raw_value
        if not isinstance(raw_value, str):
            return None
        for candidate in cls._extract_json_candidates(raw_value):
            try:
                return json.loads(candidate)
            except Exception:
                continue
        return None

    @classmethod
    def _coerce_structured_result(
        cls,
        *,
        schema_model: type[BaseModel],
        result: Any,
        operation: str,
    ) -> dict[str, Any]:
        candidates: list[Any] = []

        def add_candidate(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, BaseModel):
                candidates.append(value.model_dump())
                return
            parsed_json = cls._parse_json_like(value)
            if parsed_json is not None:
                candidates.append(parsed_json)
                return
            candidates.append(value)

        add_candidate(result)

        additional_kwargs = getattr(result, "additional_kwargs", None)
        if isinstance(additional_kwargs, dict):
            add_candidate(additional_kwargs.get("parsed"))
            function_call = additional_kwargs.get("function_call")
            if isinstance(function_call, dict):
                add_candidate(function_call.get("arguments"))
            tool_calls = additional_kwargs.get("tool_calls")
            if isinstance(tool_calls, list):
                for call in tool_calls:
                    if not isinstance(call, dict):
                        continue
                    function_payload = call.get("function")
                    if isinstance(function_payload, dict):
                        add_candidate(function_payload.get("arguments"))
            add_candidate(additional_kwargs.get("response"))

        tool_calls_attr = getattr(result, "tool_calls", None)
        if isinstance(tool_calls_attr, list):
            for call in tool_calls_attr:
                if not isinstance(call, dict):
                    continue
                args = call.get("args")
                if args is not None:
                    add_candidate(args)
                function_payload = call.get("function")
                if isinstance(function_payload, dict):
                    add_candidate(function_payload.get("arguments"))

        content = getattr(result, "content", None)
        if isinstance(content, str):
            add_candidate(content)
        elif isinstance(content, list):
            for block in content:
                if isinstance(block, dict):
                    add_candidate(block.get("text"))
                    add_candidate(block.get("input"))

        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            try:
                validated = schema_model.model_validate(candidate)
                return validated.model_dump()
            except Exception:
                continue

        result_type = type(result).__name__
        preview = str(result)
        preview = " ".join(preview.split())
        preview = preview[:280]
        logger.error(
            "OCI %s returned invalid structured payload. type=%s preview=%s",
            operation,
            result_type,
            preview,
        )
        raise RuntimeError(
            "Respuesta estructurada invalida desde LangChain OCI. "
            f"Formato recibido: {result_type}."
        )

    @staticmethod
    def _extract_text_content(result: Any) -> str:
        if result is None:
            return ""
        content = getattr(result, "content", None)
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            chunks: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    text = block.get("text")
                    if isinstance(text, str) and text.strip():
                        chunks.append(text)
            if chunks:
                return "\n".join(chunks)
        if isinstance(result, str):
            return result
        return str(result)

    @staticmethod
    def _schema_json_compact(schema_model: type[BaseModel]) -> str:
        try:
            schema = schema_model.model_json_schema()
            return json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
        except Exception:
            return "{}"

    @staticmethod
    def _build_runtime_error_message(
        *,
        operation: str,
        exc: Exception,
        model_id: str,
        endpoint: str,
    ) -> str:
        status = getattr(exc, "status", None)
        code = getattr(exc, "code", None)
        provider_message = str(getattr(exc, "message", "")) or str(exc)
        compact_message = " ".join(provider_message.split())

        if status in {401, 403, 404}:
            logger.warning(
                "OCI GenAI %s failed (status=%s, code=%s, model=%s): %s",
                operation,
                status,
                code,
                model_id,
                compact_message,
            )
            return (
                f"OCI Generative AI {operation} failed with status {status} ({code or 'n/a'}). "
                f"Model '{model_id}' is unauthorized or not found for the configured compartment/endpoint. "
                f"Endpoint: {endpoint or 'default OCI endpoint'}. "
                "Valida `genai.model`, `oci.compartment_id` y permisos IAM."
            )

        return (
            f"OCI Generative AI {operation} failed: "
            f"{compact_message[:320]}"
        )
