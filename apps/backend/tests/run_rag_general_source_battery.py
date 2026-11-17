from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from statistics import mean
from time import perf_counter
from typing import Any
import unicodedata
from urllib import error as url_error
from urllib import request as url_request


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE_URL = "http://127.0.0.1:8012/api"
DEFAULT_METADATA_CSV = ROOT / ".source" / "info-docs.metadata.csv"
DEFAULT_PLAN_JSON = ROOT / "output" / "runtime" / "reprocess_plan_all_source.json"
DEFAULT_REPORTS_DIR = ROOT / "apps" / "backend" / "tests" / "reports"
DEFAULT_DOWNLOADS_DIR = Path.home() / "Downloads"
DEFAULT_EXPECTED_COMPLETED = 90
DEFAULT_TIMEOUT_SECONDS = 240


@dataclass(slots=True)
class HttpResult:
    status_code: int
    payload: Any
    elapsed_ms: int
    error_text: str = ""


@dataclass(slots=True)
class QuestionSpec:
    id: int
    label: str
    category: str
    question: str
    scope_archive_slugs: tuple[str, ...] = ()
    expected_terms: tuple[str, ...] = ()
    top_k: int = 8
    candidate_k: int = 48
    min_pages_per_selected_doc: int = 0
    summary_mode: str = "default"
    allow_inferred_scope: bool = True


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _normalize_text(value: object | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower().strip()
    return " ".join(normalized.split())


def _short_text(value: object | None, *, limit: int = 360) -> str:
    compact = " ".join(str(value or "").split())
    return compact if len(compact) <= limit else compact[: limit - 3] + "..."


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


def _load_metadata_rows(metadata_csv: Path) -> list[dict[str, str]]:
    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        first_field = reader.fieldnames[0].strip() if reader.fieldnames else ""
        if first_field != "file":
            raise RuntimeError(f"Metadata CSV must start with 'file'. Found: {first_field!r}")
        return [{str(key): str(value or "").strip() for key, value in row.items() if key} for row in reader]


def _load_plan_items(plan_json: Path) -> list[dict[str, Any]]:
    payload = json.loads(plan_json.read_text(encoding="utf-8"))
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError(f"{plan_json} does not contain an items list.")
    return [dict(item) for item in items if isinstance(item, dict)]


def _build_expected_context(*, metadata_rows: list[dict[str, str]], plan_items: list[dict[str, Any]]) -> dict[str, Any]:
    metadata_by_file = {
        str(row.get("file") or "").strip(): row
        for row in metadata_rows
        if str(row.get("file") or "").strip()
    }
    state_counter = Counter((row.get("Estado Contrato") or "").strip() or "(blank)" for row in metadata_rows)
    figura_vigente_counter = Counter()
    for row in metadata_rows:
        if _normalize_text(row.get("Estado Contrato")) == "vigente":
            figura_vigente_counter[str(row.get("Figura Legal") or "").strip()] += 1
    site_to_contract_ids: dict[str, set[str]] = defaultdict(set)
    for row in metadata_rows:
        site = str(row.get("Codigo de Sitio") or "").strip()
        contract_id = str(row.get("Id") or "").strip()
        if site and contract_id:
            site_to_contract_ids[site].add(contract_id)
    multi_contract_sites = {
        site: sorted(contract_ids)
        for site, contract_ids in site_to_contract_ids.items()
        if len(contract_ids) > 1
    }
    doc_counts = Counter(str(item.get("archive_slug") or "").strip() for item in plan_items if str(item.get("archive_slug") or "").strip())
    top_archives = doc_counts.most_common(8)
    return {
        "metadata_by_file": metadata_by_file,
        "state_counter": dict(state_counter),
        "vigente_by_figura_legal": dict(figura_vigente_counter),
        "multi_contract_sites": multi_contract_sites,
        "doc_counts_by_archive": dict(doc_counts),
        "top_archives_by_pdf_count": top_archives,
    }


def _build_questions(context: dict[str, Any]) -> list[QuestionSpec]:
    metadata_by_file = context["metadata_by_file"]
    la122_3979 = metadata_by_file["LA122_ID_3979"]
    rm797_5515 = metadata_by_file["RM797_ID_5515"]
    return [
        QuestionSpec(
            id=1,
            label="sites-multi-contract-id",
            category="analytics",
            question=(
                "Usando toda la metadata cargada, ¿qué sitios tienen más de un ID de contrato? "
                "Devuelve el código de sitio y la lista de IDs."
            ),
            expected_terms=("LA122", "RM797"),
            top_k=10,
            candidate_k=60,
        ),
        QuestionSpec(
            id=2,
            label="contract-state-counts",
            category="analytics",
            question=(
                "Usando toda la metadata cargada, ¿cuántos contratos están vigentes, vencidos o terminados? "
                "Si existen registros sin estado, repórtalos aparte."
            ),
            expected_terms=("16", "1", "vigente", "vencido", "terminado"),
            top_k=10,
            candidate_k=60,
        ),
        QuestionSpec(
            id=3,
            label="contracts-most-document-versions",
            category="analytics",
            question=(
                "Considerando todos los archivos cargados, ¿qué contratos tienen más versiones documentales o PDFs "
                "asociados? Ordénalos de mayor a menor e indica cuántos documentos tiene cada uno."
            ),
            expected_terms=("AT565", "RM797", "11", "8"),
            top_k=10,
            candidate_k=60,
        ),
        QuestionSpec(
            id=4,
            label="metadata-document-differences",
            category="analytics",
            question=(
                "Comparando metadata CSV contra los documentos procesados, ¿en qué contratos detectas diferencias, "
                "vacíos o contradicciones relevantes? Prioriza estado, cesión a terceros, acceso, renta y partes."
            ),
            top_k=10,
            candidate_k=60,
        ),
        QuestionSpec(
            id=5,
            label="vigent-entel-pcs-count",
            category="analytics",
            question=(
                "Usando toda la metadata cargada, ¿cuántos contratos vigentes fueron firmados por ENTEL PCS? "
                "Si puedes, contrástalo con la evidencia documental recuperada."
            ),
            expected_terms=("13", "ENTEL PCS"),
            top_k=10,
            candidate_k=60,
        ),
        QuestionSpec(
            id=6,
            label="la122-owner-rut",
            category="operational",
            question="Para el sitio/contrato LA122_ID_3979, ¿cuál es el RUT del propietario?",
            scope_archive_slugs=("LA122_ID_3979",),
            expected_terms=(str(la122_3979.get("RUT Propietario Principal") or ""),),
            top_k=6,
            candidate_k=24,
            min_pages_per_selected_doc=1,
        ),
        QuestionSpec(
            id=7,
            label="rm797-beneficiary",
            category="operational",
            question="Para el sitio/contrato RM797_ID_5515, ¿quién recibe la renta y cuál es su RUT?",
            scope_archive_slugs=("RM797_ID_5515",),
            expected_terms=(
                str(rm797_5515.get("Nombre Beneficiario") or ""),
                str(rm797_5515.get("Rut Beneficiario del contrato") or ""),
            ),
            top_k=6,
            candidate_k=24,
            min_pages_per_selected_doc=1,
        ),
        QuestionSpec(
            id=8,
            label="rm797-version-count",
            category="operational",
            question=(
                "Para el sitio/contrato RM797_ID_5515, ¿cuántas modificaciones o versiones documentales tiene el "
                "contrato y cuáles son esos documentos?"
            ),
            scope_archive_slugs=("RM797_ID_5515",),
            top_k=8,
            candidate_k=30,
            min_pages_per_selected_doc=1,
            summary_mode="per_document",
        ),
        QuestionSpec(
            id=9,
            label="la122-access-clause",
            category="operational",
            question=(
                "Para el sitio/contrato LA122_ID_3979, ¿qué dice la última modificación sobre el acceso al terreno?"
            ),
            scope_archive_slugs=("LA122_ID_3979",),
            top_k=8,
            candidate_k=30,
            min_pages_per_selected_doc=1,
            summary_mode="per_document",
        ),
        QuestionSpec(
            id=10,
            label="la122-assignment-clause",
            category="operational",
            question=(
                "Para el sitio/contrato LA122_ID_3979, ¿qué dice el último contrato vigente sobre cesión a terceros?"
            ),
            scope_archive_slugs=("LA122_ID_3979",),
            top_k=8,
            candidate_k=30,
            min_pages_per_selected_doc=1,
            summary_mode="per_document",
        ),
    ]


def _resolve_scope_file_ids(
    *,
    files: list[dict[str, Any]],
    scope_archive_slugs: tuple[str, ...],
) -> list[int]:
    scope_normalized = {_normalize_text(item) for item in scope_archive_slugs if str(item).strip()}
    if not scope_normalized:
        return []
    file_ids = [
        int(item.get("file_id") or 0)
        for item in files
        if int(item.get("file_id") or 0) > 0
        and _normalize_text(item.get("archive_slug")) in scope_normalized
        and _normalize_text(item.get("status")) == "completed"
    ]
    return sorted({file_id for file_id in file_ids if file_id > 0})


def _expected_terms_report(*, answer_text: str, expected_terms: tuple[str, ...]) -> tuple[list[str], list[str]]:
    normalized_answer = _normalize_text(answer_text)
    matched: list[str] = []
    missing: list[str] = []
    for term in expected_terms:
        raw_term = str(term or "").strip()
        if not raw_term:
            continue
        if _normalize_text(raw_term) in normalized_answer:
            matched.append(raw_term)
        else:
            missing.append(raw_term)
    return matched, missing


def _build_question_payload(*, question: QuestionSpec, scope_file_ids: list[int]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "question": question.question,
        "file_ids": scope_file_ids,
        "allow_inferred_scope": question.allow_inferred_scope,
        "top_k": question.top_k,
        "candidate_k": question.candidate_k,
        "min_pages_per_selected_doc": question.min_pages_per_selected_doc,
        "summary_mode": question.summary_mode,
    }
    return payload


def _ensure_expected_completed(files: list[dict[str, Any]], expected_completed: int) -> tuple[int, dict[str, int]]:
    status_counter = Counter(_normalize_text(item.get("status")) or "(blank)" for item in files)
    completed = int(status_counter.get("completed", 0))
    if completed < expected_completed:
        raise RuntimeError(
            f"Expected at least {expected_completed} completed files before running the battery. "
            f"Found {completed}. Status summary: {dict(status_counter)}"
        )
    return completed, dict(status_counter)


def _run_question(
    *,
    base_url: str,
    token: str,
    timeout_seconds: int,
    question: QuestionSpec,
    files: list[dict[str, Any]],
) -> dict[str, Any]:
    scope_file_ids = _resolve_scope_file_ids(files=files, scope_archive_slugs=question.scope_archive_slugs)
    if question.scope_archive_slugs and not scope_file_ids:
        raise RuntimeError(
            f"Question {question.id} requires completed files for {question.scope_archive_slugs}, but none were found."
        )
    payload = _build_question_payload(question=question, scope_file_ids=scope_file_ids)
    result = _http_json(
        method="POST",
        url=f"{base_url}/questions/ask",
        timeout_seconds=timeout_seconds,
        body=payload,
        token=token,
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
            item for item in list(result.payload.get("evidence_sources") or result.payload.get("sources") or [])
            if isinstance(item, dict)
        ]
        telemetry = dict(result.payload.get("telemetry") or {})
        strategy = str(result.payload.get("strategy") or "")
        answer_mode = str(result.payload.get("answer_mode") or "")
    matched_terms, missing_terms = _expected_terms_report(answer_text=answer_text, expected_terms=question.expected_terms)
    distinct_files = len(
        {
            str(item.get("name") or item.get("file_name") or "").strip()
            for item in evidence_sources
            if str(item.get("name") or item.get("file_name") or "").strip()
        }
    )
    top_sources = [
        str(item.get("name") or "").strip()
        for item in evidence_sources[:4]
        if str(item.get("name") or "").strip()
    ]
    return {
        "id": question.id,
        "label": question.label,
        "category": question.category,
        "question": question.question,
        "scope_archive_slugs": list(question.scope_archive_slugs),
        "scope_file_ids": scope_file_ids,
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
    }


def _build_markdown_report(*, run_data: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# RAG General Source Battery Report")
    lines.append("")
    lines.append(f"- Fecha UTC: `{run_data['run_at_utc']}`")
    lines.append(f"- Base URL: `{run_data['base_url']}`")
    lines.append(f"- Documentos completados: `{run_data['completed_count']}` / `{run_data['expected_completed']}`")
    lines.append(f"- Archivos lógicos (ZIPs/archives): `{run_data['archive_count']}`")
    lines.append(f"- Preguntas ejecutadas: `{run_data['total_questions']}`")
    lines.append(f"- Exitosas HTTP 200: `{run_data['ok_count']}`")
    lines.append(f"- Fallidas: `{run_data['failed_count']}`")
    lines.append(f"- Tiempo total: `{run_data['total_elapsed_ms']} ms`")
    lines.append(f"- P50: `{run_data['elapsed_p50_ms']} ms` | P95: `{run_data['elapsed_p95_ms']} ms`")
    lines.append("")
    lines.append("## Snapshot del corpus")
    lines.append("")
    lines.append(f"- Estados en metadata: `{run_data['state_summary']}`")
    lines.append(f"- Sitios con más de un ID de contrato: `{run_data['multi_contract_sites']}`")
    lines.append(f"- Contratos vigentes por figura legal: `{run_data['vigente_by_figura_legal']}`")
    lines.append(f"- Top contratos por cantidad de PDFs: `{run_data['top_archives_by_pdf_count']}`")
    lines.append("")
    lines.append("## Resultados por pregunta")
    lines.append("")
    for item in run_data["results"]:
        lines.append(f"### {item['id']:02d}. {item['question']}")
        lines.append(
            f"- status: `{item['status_code']}` | elapsed: `{item['elapsed_ms']} ms` | "
            f"strategy: `{item['strategy'] or '-'}` | mode: `{item['answer_mode'] or '-'}`"
        )
        lines.append(
            f"- citations: `{item['citations_count']}` | evidence_sources: `{item['evidence_sources_count']}` | "
            f"distinct_files: `{item['distinct_files']}`"
        )
        if item["scope_archive_slugs"]:
            lines.append(f"- scope: `{', '.join(item['scope_archive_slugs'])}`")
        if item["matched_expected_terms"] or item["missing_expected_terms"]:
            lines.append(
                f"- expected_terms_matched: `{item['matched_expected_terms']}` | "
                f"missing: `{item['missing_expected_terms']}`"
            )
        if item["top_sources"]:
            lines.append(f"- top_sources: {', '.join(item['top_sources'])}")
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
    flagged = [
        item
        for item in run_data["results"]
        if item["status_code"] != 200 or item["missing_expected_terms"] or item["citations_count"] == 0
    ]
    lines.append("## Hallazgos rápidos")
    lines.append("")
    if not flagged:
        lines.append("- No aparecieron alertas automáticas básicas; queda pendiente la validación humana del contenido.")
    else:
        for item in flagged:
            reasons: list[str] = []
            if item["status_code"] != 200:
                reasons.append(f"HTTP {item['status_code']}")
            if item["missing_expected_terms"]:
                reasons.append(f"missing expected {item['missing_expected_terms']}")
            if item["citations_count"] == 0:
                reasons.append("sin citas")
            lines.append(f"- Q{item['id']:02d} `{item['label']}`: {', '.join(reasons)}.")
    lines.append("")
    return "\n".join(lines).strip() + "\n"


def _write_reports(*, report_basename: str, run_data: dict[str, Any], markdown_text: str, output_dir: Path, downloads_dir: Path) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    downloads_dir.mkdir(parents=True, exist_ok=True)
    json_name = f"{report_basename}.json"
    md_name = f"{report_basename}.md"
    json_path = output_dir / json_name
    md_path = output_dir / md_name
    download_md_path = downloads_dir / md_name
    json_path.write_text(json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(markdown_text, encoding="utf-8")
    download_md_path.write_text(markdown_text, encoding="utf-8")
    return {
        "json_path": str(json_path),
        "md_path": str(md_path),
        "download_md_path": str(download_md_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a 10-question RAG battery over the complete local .source corpus.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--metadata-csv", type=Path, default=DEFAULT_METADATA_CSV)
    parser.add_argument("--plan-json", type=Path, default=DEFAULT_PLAN_JSON)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--downloads-dir", type=Path, default=DEFAULT_DOWNLOADS_DIR)
    parser.add_argument("--expected-completed", type=int, default=DEFAULT_EXPECTED_COMPLETED)
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    args = parser.parse_args()

    metadata_rows = _load_metadata_rows(args.metadata_csv)
    plan_items = _load_plan_items(args.plan_json)
    context = _build_expected_context(metadata_rows=metadata_rows, plan_items=plan_items)

    token = _login(
        base_url=args.base_url,
        username=args.username,
        password=args.password,
        timeout_seconds=args.timeout_seconds,
    )
    files = _list_files(base_url=args.base_url, token=token, timeout_seconds=args.timeout_seconds)
    completed_count, status_summary = _ensure_expected_completed(files, args.expected_completed)
    questions = _build_questions(context)

    started = perf_counter()
    results = [
        _run_question(
            base_url=args.base_url,
            token=token,
            timeout_seconds=args.timeout_seconds,
            question=question,
            files=files,
        )
        for question in questions
    ]
    total_elapsed_ms = int((perf_counter() - started) * 1000)

    elapsed_values = [int(item["elapsed_ms"]) for item in results]
    ok_count = sum(1 for item in results if int(item["status_code"]) == 200)
    failed_count = len(results) - ok_count
    archive_count = len(
        {
            str(item.get("archive_slug") or "").strip()
            for item in files
            if str(item.get("archive_slug") or "").strip()
        }
    )
    run_data = {
        "run_at_utc": _utc_now(),
        "base_url": args.base_url,
        "expected_completed": args.expected_completed,
        "completed_count": completed_count,
        "status_summary": status_summary,
        "archive_count": archive_count,
        "total_questions": len(results),
        "ok_count": ok_count,
        "failed_count": failed_count,
        "total_elapsed_ms": total_elapsed_ms,
        "elapsed_avg_ms": round(mean(elapsed_values), 2) if elapsed_values else 0,
        "elapsed_p50_ms": _percentile_ms(elapsed_values, 0.50),
        "elapsed_p95_ms": _percentile_ms(elapsed_values, 0.95),
        "state_summary": context["state_counter"],
        "vigente_by_figura_legal": context["vigente_by_figura_legal"],
        "multi_contract_sites": context["multi_contract_sites"],
        "top_archives_by_pdf_count": context["top_archives_by_pdf_count"],
        "results": results,
    }
    markdown_text = _build_markdown_report(run_data=run_data)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_paths = _write_reports(
        report_basename=f"rag_general_source_battery_{timestamp}",
        run_data=run_data,
        markdown_text=markdown_text,
        output_dir=args.output_dir,
        downloads_dir=args.downloads_dir,
    )

    print(json.dumps({**report_paths, "summary": {key: run_data[key] for key in ("ok_count", "failed_count", "elapsed_p50_ms", "elapsed_p95_ms")}}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
