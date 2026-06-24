"""Session memory storage for stateless pods.

OCI Cache is Redis/Valkey-compatible, so the production path uses Redis
commands while local development keeps a tiny in-process fallback.
"""

from __future__ import annotations

import json
import re
from threading import Lock
from typing import Any

from apps.backend.app.core.config import Settings, get_settings

_LOCAL_MEMORY: dict[str, list[dict[str, str]]] = {}
_LOCAL_LOCK = Lock()
_SESSION_ID_PATTERN = re.compile(r"[^a-zA-Z0-9_.:-]+")


def normalize_session_id(session_id: str) -> str:
    normalized = _SESSION_ID_PATTERN.sub("_", str(session_id or "").strip())[:128]
    if not normalized:
        raise ValueError("session_id is required.")
    return normalized


class SessionMemoryStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._client = None
        self._backend = self.settings.session_memory_backend
        self._redis_url = self.settings.session_memory_url
        if self._backend in {"redis", "oci_cache"} and self._redis_url:
            try:
                import redis

                self._client = redis.Redis.from_url(
                    self._redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=5,
                )
                self._client.ping()
            except Exception:
                self._client = None

    def _key(self, session_id: str) -> str:
        return f"ai_document_analyzer:session:{normalize_session_id(session_id)}"

    def reset_session(self, session_id: str) -> None:
        key = self._key(session_id)
        if self._client is not None:
            self._client.delete(key)
            return
        with _LOCAL_LOCK:
            _LOCAL_MEMORY.pop(key, None)

    def get_history(self, session_id: str) -> list[dict[str, str]]:
        key = self._key(session_id)
        if self._client is not None:
            raw_value = self._client.get(key)
            if not raw_value:
                return []
            return self._coerce_history(json.loads(raw_value))
        with _LOCAL_LOCK:
            return list(_LOCAL_MEMORY.get(key, []))

    def append_turn(self, *, session_id: str, user_message: str, assistant_answer: str) -> None:
        history = self.get_history(session_id)
        history.extend(
            [
                {"role": "user", "content": str(user_message or "")[:4000]},
                {"role": "assistant", "content": str(assistant_answer or "")[:4000]},
            ]
        )
        history = self._coerce_history(history)[-24:]
        key = self._key(session_id)
        if self._client is not None:
            self._client.setex(
                key,
                int(self.settings.SESSION_MEMORY_TTL_SECONDS),
                json.dumps(history, ensure_ascii=False),
            )
            return
        with _LOCAL_LOCK:
            _LOCAL_MEMORY[key] = history

    @staticmethod
    def _coerce_history(value: Any) -> list[dict[str, str]]:
        items = value if isinstance(value, list) else []
        history: list[dict[str, str]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            content = str(item.get("content") or "").strip()
            if role not in {"user", "assistant"} or not content:
                continue
            history.append({"role": role, "content": content[:4000]})
        return history[-24:]


_STORE: SessionMemoryStore | None = None
_STORE_LOCK = Lock()


def get_session_memory_store() -> SessionMemoryStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = SessionMemoryStore()
        return _STORE
