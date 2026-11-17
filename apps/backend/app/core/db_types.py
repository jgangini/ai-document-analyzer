"""Normalizacion de tipos de datos devueltos por Oracle."""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any


def normalize_embedding_vector(value: Any) -> list[float]:
    """Normaliza payloads vectoriales en una lista de float."""
    if value is None:
        return []
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return []
        if isinstance(loaded, Sequence):
            return [float(item) for item in loaded]
        return []
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [float(item) for item in value]
    return []

