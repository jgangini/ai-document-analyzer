from __future__ import annotations

from functools import lru_cache
from importlib import import_module
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict  # type: ignore[import-untyped]

BACKEND_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Compatibilidad con codigo actual (DatabaseManager / security.py)
    ADB_USER: str = ""
    ADB_PASSWORD: str = ""
    ADB_DSN: str = ""
    ADB_WALLET_DIR: str = str(BACKEND_ROOT / "wallet")
    ADB_WALLET_PASSWORD: str = ""
    ADB_POOL_MIN: int = 1
    ADB_POOL_MAX: int = 10
    ADB_POOL_INCREMENT: int = 1
    DB_RUNTIME_CONFIG_PATH: str = "data/runtime/db_connection.json"

    SECRET_KEY: str = "your-secret-key-change-in-production-use-openssl-rand"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # Runtime general
    APP_NAME: str = "AI Document Analyzer"
    API_PREFIX: str = "/api"
    LOG_LEVEL: str = "INFO"
    TRACE: bool = False
    # OCI / GenAI / OCR / Rerank / Embeddings
    OCI_CONFIG_PATH: str = "keys/config"

    EMBEDDING_DIMENSION: int = 768
    ANSWER_MAX_EVIDENCE: int = 3
    VISUAL_ANALYSIS_TOP_K: int = 2

    # Directorios runtime
    DOCS_SOURCE_DIR: str = "data/docs"
    STAGING_DIR: str = "data/staging"
    EXTRACTED_DIR: str = "data/extracted"
    PAGE_IMAGE_DIR: str = "data/page_images"
    UPLOAD_DIR: str = "data/uploads"
    USER_RUNTIME_SCOPE: str = "global"

    @model_validator(mode="before")
    @classmethod
    def _normalize_input_keys(cls, data):
        if not isinstance(data, dict):
            return data
        field_names = set(cls.model_fields.keys())
        normalized = {}
        for key, value in data.items():
            # Claves internas de BaseSettings (_env_file, etc.) no deben pasar al modelo.
            if key.startswith("_"):
                continue
            if key in field_names:
                normalized[key] = value
                continue
            upper_key = key.upper()
            if upper_key in field_names:
                normalized[upper_key] = value
            else:
                normalized[key] = value
        return normalized

    def __init__(self, **values):
        """When `_env_file=None` is explicit, force defaults/init values only."""
        if values.get("_env_file", object()) is None and "_env_prefix" not in values:
            values["_env_prefix"] = "__defaults_only__"
        super().__init__(**values)

    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def app_name(self) -> str:
        return self.APP_NAME

    @property
    def api_prefix(self) -> str:
        return self.API_PREFIX

    @property
    def database_backend(self) -> str:
        return "oracle"

    @property
    def wallet_dir(self) -> Path:
        wallet_path = Path(self.ADB_WALLET_DIR)
        if wallet_path.is_absolute():
            return wallet_path
        return BACKEND_ROOT / wallet_path

    @property
    def runtime_db_config_path(self) -> Path:
        runtime_path = Path(self.DB_RUNTIME_CONFIG_PATH)
        if runtime_path.is_absolute():
            return runtime_path
        return BACKEND_ROOT / runtime_path

    @property
    def root_dir(self) -> Path:
        return BACKEND_ROOT

    @property
    def keys_dir(self) -> Path:
        return BACKEND_ROOT / "keys"

    @property
    def logs_dir(self) -> Path:
        return BACKEND_ROOT / "logs"

    @property
    def data_dir(self) -> Path:
        return BACKEND_ROOT / "data"

    @property
    def trace_log_path(self) -> Path:
        return self.logs_dir / "runtime_trace.jsonl"

    @property
    def oci_profile(self) -> str:
        return "DEFAULT"

    @property
    def oci_config_file(self) -> Path:
        return BACKEND_ROOT / self.OCI_CONFIG_PATH

    @property
    def docs_dir(self) -> Path:
        return BACKEND_ROOT / self.DOCS_SOURCE_DIR

    @property
    def staging_path(self) -> Path:
        return BACKEND_ROOT / self.STAGING_DIR

    @property
    def extracted_path(self) -> Path:
        return BACKEND_ROOT / self.EXTRACTED_DIR

    @property
    def page_image_path(self) -> Path:
        return BACKEND_ROOT / self.PAGE_IMAGE_DIR

    @property
    def upload_path(self) -> Path:
        return BACKEND_ROOT / self.UPLOAD_DIR

    @property
    def user_runtime_scope(self) -> str:
        value = str(self.USER_RUNTIME_SCOPE or "global").strip().lower()
        return value or "global"

    @property
    def user_data_root(self) -> Path:
        return self.data_dir / "users" / self.user_runtime_scope

    def _runtime_config_int(self, key: str, default_value: int) -> int:
        try:
            DatabaseManager = getattr(import_module("apps.backend.app.core.database"), "DatabaseManager")
            ConfigService = getattr(
                import_module("apps.backend.app.services.runtime_config_service"),
                "ConfigService",
            )

            raw_value = ConfigService(DatabaseManager.get_instance(self)).get_value(
                key,
                str(default_value),
            ).strip()
            return int(raw_value)
        except Exception:
            return int(default_value)

    @property
    def oci_genai_compartment_id(self) -> str:
        return ""

    @property
    def oci_genai_endpoint(self) -> str:
        return ""

    @property
    def oci_genai_model(self) -> str:
        return "google.gemini-2.5-flash"

    @property
    def document_understanding_live_enabled(self) -> bool:
        # Retained for API compatibility; OCR is handled locally by Docling.
        return False

    @property
    def document_understanding_language(self) -> str:
        # El idioma operativo de OCR viene desde frontend por request.
        return "es"

    @property
    def document_understanding_provider(self) -> str:
        # Docling orchestrates OCR/layout/table extraction locally.
        return "docling_rapidocr"

    @property
    def embedding_model_name(self) -> str:
        # Mandatorio: embeddings siempre con Nomic local multimodal.
        return "nomic-local-multimodal"

    @property
    def embedding_dimension(self) -> int:
        resolved = self._runtime_config_int("embedding.dimension", self.EMBEDDING_DIMENSION)
        return max(1, resolved)

    @property
    def embedding_live_enabled(self) -> bool:
        # Mandatorio: embeddings reales siempre habilitados.
        return True

    @property
    def embedding_provider(self) -> str:
        # Mandatorio: proveedor local Nomic en el proyecto.
        return "nomic_local"

    @property
    def rerank_provider(self) -> str:
        # Mandatorio: reranker siempre ONNX local.
        return "hybrid_local_onnx"

    @property
    def answer_max_evidence(self) -> int:
        resolved = self._runtime_config_int(
            "embedding.answer_max_evidence",
            self.ANSWER_MAX_EVIDENCE,
        )
        return max(1, resolved)

    @property
    def visual_analysis_top_k(self) -> int:
        resolved = self._runtime_config_int(
            "embedding.visual_analysis_top_k",
            self.VISUAL_ANALYSIS_TOP_K,
        )
        return max(1, resolved)

    @property
    def visual_verifier_provider(self) -> str:
        # Mandatorio: verificador visual siempre OCI.
        return "oci"

    @property
    def oci_genai_is_configured(self) -> bool:
        return bool(self.oci_config_file.exists())

    @property
    def ora26ai_tns_alias(self) -> str:
        return self.ADB_DSN

    @property
    def ora26ai_wallet_password(self) -> str:
        return self.ADB_WALLET_PASSWORD

    def ensure_runtime_directories(self) -> None:
        for path in (
            self.wallet_dir,
            self.keys_dir,
            self.logs_dir,
            self.data_dir,
            self.runtime_db_config_path.parent,
            self.oci_config_file.parent,
            self.docs_dir,
            self.staging_path,
            self.extracted_path,
            self.page_image_path,
            self.upload_path,
            self.user_data_root / "uploads",
            self.user_data_root / "staging",
            self.user_data_root / "extracted",
            self.user_data_root / "page_images",
            self.user_data_root / "ocr_json",
        ):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings(_env_file=BACKEND_ROOT / ".env")
    settings.ensure_runtime_directories()
    return settings
