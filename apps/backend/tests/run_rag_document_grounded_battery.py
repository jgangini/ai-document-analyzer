from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
import sys
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.tests.run_rag_archive_compound_battery import (
    DEFAULT_BASE_URL,
    DEFAULT_DOWNLOADS_DIR,
    DEFAULT_METADATA_CSV,
    DEFAULT_OUTPUT_DIR,
    DEFAULT_TIMEOUT_SECONDS,
    QuestionSpec,
    _build_findings,
    _build_question_consistency,
    _copy_report_to_downloads,
    _http_json,
    _load_metadata_row,
    _login,
    _normalize_text,
    _percentile_ms,
    _require_ok,
    _run_pass,
)


DEFAULT_FOCUS_ARCHIVES = (
    "AI041_ID_49",
    "AT565_ID_3820",
    "LA122_ID_3979",
    "RM797_ID_1668",
    "RM797_ID_5515",
)
DEFAULT_PASS_LABELS = ("cold", "warm-1")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metadata_value(row: dict[str, str], *keys: str, default_value: str = "") -> str:
    for key in keys:
        value = str(row.get(key) or "").strip()
        if value:
            return value
    return default_value


def _list_all_completed_files(*, base_url: str, token: str, timeout_seconds: int) -> list[dict[str, Any]]:
    payload = _require_ok(
        _http_json(
            method="GET",
            url=f"{base_url}/files?limit=500&offset=0",
            timeout_seconds=timeout_seconds,
            token=token,
        ),
        message="Listing completed files failed",
    )
    items = payload.get("items")
    if not isinstance(items, list):
        raise RuntimeError("The /files payload did not include an items list.")
    completed = [
        dict(item)
        for item in items
        if isinstance(item, dict) and _normalize_text(item.get("status")) == "completed"
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


def _build_archive_summary(
    *,
    files_payload: list[dict[str, Any]],
    focus_archives: tuple[str, ...],
    metadata_rows: dict[str, dict[str, str]],
) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for archive_slug in focus_archives:
        matching = [
            item
            for item in files_payload
            if _normalize_text(item.get("archive_slug")) == _normalize_text(archive_slug)
        ]
        summary[archive_slug] = {
            "file_count": len(matching),
            "file_ids": [int(item.get("file_id") or 0) for item in matching if int(item.get("file_id") or 0) > 0],
            "file_names": [str(item.get("file_name") or "") for item in matching],
            "metadata_snapshot": metadata_rows[archive_slug],
        }
    return summary


def _build_question_specs(metadata_rows: dict[str, dict[str, str]]) -> list[QuestionSpec]:
    ai041 = metadata_rows["AI041_ID_49"]
    at565 = metadata_rows["AT565_ID_3820"]
    la122 = metadata_rows["LA122_ID_3979"]
    rm797_1668 = metadata_rows["RM797_ID_1668"]
    rm797_5515 = metadata_rows["RM797_ID_5515"]

    return [
        QuestionSpec(
            id=1,
            label="sites-multi-contract-id",
            category="analytics",
            question=(
                "Que sitios tienen mas de un ID de contrato en la metadata cargada? "
                "Devuelve el codigo de sitio y la lista de IDs."
            ),
            expected_terms=("LA122", "RM797"),
            allow_zero_citations=True,
            expected_strategy="facts-first",
            top_k=10,
            candidate_k=60,
        ),
        QuestionSpec(
            id=2,
            label="contract-state-counts",
            category="analytics",
            question=(
                "Cuantos contratos estan vigentes, vencidos o terminados? "
                "Si existen registros sin estado, reportalos aparte."
            ),
            expected_terms=("16", "1", "vigente", "vencido", "terminado"),
            allow_zero_citations=True,
            expected_strategy="facts-first",
            top_k=10,
            candidate_k=60,
        ),
        QuestionSpec(
            id=3,
            label="contracts-most-document-versions",
            category="analytics",
            question=(
                "Que contratos tienen mas versiones documentales o PDFs asociados? "
                "Ordenalos de mayor a menor e indica cuantos documentos tiene cada uno."
            ),
            expected_terms=("AT565", "RM797", "11", "8"),
            allow_zero_citations=True,
            expected_strategy="facts-first",
            top_k=10,
            candidate_k=60,
        ),
        QuestionSpec(
            id=4,
            label="rm797-cross-archive-compare",
            category="cross_archive",
            question=(
                "Compara RM797_ID_1668 y RM797_ID_5515 en estado, partes, forma de pago y fecha de termino. "
                "Usa metadata y documentos, y cita los PDFs mas relevantes."
            ),
            expected_terms=tuple(
                item
                for item in (
                    _metadata_value(rm797_1668, "Forma de Pago"),
                    _metadata_value(rm797_5515, "Estado Contrato"),
                    _metadata_value(rm797_5515, "Forma de Pago"),
                    _metadata_value(rm797_1668, "Nombre Beneficiario"),
                    _metadata_value(rm797_5515, "Nombre Beneficiario"),
                )
                if item
            ),
            expected_source_fragments=(
                "RM797_Contrato",
                "RM797_-_Contrato_2",
                "RM797_Modific",
                "RM797_Rectific",
            ),
            top_k=10,
            candidate_k=48,
            summary_mode="per_document",
            min_pages_per_selected_doc=1,
        ),
        QuestionSpec(
            id=5,
            label="rm797-5515-dossier-order",
            category="same_archive",
            question=(
                "Para RM797_ID_5515, ordena el expediente documental entre contrato, subarrendamiento, modificacion 2, "
                "rectificacion, decretos y resciliacion; explica para que sirve cada documento y cuales son los hitos "
                "clave, citando al menos los PDFs determinantes."
            ),
            expected_source_fragments=(
                "RM797_-_Contrato_2",
                "RM797_Modificacion_Subarrendamiento",
                "RM797_Modificacin_2",
                "RM797_Rectific",
                "Resciliacin_Arrendamiento",
            ),
            top_k=10,
            candidate_k=54,
            summary_mode="per_document",
            min_pages_per_selected_doc=1,
        ),
        QuestionSpec(
            id=6,
            label="rm797-5515-beneficiary-evidence",
            category="same_archive",
            question=(
                "Para RM797_ID_5515, que documento mas reciente sustenta quien recibe la renta y cual es su RUT? "
                "Cita el PDF y explica si coincide con la metadata actual."
            ),
            expected_terms=tuple(
                item
                for item in (
                    _metadata_value(rm797_5515, "Nombre Beneficiario"),
                    _metadata_value(rm797_5515, "Rut Beneficiario del contrato"),
                )
                if item
            ),
            top_k=8,
            candidate_k=36,
            summary_mode="per_document",
            min_pages_per_selected_doc=1,
        ),
        QuestionSpec(
            id=7,
            label="la122-access-last-modification",
            category="same_archive",
            question=(
                "Para LA122_ID_3979, que dice la ultima modificacion sobre el acceso al terreno? "
                "Cita la clausula y el PDF."
            ),
            expected_source_fragments=(
                "LA122_Modificacion",
                "LA122_-_Modificacin_y_Cesin_de_Contrato",
            ),
            top_k=8,
            candidate_k=36,
            summary_mode="per_document",
            min_pages_per_selected_doc=1,
        ),
        QuestionSpec(
            id=8,
            label="la122-assignment-current-contract",
            category="same_archive",
            question=(
                "Para LA122_ID_3979, que dice el ultimo contrato vigente sobre cesion a terceros y coincide con lo que "
                "muestra la metadata hoy? Cita la clausula y el PDF."
            ),
            expected_terms=tuple(
                item
                for item in (
                    _metadata_value(la122, "Estado Contrato"),
                    _metadata_value(la122, "Nombre Beneficiario"),
                )
                if item
            ),
            expected_source_fragments=("LA122_-_Modificacin_y_Cesin_de_Contrato",),
            top_k=8,
            candidate_k=36,
            summary_mode="per_document",
            min_pages_per_selected_doc=1,
        ),
        QuestionSpec(
            id=9,
            label="ai041-formal-chain",
            category="same_archive",
            question=(
                "Compara AI041.pdf, AI041_Modificacin_1.pdf y AI041_Aclaracion_y_rectificacion.pdf dentro de "
                "AI041_ID_49; resume cambios de fechas de firma, notaria, repertorio y representantes, y cita cada PDF."
            ),
            expected_terms=("2005", "2017"),
            expected_source_fragments=(
                "AI041.pdf",
                "AI041_Modificacin_1",
                "AI041_Aclaracion_y_rectificacion",
            ),
            top_k=8,
            candidate_k=36,
            summary_mode="per_document",
            min_pages_per_selected_doc=1,
        ),
        QuestionSpec(
            id=10,
            label="at565-parties-payment",
            category="same_archive",
            question=(
                "Compara AT565.PDF, AT565_Modificacion.PDF y Modificacin_-_Los_Carrera.pdf dentro de AT565_ID_3820; "
                "resume que cambio en propietario, beneficiario y forma de pago, cita los documentos relevantes y di "
                "si coincide con la metadata actual."
            ),
            expected_terms=tuple(
                item
                for item in (
                    _metadata_value(at565, "Nombre de Propietario Principal"),
                    _metadata_value(at565, "Nombre Beneficiario"),
                    _metadata_value(at565, "Forma de Pago"),
                )
                if item
            ),
            expected_source_fragments=(
                "AT565.PDF",
                "AT565_Modificacion",
                "Los_Carrera",
            ),
            top_k=8,
            candidate_k=36,
            summary_mode="per_document",
            min_pages_per_selected_doc=1,
        ),
    ]


def _build_markdown_report(*, payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("# RAG Document Grounded Battery Report")
    lines.append("")
    lines.append(f"- Fecha UTC: `{payload['run_at_utc']}`")
    lines.append(f"- Base URL: `{payload['base_url']}`")
    lines.append(f"- Archivos foco: `{', '.join(payload['focus_archives'])}`")
    lines.append(f"- Scope: `{payload['scope_mode']}`")
    lines.append(f"- Documentos completados en scope: `{payload['scope_completed_docs']}`")
    lines.append(f"- Total de preguntas: `{payload['total_questions']}`")
    lines.append(f"- Pasadas: `{', '.join(payload['pass_labels'])}`")
    lines.append(f"- Precision promedio global: `{payload['overall_avg_precision_score']}`")
    lines.append(f"- Consistencia promedio global: `{payload['overall_avg_answer_similarity']}`")
    lines.append(f"- Overlap promedio de fuentes: `{payload['overall_avg_source_overlap']}`")
    lines.append(f"- P50 global: `{payload['overall_p50_ms']} ms` | P95 global: `{payload['overall_p95_ms']} ms`")
    lines.append("")
    lines.append("## Corpus")
    lines.append("")
    for archive_slug, summary in payload["archive_summary"].items():
        lines.append(
            f"- `{archive_slug}`: files=`{summary['file_count']}` | "
            f"file_ids=`{', '.join(str(item) for item in summary['file_ids'])}`"
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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a document-grounded 10-question RAG battery over the local corpus.")
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
        default=list(DEFAULT_FOCUS_ARCHIVES),
        metavar="ARCHIVE",
        help="Logical archives to highlight in the report.",
    )
    parser.add_argument(
        "--passes",
        type=int,
        default=len(DEFAULT_PASS_LABELS),
        help="How many passes to execute (2 = cold + warm-1).",
    )
    return parser.parse_args()


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

    focus_archives = tuple(
        str(item or "").strip()
        for item in list(args.archives or [])
        if str(item or "").strip()
    ) or DEFAULT_FOCUS_ARCHIVES

    token = str(args.token or "").strip()
    if not token:
        token = _login(
            base_url=base_url,
            username=str(args.username or "").strip(),
            password=str(args.password or "").strip(),
            timeout_seconds=max(30, int(args.timeout_seconds)),
        )

    metadata_rows = {
        archive_slug: _load_metadata_row(metadata_csv=metadata_csv, archive_slug=archive_slug)
        for archive_slug in focus_archives
    }
    all_completed_files = _list_all_completed_files(
        base_url=base_url,
        token=token,
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )
    corpus_file_ids = _build_scope_file_ids(all_completed_files)
    question_specs = _build_question_specs(metadata_rows)

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
    archive_summary = _build_archive_summary(
        files_payload=all_completed_files,
        focus_archives=focus_archives,
        metadata_rows=metadata_rows,
    )
    payload: dict[str, Any] = {
        "run_at_utc": _utc_now(),
        "base_url": base_url,
        "focus_archives": list(focus_archives),
        "scope_mode": "all-completed",
        "scope_completed_docs": len(corpus_file_ids),
        "pass_labels": pass_labels,
        "total_questions": len(question_specs),
        "archive_summary": archive_summary,
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
    base_name = f"rag_document_grounded_battery_{stamp}"
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
