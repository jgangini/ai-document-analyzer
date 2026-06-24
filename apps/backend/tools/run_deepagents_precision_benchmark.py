from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

import httpx

DEFAULT_BENCHMARK = Path(r"D:\dev\codex-co-police\.source\benchmark.legacy\preguntas_respuestas_tiempos.json")


def _question(item: dict[str, Any]) -> str:
    for key in ("question", "pregunta", "message", "input"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _expected(item: dict[str, Any]) -> str:
    for key in ("expected_answer", "respuesta_esperada", "answer", "respuesta", "respuesta_final"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return ""


def _item_id(item: dict[str, Any], index: int) -> str:
    for key in ("id", "question_id", "benchmark_id", "case_id"):
        value = str(item.get(key) or "").strip()
        if value:
            return value
    return f"bench_{index:03d}"


def _contains_expected_articles(answer: str, expected: str) -> bool:
    if not answer.strip():
        return False
    expected_lower = expected.lower()
    tokens = [
        token.strip(" .,;:()[]{}")
        for token in expected_lower.replace("articulo", "art.").split()
        if token.strip(" .,;:()[]{}").isdigit()
    ]
    if not tokens:
        return True
    answer_lower = answer.lower()
    return any(token in answer_lower for token in tokens)


def run_case(client: httpx.Client, *, api_url: str, item: dict[str, Any], index: int) -> dict[str, Any]:
    question = _question(item)
    expected = _expected(item)
    case_id = _item_id(item, index)
    started = time.perf_counter()
    error = ""
    payload: dict[str, Any] = {}
    try:
        response = client.post(
            api_url,
            json={"message": question, "session_id": case_id, "reset_session": True},
            timeout=120,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception as exc:
        error = str(exc)
    latency_ms = int((time.perf_counter() - started) * 1000)
    answer = str(payload.get("answer") or "")
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    return {
        "case_id": case_id,
        "question": question,
        "latency_ms": latency_ms,
        "answer_chars": len(answer),
        "sources_count": len(sources),
        "non_empty_answer": bool(answer.strip()),
        "has_sources": bool(sources),
        "expected_article_match": _contains_expected_articles(answer, expected),
        "error": error,
        "answer": answer,
        "sources": sources,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id",
        "latency_ms",
        "answer_chars",
        "sources_count",
        "non_empty_answer",
        "has_sources",
        "expected_article_match",
        "error",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the legacy precision benchmark against /api/chat.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--api-url", default="http://127.0.0.1:8012/api/chat")
    parser.add_argument("--json-out", type=Path, default=Path("output/deepagents_precision_results.json"))
    parser.add_argument("--csv-out", type=Path, default=Path("output/deepagents_precision_results.csv"))
    args = parser.parse_args()

    dataset = json.loads(args.dataset.read_text(encoding="utf-8"))
    items = dataset if isinstance(dataset, list) else list(dataset.get("items") or dataset.get("questions") or [])
    rows: list[dict[str, Any]] = []
    with httpx.Client() as client:
        for index, item in enumerate(items, start=1):
            if isinstance(item, dict) and _question(item):
                rows.append(run_case(client, api_url=args.api_url, item=item, index=index))

    summary = {
        "total": len(rows),
        "non_empty_answer": sum(1 for row in rows if row["non_empty_answer"]),
        "has_sources": sum(1 for row in rows if row["has_sources"]),
        "expected_article_match": sum(1 for row in rows if row["expected_article_match"]),
        "errors": sum(1 for row in rows if row["error"]),
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(args.csv_out, rows)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
