from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
import json
from pathlib import Path
import re
from statistics import mean
from time import perf_counter, sleep
from typing import Any
import unicodedata
from urllib import error as url_error
from urllib import request as url_request


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE_URL = "http://127.0.0.1:8012/api"
DEFAULT_BATTERY_PATH = Path("D:/Desktop/qa_bateria_en_texto.md")
DEFAULT_METADATA_CSV = ROOT / ".source" / "info-docs.metadata.csv"
DEFAULT_OUTPUT_DIR = ROOT / "apps" / "backend" / "tests" / "reports"
DEFAULT_DOWNLOADS_DIR = Path.home() / "Downloads"
DEFAULT_TIMEOUT_SECONDS = 240
DEFAULT_CURRENT_DATE = date.today().isoformat()

ARCHIVE_SLUG_PATTERN = re.compile(r"\b[A-Z0-9]+_ID_\d+\b")
BACKTICK_PATTERN = re.compile(r"`([^`]+)`")
DATE_PATTERN = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
FILENAME_CODE_PATTERN = re.compile(r"\b([A-Z][A-Z0-9]+)(?:[_-].+|\..+)\.(?:pdf|zip)\b", re.IGNORECASE)
QUESTION_PATTERN = re.compile(r"^\s*(\d+)\.\s*Pregunta:\s*(.+?)\s*$")
DISPLAY_TEXT_REPAIRS: tuple[tuple[str, str], ...] = (
    ("Aclaracin", "Aclaracion"),
    ("Cesin", "Cesion"),
    ("Comunicacin", "Comunicacion"),
    ("Constitucin", "Constitucion"),
    ("Gestin", "Gestion"),
    ("Inscripcin", "Inscripcion"),
    ("Insripcin", "Inscripcion"),
    ("Modificacin", "Modificacion"),
    ("Notificacin", "Notificacion"),
    ("Rectificacin", "Rectificacion"),
    ("Resciliacin", "Resciliacion"),
    ("Revocacin", "Revocacion"),
    ("Transaccin", "Transaccion"),
)


@dataclass(frozen=True, slots=True)
class SelectorOverride:
    use_metadata: bool = False
    metadata_fields: tuple[str, ...] = ()
    extra_archive_slugs: tuple[str, ...] = ()
    top_k: int = 8
    candidate_k: int = 40
    min_pages_per_selected_doc: int = 0
    summary_mode: str = "default"
    expects_citations: bool = False


@dataclass(slots=True)
class HttpResult:
    status_code: int
    payload: Any
    elapsed_ms: int
    error_text: str = ""


@dataclass(slots=True)
class RawBatteryCase:
    section: str
    section_index: int
    question: str
    example_answer: str


@dataclass(slots=True)
class BatteryCase:
    id: int
    label: str
    section: str
    section_index: int
    original_question: str
    selector_question: str
    example_answer: str
    archive_slugs: tuple[str, ...]
    metadata_fields: tuple[str, ...]
    metadata_mode: str
    expected_terms: tuple[str, ...]
    top_k: int
    candidate_k: int
    min_pages_per_selected_doc: int
    summary_mode: str
    allow_inferred_scope: bool
    current_date: str
    selector_warnings: tuple[str, ...] = ()
    expects_citations: bool = False


CASE_OVERRIDES: dict[tuple[str, int], SelectorOverride] = {
    ("Operativo", 1): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Renta o Precio Vigente",
            "Tipo de Moneda",
            "Periodo de Pago",
            "Pago Anticipado",
            "IVA",
        ),
        top_k=6,
        candidate_k=24,
    ),
    ("Operativo", 2): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Fecha de Inicio de Vigencia del Contrato",
            "Fecha de Termino del Contrato",
            "Duracion Inicial del Contrato",
            "Prorroga Automatica",
            "Periodo Prorroga Automatica",
        ),
        top_k=6,
        candidate_k=24,
    ),
    ("Operativo", 3): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Nombre de Propietario Principal",
            "RUT Propietario Principal",
            "Nombre Beneficiario",
            "Rut Beneficiario del contrato",
        ),
        top_k=6,
        candidate_k=24,
    ),
    ("Operativo", 4): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Estado Contrato", "Estado Actividad"),
        top_k=6,
        candidate_k=24,
    ),
    ("Operativo", 5): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Fecha de Inicio de Vigencia del Contrato",
            "Fecha de Termino del Contrato",
            "Fecha de Aviso de Termino del Contrato",
        ),
        top_k=6,
        candidate_k=24,
    ),
    ("Operativo", 6): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Clausula de Salida", "Clausula de Salida Propietario"),
        top_k=6,
        candidate_k=24,
    ),
    ("Operativo", 7): SelectorOverride(
        top_k=8,
        candidate_k=40,
        min_pages_per_selected_doc=1,
        summary_mode="per_document",
        expects_citations=True,
    ),
    ("Operativo", 8): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Servidumbre", "Rol de Propiedad"),
        top_k=6,
        candidate_k=24,
    ),
    ("Operativo", 9): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Pago Electrico", "Monto Pago Electrico UF", "IVA"),
        top_k=6,
        candidate_k=24,
    ),
    ("Operativo", 10): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Nombre de Propietario Principal", "Nombre Beneficiario"),
        top_k=10,
        candidate_k=60,
    ),
    ("Operativo", 11): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Region", "Comuna", "Tipo de Sitio", "Tipo de Contrato"),
        top_k=10,
        candidate_k=60,
    ),
    ("Operativo", 12): SelectorOverride(
        top_k=10,
        candidate_k=48,
        min_pages_per_selected_doc=1,
        summary_mode="per_document",
        expects_citations=True,
    ),
    ("Operativo", 13): SelectorOverride(
        top_k=12,
        candidate_k=60,
        min_pages_per_selected_doc=1,
        summary_mode="per_document",
        expects_citations=True,
    ),
    ("Operativo", 14): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Estado Contrato", "Revision Final"),
        top_k=8,
        candidate_k=36,
    ),
    ("Operativo", 15): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Notaria (Ultimo Contrato)",
            "Ciudad Notaria (Ultimo Contrato)",
            "Numero Repertorio (Ultimo Contrato)",
        ),
        top_k=6,
        candidate_k=24,
    ),
    ("Analitico", 1): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Renta o Precio Vigente", "Periodo de Pago", "Tipo de Moneda"),
        top_k=8,
        candidate_k=32,
    ),
    ("Analitico", 2): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Renta o Precio Vigente",
            "Periodo de Pago",
            "Duracion Inicial del Contrato",
            "Fecha de Inicio de Vigencia del Contrato",
            "Fecha de Termino del Contrato",
        ),
        top_k=8,
        candidate_k=32,
    ),
    ("Analitico", 3): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Fecha de Termino del Contrato",
            "Fecha de Aviso de Termino del Contrato",
            "Prorroga Automatica",
            "Periodo Prorroga Automatica",
        ),
        top_k=8,
        candidate_k=32,
    ),
    ("Analitico", 4): SelectorOverride(
        top_k=10,
        candidate_k=48,
        min_pages_per_selected_doc=1,
        summary_mode="per_document",
        expects_citations=True,
    ),
    ("Analitico", 5): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Codigo de Sitio",
            "Estado Contrato",
            "Renta o Precio Vigente",
            "Tipo de Moneda",
            "Periodo de Pago",
            "Fecha de Termino del Contrato",
        ),
        extra_archive_slugs=("LA122_ID_3979", "LA122_ID_18467"),
        top_k=10,
        candidate_k=40,
    ),
    ("Analitico", 6): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Indicar Otras Condiciones",
            "Otras Condiciones",
            "Clausula de Salida",
            "Clausula de Salida Propietario",
        ),
        top_k=8,
        candidate_k=32,
    ),
    ("Analitico", 7): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Estado Contrato", "Revision Final"),
        top_k=8,
        candidate_k=32,
    ),
    ("Analitico", 8): SelectorOverride(
        top_k=10,
        candidate_k=48,
        min_pages_per_selected_doc=1,
        summary_mode="per_document",
        expects_citations=True,
    ),
    ("Analitico", 9): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Prorroga Automatica",
            "Periodo Prorroga Automatica",
            "Fecha de Termino del Contrato",
            "Fecha de Aviso de Termino del Contrato",
        ),
        top_k=8,
        candidate_k=32,
    ),
    ("Analitico", 10): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Renta o Precio Vigente",
            "IVA",
            "Forma de Pago",
            "Pago Electrico",
            "Monto Pago Electrico UF",
            "Periodo de Pago",
        ),
        top_k=8,
        candidate_k=32,
    ),
    ("Analitico", 11): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Revision Final", "Estado Contrato"),
        top_k=12,
        candidate_k=60,
    ),
    ("Analitico", 12): SelectorOverride(
        use_metadata=True,
        metadata_fields=("Region", "Comuna", "Tipo de Sitio", "Tipo de Contrato"),
        top_k=10,
        candidate_k=60,
    ),
    ("Analitico", 13): SelectorOverride(
        use_metadata=True,
        metadata_fields=(
            "Nombre Beneficiario",
            "Nombre de Propietario Principal",
            "Renta o Precio Vigente",
            "Tipo de Moneda",
        ),
        top_k=10,
        candidate_k=60,
    ),
    ("Analitico", 14): SelectorOverride(
        extra_archive_slugs=(
            "AI041_ID_49",
            "LA122_ID_3979",
            "URARM002_ID_28624",
            "ZM333_ID_3261",
        ),
        top_k=12,
        candidate_k=60,
        min_pages_per_selected_doc=1,
        summary_mode="per_document",
        expects_citations=True,
    ),
    ("Analitico", 15): SelectorOverride(
        extra_archive_slugs=("LA122_ID_3979",),
        top_k=10,
        candidate_k=48,
        min_pages_per_selected_doc=1,
        summary_mode="per_document",
        expects_citations=True,
    ),
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _timestamp_slug() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_text(value: object | None) -> str:
    text = str(value or "")
    for wrong, right in DISPLAY_TEXT_REPAIRS:
        text = re.sub(re.escape(wrong), right, text, flags=re.IGNORECASE)
    normalized = unicodedata.normalize("NFKD", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower().strip()
    return " ".join(normalized.split())


def _relaxed_key(value: object | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", _normalize_text(value))


def _short_text(value: object | None, *, limit: int = 420) -> str:
    compact = " ".join(str(value or "").split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


def _slugify(value: str) -> str:
    text = _normalize_text(value)
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or "case"


def _percentile_ms(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    ordered = sorted(int(value) for value in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = max(0.0, min(1.0, float(percentile))) * (len(ordered) - 1)
    lower = int(rank)
    upper = min(lower + 1, len(ordered) - 1)
    if lower == upper:
        return ordered[lower]
    weight = rank - lower
    return int(round(ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)))


def _http_json(
    *,
    method: str,
    url: str,
    timeout_seconds: int,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> HttpResult:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = None
    if body is not None:
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    request = url_request.Request(url=url, method=method.upper(), headers=headers, data=payload)
    started = perf_counter()
    try:
        with url_request.urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            return HttpResult(
                status_code=int(response.status),
                payload=parsed,
                elapsed_ms=int((perf_counter() - started) * 1000),
            )
    except url_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(raw) if raw.strip() else {}
        except Exception:
            parsed = {"detail": raw}
        return HttpResult(
            status_code=int(exc.code),
            payload=parsed,
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_text=str(parsed.get("detail") or raw or exc.reason),
        )
    except Exception as exc:
        return HttpResult(
            status_code=0,
            payload={},
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_text=str(exc),
        )


def _require_ok(result: HttpResult, *, message: str) -> dict[str, Any]:
    if result.status_code < 200 or result.status_code >= 300:
        raise RuntimeError(f"{message}: status={result.status_code} detail={result.error_text or result.payload}")
    if not isinstance(result.payload, dict):
        raise RuntimeError(f"{message}: unexpected payload type {type(result.payload)!r}")
    return dict(result.payload)


def _login(*, base_url: str, username: str, password: str, timeout_seconds: int) -> str:
    payload = _require_ok(
        _http_json(
            method="POST",
            url=f"{base_url}/auth/login",
            timeout_seconds=timeout_seconds,
            body={"username": username, "password": password},
        ),
        message="Login failed",
    )
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise RuntimeError("Login response did not include access_token.")
    return token


def _list_files(*, base_url: str, token: str, timeout_seconds: int) -> list[dict[str, Any]]:
    payload = _require_ok(
        _http_json(
            method="GET",
            url=f"{base_url}/files?limit=500&offset=0",
            timeout_seconds=timeout_seconds,
            token=token,
        ),
        message="Listing files failed",
    )
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("The /files payload did not include an items list.")
    return [dict(item) for item in items if isinstance(item, dict)]


def _load_scope_options(*, base_url: str, token: str, timeout_seconds: int) -> dict[str, Any]:
    return _require_ok(
        _http_json(
            method="GET",
            url=f"{base_url}/questions/scope-options",
            timeout_seconds=timeout_seconds,
            token=token,
        ),
        message="Loading /questions/scope-options failed",
    )


def _load_metadata_rows(metadata_csv: Path) -> list[dict[str, str]]:
    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        first_field = reader.fieldnames[0].strip() if reader.fieldnames else ""
        if first_field != "file":
            raise RuntimeError(f"Metadata CSV must start with 'file'. Found: {first_field!r}")
        return [{str(key): str(value or "").strip() for key, value in row.items() if key} for row in reader]


def _parse_battery_markdown(battery_path: Path) -> list[RawBatteryCase]:
    lines = battery_path.read_text(encoding="utf-8").splitlines()
    cases: list[RawBatteryCase] = []
    current_section = ""
    pending_index: int | None = None
    pending_question = ""
    pending_answer: list[str] = []

    def flush_pending() -> None:
        nonlocal pending_index, pending_question, pending_answer
        if pending_index is None or not current_section:
            pending_index = None
            pending_question = ""
            pending_answer = []
            return
        cases.append(
            RawBatteryCase(
                section=current_section,
                section_index=int(pending_index),
                question=pending_question.strip(),
                example_answer=" ".join(part.strip() for part in pending_answer if part.strip()).strip(),
            )
        )
        pending_index = None
        pending_question = ""
        pending_answer = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.startswith("## "):
            flush_pending()
            current_section = line[3:].strip()
            continue
        question_match = QUESTION_PATTERN.match(line)
        if question_match:
            flush_pending()
            pending_index = int(question_match.group(1))
            pending_question = question_match.group(2).strip()
            pending_answer = []
            continue
        if line.startswith("Respuesta ejemplo:"):
            pending_answer.append(line.split(":", 1)[1].strip())
            continue
        if pending_index is not None and line.strip():
            pending_answer.append(line.strip())
    flush_pending()
    return cases


def _extract_archive_slugs(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in ARCHIVE_SLUG_PATTERN.findall(str(text or "")):
        value = match.strip()
        key = value.lower()
        if not value or key in seen:
            continue
        seen.add(key)
        ordered.append(value)
    return ordered


def _extract_unique_archive_slugs_from_terms(text: str, code_to_slugs: dict[str, list[str]]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_term in BACKTICK_PATTERN.findall(str(text or "")):
        value = str(raw_term or "").strip()
        if not value:
            continue
        filename_match = FILENAME_CODE_PATTERN.search(value)
        if filename_match is None:
            continue
        code = filename_match.group(1).upper()
        candidates = list(code_to_slugs.get(code) or [])
        if len(candidates) != 1:
            continue
        slug = candidates[0]
        key = slug.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(slug)
    return ordered


def _extract_expected_terms(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_term in BACKTICK_PATTERN.findall(str(text or "")):
        term = str(raw_term or "").strip()
        if not term:
            continue
        if _should_skip_expected_term(term):
            continue
        key = _normalize_text(term)
        if not key or key in seen:
            continue
        seen.add(key)
        ordered.append(term)
    return ordered


def _should_skip_expected_term(value: str) -> bool:
    stripped = str(value or "").strip()
    if not stripped:
        return True
    if ARCHIVE_SLUG_PATTERN.fullmatch(stripped):
        return True
    if DATE_PATTERN.fullmatch(stripped):
        return False
    if re.search(r"\.(?:pdf|zip)\b", stripped, re.IGNORECASE):
        return False
    if re.search(r"[+*/=]", stripped) and re.search(r"\d", stripped) and " " in stripped:
        return True
    return False


def _build_archive_slug_lookup(values: list[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        lookup.setdefault(_relaxed_key(cleaned), cleaned)
    return lookup


def _build_metadata_field_lookups(values: list[str]) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    exact_lookup: dict[str, str] = {}
    normalized_lookup: dict[str, str] = {}
    relaxed_lookup: dict[str, str] = {}
    for value in values:
        cleaned = str(value or "").strip()
        if not cleaned:
            continue
        exact_lookup.setdefault(cleaned.casefold(), cleaned)
        normalized_lookup.setdefault(_normalize_text(cleaned), cleaned)
        relaxed_lookup.setdefault(_relaxed_key(cleaned), cleaned)
    return exact_lookup, normalized_lookup, relaxed_lookup


def _resolve_archive_slugs(values: list[str], catalog: list[str]) -> tuple[list[str], list[str]]:
    catalog_lookup = _build_archive_slug_lookup(catalog)
    resolved: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        cleaned = str(raw_value or "").strip()
        if not cleaned:
            continue
        resolved_value = catalog_lookup.get(_relaxed_key(cleaned))
        if not resolved_value:
            missing.append(cleaned)
            continue
        key = resolved_value.lower()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(resolved_value)
    return resolved, missing


def _resolve_metadata_fields(values: tuple[str, ...], catalog: list[str]) -> tuple[list[str], list[str]]:
    exact_lookup, normalized_lookup, relaxed_lookup = _build_metadata_field_lookups(catalog)
    resolved: list[str] = []
    missing: list[str] = []
    seen: set[str] = set()
    for raw_value in values:
        cleaned = str(raw_value or "").strip()
        if not cleaned:
            continue
        resolved_value = (
            exact_lookup.get(cleaned.casefold())
            or normalized_lookup.get(_normalize_text(cleaned))
            or relaxed_lookup.get(_relaxed_key(cleaned))
        )
        if not resolved_value:
            missing.append(cleaned)
            continue
        key = resolved_value.casefold()
        if key in seen:
            continue
        seen.add(key)
        resolved.append(resolved_value)
    return resolved, missing


def _build_code_to_slugs(values: list[str]) -> dict[str, list[str]]:
    mapping: dict[str, list[str]] = defaultdict(list)
    for slug in values:
        cleaned = str(slug or "").strip()
        if not cleaned:
            continue
        code = cleaned.split("_ID_", 1)[0].strip().upper()
        if not code:
            continue
        mapping[code].append(cleaned)
    return {key: sorted(set(items)) for key, items in mapping.items()}


def _build_selector_question(
    *,
    question: str,
    metadata_mode: str,
    archive_slugs: list[str],
    metadata_fields: list[str],
) -> str:
    parts: list[str] = []
    if metadata_mode == "metadata_first":
        parts.append("@metadata")
    parts.extend(f"/file:{slug}" for slug in archive_slugs)
    for field_name in metadata_fields:
        escaped = field_name.replace('"', '\\"')
        parts.append(f'/col:"{escaped}"')
    prefix = " ".join(parts).strip()
    if not prefix:
        return question.strip()
    return f"{prefix} {question.strip()}".strip()


def _append_document_hint(question: str) -> str:
    hint = "Lista los nombres exactos de los PDF relevantes y cita la evidencia documental."
    if _normalize_text(hint) in _normalize_text(question):
        return question.strip()
    return f"{question.strip()} {hint}".strip()


def _build_cases(
    *,
    raw_cases: list[RawBatteryCase],
    available_archive_slugs: list[str],
    available_metadata_fields: list[str],
    current_date: str,
) -> list[BatteryCase]:
    code_to_slugs = _build_code_to_slugs(available_archive_slugs)
    built_cases: list[BatteryCase] = []
    global_id = 1
    for raw_case in raw_cases:
        override = CASE_OVERRIDES.get((raw_case.section, raw_case.section_index), SelectorOverride())
        derived_archive_slugs = _extract_archive_slugs(raw_case.example_answer)
        derived_archive_slugs.extend(list(override.extra_archive_slugs))
        derived_archive_slugs.extend(
            _extract_unique_archive_slugs_from_terms(raw_case.example_answer, code_to_slugs=code_to_slugs)
        )
        archive_slugs, missing_archive_slugs = _resolve_archive_slugs(derived_archive_slugs, available_archive_slugs)
        metadata_fields, missing_metadata_fields = _resolve_metadata_fields(
            override.metadata_fields,
            available_metadata_fields,
        )
        if missing_metadata_fields:
            raise RuntimeError(
                "Could not resolve metadata fields "
                f"for {raw_case.section} {raw_case.section_index}: {missing_metadata_fields}"
            )
        metadata_mode = "metadata_first" if (override.use_metadata or metadata_fields) else "auto"
        selector_warnings: list[str] = []
        if missing_archive_slugs:
            selector_warnings.append(f"missing archive slugs: {missing_archive_slugs}")
        selector_question = _build_selector_question(
            question=raw_case.question,
            metadata_mode=metadata_mode,
            archive_slugs=archive_slugs,
            metadata_fields=metadata_fields,
        )
        if metadata_mode != "metadata_first" and (
            override.expects_citations or override.summary_mode == "per_document"
        ):
            selector_question = _append_document_hint(selector_question)
        built_cases.append(
            BatteryCase(
                id=global_id,
                label=f"{_slugify(raw_case.section)}-{raw_case.section_index:02d}",
                section=raw_case.section,
                section_index=raw_case.section_index,
                original_question=raw_case.question,
                selector_question=selector_question,
                example_answer=raw_case.example_answer,
                archive_slugs=tuple(archive_slugs),
                metadata_fields=tuple(metadata_fields),
                metadata_mode=metadata_mode,
                expected_terms=tuple(_extract_expected_terms(raw_case.example_answer)),
                top_k=int(override.top_k),
                candidate_k=int(override.candidate_k),
                min_pages_per_selected_doc=int(override.min_pages_per_selected_doc),
                summary_mode=override.summary_mode,
                allow_inferred_scope=not bool(archive_slugs),
                current_date=current_date,
                selector_warnings=tuple(selector_warnings),
                expects_citations=bool(
                    override.expects_citations
                    or override.summary_mode == "per_document"
                    or (archive_slugs and metadata_mode != "metadata_first")
                ),
            )
        )
        global_id += 1
    return built_cases


def _expected_terms_report(*, answer_text: str, expected_terms: tuple[str, ...]) -> tuple[list[str], list[str]]:
    normalized_answer = _normalize_text(answer_text)
    matched: list[str] = []
    missing: list[str] = []
    for term in expected_terms:
        raw_term = str(term or "").strip()
        if not raw_term:
            continue
        if _term_matches_answer(raw_term, normalized_answer):
            matched.append(raw_term)
        else:
            missing.append(raw_term)
    return matched, missing


def _term_matches_answer(raw_term: str, normalized_answer: str) -> bool:
    normalized_term = _normalize_text(raw_term)
    if not normalized_term:
        return False
    if normalized_term in normalized_answer:
        return True
    if "=" in raw_term:
        left, right = raw_term.split("=", 1)
        return _normalize_text(left) in normalized_answer and _normalize_text(right) in normalized_answer
    if "/" in normalized_term and not re.search(r"https?://|[\\/].*\.(?:pdf|zip)\b", raw_term, re.IGNORECASE):
        parts = [part.strip() for part in normalized_term.split("/") if part.strip()]
        if len(parts) > 1:
            return all(part in normalized_answer for part in parts)
    if normalized_term.startswith("sin "):
        base_term = normalized_term[4:].strip()
        if not base_term:
            return False
        return base_term in normalized_answer and any(
            marker in normalized_answer
            for marker in (
                f"{base_term}: no",
                f"{base_term} = no",
                f"{base_term}: no se indica",
                f"{base_term} no",
            )
        )
    state_match = re.match(r"(.+?)\s+(si|no)$", normalized_term)
    if state_match is not None:
        return state_match.group(1).strip() in normalized_answer and state_match.group(2) in normalized_answer
    amount_match = re.match(r"^([0-9][0-9.,]*)\s+([a-z$]+)$", normalized_term)
    if amount_match is not None:
        return amount_match.group(1) in normalized_answer and amount_match.group(2) in normalized_answer
    return False


def _build_question_payload(case: BatteryCase) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": case.selector_question,
        "allow_inferred_scope": case.allow_inferred_scope,
        "top_k": case.top_k,
        "candidate_k": case.candidate_k,
        "min_pages_per_selected_doc": case.min_pages_per_selected_doc,
        "summary_mode": case.summary_mode,
        "metadata_mode": case.metadata_mode,
        "archive_slugs": list(case.archive_slugs),
        "metadata_fields": list(case.metadata_fields),
        "current_date": case.current_date,
    }
    return payload


def _run_case(
    *,
    case: BatteryCase,
    base_url: str,
    token: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    payload = _build_question_payload(case)
    result = _post_question_with_retries(
        base_url=base_url,
        token=token,
        timeout_seconds=timeout_seconds,
        payload=payload,
    )
    answer_text = ""
    citations: list[dict[str, Any]] = []
    evidence_sources: list[dict[str, Any]] = []
    telemetry: dict[str, Any] = {}
    strategy = ""
    answer_mode = ""
    if isinstance(result.payload, dict):
        answer_text = str(result.payload.get("answer_text") or result.payload.get("answer") or "")
        citations = [item for item in list(result.payload.get("citations") or []) if isinstance(item, dict)]
        evidence_sources = [
            item
            for item in list(result.payload.get("evidence_sources") or result.payload.get("sources") or [])
            if isinstance(item, dict)
        ]
        telemetry = dict(result.payload.get("telemetry") or {})
        strategy = str(result.payload.get("strategy") or "")
        answer_mode = str(result.payload.get("answer_mode") or "")
    matched_terms, missing_terms = _expected_terms_report(answer_text=answer_text, expected_terms=case.expected_terms)
    distinct_files = len(
        {
            str(item.get("name") or item.get("file_name") or "").strip()
            for item in evidence_sources
            if str(item.get("name") or item.get("file_name") or "").strip()
        }
    )
    top_sources = [
        str(item.get("name") or item.get("file_name") or "").strip()
        for item in evidence_sources[:4]
        if str(item.get("name") or item.get("file_name") or "").strip()
    ]
    return {
        "id": case.id,
        "label": case.label,
        "section": case.section,
        "section_index": case.section_index,
        "question": case.original_question,
        "selector_question": case.selector_question,
        "archive_slugs": list(case.archive_slugs),
        "metadata_fields": list(case.metadata_fields),
        "metadata_mode": case.metadata_mode,
        "selector_warnings": list(case.selector_warnings),
        "expected_terms": list(case.expected_terms),
        "status_code": int(result.status_code),
        "elapsed_ms": int(result.elapsed_ms),
        "answer_text": answer_text,
        "answer_preview": _short_text(answer_text, limit=420),
        "citations_count": len(citations),
        "evidence_sources_count": len(evidence_sources),
        "distinct_files": distinct_files,
        "matched_expected_terms": matched_terms,
        "missing_expected_terms": missing_terms,
        "strategy": strategy,
        "answer_mode": answer_mode,
        "telemetry": telemetry,
        "top_sources": top_sources,
        "error_text": str(result.error_text or ""),
        "request_payload": payload,
        "example_answer": case.example_answer,
        "expects_citations": case.expects_citations,
    }


def _post_question_with_retries(
    *,
    base_url: str,
    token: str,
    timeout_seconds: int,
    payload: dict[str, Any],
    max_attempts: int = 3,
) -> HttpResult:
    transient_statuses = {0, 500, 502, 503, 504}
    last_result = HttpResult(status_code=0, payload={}, elapsed_ms=0, error_text="Question call was not attempted.")
    for attempt in range(1, max_attempts + 1):
        last_result = _http_json(
            method="POST",
            url=f"{base_url}/questions/ask",
            timeout_seconds=timeout_seconds,
            body=payload,
            token=token,
        )
        if last_result.status_code not in transient_statuses:
            return last_result
        if attempt < max_attempts:
            sleep(1)
    return last_result


def _build_corpus_snapshot(
    *,
    metadata_rows: list[dict[str, str]],
    files: list[dict[str, Any]],
    available_archive_slugs: list[str],
) -> dict[str, Any]:
    visible_archive_keys = {_normalize_text(value) for value in available_archive_slugs}
    visible_metadata_rows = [
        row for row in metadata_rows if _normalize_text(row.get("file")) in visible_archive_keys
    ]
    state_counter = Counter((row.get("Estado Contrato") or "").strip() or "(blank)" for row in visible_metadata_rows)
    figura_vigente_counter = Counter()
    site_to_contract_ids: dict[str, set[str]] = defaultdict(set)
    for row in visible_metadata_rows:
        if _normalize_text(row.get("Estado Contrato")) == "vigente":
            figura_vigente_counter[str(row.get("Figura Legal") or "").strip()] += 1
        site = str(row.get("Codigo de Sitio") or "").strip()
        contract_id = str(row.get("Id") or "").strip()
        if site and contract_id:
            site_to_contract_ids[site].add(contract_id)
    multi_contract_sites = {
        site: sorted(contract_ids)
        for site, contract_ids in site_to_contract_ids.items()
        if len(contract_ids) > 1
    }
    completed_files = [
        item for item in files if _normalize_text(item.get("status")) == "completed"
    ]
    doc_counts = Counter(
        str(item.get("archive_slug") or "").strip() for item in completed_files if str(item.get("archive_slug") or "").strip()
    )
    return {
        "visible_metadata_rows": len(visible_metadata_rows),
        "state_summary": dict(state_counter),
        "multi_contract_sites": multi_contract_sites,
        "vigente_by_figura_legal": dict(figura_vigente_counter),
        "top_archives_by_pdf_count": doc_counts.most_common(10),
    }


def _build_markdown_report(run_data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# RAG Markdown Selector Battery Report")
    lines.append("")
    lines.append(f"- Fecha UTC: `{run_data['run_at_utc']}`")
    lines.append(f"- Base URL: `{run_data['base_url']}`")
    lines.append(f"- Bateria fuente: `{run_data['battery_path']}`")
    lines.append(
        f"- Scope options: `{run_data['scope_files_count']}` archivos visibles | "
        f"`{run_data['scope_metadata_fields_count']}` campos de metadata"
    )
    lines.append(f"- Documentos completados: `{run_data['completed_count']}`")
    lines.append(f"- Archivos logicos: `{run_data['archive_count']}`")
    lines.append(f"- Preguntas ejecutadas: `{run_data['total_questions']}`")
    lines.append(f"- Exitosas HTTP 200: `{run_data['ok_count']}`")
    lines.append(f"- Fallidas: `{run_data['failed_count']}`")
    lines.append(f"- Tiempo total: `{run_data['total_elapsed_ms']} ms`")
    lines.append(f"- P50: `{run_data['elapsed_p50_ms']} ms` | P95: `{run_data['elapsed_p95_ms']} ms`")
    lines.append(
        f"- Selectores: `@metadata={run_data['metadata_selector_count']}` | "
        f"`/file={run_data['file_selector_count']}` | `/col={run_data['col_selector_count']}`"
    )
    lines.append("")
    lines.append("## Snapshot del corpus")
    lines.append("")
    lines.append(f"- Estados en metadata: `{run_data['state_summary']}`")
    lines.append(f"- Sitios con mas de un ID de contrato: `{run_data['multi_contract_sites']}`")
    lines.append(f"- Contratos vigentes por figura legal: `{run_data['vigente_by_figura_legal']}`")
    lines.append(f"- Top contratos por cantidad de PDFs: `{run_data['top_archives_by_pdf_count']}`")
    lines.append("")
    lines.append("## Resultados por pregunta")
    lines.append("")
    for item in run_data["results"]:
        lines.append(f"### {item['id']:02d}. [{item['section']} {item['section_index']:02d}] {item['question']}")
        lines.append(f"- selector_question: `{item['selector_question']}`")
        lines.append(
            f"- status: `{item['status_code']}` | elapsed: `{item['elapsed_ms']} ms` | "
            f"strategy: `{item['strategy'] or '-'}` | mode: `{item['answer_mode'] or '-'}`"
        )
        lines.append(
            f"- citations: `{item['citations_count']}` | evidence_sources: `{item['evidence_sources_count']}` | "
            f"distinct_files: `{item['distinct_files']}`"
        )
        if item["archive_slugs"]:
            lines.append(f"- scope: `{', '.join(item['archive_slugs'])}`")
        if item["metadata_fields"]:
            lines.append(f"- metadata_fields: `{item['metadata_fields']}`")
        if item["matched_expected_terms"] or item["missing_expected_terms"]:
            lines.append(
                f"- expected_terms_matched: `{item['matched_expected_terms']}` | "
                f"missing: `{item['missing_expected_terms']}`"
            )
        if item["top_sources"]:
            lines.append(f"- top_sources: {', '.join(item['top_sources'])}")
        if item["selector_warnings"]:
            lines.append(f"- selector_warnings: `{item['selector_warnings']}`")
        lines.append(f"- answer_preview: {item['answer_preview']}")
        retrieval_route = str(item.get("telemetry", {}).get("retrieval_route") or "").strip()
        if retrieval_route:
            lines.append(
                f"- telemetry: route=`{retrieval_route}` "
                f"doc_shortlist=`{item['telemetry'].get('doc_shortlist_count')}` "
                f"page_pool=`{item['telemetry'].get('fused_pages_count')}` "
                f"rerank_count=`{item['telemetry'].get('rerank_count')}` "
                f"retrieval_ms=`{item['telemetry'].get('retrieval_total_ms')}`"
            )
        if item["error_text"]:
            lines.append(f"- error: `{item['error_text']}`")
        lines.append("")
    flagged: list[str] = []
    for item in run_data["results"]:
        reasons: list[str] = []
        if item["status_code"] != 200:
            reasons.append(f"HTTP {item['status_code']}")
        if item["missing_expected_terms"]:
            reasons.append(f"missing expected {item['missing_expected_terms']}")
        if item["selector_warnings"]:
            reasons.append(f"selector warnings {item['selector_warnings']}")
        if item["expects_citations"] and item["citations_count"] == 0:
            reasons.append("sin citas en una pregunta document-centric")
        if reasons:
            flagged.append(f"- Q{item['id']:02d} `{item['label']}`: {', '.join(reasons)}.")
    lines.append("## Hallazgos rapidos")
    lines.append("")
    if not flagged:
        lines.append("- No aparecieron alertas automaticas basicas; queda pendiente la validacion humana del contenido.")
    else:
        lines.extend(flagged)
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _write_reports(
    *,
    report_basename: str,
    run_data: dict[str, Any],
    markdown_text: str,
    output_dir: Path,
    downloads_dir: Path,
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{report_basename}.json"
    md_path = output_dir / f"{report_basename}.md"
    download_md_path = downloads_dir / f"{report_basename}.md"
    json_path.write_text(json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_text, encoding="utf-8")
    download_md_path.write_text(markdown_text, encoding="utf-8")
    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "download_md_path": str(download_md_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the markdown QA battery using inline @metadata, /file, and /col selectors."
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--bearer-token", default="")
    parser.add_argument("--battery-path", type=Path, default=DEFAULT_BATTERY_PATH)
    parser.add_argument("--metadata-csv", type=Path, default=DEFAULT_METADATA_CSV)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS_DIR)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--current-date", default=DEFAULT_CURRENT_DATE)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    raw_cases = _parse_battery_markdown(args.battery_path)
    if not raw_cases:
        raise RuntimeError(f"No cases were parsed from {args.battery_path}.")

    token = str(args.bearer_token or "").strip()
    if not token:
        username = str(args.username or "").strip()
        password = str(args.password or "").strip()
        if not username or not password:
            raise RuntimeError("Use --bearer-token or provide both --username and --password.")
        token = _login(
            base_url=args.base_url,
            username=username,
            password=password,
            timeout_seconds=args.timeout_seconds,
        )
    scope_options = _load_scope_options(
        base_url=args.base_url,
        token=token,
        timeout_seconds=args.timeout_seconds,
    )
    available_archive_slugs = [str(item).strip() for item in list(scope_options.get("files") or []) if str(item).strip()]
    available_metadata_fields = [
        str(item).strip() for item in list(scope_options.get("metadata_fields") or []) if str(item).strip()
    ]
    cases = _build_cases(
        raw_cases=raw_cases,
        available_archive_slugs=available_archive_slugs,
        available_metadata_fields=available_metadata_fields,
        current_date=str(args.current_date),
    )
    if args.limit and args.limit > 0:
        cases = cases[: args.limit]
    if args.dry_run:
        preview = [
            {
                "id": case.id,
                "section": case.section,
                "section_index": case.section_index,
                "question": case.original_question,
                "selector_question": case.selector_question,
                "archive_slugs": list(case.archive_slugs),
                "metadata_fields": list(case.metadata_fields),
                "metadata_mode": case.metadata_mode,
                "selector_warnings": list(case.selector_warnings),
            }
            for case in cases
        ]
        print(json.dumps(preview, ensure_ascii=False, indent=2))
        return 0

    files = _list_files(
        base_url=args.base_url,
        token=token,
        timeout_seconds=args.timeout_seconds,
    )
    metadata_rows = _load_metadata_rows(args.metadata_csv)
    completed_files = [item for item in files if _normalize_text(item.get("status")) == "completed"]
    archive_count = len(
        {
            str(item.get("archive_slug") or "").strip()
            for item in completed_files
            if str(item.get("archive_slug") or "").strip()
        }
    )
    results: list[dict[str, Any]] = []
    for case in cases:
        results.append(
            _run_case(
                case=case,
                base_url=args.base_url,
                token=token,
                timeout_seconds=args.timeout_seconds,
            )
        )

    elapsed_values = [int(item["elapsed_ms"]) for item in results]
    snapshot = _build_corpus_snapshot(
        metadata_rows=metadata_rows,
        files=files,
        available_archive_slugs=available_archive_slugs,
    )
    run_data: dict[str, Any] = {
        "run_at_utc": _utc_now_iso(),
        "base_url": args.base_url,
        "battery_path": str(args.battery_path),
        "scope_files_count": len(available_archive_slugs),
        "scope_metadata_fields_count": len(available_metadata_fields),
        "completed_count": len(completed_files),
        "archive_count": archive_count,
        "total_questions": len(results),
        "ok_count": sum(1 for item in results if int(item["status_code"]) == 200),
        "failed_count": sum(1 for item in results if int(item["status_code"]) != 200),
        "total_elapsed_ms": sum(elapsed_values),
        "elapsed_avg_ms": int(mean(elapsed_values)) if elapsed_values else 0,
        "elapsed_p50_ms": _percentile_ms(elapsed_values, 0.50),
        "elapsed_p95_ms": _percentile_ms(elapsed_values, 0.95),
        "metadata_selector_count": sum(1 for case in cases if case.metadata_mode == "metadata_first"),
        "file_selector_count": sum(1 for case in cases if case.archive_slugs),
        "col_selector_count": sum(1 for case in cases if case.metadata_fields),
        "state_summary": snapshot["state_summary"],
        "multi_contract_sites": snapshot["multi_contract_sites"],
        "vigente_by_figura_legal": snapshot["vigente_by_figura_legal"],
        "top_archives_by_pdf_count": snapshot["top_archives_by_pdf_count"],
        "results": results,
    }
    markdown_text = _build_markdown_report(run_data)
    report_basename = f"rag_markdown_selector_battery_{_timestamp_slug()}"
    paths = _write_reports(
        report_basename=report_basename,
        run_data=run_data,
        markdown_text=markdown_text,
        output_dir=args.output_dir,
        downloads_dir=args.downloads_dir,
    )
    print(json.dumps({"report_basename": report_basename, **paths}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
