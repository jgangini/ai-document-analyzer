"""Local hash-backed RAG fallback for development and benchmark smoke tests."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import html
import json
import re
from pathlib import Path
from typing import Any

from apps.backend.app.core.config import Settings, get_settings
from apps.backend.app.evidence.ledger import DocumentUnit, sha256_file

SUPPORTED_TEXT_SUFFIXES = {".md", ".txt", ".json", ".jsonl", ".html", ".csv", ".yaml", ".yml"}
EXCLUDED_DIR_NAMES = {
    ".git",
    ".venv",
    "_outputs",
    "_plans",
    "__pycache__",
    "build",
    "dist",
    "keys",
    "logs",
    "node_modules",
    "outputs",
    "wallet",
}
TOKEN_PATTERN = re.compile(r"[a-zA-ZáéíóúÁÉÍÓÚñÑüÜ0-9]{3,}")
HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
MOJIBAKE_REPLACEMENTS = {
    "Ã¡": "á",
    "Ã©": "é",
    "Ã­": "í",
    "Ã³": "ó",
    "Ãº": "ú",
    "Ã±": "ñ",
    "Ã": "Á",
    "Ã‰": "É",
    "Ã": "Í",
    "Ã“": "Ó",
    "Ãš": "Ú",
    "Ã‘": "Ñ",
    "Â¿": "¿",
    "Â¡": "¡",
    "Â°": "°",
}


@dataclass(frozen=True, slots=True)
class LocalDocument:
    path: Path
    relative_path: str
    text: str
    tokens: set[str]
    source_sha256: str
    priority: int


@dataclass(frozen=True, slots=True)
class LocalRagResult:
    answer: str
    sources: list[str]


def _tokenize(text: str) -> set[str]:
    return {match.group(0).casefold() for match in TOKEN_PATTERN.finditer(text or "")}


def _repair_mojibake(text: str) -> str:
    if "Ã" not in text and "Â" not in text:
        return text
    try:
        text = text.encode("latin-1").decode("utf-8")
    except UnicodeError:
        pass
    for broken, repaired in MOJIBAKE_REPLACEMENTS.items():
        text = text.replace(broken, repaired)
    return text


def _clean_text(path: Path, raw_text: str) -> str:
    if path.suffix.lower() == ".html":
        raw_text = HTML_TAG_PATTERN.sub(" ", raw_text)
        raw_text = html.unescape(raw_text)
    if path.suffix.lower() in {".json", ".jsonl"}:
        raw_text = re.sub(r'["{}\\[\\],:]+', " ", raw_text)
    return _repair_mojibake(re.sub(r"\s+", " ", raw_text).strip())


def _priority(path: Path) -> int:
    normalized = str(path).replace("\\", "/").casefold()
    score = 0
    if any(marker in normalized for marker in ("/_plans/", "/_outputs/", "/outputs/")):
        score -= 100
    if "diagnostico" in normalized or "resume_state" in normalized or "progress" in normalized:
        score -= 80
    if "metadata/semantic_indexes" in normalized:
        score += 35
    if "metadata/normative" in normalized or "normative_data" in normalized:
        score += 32
    if "processed/text_preview" in normalized:
        score += 30
    if "/eda/data/" in normalized:
        score += 28
    if "/data_cliente/" in normalized:
        score += 18
    if "ley_599" in normalized or "ley599" in normalized:
        score += 12
    if "captura" in normalized or "capture" in normalized:
        score += 8
    if "normative" in normalized or "ley" in normalized or "decreto" in normalized:
        score += 4
    if "/prompts/" in normalized or "/procedure_data/" in normalized:
        score -= 20
    if path.suffix.lower() in {".md", ".txt"}:
        score += 3
    if "node_modules" in normalized or "wallet" in normalized:
        score -= 100
    return score


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in SUPPORTED_TEXT_SUFFIXES:
            continue
        rel_parts = {part.casefold() for part in path.relative_to(root).parts[:-1]}
        if rel_parts & EXCLUDED_DIR_NAMES:
            continue
        try:
            if path.stat().st_size > 2_000_000:
                continue
        except OSError:
            continue
        files.append(path)
    return sorted(files, key=lambda item: (-_priority(item), str(item).casefold()))


def _load_documents(settings: Settings) -> list[LocalDocument]:
    root = settings.local_rag_corpus_root
    docs: list[LocalDocument] = []
    for path in _iter_files(root)[: max(1, int(settings.LOCAL_RAG_MAX_FILES))]:
        try:
            raw_text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        text = _clean_text(path, raw_text)
        tokens = _tokenize(text)
        if not text or len(tokens) < 3:
            continue
        try:
            source_hash = sha256_file(path)
        except OSError:
            source_hash = ""
        docs.append(
            LocalDocument(
                path=path,
                relative_path=path.relative_to(root).as_posix(),
                text=text,
                tokens=tokens,
                source_sha256=source_hash,
                priority=_priority(path),
            )
        )
    return docs


@lru_cache(maxsize=1)
def _cached_documents() -> tuple[LocalDocument, ...]:
    return tuple(_load_documents(get_settings()))


def _best_snippet(text: str, query_tokens: set[str], *, max_chars: int = 520) -> str:
    if not text:
        return ""
    lowered = text.casefold()
    positions = [lowered.find(token) for token in query_tokens if lowered.find(token) >= 0]
    start = max(0, min(positions) - 140) if positions else 0
    snippet = text[start : start + max_chars].strip()
    if start > 0:
        snippet = "..." + snippet
    if start + max_chars < len(text):
        snippet += "..."
    return snippet


def _score(doc: LocalDocument, query_tokens: set[str]) -> float:
    overlap = doc.tokens & query_tokens
    if not overlap:
        return 0.0
    return (len(overlap) * 10.0) + min(len(overlap) / max(1, len(query_tokens)), 1.0) + doc.priority


def _jsonl_records(doc: LocalDocument) -> list[tuple[dict[str, Any], str]]:
    if doc.path.suffix.lower() != ".jsonl":
        return []
    records: list[tuple[dict[str, Any], str]] = []
    try:
        raw_lines = doc.path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        raw_lines = doc.text.split("} {")
    for raw_line in raw_lines:
        line = raw_line.strip()
        if not line:
            continue
        try:
            payload = json.loads(_repair_mojibake(line))
        except Exception:
            continue
        if isinstance(payload, dict):
            records.append((payload, line))
    return records


def _best_eda_record(docs: tuple[LocalDocument, ...], query_tokens: set[str]) -> tuple[LocalDocument, dict[str, Any], str] | None:
    best: tuple[float, LocalDocument, dict[str, Any], str] | None = None
    for doc in docs:
        if "eda/data/preguntas_ley_599_captura.jsonl" not in doc.relative_path.replace("\\", "/").casefold():
            continue
        for payload, raw_line in _jsonl_records(doc):
            question_text = " ".join(
                [
                    str(payload.get("pregunta") or ""),
                    str(payload.get("tema_ley_599") or ""),
                    " ".join(str(item) for item in list(payload.get("articulos_ley_599_sugeridos") or [])),
                ]
            )
            overlap = _tokenize(question_text) & query_tokens
            score = float(len(overlap))
            if score < 4:
                continue
            if best is None or score > best[0]:
                best = (score, doc, payload, raw_line)
    if best is None:
        return None
    return best[1], best[2], best[3]


def _find_ley_599_article_record(
    docs: tuple[LocalDocument, ...],
    article_id: str,
) -> tuple[LocalDocument, dict[str, Any], str] | None:
    normalized_article_id = str(article_id or "").strip().casefold()
    preferred_paths = (
        "metadata/semantic_indexes/ley_599_2000.capture_article_selector.jsonl",
        "metadata/semantic_indexes/ley_599_2000.delitos_principales_selector.jsonl",
        "metadata/normative_units.jsonl",
    )
    candidates = sorted(
        docs,
        key=lambda doc: next(
            (index for index, marker in enumerate(preferred_paths) if marker in doc.relative_path.replace("\\", "/").casefold()),
            len(preferred_paths),
        ),
    )
    for doc in candidates:
        normalized_path = doc.relative_path.replace("\\", "/").casefold()
        if not any(marker in normalized_path for marker in preferred_paths):
            continue
        for payload, raw_line in _jsonl_records(doc):
            if str(payload.get("source_id") or "").casefold() != "ley_599_2000":
                continue
            payload_article_id = str(payload.get("canonical_article_id") or payload.get("article_id") or "").strip().casefold()
            if payload_article_id == normalized_article_id:
                return doc, payload, raw_line
    return None


def _format_article_record(payload: dict[str, Any]) -> str:
    citation = _repair_mojibake(str(payload.get("citation_label") or "").strip())
    if not citation:
        citation = f"Ley 599 de 2000, art. {payload.get('article_id') or payload.get('canonical_article_id')}"
    summary = _repair_mojibake(str(payload.get("summary_short") or payload.get("title") or "").strip())
    operational = _repair_mojibake(str(payload.get("summary_operational") or "").strip())
    unit_id = str(payload.get("unit_id") or payload.get("evidence_unit_id") or "").strip()
    parts = [citation]
    if summary:
        parts.append(summary)
    if operational and operational != summary:
        parts.append(operational)
    if unit_id:
        parts.append(f"unit_id={unit_id}")
    return " - ".join(parts)


def _answer_from_eda_match(
    docs: tuple[LocalDocument, ...],
    query_tokens: set[str],
) -> LocalRagResult | None:
    match = _best_eda_record(docs, query_tokens)
    if match is None:
        return None
    eda_doc, payload, raw_line = match
    article_ids = [
        str(item).strip()
        for item in list(payload.get("articulos_ley_599_sugeridos") or [])
        if str(item).strip()
    ]
    if not article_ids:
        return None

    evidence_units: list[DocumentUnit] = []
    eda_unit = DocumentUnit.from_text(
        source_id=eda_doc.relative_path,
        unit_id=str(payload.get("question_id") or "eda-question"),
        text=raw_line,
        citation_label=eda_doc.relative_path,
        source_sha256=eda_doc.source_sha256,
        hash_verified=True,
        metadata={"local_path": str(eda_doc.path)},
    )
    evidence_units.append(eda_unit)

    article_lines: list[str] = []
    for article_id in article_ids:
        article_match = _find_ley_599_article_record(docs, article_id)
        if article_match is None:
            continue
        article_doc, article_payload, raw_article_line = article_match
        unit = DocumentUnit.from_text(
            source_id=article_doc.relative_path,
            unit_id=str(article_payload.get("unit_id") or article_payload.get("evidence_unit_id") or f"article:{article_id}"),
            text=raw_article_line,
            citation_label=str(article_payload.get("citation_label") or article_doc.relative_path),
            source_sha256=article_doc.source_sha256,
            hash_verified=True,
            metadata={"local_path": str(article_doc.path)},
        )
        evidence_units.append(unit)
        article_lines.append(f"- {_format_article_record(article_payload)} [{unit.evidence_id}]")

    if not article_lines:
        return None

    topic = str(payload.get("tema_ley_599") or "").strip()
    unit_ids = ", ".join(str(item) for item in list(payload.get("unit_ids_ley_599_sugeridos") or []) if str(item))
    answer_lines = [
        "Respuesta generada en modo local con evidencia verificada por hash.",
        "",
        f"- Caso EDA relacionado: {topic or 'consulta legal de Ley 599'}; articulos sugeridos: {', '.join(article_ids)}"
        + (f"; unit_ids: {unit_ids}" if unit_ids else "")
        + f" [{eda_unit.evidence_id}]",
        *article_lines,
        "",
        "Para precision legal maxima, valida estas citas contra el ledger en Autonomous Database.",
    ]
    return LocalRagResult(
        answer="\n".join(answer_lines),
        sources=[f"{unit.citation_label} [{unit.evidence_id}]" for unit in evidence_units],
    )


def answer_local_chat(message: str) -> LocalRagResult:
    query_tokens = _tokenize(message)
    docs = _cached_documents()
    eda_result = _answer_from_eda_match(docs, query_tokens)
    if eda_result is not None:
        return eda_result
    ranked = sorted(
        (
            (_score(doc, query_tokens), doc)
            for doc in docs
        ),
        key=lambda item: item[0],
        reverse=True,
    )
    selected = [doc for score, doc in ranked[:5] if score > 0]
    if not selected:
        return LocalRagResult(
            answer=(
                "No encontre evidencia local suficiente en el corpus cargado para responder con precision. "
                "Carga documentos o habilita el runtime OCI para busqueda completa."
            ),
            sources=[],
        )

    evidence_units: list[tuple[DocumentUnit, str]] = []
    for index, doc in enumerate(selected, start=1):
        snippet = _best_snippet(doc.text, query_tokens)
        unit = DocumentUnit.from_text(
            source_id=doc.relative_path,
            unit_id=f"snippet:{index}",
            text=snippet,
            citation_label=doc.relative_path,
            source_sha256=doc.source_sha256,
            hash_verified=True,
            metadata={"local_path": str(doc.path)},
        )
        evidence_units.append((unit, snippet))

    answer_lines = [
        "Respuesta generada en modo local con evidencia verificada por hash.",
        "",
    ]
    for unit, snippet in evidence_units[:3]:
        answer_lines.append(f"- {snippet} [{unit.evidence_id}]")
    answer_lines.append("")
    answer_lines.append("Para precision legal maxima, valida estas citas contra el ledger en Autonomous Database.")

    sources = [f"{unit.citation_label} [{unit.evidence_id}]" for unit, _ in evidence_units]
    return LocalRagResult(answer="\n".join(answer_lines), sources=sources)


def local_rag_status() -> dict[str, Any]:
    docs = _cached_documents()
    return {
        "enabled": get_settings().local_rag_enabled,
        "documents_indexed": len(docs),
        "corpus_root": str(get_settings().local_rag_corpus_root),
    }


def list_local_documents() -> list[LocalDocument]:
    return list(_cached_documents())


def dump_local_rag_status_json() -> str:
    return json.dumps(local_rag_status(), ensure_ascii=False)
