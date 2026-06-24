from __future__ import annotations

import argparse
import asyncio
import csv
import json
import time
from pathlib import Path
from typing import Any

import httpx


async def run_user(
    *,
    client: httpx.AsyncClient,
    api_url: str,
    user_index: int,
    message: str,
    semaphore: asyncio.Semaphore,
) -> dict[str, Any]:
    async with semaphore:
        session_id = f"load-user-{user_index:04d}"
        started = time.perf_counter()
        error = ""
        status_code = 0
        sources_count = 0
        try:
            response = await client.post(
                api_url,
                json={"message": message, "session_id": session_id, "reset_session": True},
            )
            status_code = response.status_code
            payload = response.json() if response.headers.get("content-type", "").startswith("application/json") else {}
            sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
            sources_count = len(sources)
            response.raise_for_status()
        except Exception as exc:
            error = str(exc)
        return {
            "session_id": session_id,
            "status_code": status_code,
            "latency_ms": int((time.perf_counter() - started) * 1000),
            "sources_count": sources_count,
            "error": error,
        }


async def run_load(args: argparse.Namespace) -> list[dict[str, Any]]:
    timeout = httpx.Timeout(args.timeout_seconds)
    limits = httpx.Limits(max_connections=args.concurrency, max_keepalive_connections=args.concurrency)
    semaphore = asyncio.Semaphore(args.concurrency)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        tasks = [
            run_user(
                client=client,
                api_url=args.api_url,
                user_index=index,
                message=args.message,
                semaphore=semaphore,
            )
            for index in range(1, args.users + 1)
        ]
        return await asyncio.gather(*tasks)


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = ["session_id", "status_code", "latency_ms", "sources_count", "error"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fields})


def main() -> int:
    parser = argparse.ArgumentParser(description="Run 600-user /api/chat load check.")
    parser.add_argument("--api-url", default="http://127.0.0.1:8012/api/chat")
    parser.add_argument("--users", type=int, default=600)
    parser.add_argument("--concurrency", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--message", default="Resume los documentos disponibles y cita las fuentes principales.")
    parser.add_argument("--json-out", type=Path, default=Path("output/deepagents_load_600_results.json"))
    parser.add_argument("--csv-out", type=Path, default=Path("output/deepagents_load_600_results.csv"))
    args = parser.parse_args()

    started = time.perf_counter()
    rows = asyncio.run(run_load(args))
    elapsed_ms = int((time.perf_counter() - started) * 1000)
    errors = sum(1 for row in rows if row.get("error"))
    latencies = sorted(int(row["latency_ms"]) for row in rows)
    p95 = latencies[int(len(latencies) * 0.95) - 1] if latencies else 0
    summary = {
        "users": len(rows),
        "concurrency": args.concurrency,
        "elapsed_ms": elapsed_ms,
        "errors": errors,
        "p95_latency_ms": p95,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps({"summary": summary, "rows": rows}, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(args.csv_out, rows)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
