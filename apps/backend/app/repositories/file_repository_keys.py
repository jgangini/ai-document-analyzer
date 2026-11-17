"""Pure key builders used by file repository lookup and lexical scans."""

from __future__ import annotations

import re
import unicodedata

_LEXICAL_SCAN_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_LEXICAL_SCAN_STOPWORDS = {
    "a",
    "al",
    "an",
    "and",
    "archivo",
    "archivos",
    "con",
    "cual",
    "cuales",
    "de",
    "del",
    "documento",
    "documentos",
    "el",
    "en",
    "esta",
    "este",
    "habla",
    "hablan",
    "la",
    "las",
    "los",
    "o",
    "or",
    "para",
    "por",
    "que",
    "se",
    "sobre",
    "the",
    "un",
    "una",
    "y",
}
_FILE_LOOKUP_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]{1,12}$")
_FILE_LOOKUP_SEPARATOR_RE = re.compile(r"[^0-9a-z]+")
_FILE_LOOKUP_VOWEL_RE = re.compile(r"[aeiou]")


def file_lookup_base(value: str | None) -> str:
    normalized = str(value or "").strip().strip("`\"'")
    if not normalized:
        return ""
    normalized = normalized.replace("\\", "/").rstrip("/")
    normalized = normalized.rsplit("/", 1)[-1]
    normalized = _FILE_LOOKUP_EXTENSION_RE.sub("", normalized)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return normalized.casefold()


def file_lookup_primary_keys(value: str | None) -> set[str]:
    base = file_lookup_base(value)
    if not base:
        return set()
    spaced = " ".join(part for part in _FILE_LOOKUP_SEPARATOR_RE.split(base) if part)
    compact = _FILE_LOOKUP_SEPARATOR_RE.sub("", base)
    return {key for key in (spaced, compact) if key}


def file_lookup_signature(value: str | None) -> str:
    compact = _FILE_LOOKUP_SEPARATOR_RE.sub("", file_lookup_base(value))
    if len(compact) < 8:
        return ""
    signature = _FILE_LOOKUP_VOWEL_RE.sub("", compact)
    return signature if len(signature) >= 6 else ""


def normalize_lexical_scan_text(value: str | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower()
    normalized = re.sub(r"[_/\\\-]+", " ", normalized)
    normalized = re.sub(r"[^\w\s]+", " ", normalized)
    return " ".join(normalized.split())


def lexical_scan_keys(token: str) -> set[str]:
    normalized = normalize_lexical_scan_text(token)
    if not normalized or " " in normalized:
        return set()
    keys = {normalized}
    if len(normalized) > 4 and normalized.endswith("s"):
        keys.add(normalized[:-1])
    for suffix in (
        "aciones",
        "acion",
        "ando",
        "iendo",
        "ados",
        "adas",
        "idos",
        "idas",
        "ado",
        "ada",
        "ido",
        "ida",
        "ar",
        "er",
        "ir",
    ):
        if len(normalized) > len(suffix) + 3 and normalized.endswith(suffix):
            keys.add(normalized[: -len(suffix)])
            break
    if len(normalized) > 5 and normalized[-1] in {"a", "e", "o"}:
        keys.add(normalized[:-1])
    if normalized.startswith("atras"):
        keys.add(normalized.replace("atras", "retras", 1))
    if normalized.startswith("retras"):
        keys.add(normalized.replace("retras", "atras", 1))
    return {key for key in keys if len(key) >= 3}


def build_lexical_scan_terms(text: str | None, *, limit: int = 8) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in _LEXICAL_SCAN_TOKEN_RE.findall(normalize_lexical_scan_text(text)):
        if len(token) < 3 or token in _LEXICAL_SCAN_STOPWORDS:
            continue
        for key in sorted(lexical_scan_keys(token), key=lambda item: (len(item), item), reverse=True):
            if key in seen:
                continue
            seen.add(key)
            ordered.append(key)
            if len(ordered) >= limit:
                return ordered
    return ordered
