from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from apps.backend.app.api.setup_guard import require_setup_completed
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.security import get_current_user
from apps.backend.app.core.session import get_db_manager
from apps.backend.app.services.runtime_config_service import ConfigService
from apps.backend.app.services.bootstrap_service import SetupService

router = APIRouter(
    prefix="/settings",
    tags=["settings"],
    dependencies=[Depends(require_setup_completed)],
)


class SettingsUpdateRequest(BaseModel):
    updates: dict[str, Any] = Field(default_factory=dict)


def get_config_service() -> ConfigService:
    return ConfigService(get_db_manager())


def get_setup_service() -> SetupService:
    return SetupService(get_db_manager())


def _to_scalar(value: Any) -> Any:
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"true", "false"}:
            return lower == "true"
        if lower.isdigit():
            try:
                return int(lower)
            except Exception:
                return value
    return value


_AVATAR_ALLOWED_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
}
_AVATAR_MAX_BYTES = 2 * 1024 * 1024
_DYNAMIC_APP_FIELDS = {"avatar_url", "avatar_updated_at"}
_HIDDEN_CONFIG_CATEGORIES: set[str] = set()
_RETIRED_CONFIG_KEYS = {
    "rag.retrieval.rerank_max_pool",
}
DEFAULT_APP_NAME = "AI Document Analyzer"
DEFAULT_AGENT_NAME = "Nadia Assist"


def _avatar_dir() -> Path:
    settings = get_settings()
    path = settings.data_dir / "runtime" / "agent"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _avatar_candidates() -> list[Path]:
    directory = _avatar_dir()
    return [
        directory / "avatar.png",
        directory / "avatar.jpg",
        directory / "avatar.jpeg",
        directory / "avatar.gif",
    ]


def _resolve_avatar_file() -> Path | None:
    for candidate in _avatar_candidates():
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _avatar_url(path: Path | None = None) -> str:
    avatar_path = path or _resolve_avatar_file()
    if avatar_path is None:
        return ""
    version = int(avatar_path.stat().st_mtime)
    return f"/api/settings/agent-avatar?v={version}"


def _default_payload() -> dict[str, Any]:
    return {
        "rag": {
            "ingest.max_parallel_jobs": 2,
            "ingest.max_parallel_documents": 3,
            "ingest.native_text_min_chars": 160,
            "ingest.visual_enrichment_enabled": False,
            "ingest.structured_facts_enabled": False,
            "retrieval.doc_shortlist_scoped": 12,
            "retrieval.doc_shortlist_global": 20,
            "retrieval.page_pool_scoped": 36,
            "retrieval.page_pool_global": 60,
            "retrieval.rerank_scoped": 24,
            "retrieval.rerank_global": 32,
            "retrieval.max_candidates": 2000,
            "retrieval.max_mmr_pool": 1200,
        },
        "app": {
            "name": DEFAULT_APP_NAME,
            "agent_name": DEFAULT_AGENT_NAME,
            "session_timeout_minutes": 480,
            "timezone": "America/Lima",
            "language": "es",
            "avatar_url": "",
            "avatar_updated_at": 0,
        },
        "embedding": {
            "dimension": 768,
            "answer_max_evidence": 3,
            "visual_analysis_top_k": 2,
        },
    }


def _build_payload(service: ConfigService) -> dict[str, Any]:
    payload = _default_payload()
    seen_keys: set[str] = set()
    groups = service.list_grouped()
    for items in groups.values():
        for item in items:
            key = str(item.get("key") or "")
            seen_keys.add(key)
            value = _to_scalar(item.get("value"))
            if key in _RETIRED_CONFIG_KEYS:
                continue
            if "." not in key:
                continue
            category, field = key.split(".", 1)
            if not category or not field:
                continue
            if category in _HIDDEN_CONFIG_CATEGORIES:
                continue
            if category == "app" and field in _DYNAMIC_APP_FIELDS:
                continue
            payload.setdefault(category, {})
            payload[category][field] = value
    avatar_path = _resolve_avatar_file()
    payload.setdefault("app", {})
    payload["app"]["avatar_url"] = _avatar_url(avatar_path)
    payload["app"]["avatar_updated_at"] = int(avatar_path.stat().st_mtime) if avatar_path else 0
    return payload


@router.get("")
def get_settings_payload(current_user: dict = Depends(get_current_user)) -> dict:
    del current_user
    service = get_config_service()
    if not service.table_exists():
        return _default_payload()
    return _build_payload(service)


@router.get("/public")
def get_public_settings_payload() -> dict:
    service = get_config_service()
    payload = _default_payload() if not service.table_exists() else _build_payload(service)
    app_payload = dict(payload.get("app") or {})
    return {
        "app": {
            "name": str(app_payload.get("name") or DEFAULT_APP_NAME).strip() or DEFAULT_APP_NAME,
            "avatar_url": str(app_payload.get("avatar_url") or "").strip(),
            "avatar_updated_at": int(app_payload.get("avatar_updated_at") or 0),
        }
    }


@router.put("")
def update_settings(request: SettingsUpdateRequest, current_user: dict = Depends(get_current_user)) -> dict:
    del current_user
    service = get_config_service()
    entries = []
    for category, values in request.updates.items():
        if str(category) in _HIDDEN_CONFIG_CATEGORIES:
            continue
        if isinstance(values, dict):
            for field, value in values.items():
                if category == "app" and str(field) in _DYNAMIC_APP_FIELDS:
                    continue
                key = f"{category}.{field}"
                if key in _RETIRED_CONFIG_KEYS:
                    continue
                entries.append(
                    {
                        "key": key,
                        "value": value,
                        "category": category,
                        "description": f"Actualizado desde settings UI: {key}",
                    }
                )
        else:
            key = str(category)
            if key in _RETIRED_CONFIG_KEYS:
                continue
            entries.append(
                {
                    "key": key,
                    "value": values,
                    "category": key.split(".", 1)[0] if "." in key else "general",
                    "description": f"Actualizado desde settings UI: {key}",
                }
            )
    if entries:
        service.upsert_many(entries)
    service.delete_keys(sorted(_RETIRED_CONFIG_KEYS))
    return {"success": True, "settings": _build_payload(service)}


@router.get("/status")
def settings_status(current_user: dict = Depends(get_current_user)) -> dict:
    del current_user
    return {"completed": bool(get_setup_service().check_setup_status())}


@router.post("/reset")
def reset_settings(current_user: dict = Depends(get_current_user)) -> dict:
    del current_user
    service = get_config_service()
    defaults = _default_payload()
    entries = []
    for category, values in defaults.items():
        if not isinstance(values, dict):
            continue
        for field, value in values.items():
            key = f"{category}.{field}"
            entries.append(
                {
                    "key": key,
                    "value": value,
                    "category": category,
                    "description": f"Valor por defecto: {key}",
                }
            )
    service.upsert_many(entries)
    service.delete_keys(sorted(_RETIRED_CONFIG_KEYS))
    return {"success": True, "settings": _build_payload(service)}


@router.get("/agent-avatar")
def get_agent_avatar():
    avatar_path = _resolve_avatar_file()
    if avatar_path is None:
        raise HTTPException(status_code=404, detail="Agent avatar not found")
    suffix = avatar_path.suffix.lower()
    media_type = "image/png"
    if suffix in {".jpg", ".jpeg"}:
        media_type = "image/jpeg"
    elif suffix == ".gif":
        media_type = "image/gif"
    return FileResponse(path=avatar_path, media_type=media_type, filename=avatar_path.name)


@router.post("/agent-avatar")
async def upload_agent_avatar(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user),
):
    del current_user
    content_type = str(file.content_type or "").strip().lower()
    extension = _AVATAR_ALLOWED_TYPES.get(content_type)
    if not extension:
        allowed = ", ".join(sorted(_AVATAR_ALLOWED_TYPES.keys()))
        raise HTTPException(status_code=400, detail=f"Unsupported avatar type. Allowed: {allowed}")
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty image file")
    if len(content) > _AVATAR_MAX_BYTES:
        raise HTTPException(status_code=400, detail="Image too large. Max size is 2 MB")
    for candidate in _avatar_candidates():
        if candidate.exists():
            candidate.unlink()
    target = _avatar_dir() / f"avatar{extension}"
    target.write_bytes(content)
    return {
        "success": True,
        "avatar_url": _avatar_url(target),
    }


@router.delete("/agent-avatar")
def delete_agent_avatar(current_user: dict = Depends(get_current_user)):
    del current_user
    removed = False
    for candidate in _avatar_candidates():
        if candidate.exists():
            candidate.unlink()
            removed = True
    return {"success": True, "removed": removed}
