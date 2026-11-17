from __future__ import annotations

import argparse
import csv
import json
import math
import mimetypes
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter, sleep
from typing import Any
from urllib import error as url_error
from urllib import request as url_request
import uuid


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE_URL = "http://127.0.0.1:8012/api"
DEFAULT_METADATA_CSV = ROOT / ".source" / "info-docs.metadata.csv"
DEFAULT_ARCHIVES = (
    ROOT / ".source" / "RM797_ID_1668.zip",
    ROOT / ".source" / "RM797_ID_5515.zip",
)
DEFAULT_OUTPUT_DIR = ROOT / "apps" / "backend" / "tests" / "reports"
DEFAULT_PREFERRED_FILES = ("RM797_ID_1668", "RM797_ID_5515")
DEFAULT_RUNTIME_UPDATES = {
    "rag": {
        "retrieval.doc_shortlist_scoped": 12,
        "retrieval.doc_shortlist_global": 20,
        "retrieval.page_pool_scoped": 36,
        "retrieval.page_pool_global": 60,
        "retrieval.rerank_scoped": 24,
        "retrieval.rerank_global": 32,
        "ingest.native_text_min_chars": 160,
        "ingest.visual_enrichment_enabled": False,
        "ingest.structured_facts_enabled": False,
    },
}


@dataclass(slots=True)
class HttpResult:
    status_code: int
    payload: Any
    elapsed_ms: int
    error_text: str = ""


@dataclass(slots=True)
class QuerySpec:
    id: int
    category: str
    label: str
    question: str
    file_ids: list[int]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan benchmark for scoped RAG with metadata CSV keyed by `file`.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--token", default="")
    parser.add_argument("--metadata-csv", default=str(DEFAULT_METADATA_CSV))
    parser.add_argument(
        "--archives",
        nargs="*",
        default=[str(path) for path in DEFAULT_ARCHIVES],
        metavar="ZIP",
        help="ZIP archives to upload/process when --upload-and-process is enabled.",
    )
    parser.add_argument(
        "--preferred-files",
        nargs="*",
        default=list(DEFAULT_PREFERRED_FILES),
        metavar="FILE",
        help="Preferred `file` keys from the metadata CSV.",
    )
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--candidate-k", type=int, default=40)
    parser.add_argument("--passes", type=int, default=2, help="2 runs = cold and warm using the same 12 queries.")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--upload-and-process",
        action="store_true",
        help="Upload metadata + ZIPs and wait for process-batch before asking questions.",
    )
    parser.add_argument(
        "--apply-settings",
        action="store_true",
        help="Push the plan retrieval settings before running the benchmark.",
    )
    return parser.parse_args()


def _http_json(
    *,
    method: str,
    url: str,
    timeout_seconds: int,
    body: dict[str, Any] | None = None,
    token: str | None = None,
    headers: dict[str, str] | None = None,
) -> HttpResult:
    final_headers = {"Accept": "application/json"}
    if headers:
        final_headers.update(headers)
    if token:
        final_headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        final_headers.setdefault("Content-Type", "application/json")
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = url_request.Request(url=url, method=method.upper(), headers=final_headers, data=data)
    started = perf_counter()
    try:
        with url_request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw.strip() else {}
            return HttpResult(
                status_code=int(resp.status),
                payload=payload,
                elapsed_ms=int((perf_counter() - started) * 1000),
            )
    except url_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except Exception:
            payload = {"detail": raw}
        return HttpResult(
            status_code=int(exc.code),
            payload=payload,
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_text=str(payload.get("detail") or raw or exc.reason),
        )
    except Exception as exc:
        return HttpResult(
            status_code=0,
            payload={},
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_text=str(exc),
        )


def _encode_multipart(
    *,
    fields: list[tuple[str, str]] | None = None,
    files: list[tuple[str, Path]] | None = None,
) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in list(fields or []):
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"),
                str(value).encode("utf-8"),
                b"\r\n",
            ]
        )
    for field_name, file_path in list(files or []):
        content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        chunks.extend(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{file_path.name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"),
                file_path.read_bytes(),
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _http_multipart(
    *,
    method: str,
    url: str,
    timeout_seconds: int,
    token: str | None = None,
    fields: list[tuple[str, str]] | None = None,
    files: list[tuple[str, Path]] | None = None,
) -> HttpResult:
    body, content_type = _encode_multipart(fields=fields, files=files)
    headers = {
        "Accept": "application/json",
        "Content-Type": content_type,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = url_request.Request(url=url, method=method.upper(), headers=headers, data=body)
    started = perf_counter()
    try:
        with url_request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            payload = json.loads(raw) if raw.strip() else {}
            return HttpResult(
                status_code=int(resp.status),
                payload=payload,
                elapsed_ms=int((perf_counter() - started) * 1000),
            )
    except url_error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except Exception:
            payload = {"detail": raw}
        return HttpResult(
            status_code=int(exc.code),
            payload=payload,
            elapsed_ms=int((perf_counter() - started) * 1000),
            error_text=str(payload.get("detail") or raw or exc.reason),
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
    if not username or not password:
        raise RuntimeError("Username and password are required when no bearer token is supplied.")
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


def _apply_runtime_settings(*, base_url: str, token: str, timeout_seconds: int) -> dict[str, Any]:
    return _require_ok(
        _http_json(
            method="PUT",
            url=f"{base_url}/settings",
            timeout_seconds=timeout_seconds,
            token=token,
            body={"updates": DEFAULT_RUNTIME_UPDATES},
        ),
        message="Updating runtime settings failed",
    )


def _upload_metadata_csv(*, base_url: str, token: str, metadata_csv: Path, timeout_seconds: int) -> dict[str, Any]:
    return _require_ok(
        _http_multipart(
            method="POST",
            url=f"{base_url}/metadata/upload",
            timeout_seconds=timeout_seconds,
            token=token,
            files=[("file", metadata_csv)],
        ),
        message="Metadata upload failed",
    )


def _upload_archives(
    *,
    base_url: str,
    token: str,
    archive_paths: list[Path],
    timeout_seconds: int,
) -> list[str]:
    payload = _require_ok(
        _http_multipart(
            method="POST",
            url=f"{base_url}/files/upload",
            timeout_seconds=timeout_seconds,
            token=token,
            files=[("files", path) for path in archive_paths],
        ),
        message="Archive upload failed",
    )
    saved_files = payload.get("saved_files")
    if not isinstance(saved_files, list) or not saved_files:
        raise RuntimeError("The backend did not return any saved_files after archive upload.")
    return [str(item) for item in saved_files]


def _prepare_upload_plan(
    *,
    base_url: str,
    token: str,
    saved_files: list[str],
    timeout_seconds: int,
) -> dict[str, Any]:
    return _require_ok(
        _http_json(
            method="POST",
            url=f"{base_url}/files/prepare",
            timeout_seconds=timeout_seconds,
            token=token,
            body={
                "saved_files": saved_files,
                "default_document_language": "es",
                "default_access": "private",
            },
        ),
        message="Prepare upload plan failed",
    )


def _process_batch(
    *,
    base_url: str,
    token: str,
    groups_payload: dict[str, Any],
    metadata_upload_id: str | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    groups = list(groups_payload.get("groups") or [])
    items: list[dict[str, Any]] = []
    for group in groups:
        for item in list(group.get("items") or []):
            if not bool(item.get("enabled", True)):
                continue
            items.append(
                {
                    "source_path": str(item.get("source_path") or ""),
                    "source_zip_path": item.get("source_zip_path"),
                    "archive_slug": item.get("archive_slug"),
                    "file_name": str(item.get("file_name") or ""),
                    "group_name": item.get("group_name"),
                    "display_name": item.get("display_name"),
                    "document_language": item.get("document_language") or "es",
                    "access": item.get("access") or "private",
                    "document_code": item.get("document_code"),
                    "document_code_source": item.get("document_code_source"),
                    "enabled": True,
                }
            )
    if not items:
        raise RuntimeError("Prepare response did not contain enabled items for process-batch.")
    return _require_ok(
        _http_json(
            method="POST",
            url=f"{base_url}/files/process-batch",
            timeout_seconds=timeout_seconds,
            token=token,
            body={
                "metadata_upload_id": metadata_upload_id,
                "items": items,
            },
        ),
        message="process-batch failed",
    )


def _wait_for_job(
    *,
    base_url: str,
    token: str,
    job_id: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict[str, Any]:
    started = perf_counter()
    while True:
        payload = _require_ok(
            _http_json(
                method="GET",
                url=f"{base_url}/files/jobs/{job_id}",
                timeout_seconds=max(30, timeout_seconds),
                token=token,
            ),
            message="Polling ingest job failed",
        )
        job = dict(payload.get("job") or {})
        status = str(job.get("status") or "").strip().lower()
        if status in {"completed", "failed"}:
            return payload
        if (perf_counter() - started) > float(timeout_seconds):
            raise RuntimeError(f"Ingest job {job_id} timed out after {timeout_seconds} seconds.")
        sleep(max(0.5, float(poll_seconds)))


def _load_metadata_rows(csv_path: Path) -> dict[str, dict[str, str]]:
    with csv_path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: dict[str, dict[str, str]] = {}
        for row in reader:
            file_key = str(row.get("file") or "").strip()
            if file_key:
                rows[file_key] = {str(key): str(value or "") for key, value in row.items()}
        return rows


def _select_files(rows: dict[str, dict[str, str]], preferred_files: list[str]) -> tuple[str, str]:
    available = sorted(rows.keys(), key=str.lower)
    selected: list[str] = []
    for preferred in preferred_files:
        normalized = str(preferred or "").strip()
        if normalized and normalized in rows and normalized not in selected:
            selected.append(normalized)
    for file_key in available:
        if file_key not in selected:
            selected.append(file_key)
        if len(selected) >= 2:
            break
    if len(selected) < 2:
        raise RuntimeError("At least two metadata rows are required to build the 12-query benchmark.")
    return selected[0], selected[1]


def _metadata_value(row: dict[str, str], *keys: str, default_value: str = "") -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return default_value


def _build_query_specs(
    *,
    archive_a: str,
    archive_b: str,
    row_a: dict[str, str],
    row_b: dict[str, str],
    file_ids_a: list[int],
    file_ids_b: list[int],
) -> list[QuerySpec]:
    site_code = _metadata_value(row_a, "Codigo de Sitio", default_value=archive_a.split("_ID_")[0])
    row_a_id = _metadata_value(row_a, "Id", default_value=archive_a.split("_ID_")[-1])
    state_a = _metadata_value(row_a, "Estado Contrato", default_value="desconocido")
    state_b = _metadata_value(row_b, "Estado Contrato", default_value="desconocido")
    payment_a = _metadata_value(row_a, "Forma de Pago", default_value="desconocido")
    payment_b = _metadata_value(row_b, "Forma de Pago", default_value="desconocido")

    return [
        QuerySpec(
            id=1,
            category="lookup",
            label=f"{archive_a} fechas",
            question=(
                f"En el archivo {archive_a}, valida la Fecha de Término del Contrato "
                f"y la Fecha de Aviso de Término del Contrato con evidencia concreta."
            ),
            file_ids=list(file_ids_a),
        ),
        QuerySpec(
            id=2,
            category="lookup",
            label=f"{archive_a} pago",
            question=(
                f"En el archivo {archive_a}, resume la Forma de Pago, el Pago Anticipado "
                f"y la Renta o Precio Vigente."
            ),
            file_ids=list(file_ids_a),
        ),
        QuerySpec(
            id=3,
            category="lookup",
            label=f"{archive_b} fechas",
            question=(
                f"En el archivo {archive_b}, valida la Fecha de Término del Contrato "
                f"y la Fecha de Aviso de Término del Contrato con evidencia concreta."
            ),
            file_ids=list(file_ids_b),
        ),
        QuerySpec(
            id=4,
            category="lookup",
            label=f"{archive_b} pago",
            question=(
                f"En el archivo {archive_b}, resume la Forma de Pago, el Pago Anticipado "
                f"y la Renta o Precio Vigente."
            ),
            file_ids=list(file_ids_b),
        ),
        QuerySpec(
            id=5,
            category="metadata_filter",
            label=f"{archive_a} estado",
            question=(
                f"Usa la metadata para encontrar el file {archive_a} y confirma si el Estado Contrato es "
                f"{state_a}; además indica la Comuna y la Dirección."
            ),
            file_ids=[],
        ),
        QuerySpec(
            id=6,
            category="metadata_filter",
            label=f"{archive_a} owner",
            question=(
                f"Usa la metadata para ubicar el archivo con Codigo de Sitio {site_code} e Id {row_a_id}; "
                f"luego confirma el Nombre de Propietario Principal y la Dirección."
            ),
            file_ids=[],
        ),
        QuerySpec(
            id=7,
            category="metadata_filter",
            label=f"{archive_b} payment",
            question=(
                f"Filtra por file {archive_b} y revisa si la Forma de Pago reportada en metadata es "
                f"{payment_b}."
            ),
            file_ids=[],
        ),
        QuerySpec(
            id=8,
            category="metadata_filter",
            label=f"{site_code} estados",
            question=(
                f"Entre los archivos con Codigo de Sitio {site_code}, identifica cuál tiene Estado Contrato "
                f"{state_a} y cuál tiene Estado Contrato {state_b}."
            ),
            file_ids=[],
        ),
        QuerySpec(
            id=9,
            category="comparison",
            label="fechas comparadas",
            question=(
                f"Compara {archive_a} y {archive_b} en Fecha de Término del Contrato "
                f"y Fecha de Aviso de Término del Contrato."
            ),
            file_ids=[],
        ),
        QuerySpec(
            id=10,
            category="comparison",
            label="pago comparado",
            question=(
                f"Compara {archive_a} y {archive_b} en Forma de Pago, Pago Anticipado "
                f"y Renta o Precio Vigente."
            ),
            file_ids=[],
        ),
        QuerySpec(
            id=11,
            category="comparison",
            label="owner comparado",
            question=(
                f"Compara {archive_a} y {archive_b} en Nombre de Propietario Principal, "
                f"Nombre Beneficiario y Rut Beneficiario del contrato."
            ),
            file_ids=[],
        ),
        QuerySpec(
            id=12,
            category="comparison",
            label="metadata vs documento",
            question=(
                f"Compara {archive_a} y {archive_b} en Metros cuadrados arrendados, "
                f"Clausula de Acceso Sitio y Cesión a Terceros usando metadata y documento."
            ),
            file_ids=[],
        ),
    ]


def _list_files(*, base_url: str, token: str, timeout_seconds: int) -> list[dict[str, Any]]:
    payload = _require_ok(
        _http_json(
            method="GET",
            url=f"{base_url}/files",
            timeout_seconds=timeout_seconds,
            token=token,
        ),
        message="Listing files failed",
    )
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("The /files payload did not include an `items` list.")
    return [dict(item) for item in items if isinstance(item, dict)]


def _resolve_archive_file_ids(
    *,
    files_payload: list[dict[str, Any]],
    archive_slug: str,
) -> list[int]:
    resolved: list[int] = []
    seen: set[int] = set()
    for item in sorted(
        files_payload,
        key=lambda entry: str(entry.get("updated_at") or ""),
        reverse=True,
    ):
        if str(item.get("archive_slug") or "").strip() != archive_slug:
            continue
        if str(item.get("status") or "").strip().lower() != "completed":
            continue
        file_id = int(item.get("file_id") or 0)
        if file_id <= 0 or file_id in seen:
            continue
        seen.add(file_id)
        resolved.append(file_id)
    return resolved


def _percentile_ms(values: list[int], percentile: float) -> int:
    if not values:
        return 0
    if len(values) == 1:
        return int(values[0])
    ordered = sorted(int(value) for value in values)
    rank = max(0.0, min(1.0, float(percentile))) * (len(ordered) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return int(ordered[lower])
    weight = rank - lower
    interpolated = ordered[lower] + ((ordered[upper] - ordered[lower]) * weight)
    return int(round(interpolated))


def _run_query_pass(
    *,
    base_url: str,
    token: str,
    query_specs: list[QuerySpec],
    timeout_seconds: int,
    top_k: int,
    candidate_k: int,
    pass_label: str,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    pass_started = perf_counter()
    for spec in query_specs:
        response = _http_json(
            method="POST",
            url=f"{base_url}/questions/ask",
            timeout_seconds=timeout_seconds,
            token=token,
            body={
                "question": spec.question,
                "file_ids": list(spec.file_ids),
                "allow_inferred_scope": True,
                "top_k": int(top_k),
                "candidate_k": int(candidate_k),
            },
        )
        payload = response.payload if isinstance(response.payload, dict) else {}
        results.append(
            {
                "id": spec.id,
                "category": spec.category,
                "label": spec.label,
                "question": spec.question,
                "file_ids": list(spec.file_ids),
                "status_code": response.status_code,
                "elapsed_ms": response.elapsed_ms,
                "error": response.error_text,
                "telemetry": dict(payload.get("telemetry") or {}),
                "strategy": str(payload.get("strategy") or ""),
                "answer_preview": str(payload.get("answer_text") or payload.get("answer") or "")[:280],
            }
        )
        print(
            f"[{pass_label}] {spec.id:02d}/12 {spec.category:<15} "
            f"status={response.status_code} elapsed={response.elapsed_ms}ms",
            flush=True,
        )
    elapsed_values = [int(item["elapsed_ms"]) for item in results if int(item["status_code"]) == 200]
    return {
        "label": pass_label,
        "started_at_utc": _utc_now(),
        "elapsed_ms_total": int((perf_counter() - pass_started) * 1000),
        "ok_count": sum(1 for item in results if int(item["status_code"]) == 200),
        "failed_count": sum(1 for item in results if int(item["status_code"]) != 200),
        "p50_ms": _percentile_ms(elapsed_values, 0.50),
        "p95_ms": _percentile_ms(elapsed_values, 0.95),
        "results": results,
    }


def _build_markdown_report(*, payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# RAG Plan Benchmark")
    lines.append("")
    lines.append(f"- Run UTC: `{payload['run_at_utc']}`")
    lines.append(f"- Base URL: `{payload['base_url']}`")
    lines.append(f"- Selected files: `{', '.join(payload['selected_files'])}`")
    lines.append(f"- Upload/process executed: `{payload['upload_and_process']}`")
    lines.append(f"- Settings applied: `{payload['apply_settings']}`")
    if payload.get("metadata_upload_id"):
        lines.append(f"- Metadata upload id: `{payload['metadata_upload_id']}`")
    if payload.get("ingest_job_id"):
        lines.append(f"- Ingest job id: `{payload['ingest_job_id']}`")
    lines.append("")
    lines.append("## Pass Summary")
    lines.append("")
    for pass_result in payload["passes"]:
        lines.append(f"### {pass_result['label']}")
        lines.append(f"- ok: `{pass_result['ok_count']}` | failed: `{pass_result['failed_count']}`")
        lines.append(f"- total_elapsed_ms: `{pass_result['elapsed_ms_total']}`")
        lines.append(f"- p50_ms: `{pass_result['p50_ms']}` | p95_ms: `{pass_result['p95_ms']}`")
        lines.append("")
    lines.append("## Query Results")
    lines.append("")
    for pass_result in payload["passes"]:
        lines.append(f"### {pass_result['label']}")
        lines.append("")
        for item in pass_result["results"]:
            lines.append(
                f"- [{item['id']:02d}] `{item['category']}` {item['label']} | "
                f"status=`{item['status_code']}` | elapsed=`{item['elapsed_ms']} ms` | "
                f"strategy=`{item['strategy']}`"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = _parse_args()
    base_url = str(args.base_url).rstrip("/")
    metadata_csv = Path(args.metadata_csv)
    if not metadata_csv.is_absolute():
        metadata_csv = ROOT / metadata_csv
    if not metadata_csv.exists():
        raise SystemExit(f"Metadata CSV not found: {metadata_csv}")

    archive_paths: list[Path] = []
    for raw_path in list(args.archives or []):
        path = Path(raw_path)
        if not path.is_absolute():
            path = ROOT / path
        if path.exists():
            archive_paths.append(path)

    token = str(args.token or "").strip()
    if not token:
        token = _login(
            base_url=base_url,
            username=str(args.username or "").strip(),
            password=str(args.password or "").strip(),
            timeout_seconds=max(30, int(args.timeout_seconds)),
        )

    apply_settings_payload: dict[str, Any] | None = None
    if bool(args.apply_settings):
        print("[INFO] Applying runtime settings for the plan benchmark...", flush=True)
        apply_settings_payload = _apply_runtime_settings(
            base_url=base_url,
            token=token,
            timeout_seconds=max(30, int(args.timeout_seconds)),
        )

    metadata_rows = _load_metadata_rows(metadata_csv)
    archive_a, archive_b = _select_files(metadata_rows, [str(item) for item in list(args.preferred_files or [])])
    selected_files = [archive_a, archive_b]
    metadata_upload_payload: dict[str, Any] | None = None
    prepare_payload: dict[str, Any] | None = None
    process_payload: dict[str, Any] | None = None
    job_status_payload: dict[str, Any] | None = None

    if bool(args.upload_and_process):
        print("[INFO] Uploading metadata CSV...", flush=True)
        metadata_upload_payload = _upload_metadata_csv(
            base_url=base_url,
            token=token,
            metadata_csv=metadata_csv,
            timeout_seconds=max(30, int(args.timeout_seconds)),
        )
        selected_archives = [
            path
            for path in archive_paths
            if path.stem in set(selected_files)
        ]
        if len(selected_archives) < 2:
            raise RuntimeError(
                "The selected archive pair was not found on disk. "
                f"Expected ZIPs for {selected_files!r}."
            )
        print("[INFO] Uploading selected ZIP archives...", flush=True)
        saved_files = _upload_archives(
            base_url=base_url,
            token=token,
            archive_paths=selected_archives,
            timeout_seconds=max(60, int(args.timeout_seconds)),
        )
        print("[INFO] Preparing upload plan...", flush=True)
        prepare_payload = _prepare_upload_plan(
            base_url=base_url,
            token=token,
            saved_files=saved_files,
            timeout_seconds=max(60, int(args.timeout_seconds)),
        )
        print("[INFO] Starting process-batch...", flush=True)
        process_payload = _process_batch(
            base_url=base_url,
            token=token,
            groups_payload=prepare_payload,
            metadata_upload_id=(
                str(metadata_upload_payload.get("metadata_upload_id") or "").strip()
                if metadata_upload_payload
                else None
            ),
            timeout_seconds=max(60, int(args.timeout_seconds)),
        )
        job_id = str(((process_payload.get("job") or {}) if process_payload else {}).get("job_id") or "").strip()
        if not job_id:
            raise RuntimeError("process-batch did not return a job_id.")
        print(f"[INFO] Waiting for ingest job {job_id}...", flush=True)
        job_status_payload = _wait_for_job(
            base_url=base_url,
            token=token,
            job_id=job_id,
            timeout_seconds=max(600, int(args.timeout_seconds)),
            poll_seconds=float(args.poll_seconds),
        )

    files_payload = _list_files(
        base_url=base_url,
        token=token,
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )
    file_ids_a = _resolve_archive_file_ids(files_payload=files_payload, archive_slug=archive_a)
    file_ids_b = _resolve_archive_file_ids(files_payload=files_payload, archive_slug=archive_b)
    if not file_ids_a or not file_ids_b:
        raise RuntimeError(
            "Completed files for the selected archive slugs were not found. "
            f"{archive_a} -> {file_ids_a}, {archive_b} -> {file_ids_b}"
        )

    query_specs = _build_query_specs(
        archive_a=archive_a,
        archive_b=archive_b,
        row_a=metadata_rows[archive_a],
        row_b=metadata_rows[archive_b],
        file_ids_a=file_ids_a,
        file_ids_b=file_ids_b,
    )

    passes: list[dict[str, Any]] = []
    for index in range(max(1, int(args.passes))):
        pass_label = "cold" if index == 0 else f"warm-{index}"
        passes.append(
            _run_query_pass(
                base_url=base_url,
                token=token,
                query_specs=query_specs,
                timeout_seconds=max(60, int(args.timeout_seconds)),
                top_k=max(1, int(args.top_k)),
                candidate_k=max(1, int(args.candidate_k)),
                pass_label=pass_label,
            )
        )

    payload = {
        "run_at_utc": _utc_now(),
        "base_url": base_url,
        "selected_files": selected_files,
        "selected_file_ids": {
            archive_a: file_ids_a,
            archive_b: file_ids_b,
        },
        "apply_settings": bool(args.apply_settings),
        "upload_and_process": bool(args.upload_and_process),
        "metadata_csv": str(metadata_csv),
        "metadata_upload_id": (
            str(metadata_upload_payload.get("metadata_upload_id") or "").strip()
            if metadata_upload_payload
            else ""
        ),
        "ingest_job_id": (
            str(((process_payload.get("job") or {}) if process_payload else {}).get("job_id") or "").strip()
        ),
        "settings_response": apply_settings_payload,
        "metadata_upload_response": metadata_upload_payload,
        "prepare_response": prepare_payload,
        "process_response": process_payload,
        "job_status_response": job_status_payload,
        "passes": passes,
    }

    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"rag_plan_benchmark_{archive_a}_{archive_b}_{stamp}.json"
    md_path = output_dir / f"rag_plan_benchmark_{archive_a}_{archive_b}_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_build_markdown_report(payload=payload), encoding="utf-8")

    print(f"[REPORT] json={json_path}", flush=True)
    print(f"[REPORT] md={md_path}", flush=True)
    for pass_result in passes:
        print(
            f"[SUMMARY] {pass_result['label']} ok={pass_result['ok_count']}/12 "
            f"p50={pass_result['p50_ms']}ms p95={pass_result['p95_ms']}ms",
            flush=True,
        )
    return 0 if all(int(pass_result["failed_count"]) == 0 for pass_result in passes) else 1


if __name__ == "__main__":
    raise SystemExit(main())
