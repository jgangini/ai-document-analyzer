from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from apps.backend.tests.run_rag_archive_compound_battery import (
    DEFAULT_BASE_URL,
    DEFAULT_DOWNLOADS_DIR,
    DEFAULT_METADATA_CSV,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TIMEOUT_SECONDS,
    QuestionSpec,
    _build_ai041_questions,
    _build_findings,
    _build_question_consistency,
    _copy_report_to_downloads,
    _http_json,
    _list_completed_files,
    _load_metadata_row,
    _login,
    _normalize_text,
    _percentile_ms,
    _require_ok,
    _run_pass,
)


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ARCHIVES = (
    "AI041_ID_49",
    "AT565_ID_3820",
    "RM797_ID_1668",
    "RM797_ID_5515",
)
DEFAULT_PASS_LABELS = ("cold", "warm-1")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a large-corpus RAG battery across multiple folios.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--metadata-csv", default=str(DEFAULT_METADATA_CSV))
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--token", default="")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR))
    parser.add_argument("--skip-downloads-copy", action="store_true")
    parser.add_argument(
        "--archives",
        nargs="*",
        default=list(DEFAULT_ARCHIVES),
        metavar="ARCHIVE",
        help="Archive slugs that must be completed before running the battery.",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=len(DEFAULT_PASS_LABELS),
        help="How many passes to execute (2 = cold + warm-1).",
    )
    parser.add_argument(
        "--scope",
        choices=("all-completed", "archives"),
        default="all-completed",
        help=(
            "Query scope for the battery. "
            "`all-completed` uses every completed file available for the user to stress the larger corpus; "
            "`archives` only scopes queries to the required benchmark archives."
        ),
    )
    return parser.parse_args()


def _metadata_value(row: dict[str, str], *keys: str, default_value: str = "") -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return default_value


def _short_name(file_name: str) -> str:
    return Path(str(file_name or "").strip()).name


def _pick_source_names(file_names: list[str], *, count: int = 3) -> tuple[str, ...]:
    selected = [
        _short_name(name)
        for name in list(file_names or [])
        if _short_name(name)
    ]
    deduped: list[str] = []
    seen: set[str] = set()
    for item in selected:
        key = item.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
        if len(deduped) >= max(1, int(count)):
            break
    return tuple(deduped)


def _build_same_archive_specs(
    *,
    start_id: int,
    archive_slug: str,
    metadata_row: dict[str, str],
    file_names: list[str],
) -> list[QuestionSpec]:
    source_names = _pick_source_names(file_names, count=3)
    if len(source_names) < 3:
        raise RuntimeError(f"Archive {archive_slug} requires at least 3 completed documents for same-folio checks.")

    state = _metadata_value(metadata_row, "Estado Contrato", default_value="desconocido")
    payment = _metadata_value(metadata_row, "Forma de Pago", default_value="desconocido")
    owner = _metadata_value(metadata_row, "Nombre de Propietario Principal", default_value="desconocido")
    beneficiary = _metadata_value(metadata_row, "Nombre Beneficiario", default_value="desconocido")
    comuna = _metadata_value(metadata_row, "Comuna", default_value="desconocida")
    address = _metadata_value(metadata_row, "Dirección", "Direccion", default_value="desconocida")
    doc_a, doc_b, doc_c = source_names

    return [
        QuestionSpec(
            id=start_id,
            label=f"{archive_slug.lower()} timeline",
            category="same_archive",
            question=(
                f"Reconstruye la línea de tiempo documental de {archive_slug} usando {doc_a}, {doc_b} y {doc_c}; "
                f"identifica documento base, modificaciones o avisos y conecta el resultado con el Estado Contrato "
                f"{state}."
            ),
            expected_terms=tuple(item for item in (state,) if item),
            expected_source_fragments=source_names,
        ),
        QuestionSpec(
            id=start_id + 1,
            label=f"{archive_slug.lower()} parties",
            category="same_archive",
            question=(
                f"Compara {doc_a}, {doc_b} y {doc_c} dentro de {archive_slug}; resume cómo cambian propietario, "
                f"beneficiario y forma de pago frente a la metadata actual."
            ),
            expected_terms=tuple(item for item in (owner, beneficiary, payment) if item),
            expected_source_fragments=source_names,
        ),
        QuestionSpec(
            id=start_id + 2,
            label=f"{archive_slug.lower()} current-state",
            category="same_archive",
            question=(
                f"Usando metadata y documentos de {archive_slug}, valida si el Estado Contrato es {state}, si la "
                f"Forma de Pago es {payment}, y confirma Comuna {comuna} y Dirección {address} con evidencia."
            ),
            expected_terms=tuple(item for item in (state, payment, comuna, address) if item),
            expected_source_fragments=source_names[:2],
            expected_strategy="facts-first",
        ),
    ]


def _build_pair_specs(
    *,
    start_id: int,
    archive_a: str,
    archive_b: str,
    row_a: dict[str, str],
    row_b: dict[str, str],
    file_names_a: list[str],
    file_names_b: list[str],
) -> list[QuestionSpec]:
    source_a = _pick_source_names(file_names_a, count=2)
    source_b = _pick_source_names(file_names_b, count=2)
    source_fragments = source_a + source_b

    state_a = _metadata_value(row_a, "Estado Contrato", default_value="desconocido")
    state_b = _metadata_value(row_b, "Estado Contrato", default_value="desconocido")
    payment_a = _metadata_value(row_a, "Forma de Pago", default_value="desconocido")
    payment_b = _metadata_value(row_b, "Forma de Pago", default_value="desconocido")
    owner_a = _metadata_value(row_a, "Nombre de Propietario Principal", default_value="desconocido")
    owner_b = _metadata_value(row_b, "Nombre de Propietario Principal", default_value="desconocido")
    beneficiary_a = _metadata_value(row_a, "Nombre Beneficiario", default_value="desconocido")
    beneficiary_b = _metadata_value(row_b, "Nombre Beneficiario", default_value="desconocido")
    end_a = _metadata_value(row_a, "Fecha de Término del Contrato", "Fecha de Termino del Contrato", default_value="")
    end_b = _metadata_value(row_b, "Fecha de Término del Contrato", "Fecha de Termino del Contrato", default_value="")

    return [
        QuestionSpec(
            id=start_id,
            label="rm797 state-date",
            category="cross_archive",
            question=(
                f"Compara {archive_a} y {archive_b} en Estado Contrato y Fecha de Término del Contrato; indica "
                "si ambos casos parecen vigentes o si hay diferencias claras entre los dos folios."
            ),
            expected_terms=tuple(item for item in (state_a, state_b, end_a, end_b) if item),
            expected_source_fragments=source_fragments,
            expected_strategy="facts-first",
        ),
        QuestionSpec(
            id=start_id + 1,
            label="rm797 payment",
            category="cross_archive",
            question=(
                f"Compara {archive_a} y {archive_b} en Forma de Pago, Pago Anticipado y Renta o Precio Vigente; "
                "resume coincidencias y diferencias relevantes."
            ),
            expected_terms=tuple(item for item in (payment_a, payment_b) if item),
            expected_source_fragments=source_fragments,
        ),
        QuestionSpec(
            id=start_id + 2,
            label="rm797 parties",
            category="cross_archive",
            question=(
                f"Compara {archive_a} y {archive_b} en Nombre de Propietario Principal y Nombre Beneficiario; "
                "si los documentos contradicen la metadata en alguno de los dos casos, dilo explícitamente."
            ),
            expected_terms=tuple(item for item in (owner_a, owner_b, beneficiary_a, beneficiary_b) if item),
            expected_source_fragments=source_fragments,
        ),
        QuestionSpec(
            id=start_id + 3,
            label="rm797 metadata-vs-docs",
            category="cross_archive",
            question=(
                f"Compara {archive_a} y {archive_b} en metros cuadrados arrendados, cláusula de acceso al sitio y "
                "cesión a terceros usando metadata y documento; destaca cualquier discrepancia real entre folios."
            ),
            expected_source_fragments=source_fragments,
        ),
    ]


def _build_question_specs(
    *,
    metadata_rows: dict[str, dict[str, str]],
    files_by_archive: dict[str, list[dict[str, Any]]],
) -> list[QuestionSpec]:
    ai041_questions = _build_ai041_questions(metadata_rows["AI041_ID_49"])
    selected_ai041_labels = {"timeline-docs", "assignment-operational-shift", "date-consistency"}
    ai041_selected = [
        QuestionSpec(
            id=index + 1,
            label=spec.label,
            category=f"same_archive:{spec.category}",
            question=spec.question,
            expected_terms=tuple(spec.expected_terms),
            expected_source_fragments=tuple(spec.expected_source_fragments),
            allow_zero_citations=bool(spec.allow_zero_citations),
            expected_strategy=spec.expected_strategy,
            top_k=int(spec.top_k),
            candidate_k=int(spec.candidate_k),
            summary_mode=str(spec.summary_mode),
            min_pages_per_selected_doc=int(spec.min_pages_per_selected_doc),
        )
        for index, spec in enumerate(
            [item for item in ai041_questions if item.label in selected_ai041_labels]
        )
    ]

    at565_specs = _build_same_archive_specs(
        start_id=len(ai041_selected) + 1,
        archive_slug="AT565_ID_3820",
        metadata_row=metadata_rows["AT565_ID_3820"],
        file_names=[str(item.get("file_name") or "") for item in files_by_archive["AT565_ID_3820"]],
    )
    rm797_1668_specs = _build_same_archive_specs(
        start_id=len(ai041_selected) + len(at565_specs) + 1,
        archive_slug="RM797_ID_1668",
        metadata_row=metadata_rows["RM797_ID_1668"],
        file_names=[str(item.get("file_name") or "") for item in files_by_archive["RM797_ID_1668"]],
    )
    pair_specs = _build_pair_specs(
        start_id=len(ai041_selected) + len(at565_specs) + len(rm797_1668_specs) + 1,
        archive_a="RM797_ID_1668",
        archive_b="RM797_ID_5515",
        row_a=metadata_rows["RM797_ID_1668"],
        row_b=metadata_rows["RM797_ID_5515"],
        file_names_a=[str(item.get("file_name") or "") for item in files_by_archive["RM797_ID_1668"]],
        file_names_b=[str(item.get("file_name") or "") for item in files_by_archive["RM797_ID_5515"]],
    )
    return ai041_selected + at565_specs + rm797_1668_specs + pair_specs


def _build_corpus_file_ids(files_by_archive: dict[str, list[dict[str, Any]]]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for archive_slug in DEFAULT_ARCHIVES:
        for item in files_by_archive[archive_slug]:
            file_id = int(item.get("file_id") or 0)
            if file_id <= 0 or file_id in seen:
                continue
            seen.add(file_id)
            ordered.append(file_id)
    return ordered


def _list_all_completed_files(*, base_url: str, token: str, timeout_seconds: int) -> list[dict[str, Any]]:
    payload = _require_ok(
        _http_json(
            method="GET",
            url=f"{base_url}/files",
            timeout_seconds=timeout_seconds,
            token=token,
        ),
        message="Listing all completed files failed",
    )
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("The /files payload did not include an `items` list.")
    completed = [
        dict(item)
        for item in items
        if isinstance(item, dict)
        and str(item.get("status") or "").strip().lower() == "completed"
    ]
    completed.sort(
        key=lambda item: (
            str(item.get("archive_slug") or "").lower(),
            str(item.get("file_name") or "").lower(),
            int(item.get("file_id") or 0),
        )
    )
    return completed


def _build_scope_file_ids(files_payload: list[dict[str, Any]]) -> list[int]:
    ordered: list[int] = []
    seen: set[int] = set()
    for item in files_payload:
        file_id = int(item.get("file_id") or 0)
        if file_id <= 0 or file_id in seen:
            continue
        seen.add(file_id)
        ordered.append(file_id)
    return ordered


def _build_markdown_report(*, payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# RAG Corpus Battery Report")
    lines.append("")
    lines.append(f"- Fecha UTC: `{payload['run_at_utc']}`")
    lines.append(f"- Base URL: `{payload['base_url']}`")
    lines.append(f"- Archivos evaluados: `{', '.join(payload['archives'])}`")
    lines.append(f"- Query scope: `{payload['scope_mode']}`")
    lines.append(f"- Documentos completados en scope: `{payload['scope_completed_docs']}`")
    lines.append(f"- Total de preguntas: `{payload['total_questions']}`")
    lines.append(f"- Pasadas: `{', '.join(payload['pass_labels'])}`")
    lines.append(f"- Precision promedio global: `{payload['overall_avg_precision_score']}`")
    lines.append(f"- Consistencia promedio global: `{payload['overall_avg_answer_similarity']}`")
    lines.append(f"- Overlap promedio de fuentes: `{payload['overall_avg_source_overlap']}`")
    lines.append("")
    lines.append("## Corpus")
    lines.append("")
    for archive_slug, summary in payload["archive_summary"].items():
        lines.append(
            f"- `{archive_slug}`: files=`{summary['file_count']}` | file_ids=`{', '.join(str(item) for item in summary['file_ids'])}`"
        )
    lines.append("")
    lines.append("## Resumen por pasada")
    lines.append("")
    for pass_result in payload["passes"]:
        lines.append(f"### {pass_result['label']}")
        lines.append(f"- ok: `{pass_result['ok_count']}` | failed: `{pass_result['failed_count']}`")
        lines.append(f"- total_elapsed_ms: `{pass_result['elapsed_ms_total']}`")
        lines.append(f"- p50_ms: `{pass_result['p50_ms']}` | p95_ms: `{pass_result['p95_ms']}`")
        lines.append(f"- avg_precision_score: `{pass_result['avg_precision_score']}`")
        lines.append("")
    lines.append("## Hallazgos")
    lines.append("")
    if payload["findings"]["strong"]:
        lines.append("### Recuperacion mas estable")
        for item in payload["findings"]["strong"]:
            lines.append(
                f"- [{item['id']:02d}] `{item['label']}` | precision=`{item['avg_precision_score']}` "
                f"| consistency=`{item['avg_answer_similarity']}` | source_overlap=`{item['avg_source_overlap']}`"
            )
        lines.append("")
    if payload["findings"]["weak"]:
        lines.append("### Recuperacion debil o inconsistente")
        for item in payload["findings"]["weak"]:
            lines.append(
                f"- [{item['id']:02d}] `{item['label']}` | precision=`{item['avg_precision_score']}` "
                f"| consistency=`{item['avg_answer_similarity']}` | source_overlap=`{item['avg_source_overlap']}` "
                f"| strategies=`{', '.join(item['strategies']) or '-'}`"
            )
        lines.append("")
    lines.append("## Resultados por pregunta")
    lines.append("")
    for consistency in payload["question_consistency"]:
        question_id = int(consistency["id"])
        question_text = next(
            item["question"]
            for item in payload["passes"][0]["results"]
            if int(item["id"]) == question_id
        )
        lines.append(f"### {question_id:02d}. {question_text}")
        lines.append(
            f"- avg_precision_score: `{consistency['avg_precision_score']}` | "
            f"avg_answer_similarity: `{consistency['avg_answer_similarity']}` | "
            f"avg_source_overlap: `{consistency['avg_source_overlap']}` | "
            f"strategies: `{', '.join(consistency['strategies']) or '-'}`"
        )
        for pass_result in payload["passes"]:
            item = next(result for result in pass_result["results"] if int(result["id"]) == question_id)
            lines.append(
                f"- {pass_result['label']}: status=`{item['status_code']}` | elapsed=`{item['elapsed_ms']} ms` | "
                f"strategy=`{item['strategy'] or '-'}` | precision=`{item['precision_score']}` | "
                f"citations=`{item['citations_count']}` | evidence=`{item['evidence_sources_count']}`"
            )
            if item["term_hits"] or item["term_misses"]:
                lines.append(
                    f"- {pass_result['label']} term_hits=`{', '.join(item['term_hits']) or '-'}` | "
                    f"term_misses=`{', '.join(item['term_misses']) or '-'}`"
                )
            if item["source_hits"] or item["source_misses"]:
                lines.append(
                    f"- {pass_result['label']} source_hits=`{', '.join(item['source_hits']) or '-'}` | "
                    f"source_misses=`{', '.join(item['source_misses']) or '-'}`"
                )
            if item["evidence_source_names"]:
                lines.append(f"- {pass_result['label']} top_sources: {', '.join(item['evidence_source_names'][:4])}")
            if item["error"]:
                lines.append(f"- {pass_result['label']} error: `{item['error']}`")
            lines.append(f"- {pass_result['label']} answer_preview: {item['answer_preview'] or '-'}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = _parse_args()
    base_url = str(args.base_url).rstrip("/")
    metadata_csv = Path(str(args.metadata_csv))
    if not metadata_csv.is_absolute():
        metadata_csv = ROOT / metadata_csv
    if not metadata_csv.exists():
        raise SystemExit(f"Metadata CSV not found: {metadata_csv}")

    output_dir = Path(str(args.output_dir))
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    downloads_dir = Path(str(args.downloads_dir))
    pass_count = max(1, int(args.passes))
    pass_labels = list(DEFAULT_PASS_LABELS[:pass_count])
    if len(pass_labels) < pass_count:
        while len(pass_labels) < pass_count:
            pass_labels.append(f"warm-{len(pass_labels)}")

    token = str(args.token or "").strip()
    if not token:
        token = _login(
            base_url=base_url,
            username=str(args.username or "").strip(),
            password=str(args.password or "").strip(),
            timeout_seconds=max(30, int(args.timeout_seconds)),
        )

    archive_slugs = [str(item or "").strip() for item in list(args.archives or []) if str(item or "").strip()]
    required_archives = list(DEFAULT_ARCHIVES)
    if archive_slugs:
        required_archives = archive_slugs

    metadata_rows: dict[str, dict[str, str]] = {
        archive_slug: _load_metadata_row(metadata_csv=metadata_csv, archive_slug=archive_slug)
        for archive_slug in required_archives
    }
    files_by_archive: dict[str, list[dict[str, Any]]] = {
        archive_slug: _list_completed_files(
            base_url=base_url,
            token=token,
            archive_slug=archive_slug,
            timeout_seconds=max(30, int(args.timeout_seconds)),
        )
        for archive_slug in required_archives
    }
    all_completed_files = _list_all_completed_files(
        base_url=base_url,
        token=token,
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )

    question_specs = _build_question_specs(
        metadata_rows=metadata_rows,
        files_by_archive=files_by_archive,
    )
    scope_mode = str(args.scope or "all-completed").strip().lower()
    if scope_mode == "archives":
        corpus_scope_files = [
            item
            for archive_slug in required_archives
            for item in files_by_archive[archive_slug]
        ]
    else:
        scope_mode = "all-completed"
        corpus_scope_files = list(all_completed_files)
    corpus_file_ids = _build_scope_file_ids(corpus_scope_files)

    passes: list[dict[str, Any]] = []
    for pass_label in pass_labels:
        passes.append(
            _run_pass(
                base_url=base_url,
                token=token,
                file_ids=corpus_file_ids,
                specs=question_specs,
                timeout_seconds=max(30, int(args.timeout_seconds)),
                pass_label=pass_label,
            )
        )

    question_consistency = _build_question_consistency(passes=passes)
    findings = _build_findings(question_consistency=question_consistency)
    precision_values = [float(item["avg_precision_score"]) for item in passes]
    payload: dict[str, Any] = {
        "run_at_utc": _utc_now(),
        "base_url": base_url,
        "archives": required_archives,
        "scope_mode": scope_mode,
        "scope_completed_docs": len(corpus_file_ids),
        "pass_labels": pass_labels,
        "total_questions": len(question_specs),
        "archive_summary": {
            archive_slug: {
                "file_count": len(files_by_archive[archive_slug]),
                "file_ids": [int(item.get("file_id") or 0) for item in files_by_archive[archive_slug]],
                "file_names": [str(item.get("file_name") or "") for item in files_by_archive[archive_slug]],
                "metadata_snapshot": metadata_rows[archive_slug],
            }
            for archive_slug in required_archives
        },
        "passes": passes,
        "question_consistency": question_consistency,
        "overall_avg_precision_score": round(mean(precision_values), 3) if precision_values else 0.0,
        "overall_avg_answer_similarity": round(
            mean(float(item["avg_answer_similarity"]) for item in question_consistency), 3
        )
        if question_consistency
        else 0.0,
        "overall_avg_source_overlap": round(
            mean(float(item["avg_source_overlap"]) for item in question_consistency), 3
        )
        if question_consistency
        else 0.0,
        "overall_p50_ms": _percentile_ms(
            [int(item["elapsed_ms"]) for result in passes for item in result["results"] if int(item["status_code"]) == 200],
            0.50,
        ),
        "overall_p95_ms": _percentile_ms(
            [int(item["elapsed_ms"]) for result in passes for item in result["results"] if int(item["status_code"]) == 200],
            0.95,
        ),
        "findings": findings,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_name = f"rag_corpus_battery_{'_'.join(item.lower() for item in required_archives)}_{stamp}"
    json_path = output_dir / f"{base_name}.json"
    md_path = output_dir / f"{base_name}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_build_markdown_report(payload=payload), encoding="utf-8")

    downloads_copy = None
    if not bool(args.skip_downloads_copy):
        downloads_copy = _copy_report_to_downloads(source_path=md_path, downloads_dir=downloads_dir)

    print(f"[DONE] JSON report: {json_path}", flush=True)
    print(f"[DONE] Markdown report: {md_path}", flush=True)
    if downloads_copy is not None:
        print(f"[DONE] Downloads copy: {downloads_copy}", flush=True)
    print(
        "[DONE] Overall precision="
        f"{payload['overall_avg_precision_score']} | "
        f"consistency={payload['overall_avg_answer_similarity']} | "
        f"source_overlap={payload['overall_avg_source_overlap']} | "
        f"p50={payload['overall_p50_ms']}ms | p95={payload['overall_p95_ms']}ms",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
