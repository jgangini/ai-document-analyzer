from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
from difflib import SequenceMatcher
import json
import os
from pathlib import Path
import shutil
from statistics import mean
from time import perf_counter
from typing import Any
import unicodedata
from urllib import error as url_error
from urllib import request as url_request


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_BASE_URL = "http://127.0.0.1:8012/api"
DEFAULT_OUTPUT_DIR = ROOT / "apps" / "backend" / "tests" / "reports"
DEFAULT_METADATA_CSV = ROOT / ".source" / "info-docs.metadata.csv"
DEFAULT_ARCHIVE_SLUG = "AI041_ID_49"
DEFAULT_DOWNLOADS_DIR = Path.home() / "Downloads"
DEFAULT_TOP_K = 8
DEFAULT_CANDIDATE_K = 40
DEFAULT_TIMEOUT_SECONDS = 240
DEFAULT_PASSES = ("cold", "warm-1", "warm-2")
UNCERTAINTY_HINTS = (
    "no se encuentra",
    "no se identific",
    "no se observa",
    "no disponible",
    "no hay evidencia",
    "no puedo confirmar",
    "insuficiente",
    "no se puede determinar",
    "falta evidencia",
)


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
    expected_terms: tuple[str, ...] = ()
    expected_source_fragments: tuple[str, ...] = ()
    allow_zero_citations: bool = False
    expected_strategy: str | None = None
    top_k: int = DEFAULT_TOP_K
    candidate_k: int = DEFAULT_CANDIDATE_K
    summary_mode: str = "default"
    min_pages_per_selected_doc: int = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_text(value: object | None) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = normalized.lower().strip()
    return " ".join(normalized.split())


def _short_text(value: str, *, limit: int = 320) -> str:
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
            return HttpResult(
                status_code=int(response.status),
                payload=json.loads(raw) if raw.strip() else {},
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


def _list_completed_files(*, base_url: str, token: str, archive_slug: str, timeout_seconds: int) -> list[dict[str, Any]]:
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
        raise RuntimeError("The /files payload did not include an items list.")
    filtered = [
        dict(item)
        for item in items
        if isinstance(item, dict)
        and str(item.get("archive_slug") or "").strip().lower() == archive_slug.lower()
        and str(item.get("status") or "").strip().lower() == "completed"
    ]
    filtered.sort(key=lambda item: str(item.get("file_name") or "").lower())
    if not filtered:
        raise RuntimeError(f"No completed files were found for archive {archive_slug}.")
    return filtered


def _load_metadata_row(*, metadata_csv: Path, archive_slug: str) -> dict[str, str]:
    with metadata_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        first_field = reader.fieldnames[0].strip() if reader.fieldnames else ""
        if first_field != "file":
            raise RuntimeError(f"Metadata CSV must start with 'file'. Found: {first_field!r}")
        for row in reader:
            if _normalize_text(row.get("file")) == _normalize_text(archive_slug):
                return {str(key): str(value or "").strip() for key, value in row.items() if key}
    raise RuntimeError(f"Metadata row not found for archive {archive_slug} in {metadata_csv}.")


def _build_ai041_questions(metadata_row: dict[str, str]) -> list[QuestionSpec]:
    owner = metadata_row.get("Nombre de Propietario Principal", "FILADELFIA DE LA PENA ECHAVEGUREN")
    owner_rut = metadata_row.get("RUT Propietario Principal", "7068392-K")
    beneficiary = metadata_row.get("Nombre Beneficiario", "ATC SITIOS CHILE S.A.")
    beneficiary_rut = metadata_row.get("Rut Beneficiario del contrato", "76101962-7")
    payment = metadata_row.get("Forma de Pago", "Vale Vista")
    state = metadata_row.get("Estado Contrato", "Vigente")
    rent = metadata_row.get("Renta o Precio Vigente", "420")
    notice_date = metadata_row.get("Fecha de Aviso de Término del Contrato", "01/11/2028")
    end_date = metadata_row.get("Fecha de Término del Contrato", "01/11/2029")
    first_sign = metadata_row.get("Fecha de Firma Primer Contrato", "02/11/2005")
    last_sign = metadata_row.get("Fecha Firma Último Contrato", "04/08/2017")

    return [
        QuestionSpec(
            id=1,
            label="timeline-docs",
            category="document_timeline",
            question=(
                "Reconstruye la linea de tiempo documental de AI041_ID_49 usando AI041.pdf, "
                "AI041_Modificacin_1.pdf, AI041_Aclaracion_y_rectificacion.pdf y "
                "AI041_Carta_Aviso_Cesin_Contrato_Alba_ATC.pdf; identifica fecha y documento en cada hito."
            ),
            expected_terms=("2005", "2017", "2020"),
            expected_source_fragments=(
                "AI041.pdf",
                "AI041_Modific",
                "AI041_Aclaracion",
                "AI041_Carta_Aviso",
            ),
        ),
        QuestionSpec(
            id=2,
            label="formal-chain",
            category="document_comparison",
            question=(
                "Compara AI041.pdf, AI041_Modificacin_1.pdf y AI041_Aclaracion_y_rectificacion.pdf "
                "en fecha de firma, notaria, repertorio y representante de Entel."
            ),
            expected_terms=(
                "1716-2005",
                "255-2017",
                "25697-2017",
                "francisco javier sprenger",
                "carlos alberto oyarzun",
            ),
            expected_source_fragments=("AI041.pdf", "AI041_Modific", "AI041_Aclaracion"),
        ),
        QuestionSpec(
            id=3,
            label="term-payment-change",
            category="document_comparison",
            question=(
                "Entre AI041.pdf y AI041_Modificacin_1.pdf, compara renta, forma o periodo de pago, "
                "vigencia y prorroga automatica, indicando que cambio en 2017."
            ),
            expected_terms=("200", "420", "anual", "cada 4", "2029"),
            expected_source_fragments=("AI041.pdf", "AI041_Modific"),
        ),
        QuestionSpec(
            id=4,
            label="metadata-current-state",
            category="metadata_validation",
            question=(
                f"Usando metadata de AI041_ID_49, valida si Estado Contrato es {state}, "
                f"Pago Anticipado es SI, Forma de Pago es {payment} y Renta o Precio Vigente es {rent}."
            ),
            expected_terms=(state, "SI", payment, rent),
            allow_zero_citations=True,
            expected_strategy="facts-first",
        ),
        QuestionSpec(
            id=5,
            label="metadata-identity",
            category="metadata_validation",
            question=(
                "Usando metadata del archivo AI041_ID_49, indica propietario principal, "
                "RUT propietario principal, beneficiario actual y RUT beneficiario del contrato."
            ),
            expected_terms=(owner, owner_rut, beneficiary, beneficiary_rut),
            allow_zero_citations=True,
            expected_strategy="facts-first",
        ),
        QuestionSpec(
            id=6,
            label="doc-current-parties",
            category="hybrid_identity",
            question=(
                "En los documentos de AI041_ID_49, identifica quien figura como propietaria y quien figura "
                "como arrendatario o cesionario en 2005, 2017 y 2020; luego compara eso con la metadata actual."
            ),
            expected_terms=(owner, "entel pcs", "atc", beneficiary),
            expected_source_fragments=("AI041.pdf", "AI041_Modific", "AI041_Carta_Aviso", "ATC-Comunic"),
        ),
        QuestionSpec(
            id=7,
            label="assignment-operational-shift",
            category="document_comparison",
            question=(
                "Compara AI041_Carta_Aviso_Cesin_Contrato_Alba_ATC.pdf y "
                "ATC-Comunicacin_Entel_Chile_1275126_Sitios.pdf para explicar la diferencia entre "
                "la cesion contractual de enero de 2020 y el traspaso operacional informado en junio de 2020."
            ),
            expected_terms=("2020", "atc", "entel", "1399"),
            expected_source_fragments=("AI041_Carta_Aviso", "ATC-Comunic"),
        ),
        QuestionSpec(
            id=8,
            label="access-and-cession",
            category="hybrid_clause",
            question=(
                "Compara lo que dice AI041.pdf sobre acceso al predio y cesion a terceros "
                "con lo que reporta la metadata actual de AI041_ID_49."
            ),
            expected_terms=("acceso", "servidumbre", "libre", "cesion"),
            expected_source_fragments=("AI041.pdf",),
        ),
        QuestionSpec(
            id=9,
            label="representatives",
            category="document_comparison",
            question=(
                "Identifica y compara los representantes de Entel en AI041.pdf, "
                "AI041_Modificacin_1.pdf y AI041_Aclaracion_y_rectificacion.pdf."
            ),
            expected_terms=("francisco javier sprenger", "carlos alberto oyarzun"),
            expected_source_fragments=("AI041.pdf", "AI041_Modific", "AI041_Aclaracion"),
        ),
        QuestionSpec(
            id=10,
            label="date-consistency",
            category="hybrid_temporal",
            question=(
                "Valida con documentos y metadata si las fechas clave de AI041_ID_49 son coherentes: "
                f"primer contrato {first_sign}, modificacion 27/01/2017, aclaracion {last_sign}, "
                f"aviso de cesion 08/01/2020, aviso de termino {notice_date} y termino {end_date}."
            ),
            expected_terms=(first_sign, last_sign, notice_date, end_date),
            expected_source_fragments=("AI041.pdf", "AI041_Modific", "AI041_Aclaracion", "AI041_Carta_Aviso"),
        ),
        QuestionSpec(
            id=11,
            label="surface-mismatch",
            category="hybrid_difference",
            question=(
                "Contrasta la metadata de AI041_ID_49 sobre metros cuadrados arrendados con el detalle "
                "del contrato base AI041.pdf; di si la cifra coincide o si parece haber una discrepancia."
            ),
            expected_terms=("110", "100", "10 metros", "tres retazos"),
            expected_source_fragments=("AI041.pdf",),
        ),
    ]


def _build_question_specs(*, question_set: str, metadata_row: dict[str, str]) -> list[QuestionSpec]:
    if question_set == "ai041":
        return _build_ai041_questions(metadata_row)
    raise RuntimeError(f"Unsupported question set: {question_set}")


def _term_hits(answer_text: str, expected_terms: tuple[str, ...]) -> tuple[list[str], list[str]]:
    normalized_answer = _normalize_text(answer_text)
    hits: list[str] = []
    misses: list[str] = []
    for raw_term in expected_terms:
        normalized_term = _normalize_text(raw_term)
        if not normalized_term:
            continue
        if normalized_term in normalized_answer:
            hits.append(str(raw_term))
        else:
            misses.append(str(raw_term))
    return hits, misses


def _source_hits(source_names: list[str], expected_fragments: tuple[str, ...]) -> tuple[list[str], list[str]]:
    normalized_sources = [_normalize_text(item) for item in source_names]
    hits: list[str] = []
    misses: list[str] = []
    for raw_fragment in expected_fragments:
        normalized_fragment = _normalize_text(raw_fragment)
        if normalized_fragment and any(normalized_fragment in source for source in normalized_sources):
            hits.append(str(raw_fragment))
        else:
            misses.append(str(raw_fragment))
    return hits, misses


def _derive_precision_score(
    *,
    spec: QuestionSpec,
    answer_text: str,
    citations_count: int,
    source_names: list[str],
    strategy: str,
) -> tuple[float, dict[str, Any]]:
    normalized_answer = _normalize_text(answer_text)
    term_hits, term_misses = _term_hits(answer_text, spec.expected_terms)
    source_hits, source_misses = _source_hits(source_names, spec.expected_source_fragments)
    has_uncertainty = any(hint in normalized_answer for hint in UNCERTAINTY_HINTS)

    weighted_scores: list[tuple[float, float]] = [
        (0.15, 1.0 if len(answer_text.strip()) >= 40 else 0.0),
        (
            0.15,
            1.0 if spec.allow_zero_citations or citations_count > 0 or bool(source_names) else 0.0,
        ),
        (
            0.1,
            1.0 if not spec.expected_strategy or spec.expected_strategy in str(strategy or "") else 0.0,
        ),
        (
            0.1,
            0.0 if has_uncertainty and len(term_hits) < max(1, len(spec.expected_terms) // 2) else 1.0,
        ),
    ]
    if spec.expected_terms:
        weighted_scores.append((0.3, len(term_hits) / len(spec.expected_terms)))
    if spec.expected_source_fragments:
        weighted_scores.append((0.2, len(source_hits) / len(spec.expected_source_fragments)))

    total_weight = sum(weight for weight, _ in weighted_scores)
    precision = sum(weight * score for weight, score in weighted_scores) / max(total_weight, 0.0001)
    return round(min(max(precision, 0.0), 1.0), 3), {
        "term_hits": term_hits,
        "term_misses": term_misses,
        "source_hits": source_hits,
        "source_misses": source_misses,
        "has_uncertainty": has_uncertainty,
    }


def _run_question(
    *,
    base_url: str,
    token: str,
    file_ids: list[int],
    spec: QuestionSpec,
    timeout_seconds: int,
) -> dict[str, Any]:
    response = _http_json(
        method="POST",
        url=f"{base_url}/questions/ask",
        timeout_seconds=timeout_seconds,
        token=token,
        body={
            "question": spec.question,
            "file_ids": list(file_ids),
            "allow_inferred_scope": True,
            "top_k": int(spec.top_k),
            "candidate_k": int(spec.candidate_k),
            "summary_mode": spec.summary_mode,
            "min_pages_per_selected_doc": int(spec.min_pages_per_selected_doc),
        },
    )
    payload = response.payload if isinstance(response.payload, dict) else {}
    answer_text = str(payload.get("answer_text") or payload.get("answer") or "")
    citations = payload.get("citations") if isinstance(payload.get("citations"), list) else []
    evidence_sources = (
        payload.get("evidence_sources")
        if isinstance(payload.get("evidence_sources"), list)
        else (payload.get("sources") if isinstance(payload.get("sources"), list) else [])
    )
    source_names = [
        str(item.get("name") or item.get("file_name") or "").strip()
        for item in evidence_sources
        if isinstance(item, dict) and str(item.get("name") or item.get("file_name") or "").strip()
    ]
    precision_score, diagnostics = _derive_precision_score(
        spec=spec,
        answer_text=answer_text,
        citations_count=len(citations),
        source_names=source_names,
        strategy=str(payload.get("strategy") or ""),
    )
    return {
        "id": spec.id,
        "label": spec.label,
        "category": spec.category,
        "question": spec.question,
        "status_code": response.status_code,
        "elapsed_ms": response.elapsed_ms,
        "strategy": str(payload.get("strategy") or ""),
        "answer_chars": len(answer_text),
        "answer_text": answer_text,
        "answer_preview": _short_text(answer_text, limit=420),
        "citations_count": len(citations),
        "evidence_sources_count": len(evidence_sources),
        "evidence_source_names": source_names[:8],
        "telemetry": dict(payload.get("telemetry") or {}),
        "error": response.error_text,
        "precision_score": precision_score,
        "term_hits": diagnostics["term_hits"],
        "term_misses": diagnostics["term_misses"],
        "source_hits": diagnostics["source_hits"],
        "source_misses": diagnostics["source_misses"],
        "has_uncertainty": diagnostics["has_uncertainty"],
    }


def _run_pass(
    *,
    base_url: str,
    token: str,
    file_ids: list[int],
    specs: list[QuestionSpec],
    timeout_seconds: int,
    pass_label: str,
) -> dict[str, Any]:
    started = perf_counter()
    results: list[dict[str, Any]] = []
    for index, spec in enumerate(specs, start=1):
        result = _run_question(
            base_url=base_url,
            token=token,
            file_ids=file_ids,
            spec=spec,
            timeout_seconds=timeout_seconds,
        )
        results.append(result)
        print(
            f"[{pass_label}] {index:02d}/{len(specs):02d} {spec.label:<26} "
            f"status={result['status_code']} elapsed={result['elapsed_ms']}ms "
            f"strategy={result['strategy'] or '-'} score={result['precision_score']}",
            flush=True,
        )

    elapsed_values = [int(item["elapsed_ms"]) for item in results if int(item["status_code"]) == 200]
    precision_values = [float(item["precision_score"]) for item in results]
    return {
        "label": pass_label,
        "started_at_utc": _utc_now(),
        "elapsed_ms_total": int((perf_counter() - started) * 1000),
        "ok_count": sum(1 for item in results if int(item["status_code"]) == 200),
        "failed_count": sum(1 for item in results if int(item["status_code"]) != 200),
        "p50_ms": _percentile_ms(elapsed_values, 0.50),
        "p95_ms": _percentile_ms(elapsed_values, 0.95),
        "avg_precision_score": round(mean(precision_values), 3) if precision_values else 0.0,
        "results": results,
    }


def _answer_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_text(left)
    normalized_right = _normalize_text(right)
    if not normalized_left and not normalized_right:
        return 1.0
    return round(SequenceMatcher(None, normalized_left, normalized_right).ratio(), 3)


def _source_overlap(left_sources: list[str], right_sources: list[str]) -> float:
    left = {_normalize_text(item) for item in left_sources if _normalize_text(item)}
    right = {_normalize_text(item) for item in right_sources if _normalize_text(item)}
    if not left and not right:
        return 1.0
    universe = left | right
    if not universe:
        return 0.0
    return round(len(left & right) / len(universe), 3)


def _build_question_consistency(*, passes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_question: dict[int, list[dict[str, Any]]] = {}
    for pass_result in passes:
        for item in pass_result["results"]:
            by_question.setdefault(int(item["id"]), []).append(dict(item))

    summary: list[dict[str, Any]] = []
    for question_id, items in sorted(by_question.items()):
        similarities: list[float] = []
        overlaps: list[float] = []
        for index, left in enumerate(items):
            for right in items[index + 1 :]:
                similarities.append(_answer_similarity(left["answer_text"], right["answer_text"]))
                overlaps.append(
                    _source_overlap(
                        left.get("evidence_source_names") or [],
                        right.get("evidence_source_names") or [],
                    )
                )
        summary.append(
            {
                "id": question_id,
                "label": items[0]["label"],
                "category": items[0]["category"],
                "avg_answer_similarity": round(mean(similarities), 3) if similarities else 1.0,
                "avg_source_overlap": round(mean(overlaps), 3) if overlaps else 1.0,
                "avg_precision_score": round(mean(float(item["precision_score"]) for item in items), 3),
                "strategies": sorted({str(item.get("strategy") or "") for item in items if str(item.get("strategy") or "")}),
            }
        )
    return summary


def _build_findings(*, question_consistency: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    strong = [
        item
        for item in question_consistency
        if float(item["avg_precision_score"]) >= 0.75 and float(item["avg_answer_similarity"]) >= 0.8
    ]
    weak = [
        item
        for item in question_consistency
        if float(item["avg_precision_score"]) < 0.55 or float(item["avg_answer_similarity"]) < 0.65
    ]
    weak.sort(key=lambda item: (float(item["avg_precision_score"]), float(item["avg_answer_similarity"])))
    strong.sort(key=lambda item: (float(item["avg_precision_score"]), float(item["avg_answer_similarity"])), reverse=True)
    return {
        "strong": strong[:5],
        "weak": weak[:6],
    }


def _build_markdown_report(*, payload: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append(f"# RAG Question Battery Report - {payload['archive_slug'].lower()}")
    lines.append("")
    lines.append(f"- Fecha UTC: `{payload['run_at_utc']}`")
    lines.append(f"- Base URL: `{payload['base_url']}`")
    lines.append(f"- Archivo evaluado: `{payload['archive_slug']}`")
    lines.append(f"- File IDs evaluados: `{', '.join(str(item) for item in payload['file_ids'])}`")
    lines.append(f"- Preguntas ejecutadas: `{payload['total_questions']}`")
    lines.append(f"- Pasadas: `{', '.join(payload['pass_labels'])}`")
    lines.append(f"- Precision promedio global: `{payload['overall_avg_precision_score']}`")
    lines.append(f"- Consistencia promedio global: `{payload['overall_avg_answer_similarity']}`")
    lines.append(f"- Overlap promedio de fuentes: `{payload['overall_avg_source_overlap']}`")
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


def _copy_report_to_downloads(*, source_path: Path, downloads_dir: Path) -> Path | None:
    if not downloads_dir.exists():
        return None
    target_path = downloads_dir / source_path.name
    shutil.copyfile(source_path, target_path)
    return target_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run repeated compound RAG diagnostics for a single archive.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--archive-slug", default=DEFAULT_ARCHIVE_SLUG)
    parser.add_argument("--question-set", choices=["ai041"], default="ai041")
    parser.add_argument("--metadata-csv", default=str(DEFAULT_METADATA_CSV))
    parser.add_argument("--timeout-seconds", type=int, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--token", default=os.environ.get("RAG_BATTERY_TOKEN", ""))
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--downloads-dir", default=str(DEFAULT_DOWNLOADS_DIR))
    parser.add_argument("--skip-downloads-copy", action="store_true")
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
    archive_slug = str(args.archive_slug).strip()
    token = str(args.token or "").strip()
    if not token:
        token = _login(
            base_url=base_url,
            username=str(args.username or "").strip(),
            password=str(args.password or "").strip(),
            timeout_seconds=max(30, int(args.timeout_seconds)),
        )

    completed_files = _list_completed_files(
        base_url=base_url,
        token=token,
        archive_slug=archive_slug,
        timeout_seconds=max(30, int(args.timeout_seconds)),
    )
    file_ids = [int(item.get("file_id") or 0) for item in completed_files if int(item.get("file_id") or 0) > 0]
    file_names = [str(item.get("file_name") or "") for item in completed_files]
    metadata_row = _load_metadata_row(metadata_csv=metadata_csv, archive_slug=archive_slug)
    specs = _build_question_specs(question_set=str(args.question_set), metadata_row=metadata_row)

    passes: list[dict[str, Any]] = []
    for pass_label in DEFAULT_PASSES:
        passes.append(
            _run_pass(
                base_url=base_url,
                token=token,
                file_ids=file_ids,
                specs=specs,
                timeout_seconds=max(30, int(args.timeout_seconds)),
                pass_label=pass_label,
            )
        )

    question_consistency = _build_question_consistency(passes=passes)
    findings = _build_findings(question_consistency=question_consistency)
    all_precision_scores = [float(item["avg_precision_score"]) for item in passes]
    payload: dict[str, Any] = {
        "run_at_utc": _utc_now(),
        "base_url": base_url,
        "archive_slug": archive_slug,
        "question_set": args.question_set,
        "file_ids": file_ids,
        "file_names": file_names,
        "pass_labels": list(DEFAULT_PASSES),
        "total_questions": len(specs),
        "metadata_snapshot": metadata_row,
        "passes": passes,
        "question_consistency": question_consistency,
        "overall_avg_precision_score": round(mean(all_precision_scores), 3) if all_precision_scores else 0.0,
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
        "findings": findings,
    }

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_name = f"rag_question_battery_{archive_slug.lower()}_{stamp}"
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
        f"source_overlap={payload['overall_avg_source_overlap']}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
