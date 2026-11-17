"""Local multimodal embeddings backed by Nomic."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import RLock
from typing import Any
import warnings

from apps.backend.app.core.config import Settings

logger = logging.getLogger(__name__)

_NOMIC_LOCAL_PROVIDER: "NomicLocalMultimodalProvider | None" = None
_NOMIC_LOCAL_PROVIDER_LOCK = RLock()


class NomicLocalMultimodalProvider:
    TEXT_MODEL_ID = "nomic-ai/nomic-embed-text-v1.5"
    VISION_MODEL_ID = "nomic-ai/nomic-embed-vision-v1.5"

    def __init__(self) -> None:
        try:
            import torch
            import torch.nn.functional as F
            from PIL import Image
            from transformers import AutoImageProcessor, AutoModel, AutoTokenizer
        except Exception as exc:
            raise RuntimeError(
                "Local Nomic dependencies are not installed. "
                "Run: pip install torch transformers pillow"
            ) from exc

        self._torch = torch
        self._F = F
        self._Image = Image
        self._AutoTokenizer = AutoTokenizer
        self._AutoModel = AutoModel
        self._AutoImageProcessor = AutoImageProcessor
        self._inference_lock = RLock()

        # Reduce third-party noise during model bootstrap.
        logging.getLogger("transformers_modules.nomic-ai").setLevel(logging.ERROR)
        logging.getLogger("transformers_modules.nomic_ai").setLevel(logging.ERROR)

        # Project requirement: run embeddings locally on CPU.
        self._device = "cpu"
        self._text_tokenizer = self._AutoTokenizer.from_pretrained(self.TEXT_MODEL_ID, trust_remote_code=True)
        self._text_model = self._AutoModel.from_pretrained(self.TEXT_MODEL_ID, trust_remote_code=True).to(self._device)
        self._text_model.eval()
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore",
                message=r"Using a slow image processor as `use_fast` is unset.*",
            )
            self._image_processor = self._AutoImageProcessor.from_pretrained(
                self.VISION_MODEL_ID,
                use_fast=False,
            )
        self._image_model = self._AutoModel.from_pretrained(self.VISION_MODEL_ID, trust_remote_code=True).to(self._device)
        self._image_model.eval()

    def _normalize(self, vector: Any) -> Any:
        return self._F.normalize(vector, p=2, dim=-1)

    def _mean_pooling(self, last_hidden_state: Any, attention_mask: Any) -> Any:
        expanded = attention_mask.unsqueeze(-1).expand(last_hidden_state.size()).float()
        summed = self._torch.sum(last_hidden_state * expanded, dim=1)
        denom = self._torch.clamp(expanded.sum(dim=1), min=1e-9)
        return summed / denom

    def _embed_prefixed_text(self, *, text: str, prefix: str) -> list[float]:
        normalized_text = (text or "").strip()
        if not normalized_text:
            raise RuntimeError("Empty text provided for embedding.")
        prompt = f"{prefix}: {normalized_text}"
        inputs = self._text_tokenizer(
            [prompt],
            padding=True,
            truncation=True,
            max_length=8192,
            return_tensors="pt",
        )
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with self._inference_lock:
            with self._torch.inference_mode():
                outputs = self._text_model(**inputs)
                pooled = self._mean_pooling(outputs.last_hidden_state, inputs["attention_mask"])
                normalized = self._normalize(pooled)[0]
        return [float(value) for value in normalized.detach().cpu().tolist()]

    def embed_document_text(self, *, text: str) -> list[float]:
        # Nomic recommends document and query task prefixes for retrieval parity.
        return self._embed_prefixed_text(text=text, prefix="search_document")

    def embed_query_text(self, *, text: str) -> list[float]:
        return self._embed_prefixed_text(text=text, prefix="search_query")

    def embed_image(self, *, image_path: Path, context_text: str = "") -> tuple[list[float], str]:
        if not image_path.exists():
            raise RuntimeError(f"Imagen no encontrada para embedding: {image_path}")
        with self._Image.open(image_path) as image:
            rgb_image = image.convert("RGB")
            inputs = self._image_processor(images=rgb_image, return_tensors="pt")
        inputs = {key: value.to(self._device) for key, value in inputs.items()}
        with self._inference_lock:
            with self._torch.inference_mode():
                outputs = self._image_model(**inputs)
                if hasattr(outputs, "last_hidden_state") and outputs.last_hidden_state is not None:
                    pooled = outputs.last_hidden_state[:, 0]
                elif hasattr(outputs, "pooler_output") and outputs.pooler_output is not None:
                    pooled = outputs.pooler_output
                else:
                    raise RuntimeError("The Nomic model did not return a visual embedding.")
                normalized = self._normalize(pooled)[0]
        summary = (context_text or "").strip() or f"Visual embedding generated for {image_path.name}"
        return [float(value) for value in normalized.detach().cpu().tolist()], summary


def get_nomic_local_provider() -> NomicLocalMultimodalProvider:
    global _NOMIC_LOCAL_PROVIDER
    if _NOMIC_LOCAL_PROVIDER is None:
        with _NOMIC_LOCAL_PROVIDER_LOCK:
            if _NOMIC_LOCAL_PROVIDER is None:
                _NOMIC_LOCAL_PROVIDER = NomicLocalMultimodalProvider()
    return _NOMIC_LOCAL_PROVIDER


def reset_nomic_local_provider_cache() -> None:
    """Clear the process-wide Nomic provider cache for tests and setup resets."""

    global _NOMIC_LOCAL_PROVIDER
    with _NOMIC_LOCAL_PROVIDER_LOCK:
        _NOMIC_LOCAL_PROVIDER = None


class EmbeddingService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._provider: NomicLocalMultimodalProvider | None = None

    def _assert_provider(self) -> None:
        provider = (self.settings.embedding_provider or "").strip().lower()
        if provider != "nomic_local":
            raise RuntimeError(
                f"Unsupported embedding provider: {provider}. Expected 'nomic_local'."
            )

    def _get_provider(self) -> NomicLocalMultimodalProvider:
        if self._provider is None:
            logger.info("Initializing or reusing local Nomic embedding provider on CPU...")
            self._provider = get_nomic_local_provider()
        return self._provider

    def embed_text(self, *, text: str, input_type: str = "document") -> list[float]:
        self._assert_provider()
        normalized_type = str(input_type or "document").strip().lower()
        if normalized_type == "query":
            return self._get_provider().embed_query_text(text=text)
        return self._get_provider().embed_document_text(text=text)

    def embed_document_text(self, *, text: str) -> list[float]:
        return self.embed_text(text=text, input_type="document")

    def embed_query_text(self, *, text: str) -> list[float]:
        return self.embed_text(text=text, input_type="query")

    def embed_image(self, *, image_path: Path, context_text: str = "") -> tuple[list[float], str]:
        self._assert_provider()
        return self._get_provider().embed_image(image_path=image_path, context_text=context_text)
