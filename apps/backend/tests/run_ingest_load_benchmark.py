from __future__ import annotations

import argparse
import json
import traceback
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event, Thread
from time import perf_counter

ROOT = Path(__file__).resolve().parents[3]

import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.backend.app.core.config import get_settings
from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.ingest.ingestion_factory import get_ingestion_service


TABLE_NAMES = (
    "files",
    "file_pages",
    "page_embeddings",
    "file_embeddings",
    "file_groups",
    "file_profiles",
    "file_entities",
    "file_attributes",
    "file_links",
)


@dataclass(slots=True)
class ArchiveRunResult:
    archive_name: str
    zip_bytes: int
    elapsed_ms: int
    success: bool
    processed_count: int
    processed_files: list[dict[str, object]]
    error: str
    traceback_text: str
    counts_before: dict[str, int]
    counts_after: dict[str, int]


@dataclass(slots=True)
class LiveArchiveSnapshot:
    processing_files: int
    registered_files: int
    completed_files: int
    failed_files: int
    latest_processing_file: str
    latest_processing_page_count: int
    latest_processing_recorded_pages: int
    latest_processing_embeddings: int


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run an ingestion load benchmark over tests_docs archives.")
    parser.add_argument(
        "--source-dir",
        default="tests_docs",
        help="Directory containing ZIP archives.",
    )
    parser.add_argument(
        "--archives",
        nargs="*",
        default=None,
        metavar="ZIP",
        help="Optional explicit archive names to benchmark.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Limit how many archives to run after selection (0 = all).",
    )
    parser.add_argument(
        "--user-id",
        type=int,
        default=0,
        help="Target user_id for ingestion.",
    )
    parser.add_argument(
        "--document-language",
        default="es",
        help="Language passed to Docling OCR.",
    )
    parser.add_argument(
        "--output-dir",
        default="apps/backend/tests/reports",
        help="Output directory for JSON and Markdown reports.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop the benchmark on the first failing archive.",
    )
    parser.add_argument(
        "--heartbeat-seconds",
        type=int,
        default=30,
        help="Heartbeat interval while a single archive is being ingested (0 disables heartbeat).",
    )
    return parser.parse_args()


def _resolve_archives(args: argparse.Namespace) -> list[Path]:
    source_dir = Path(args.source_dir)
    if not source_dir.is_absolute():
        source_dir = ROOT / source_dir
    if args.archives:
        resolved: list[Path] = []
        for raw_name in args.archives:
            candidate = source_dir / raw_name
            if not candidate.exists():
                raise FileNotFoundError(f"Archive not found: {candidate}")
            resolved.append(candidate)
    else:
        resolved = sorted(source_dir.glob("*.zip"))
    if int(args.limit or 0) > 0:
        resolved = resolved[: int(args.limit)]
    return resolved


def _get_counts() -> dict[str, int]:
    settings = get_settings()
    db = DatabaseManager.get_instance(settings)
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        counts: dict[str, int] = {}
        for table_name in TABLE_NAMES:
            cur.execute(f"SELECT COUNT(*) FROM {table_name}")
            row = cur.fetchone()
            counts[table_name] = int(row[0] or 0) if row else 0
        return counts
    finally:
        cur.close()
        conn.close()


def _format_duration(milliseconds: int) -> str:
    seconds = max(0.0, float(milliseconds) / 1000.0)
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, sec = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {sec:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


def _get_live_snapshot() -> LiveArchiveSnapshot:
    settings = get_settings()
    db = DatabaseManager.get_instance(settings)
    conn = db.get_connection()
    cur = conn.cursor()
    try:
        counts: dict[str, int] = {}
        for key, state in (
            ("registered_files", 1),
            ("processing_files", 2),
            ("completed_files", 3),
            ("failed_files", -1),
        ):
            cur.execute("SELECT COUNT(*) FROM files WHERE file_state = :state", state=state)
            counts[key] = int(cur.fetchone()[0] or 0)
        cur.execute(
            """
            SELECT file_id, file_input_file_name, file_page_count
            FROM files
            WHERE file_state = 2
            ORDER BY file_updated DESC
            FETCH FIRST 1 ROWS ONLY
            """
        )
        row = cur.fetchone()
        if not row:
            return LiveArchiveSnapshot(
                processing_files=counts["processing_files"],
                registered_files=counts["registered_files"],
                completed_files=counts["completed_files"],
                failed_files=counts["failed_files"],
                latest_processing_file="",
                latest_processing_page_count=0,
                latest_processing_recorded_pages=0,
                latest_processing_embeddings=0,
            )
        file_id = int(row[0] or 0)
        file_name = str(row[1] or "")
        file_page_count = int(row[2] or 0)
        cur.execute("SELECT COUNT(*) FROM file_pages WHERE file_id = :file_id", file_id=file_id)
        recorded_pages = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM page_embeddings WHERE file_id = :file_id", file_id=file_id)
        embeddings = int(cur.fetchone()[0] or 0)
        return LiveArchiveSnapshot(
            processing_files=counts["processing_files"],
            registered_files=counts["registered_files"],
            completed_files=counts["completed_files"],
            failed_files=counts["failed_files"],
            latest_processing_file=file_name,
            latest_processing_page_count=file_page_count,
            latest_processing_recorded_pages=recorded_pages,
            latest_processing_embeddings=embeddings,
        )
    finally:
        cur.close()
        conn.close()


def _start_archive_heartbeat(
    *,
    archive_name: str,
    started_at: float,
    heartbeat_seconds: int,
) -> tuple[Event, Thread] | None:
    if heartbeat_seconds <= 0:
        return None
    stop_event = Event()

    def _run() -> None:
        while not stop_event.wait(timeout=float(heartbeat_seconds)):
            snapshot = _get_live_snapshot()
            elapsed_ms = int((perf_counter() - started_at) * 1000)
            print(
                "[HEARTBEAT] "
                f"archive={archive_name} | elapsed={_format_duration(elapsed_ms)} | "
                f"completed_files={snapshot.completed_files} | processing_files={snapshot.processing_files} | "
                f"registered_files={snapshot.registered_files} | failed_files={snapshot.failed_files}",
                flush=True,
            )
            if snapshot.latest_processing_file:
                print(
                    "           "
                    f"active_file={snapshot.latest_processing_file} | "
                    f"declared_pages={snapshot.latest_processing_page_count} | "
                    f"recorded_pages={snapshot.latest_processing_recorded_pages} | "
                    f"page_embeddings={snapshot.latest_processing_embeddings}",
                    flush=True,
                )

    thread = Thread(target=_run, name=f"benchmark-heartbeat-{archive_name}", daemon=True)
    thread.start()
    return stop_event, thread


def _run_archive(*, archive_path: Path, args: argparse.Namespace) -> ArchiveRunResult:
    service = get_ingestion_service()
    counts_before = _get_counts()
    started = perf_counter()
    heartbeat_handle = _start_archive_heartbeat(
        archive_name=archive_path.name,
        started_at=started,
        heartbeat_seconds=max(0, int(args.heartbeat_seconds or 0)),
    )
    try:
        processed = service.process_documents(
            source_path=archive_path,
            include_archives=True,
            user_id=int(args.user_id),
            document_language=str(args.document_language or "").strip() or None,
        )
        elapsed_ms = int((perf_counter() - started) * 1000)
        counts_after = _get_counts()
        processed_files = [
            {
                "file_id": int(item.file_id),
                "file_name": str(item.file_name),
                "status": str(item.status),
                "page_count": int(item.page_count),
                "object_name": str(item.object_name),
            }
            for item in processed
        ]
        return ArchiveRunResult(
            archive_name=archive_path.name,
            zip_bytes=int(archive_path.stat().st_size),
            elapsed_ms=elapsed_ms,
            success=True,
            processed_count=len(processed_files),
            processed_files=processed_files,
            error="",
            traceback_text="",
            counts_before=counts_before,
            counts_after=counts_after,
        )
    except Exception as exc:
        elapsed_ms = int((perf_counter() - started) * 1000)
        return ArchiveRunResult(
            archive_name=archive_path.name,
            zip_bytes=int(archive_path.stat().st_size),
            elapsed_ms=elapsed_ms,
            success=False,
            processed_count=0,
            processed_files=[],
            error=str(exc),
            traceback_text=traceback.format_exc(),
            counts_before=counts_before,
            counts_after=_get_counts(),
        )
    finally:
        if heartbeat_handle is not None:
            stop_event, thread = heartbeat_handle
            stop_event.set()
            thread.join(timeout=2.0)


def _build_markdown_report(*, payload: dict[str, object]) -> str:
    lines: list[str] = []
    lines.append("# Ingestion Load Benchmark")
    lines.append("")
    lines.append(f"- Run UTC: `{payload['run_at_utc']}`")
    lines.append(f"- Source dir: `{payload['source_dir']}`")
    lines.append(f"- Archives requested: `{payload['archives_requested']}`")
    lines.append(f"- Archives completed: `{payload['archives_completed']}`")
    lines.append(f"- Archives failed: `{payload['archives_failed']}`")
    lines.append(f"- Total elapsed: `{payload['total_elapsed_ms']} ms`")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    for item in payload["results"]:
        lines.append(f"### {item['archive_name']}")
        lines.append(
            f"- success: `{item['success']}` | elapsed: `{item['elapsed_ms']} ms` ({_format_duration(int(item['elapsed_ms']))})"
        )
        lines.append(f"- zip_bytes: `{item['zip_bytes']}` | processed_count: `{item['processed_count']}`")
        if item["error"]:
            lines.append(f"- error: `{item['error']}`")
        if item["processed_files"]:
            rendered = ", ".join(
                f"{entry['file_name']}[{entry['status']}|pages={entry['page_count']}]"
                for entry in item["processed_files"]
            )
            lines.append(f"- processed_files: {rendered}")
        before_counts = item["counts_before"]
        after_counts = item["counts_after"]
        delta_parts = []
        for table_name in TABLE_NAMES:
            delta = int(after_counts.get(table_name, 0)) - int(before_counts.get(table_name, 0))
            delta_parts.append(f"{table_name}={delta:+d}")
        lines.append(f"- deltas: {', '.join(delta_parts)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    args = _parse_args()
    archives = _resolve_archives(args)
    output_dir = Path(args.output_dir)
    if not output_dir.is_absolute():
        output_dir = ROOT / output_dir
    output_dir.mkdir(parents=True, exist_ok=True)

    print(
        f"[INFO] archives={len(archives)} | source_dir={Path(args.source_dir)} | user_id={int(args.user_id)}",
        flush=True,
    )
    benchmark_started = perf_counter()
    results: list[ArchiveRunResult] = []
    for index, archive_path in enumerate(archives, start=1):
        print(f"[RUN] {index}/{len(archives)} -> {archive_path.name}", flush=True)
        result = _run_archive(archive_path=archive_path, args=args)
        results.append(result)
        status = "OK" if result.success else "FAIL"
        print(
            f"[DONE] {archive_path.name} | status={status} | elapsed={_format_duration(result.elapsed_ms)} | processed={result.processed_count}",
            flush=True,
        )
        if result.error:
            print(f"       error={result.error}", flush=True)
        if args.stop_on_error and not result.success:
            break

    total_elapsed_ms = int((perf_counter() - benchmark_started) * 1000)
    payload = {
        "run_at_utc": _utc_now(),
        "source_dir": str(Path(args.source_dir)),
        "archives_requested": len(archives),
        "archives_completed": sum(1 for item in results if item.success),
        "archives_failed": sum(1 for item in results if not item.success),
        "total_elapsed_ms": total_elapsed_ms,
        "results": [asdict(item) for item in results],
        "final_counts": _get_counts(),
    }
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"ingest_load_benchmark_{stamp}.json"
    md_path = output_dir / f"ingest_load_benchmark_{stamp}.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(_build_markdown_report(payload=payload), encoding="utf-8")
    print(f"[REPORT] json={json_path}", flush=True)
    print(f"[REPORT] md={md_path}", flush=True)
    return 0 if payload["archives_failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
