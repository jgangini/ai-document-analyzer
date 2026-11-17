"""
Runner de bateria RAG para preguntas de contratos.

Ejemplo:
  & "apps/backend/.venv/Scripts/python.exe" `
    "apps/backend/tests/run_rag_question_battery.py" `
    --base-url "http://127.0.0.1:8012/api"

Solo dos carpetas (un reporte JSON/MD por carpeta):
  ... run_rag_question_battery.py `
    --folders RM797_ID_1668 RM797_ID_5515 --timeout-seconds 300
"""

from __future__ import annotations

import argparse
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib import error as url_error
from urllib import request as url_request


QUESTIONS: list[str] = [
    "¿Cuál es el/los Rut del propietario(s)?",
    "¿Cuál es el nombre y rut de la persona que recibe la renta?",
    "¿Cuál es el medio de pago del contrato?",
    "¿Hay penalización por pago atrasado de renta?",
    "¿Qué dicen la última modificación del acceso al terreno?",
    "¿Qué sociedad Entel firmó el contrato?",
    "¿Cuánto tiempo le queda de vigencia al contrato? / Si hoy es 20 de Marzo 2026",
    "¿Tiene renovación Automática?",
    "¿Cuando se firmó el contrato?",
    "¿Cuántas modificaciones tiene el contrato?",
    "¿Qué dice el último contrato vigente respecto a la cláusula de cesión a terceros?",
    "¿Quién es el representante de Entel?",
    "¿Con cuánta anticipación debo enviar la carta Entel para dar término al contrato?",
    "¿Tiene término anticipado para el propietario?",
    "¿Qué representante de Entel firmó el contrato?",
    "Muéstrame la firma del representante de Entel de los documentos PDF.",
    "¿Hay diferencia entre los metros cuadrados arrendados de la metadata vs lo que dice el/los documento PDF?",
    "¿Cuántos contratos están vigentes y firmados por Empresa Nacional de Telecomunicaciones SA?",
    "¿Cuántos contratos fueron firmados por TRANSAM?",
    "¿Cuántos contratos están vencidos?",
    "¿Qué sitios tienen más de ID de contrato?",
]

def _format_duration(seconds: float) -> str:
    if seconds < 0 or seconds != seconds:  # NaN
        return "-"
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _match_folder_key(candidates: list[str], wanted: str) -> str | None:
    w = wanted.strip()
    if not w:
        return None
    w_lower = w.lower()
    for key in candidates:
        if key == w:
            return key
    for key in candidates:
        if key.lower() == w_lower:
            return key
    for key in candidates:
        if w_lower in key.lower() or key.lower() in w_lower:
            return key
    return None


def _filter_groups_by_folder_names(
    group_file_ids: dict[str, list[int]],
    wanted_names: list[str],
) -> dict[str, list[int]]:
    """Conserva el orden de `wanted_names`; avisa si falta alguna carpeta."""
    out: dict[str, list[int]] = {}
    keys_available = list(group_file_ids.keys())
    for raw in wanted_names:
        name = raw.strip()
        if not name:
            continue
        key = _match_folder_key(keys_available, name)
        if key is None:
            print(f"[WARN] Carpeta solicitada '{name}' no coincide con ningún grupo conocido.", flush=True)
            continue
        if key in out:
            continue
        out[key] = group_file_ids[key]
    return out


UNCERTAINTY_HINTS = (
    "no se encuentra",
    "no se identific",
    "no se observa",
    "no disponible",
    "no hay evidencia",
    "no puedo confirmar",
    "insuficiente",
    "no se puede determinar",
)


@dataclass
class HttpResult:
    status_code: int
    payload: Any
    elapsed_ms: int
    error_text: str = ""


def _http_json(
    *,
    method: str,
    url: str,
    timeout_seconds: int,
    body: dict[str, Any] | None = None,
    token: str | None = None,
) -> HttpResult:
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = url_request.Request(url=url, method=method.upper(), headers=headers, data=data)
    started = perf_counter()
    try:
        with url_request.urlopen(req, timeout=timeout_seconds) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            elapsed_ms = int((perf_counter() - started) * 1000)
            payload = json.loads(raw) if raw.strip() else {}
            return HttpResult(status_code=int(resp.status), payload=payload, elapsed_ms=elapsed_ms)
    except url_error.HTTPError as exc:
        elapsed_ms = int((perf_counter() - started) * 1000)
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except Exception:
            payload = {"detail": raw}
        return HttpResult(
            status_code=int(exc.code),
            payload=payload,
            elapsed_ms=elapsed_ms,
            error_text=str(payload.get("detail") or raw or exc.reason),
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return HttpResult(
            status_code=0,
            payload={},
            elapsed_ms=elapsed_ms,
            error_text=str(exc),
        )


def _extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        items = payload.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    return []


def _normalize_file_status(raw: Any) -> str:
    value = str(raw or "").strip().lower()
    if value == "processing":
        return "processing_ocr"
    if value == "failed":
        return "error"
    return value


def _extract_folder_from_object_path(object_path: str) -> str:
    """Extrae el identificador de carpeta desde file_input_obj_name o file_output_obj_name."""
    normalized = str(object_path or "").strip().replace("\\", "/")
    if not normalized:
        return ""
    segments = [s for s in normalized.split("/") if s]
    try:
        idx = next(i for i, s in enumerate(segments) if s.lower() in ("source", "sources", "processed", "output", "outputs", "ocr"))
    except StopIteration:
        return segments[0] if segments else ""
    if idx <= 1:
        return ""
    direct = segments[idx - 1] or ""
    parent = segments[idx - 2] if idx >= 2 else ""
    if parent and re.search(r"-[a-f0-9]{8,}$", parent, re.I):
        return re.sub(r"-[a-f0-9]{8,}$", "", parent, flags=re.I)
    return direct


def _group_docs_by_folder(docs: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Agrupa documentos por carpeta (archive_slug) extraída del object path."""
    groups: dict[str, list[dict[str, Any]]] = {}
    for item in docs:
        obj_name = str(item.get("file_input_obj_name") or item.get("file_output_obj_name") or "").strip()
        folder = _extract_folder_from_object_path(obj_name)
        if not folder:
            folder = "_sin_carpeta"
        groups.setdefault(folder, []).append(item)
    return groups


def _derive_precision_proxy(*, answer_text: str, citations: int, distinct_files: int) -> float:
    score = 0.0
    normalized = answer_text.strip().lower()
    has_answer = len(normalized) >= 20
    uncertain = any(hint in normalized for hint in UNCERTAINTY_HINTS)
    if has_answer:
        score += 0.45
    if citations > 0:
        score += 0.35
    if distinct_files > 0:
        score += 0.1
    if not uncertain:
        score += 0.1
    return round(min(score, 1.0), 3)


def _build_md_report(*, run_data: dict[str, Any], folder_name: str | None = None) -> str:
    lines: list[str] = []
    title = "RAG Question Battery Report"
    if folder_name:
        title += f" — {folder_name}"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Fecha UTC: `{run_data['run_at_utc']}`")
    lines.append(f"- Base URL: `{run_data['base_url']}`")
    lines.append(f"- Documentos completados usados: `{run_data['selected_completed_docs']}`")
    lines.append(f"- Preguntas ejecutadas: `{run_data['total_questions']}`")
    lines.append(f"- Exitosas HTTP 200: `{run_data['ok_count']}`")
    lines.append(f"- Fallidas: `{run_data['failed_count']}`")
    lines.append(f"- Tiempo total: `{run_data['total_elapsed_ms']} ms`")
    lines.append(
        f"- Promedio precision_proxy: `{run_data['avg_precision_proxy']}` "
        "(métrica heurística, requiere validación humana)"
    )
    lines.append("")
    lines.append("## Resultados por pregunta")
    lines.append("")
    for item in run_data["results"]:
        lines.append(f"### {item['id']:02d}. {item['question']}")
        lines.append(
            f"- status: `{item['status_code']}` | elapsed: `{item['elapsed_ms']} ms` | "
            f"precision_proxy: `{item['precision_proxy']}`"
        )
        lines.append(
            f"- respuesta_chars: `{item['answer_chars']}` | citations: `{item['citations_count']}` | "
            f"evidence_sources: `{item['evidence_sources_count']}` | distinct_files: `{item['distinct_files_in_sources']}`"
        )
        if item["error"]:
            lines.append(f"- error: `{item['error']}`")
        if item["answer_preview"]:
            lines.append(f"- answer_preview: {item['answer_preview']}")
        if item["top_sources"]:
            lines.append(f"- top_sources: {', '.join(item['top_sources'])}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ejecuta batería de preguntas RAG y genera reporte.")
    parser.add_argument("--base-url", default="http://127.0.0.1:8012/api")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--top-k", type=int, default=10)
    parser.add_argument("--candidate-k", type=int, default=40)
    parser.add_argument("--min-pages-per-selected-doc", type=int, default=0)
    parser.add_argument("--summary-mode", choices=["default", "per_document"], default="default")
    parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="1 = una pregunta tras otra en orden (por carpeta). >1 = paralelo dentro de la carpeta.",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=0,
        help="Limita cantidad de preguntas (0 = todas).",
    )
    parser.add_argument(
        "--include-non-completed",
        action="store_true",
        help="Incluye docs no completados al construir file_ids.",
    )
    parser.add_argument(
        "--token",
        default=os.environ.get("RAG_BATTERY_TOKEN", ""),
        help="Bearer token opcional (también por env RAG_BATTERY_TOKEN).",
    )
    parser.add_argument(
        "--output-dir",
        default="apps/backend/tests/reports",
        help="Carpeta de salida para JSON/MD.",
    )
    parser.add_argument(
        "--folders",
        nargs="*",
        default=None,
        metavar="NAME",
        help=(
            "Solo ejecutar estos grupos/carpetas (orden conservado), p. ej. RM797_ID_1668 RM797_ID_5515. "
            "Sin este flag = todos los grupos con documentos."
        ),
    )
    parser.add_argument(
        "--group-by-folder",
        action="store_true",
        default=True,
        help="Ejecuta por grupo de carpeta (archivo/source). Default: True.",
    )
    parser.add_argument(
        "--no-group-by-folder",
        action="store_false",
        dest="group_by_folder",
        help="No agrupar por carpeta; ejecutar todas las preguntas con todos los docs.",
    )
    return parser.parse_args()


def _emit_question_progress_line(
    *,
    folder_name: str,
    result: dict[str, Any],
    results: list[dict[str, Any]],
    run_started: float,
    total_questions: int,
) -> None:
    """Log tras cada pregunta terminada (tiempos + ETA)."""
    ordered_done = len(results)
    index = int(result["id"])
    q_sec = float(result["elapsed_ms"]) / 1000.0
    wall_sec = perf_counter() - run_started
    sum_ms = sum(int(r["elapsed_ms"]) for r in results)
    avg_q_sec = (sum_ms / 1000.0) / max(1, ordered_done)
    eta_txt = "-"
    if ordered_done > 0 and wall_sec > 0.05:
        rate = ordered_done / wall_sec
        remaining = total_questions - ordered_done
        if rate > 0 and remaining > 0:
            eta_sec = remaining / rate
            eta_txt = f"~{_format_duration(eta_sec)}"
        elif remaining <= 0:
            eta_txt = "0s"
    q_preview = str(result.get("question") or "")[:72].replace("\n", " ")
    if len(str(result.get("question") or "")) > 72:
        q_preview += "..."
    print(
        f"  [{folder_name}] [{index:02d}/{total_questions}] http={result['status_code']} | "
        f"esta_pregunta={_format_duration(q_sec)} | media_pregunta={_format_duration(avg_q_sec)} | "
        f"hechas={ordered_done}/{total_questions} | ETA_restante={eta_txt} | "
        f"precision_proxy={result['precision_proxy']}",
        flush=True,
    )
    if q_preview:
        print(f"      -> {q_preview}", flush=True)


def _run_battery_for_file_ids(
    *,
    file_ids: list[int],
    folder_name: str,
    questions: list[str],
    base_url: str,
    token: str | None,
    args: argparse.Namespace,
    workers: int,
) -> dict[str, Any]:
    """Ejecuta la batería de preguntas para un conjunto de file_ids."""
    run_started = perf_counter()
    results: list[dict[str, Any]] = []
    total_q = len(questions)
    timeout_s = max(30, int(args.timeout_seconds))
    modo = "secuencial (pregunta a pregunta)" if workers <= 1 else f"paralelo workers={workers}"
    print(
        f"[PROGRESS] carpeta={folder_name} | docs={len(file_ids)} | preguntas={total_q} | "
        f"modo={modo} | timeout_por_pregunta={timeout_s}s",
        flush=True,
    )

    def _run_question(index: int, question: str) -> dict[str, Any]:
        payload = {
            "question": question,
            "file_ids": file_ids,
            "top_k": int(args.top_k),
            "candidate_k": int(args.candidate_k),
            "min_pages_per_selected_doc": int(args.min_pages_per_selected_doc),
            "summary_mode": str(args.summary_mode),
        }
        response = _http_json(
            method="POST",
            url=f"{base_url}/questions/ask",
            timeout_seconds=timeout_s,
            body=payload,
            token=token,
        )

        answer_text = ""
        citations_count = 0
        evidence_sources_count = 0
        distinct_files = 0
        top_sources: list[str] = []
        error_text = response.error_text
        if response.status_code == 200 and isinstance(response.payload, dict):
            answer_text = str(response.payload.get("answer_text") or response.payload.get("answer") or "")
            citations = response.payload.get("citations") or []
            evidence = response.payload.get("evidence_sources") or response.payload.get("sources") or []
            citations_count = len(citations) if isinstance(citations, list) else 0
            evidence_sources_count = len(evidence) if isinstance(evidence, list) else 0
            if isinstance(evidence, list):
                ids = {
                    int(item.get("file_id") or 0)
                    for item in evidence
                    if isinstance(item, dict) and int(item.get("file_id") or 0) > 0
                }
                distinct_files = len(ids)
                top_sources = [
                    str(item.get("name") or item.get("file_name") or "").strip()
                    for item in evidence[:3]
                    if isinstance(item, dict)
                ]

        precision_proxy = _derive_precision_proxy(
            answer_text=answer_text,
            citations=citations_count,
            distinct_files=distinct_files,
        )
        answer_preview = answer_text.replace("\n", " ").strip()
        if len(answer_preview) > 260:
            answer_preview = answer_preview[:257] + "..."
        return {
            "id": index,
            "question": question,
            "status_code": response.status_code,
            "elapsed_ms": response.elapsed_ms,
            "answer_chars": len(answer_text),
            "answer_preview": answer_preview,
            "citations_count": citations_count,
            "evidence_sources_count": evidence_sources_count,
            "distinct_files_in_sources": distinct_files,
            "precision_proxy": precision_proxy,
            "top_sources": [src for src in top_sources if src],
            "error": error_text,
            "requires_manual_review": True,
        }

    if workers <= 1:
        for idx, question in enumerate(questions, start=1):
            q_head = question.replace("\n", " ").strip()
            if len(q_head) > 100:
                q_head = q_head[:97] + "..."
            print(
                f"  [{folder_name}] >> Iniciando pregunta {idx}/{total_q} ... {q_head}",
                flush=True,
            )
            result = _run_question(idx, question)
            results.append(result)
            _emit_question_progress_line(
                folder_name=folder_name,
                result=result,
                results=results,
                run_started=run_started,
                total_questions=total_q,
            )
    else:
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="rag-battery-q") as executor:
            future_map = {
                executor.submit(_run_question, idx, question): idx
                for idx, question in enumerate(questions, start=1)
            }
            for future in as_completed(future_map):
                result = future.result()
                results.append(result)
                _emit_question_progress_line(
                    folder_name=folder_name,
                    result=result,
                    results=results,
                    run_started=run_started,
                    total_questions=total_q,
                )

    results.sort(key=lambda item: int(item.get("id") or 0))
    total_elapsed_ms = int((perf_counter() - run_started) * 1000)
    ok_count = sum(1 for item in results if int(item["status_code"]) == 200)
    avg_precision = round(
        sum(float(item["precision_proxy"]) for item in results) / max(1, len(results)),
        3,
    )
    return {
        "folder_name": folder_name,
        "selected_completed_docs": len(file_ids),
        "total_questions": len(questions),
        "ok_count": ok_count,
        "failed_count": len(questions) - ok_count,
        "avg_precision_proxy": avg_precision,
        "total_elapsed_ms": total_elapsed_ms,
        "results": results,
    }


def main() -> int:
    args = _parse_args()
    base_url = str(args.base_url).rstrip("/")
    token = str(args.token or "").strip() or None

    files_resp = _http_json(
        method="GET",
        url=f"{base_url}/files",
        timeout_seconds=max(30, int(args.timeout_seconds)),
        token=token,
    )
    if files_resp.status_code != 200:
        print(f"[ERROR] No se pudo listar documentos: status={files_resp.status_code} detail={files_resp.error_text}")
        return 2
    files = _extract_items(files_resp.payload)
    completed_docs = [
        item
        for item in files
        if _normalize_file_status(item.get("status")) == "completed"
    ]
    selected_docs = files if args.include_non_completed else completed_docs

    questions = QUESTIONS
    if int(args.max_questions or 0) > 0:
        questions = QUESTIONS[: int(args.max_questions)]
    workers = max(1, int(args.workers))

    if args.group_by_folder:
        groups = _group_docs_by_folder(selected_docs)
        group_file_ids: dict[str, list[int]] = {}
        for folder, docs in groups.items():
            ids = sorted(
                {
                    int(item.get("file_id") or item.get("id") or 0)
                    for item in docs
                    if int(item.get("file_id") or item.get("id") or 0) > 0
                }
            )
            if ids:
                group_file_ids[folder] = ids

        if args.folders is not None:
            wanted = [str(x).strip() for x in args.folders if str(x).strip()]
            if wanted:
                group_file_ids = _filter_groups_by_folder_names(group_file_ids, wanted)
            else:
                print(
                    "[WARN] --folders sin nombres; se ejecutan todas las carpetas con documentos.",
                    flush=True,
                )

        print(f"[INFO] Docs totales={len(files)} | completados={len(completed_docs)} | grupos={len(group_file_ids)}")
        for folder, ids in sorted(group_file_ids.items()):
            print(f"[INFO] Carpeta '{folder}': {len(ids)} documentos -> file_ids={ids}", flush=True)

        if not group_file_ids:
            print("[WARN] No hay grupos con documentos completados para la batería.")
            return 1

        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        total_ok = 0
        total_q = 0

        for folder in group_file_ids.keys():
            file_ids = group_file_ids[folder]
            print(f"\n[RUN] Ejecutando batería para carpeta '{folder}' ({len(file_ids)} docs)...", flush=True)
            run_data = _run_battery_for_file_ids(
                file_ids=file_ids,
                folder_name=folder,
                questions=questions,
                base_url=base_url,
                token=token,
                args=args,
                workers=workers,
            )
            run_data["run_at_utc"] = datetime.now(timezone.utc).isoformat()
            run_data["base_url"] = base_url
            run_data["folder_name"] = folder

            json_path = output_dir / f"rag_question_battery_{folder}_{stamp}.json"
            md_path = output_dir / f"rag_question_battery_{folder}_{stamp}.md"
            json_path.write_text(json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8")
            md_path.write_text(_build_md_report(run_data=run_data, folder_name=folder), encoding="utf-8")
            total_ok += run_data["ok_count"]
            total_q += run_data["total_questions"]
            print(f"[DONE] Reporte carpeta '{folder}': {json_path.name} | {md_path.name}")

        print(f"\n[DONE] Total preguntas OK: {total_ok}/{total_q}")
        return 0

    # Modo sin agrupar: todos los docs juntos
    selected_file_ids = sorted(
        {
            int(item.get("file_id") or item.get("id") or 0)
            for item in selected_docs
            if int(item.get("file_id") or item.get("id") or 0) > 0
        }
    )
    print(f"[INFO] Docs totales={len(files)} | completados={len(completed_docs)} | usados={len(selected_file_ids)}")
    if not selected_file_ids:
        print("[WARN] No hay documentos seleccionados para la batería (file_ids vacío).")
        return 1

    run_data = _run_battery_for_file_ids(
        file_ids=selected_file_ids,
        folder_name="_todos",
        questions=questions,
        base_url=base_url,
        token=token,
        args=args,
        workers=workers,
    )
    run_data["run_at_utc"] = datetime.now(timezone.utc).isoformat()
    run_data["base_url"] = base_url

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"rag_question_battery_{stamp}.json"
    md_path = output_dir / f"rag_question_battery_{stamp}.md"
    json_path.write_text(json.dumps(run_data, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_build_md_report(run_data=run_data, folder_name=None), encoding="utf-8")

    print(f"[DONE] Reporte JSON: {json_path}")
    print(f"[DONE] Reporte MD:   {md_path}")
    print(f"[DONE] Preguntas OK: {run_data['ok_count']}/{run_data['total_questions']} | promedio precision_proxy={run_data['avg_precision_proxy']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
