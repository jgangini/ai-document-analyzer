"""Rerank local ONNX como unica estrategia permitida."""

from __future__ import annotations

import logging
from pathlib import Path
from threading import Lock

from huggingface_hub import snapshot_download
import numpy as np
from onnxruntime import InferenceSession
from tokenizers import Tokenizer

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.core.config import Settings

logger = logging.getLogger(__name__)


class HybridLocalOnnxRerankService:
    MODEL_ID = "jinaai/jina-reranker-v2-base-multilingual"
    MODEL_DIRNAME = "jina-reranker-v2-base-multilingual"
    MAX_SEQUENCE_LENGTH = 512
    _download_lock = Lock()

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._tokenizer: Tokenizer | None = None
        self._session: InferenceSession | None = None
        self._onnx_model_path: Path | None = None

    @property
    def model_dir(self) -> Path:
        return self.settings.data_dir / "models" / self.MODEL_DIRNAME

    def is_ready(self) -> bool:
        return self._find_onnx_model_path() is not None

    def ensure_available(self) -> None:
        if self._session is not None and self._tokenizer is not None:
            return
        with self._download_lock:
            if self._session is not None and self._tokenizer is not None:
                return
            self.model_dir.mkdir(parents=True, exist_ok=True)
            onnx_model_path = self._find_onnx_model_path()
            if onnx_model_path is None:
                logger.info("Downloading local ONNX reranker model to %s", self.model_dir)
                try:
                    snapshot_download(
                        repo_id=self.MODEL_ID,
                        local_dir=str(self.model_dir),
                        allow_patterns=[
                            "*.json",
                            "*.txt",
                            "*.model",
                            "tokenizer.*",
                            "special_tokens_map.json",
                            "config.json",
                            "onnx/*",
                        ],
                    )
                except Exception as exc:
                    raise RuntimeError("No fue posible descargar el modelo local ONNX de rerank.") from exc
                onnx_model_path = self._find_onnx_model_path()
            if onnx_model_path is None:
                raise RuntimeError("No se encontro un archivo ONNX valido para el reranker local.")
            try:
                logger.info("Initializing local ONNX reranker from %s", onnx_model_path)
                self._tokenizer = self._load_tokenizer()
                self._session = InferenceSession(str(onnx_model_path), providers=["CPUExecutionProvider"])
                self._onnx_model_path = onnx_model_path
                self._predict_scores([("warmup", "warmup")])
                logger.info("Local ONNX reranker is ready.")
            except Exception as exc:
                raise RuntimeError("No fue posible inicializar el reranker local ONNX.") from exc

    def rerank(self, *, question: str, evidence: list[EvidenceItem], top_k: int) -> list[EvidenceItem]:
        if not evidence:
            return []
        self.ensure_available()
        pairs = [(question, self._build_document(item)) for item in evidence]
        scores = self._predict_scores(pairs)
        ranked_pairs = sorted(
            zip(evidence, scores, strict=False),
            key=lambda item: item[1],
            reverse=True,
        )
        return [
            evidence_item.model_copy(update={"source_number": index, "score": float(score)})
            for index, (evidence_item, score) in enumerate(ranked_pairs[:top_k], start=1)
        ]

    def _find_onnx_model_path(self) -> Path | None:
        preferred = sorted(self.model_dir.glob("onnx/*.onnx"))
        if preferred:
            return preferred[0]
        root_files = sorted(self.model_dir.glob("*.onnx"))
        if root_files:
            return root_files[0]
        return None

    @staticmethod
    def _build_document(item: EvidenceItem) -> str:
        header_parts = [
            f"file={item.file_name}",
            f"page={item.page_number}",
        ]
        if item.file_code:
            header_parts.append(f"file_code={item.file_code}")
        if item.text_score is not None:
            header_parts.append(f"text_score={item.text_score:.4f}")
        if item.image_score is not None:
            header_parts.append(f"image_score={item.image_score:.4f}")
        if item.lexical_score is not None:
            header_parts.append(f"lexical_score={item.lexical_score:.4f}")
        header = " ".join(header_parts)
        body = (item.summary_text or "").strip()
        return f"{header}\n{body}".strip()

    def _predict_scores(self, pairs: list[tuple[str, str]]) -> list[float]:
        if self._session is None or self._tokenizer is None:
            raise RuntimeError("Reranker local ONNX no inicializado.")
        encoded = self._encode_pairs(pairs)
        required_inputs = {item.name for item in self._session.get_inputs()}
        feeds = {}
        for key, value in encoded.items():
            if key not in required_inputs:
                continue
            feeds[key] = value.astype("int64", copy=False)
        raw_output = self._session.run(None, feeds)[0]
        if getattr(raw_output, "ndim", 1) == 2:
            if raw_output.shape[1] == 1:
                return [float(item) for item in raw_output[:, 0].tolist()]
            return [float(item) for item in raw_output[:, -1].tolist()]
        return [float(item) for item in raw_output.tolist()]

    def _load_tokenizer(self) -> Tokenizer:
        tokenizer_path = self.model_dir / "tokenizer.json"
        if not tokenizer_path.exists():
            raise RuntimeError("No se encontro tokenizer.json para el reranker local ONNX.")
        tokenizer = Tokenizer.from_file(str(tokenizer_path))
        tokenizer.enable_truncation(max_length=self.MAX_SEQUENCE_LENGTH)
        pad_id = tokenizer.token_to_id("<pad>")
        tokenizer.enable_padding(
            pad_id=int(pad_id if pad_id is not None else 0),
            pad_token="<pad>",
        )
        return tokenizer

    def _encode_pairs(self, pairs: list[tuple[str, str]]) -> dict[str, np.ndarray]:
        assert self._tokenizer is not None
        encodings = self._tokenizer.encode_batch(pairs)
        return {
            "input_ids": np.asarray([item.ids for item in encodings], dtype=np.int64),
            "attention_mask": np.asarray([item.attention_mask for item in encodings], dtype=np.int64),
            "token_type_ids": np.asarray([item.type_ids for item in encodings], dtype=np.int64),
        }
