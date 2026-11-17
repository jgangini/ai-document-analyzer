"""Helpers to build canonical Object Storage keys."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

SAFE_SEGMENT_DEFAULT = "item"
_MULTI_DASH = re.compile(r"-{2,}")


def _slugify(value: str, *, default_value: str = SAFE_SEGMENT_DEFAULT) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    cleaned = re.sub(r"[^a-z0-9._-]+", "-", lowered).strip(".-_")
    compact = _MULTI_DASH.sub("-", cleaned)
    return compact or default_value


def build_archive_prefix(*, username: str, archive_slug: str, archive_id: str) -> str:
    user_segment = _slugify(username, default_value="user")
    archive_segment = _slugify(archive_slug, default_value="archive")
    del archive_id
    return f"{user_segment}/{archive_segment}"


def build_zip_source_key(*, archive_prefix: str, zip_name: str) -> str:
    normalized_name = _slugify(Path(zip_name).name, default_value="archive.zip")
    if not normalized_name.endswith(".zip"):
        normalized_name = f"{normalized_name}.zip"
    return f"{archive_prefix}/source/{normalized_name}"


def build_pdf_source_key(*, archive_prefix: str, doc_name: str) -> str:
    doc_path = Path(doc_name)
    normalized_name = _slugify(doc_path.name, default_value="document.pdf")
    if not normalized_name.endswith(".pdf"):
        normalized_name = f"{normalized_name}.pdf"
    return f"{archive_prefix}/source/{normalized_name}"


def build_page_png_key(*, archive_prefix: str, doc_name: str, page_number: int) -> str:
    doc_slug = _slugify(Path(doc_name).stem, default_value="document")
    safe_page = max(1, int(page_number))
    return f"{archive_prefix}/{doc_slug}/pages/{safe_page:03d}.png"


def build_page_ocr_json_key(*, archive_prefix: str, doc_name: str, page_number: int) -> str:
    doc_slug = _slugify(Path(doc_name).stem, default_value="document")
    safe_page = max(1, int(page_number))
    return f"{archive_prefix}/{doc_slug}/ocr/{safe_page:03d}.json"
