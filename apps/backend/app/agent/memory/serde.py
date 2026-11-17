"""JSON serde utilities for LangGraph checkpoint/store payloads."""

from __future__ import annotations

import json
from typing import Any


def dumps_payload(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def loads_payload(payload: str | bytes | bytearray | None) -> Any:
    if payload is None:
        return None
    if isinstance(payload, (bytes, bytearray)):
        payload = payload.decode("utf-8")
    return json.loads(payload)

