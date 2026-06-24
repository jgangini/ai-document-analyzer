from __future__ import annotations

import argparse
import csv
import json
from hashlib import sha256
from pathlib import Path
from typing import Iterable

DEFAULT_LEGACY_ROOT = Path(r"D:\dev\codex-co-police\.source\app.legacy.v2")
SUPPORTED_SUFFIXES = {
    ".csv",
    ".docx",
    ".html",
    ".json",
    ".jsonl",
    ".md",
    ".pdf",
    ".txt",
    ".xls",
    ".xlsx",
}
EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "keys",
    "logs",
    "node_modules",
    "wallet",
}
EXCLUDED_SUFFIXES = {".env", ".key", ".pem", ".pfx", ".pyc", ".zip"}


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def iter_candidate_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel_parts = {part.lower() for part in path.relative_to(root).parts[:-1]}
        if rel_parts & EXCLUDED_DIRS:
            continue
        suffix = path.suffix.lower()
        if suffix in EXCLUDED_SUFFIXES or suffix not in SUPPORTED_SUFFIXES:
            continue
        name = path.name.lower()
        if "secret" in name or "wallet" in name or "private" in name:
            continue
        yield path


def classify(path: Path) -> str:
    text = str(path).lower()
    if "normative" in text or "ley" in text or "decreto" in text:
        return "normative"
    if "processed" in text or path.suffix.lower() in {".txt", ".md"}:
        return "processed_text"
    if "raw" in text or path.suffix.lower() in {".pdf", ".html"}:
        return "raw_source"
    return "document"


def build_inventory(root: Path) -> dict[str, object]:
    items: list[dict[str, object]] = []
    suffix_counts: dict[str, int] = {}
    category_counts: dict[str, int] = {}
    for path in sorted(iter_candidate_files(root)):
        rel = path.relative_to(root).as_posix()
        suffix = path.suffix.lower()
        category = classify(path)
        suffix_counts[suffix] = suffix_counts.get(suffix, 0) + 1
        category_counts[category] = category_counts.get(category, 0) + 1
        items.append(
            {
                "source_id": rel,
                "relative_path": rel,
                "suffix": suffix,
                "category": category,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
        )
    return {
        "legacy_root": str(root),
        "total_items": len(items),
        "suffix_counts": suffix_counts,
        "category_counts": category_counts,
        "items": items,
    }


def write_csv(path: Path, items: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = ["source_id", "relative_path", "suffix", "category", "size_bytes", "sha256"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for item in items:
            writer.writerow({key: item.get(key, "") for key in fieldnames})


def main() -> int:
    parser = argparse.ArgumentParser(description="Inventory legacy documents for evidence-ledger migration.")
    parser.add_argument("--root", type=Path, default=DEFAULT_LEGACY_ROOT)
    parser.add_argument("--json-out", type=Path, default=Path("output/legacy_corpus_inventory.json"))
    parser.add_argument("--csv-out", type=Path, default=Path("output/legacy_corpus_inventory.csv"))
    args = parser.parse_args()

    inventory = build_inventory(args.root)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(inventory, indent=2, ensure_ascii=False), encoding="utf-8")
    write_csv(args.csv_out, list(inventory["items"]))
    print(json.dumps({k: v for k, v in inventory.items() if k != "items"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
