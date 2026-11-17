"""Development runner for the backend server."""

from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path
from typing import Any

import uvicorn

APP_IMPORT = "apps.backend.app.main:app"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8012


def resolve_repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def resolve_reload_dirs(repo_root: Path) -> list[str]:
    candidates = [
        repo_root / "apps" / "backend" / "app",
        repo_root / "apps" / "backend" / "db",
    ]
    return [str(path) for path in candidates if path.exists()]


def _to_reload_pattern(*, path: Path, repo_root: Path) -> str:
    try:
        relative_path = path.relative_to(repo_root)
    except ValueError:
        relative_path = path
    return str(relative_path).replace("\\", "/")


def resolve_reload_excludes(repo_root: Path) -> list[str]:
    candidates = [
        repo_root / "apps" / "backend" / "data",
        repo_root / "apps" / "backend" / "logs",
        repo_root / "apps" / "backend" / "wallet",
        repo_root / "apps" / "backend" / "keys",
        repo_root / "apps" / "backend" / ".venv",
        repo_root / "apps" / "backend" / "__pycache__",
        repo_root / "apps" / "frontend" / "node_modules",
        repo_root / "tests_docs",
    ]
    patterns: list[str] = []
    for path in candidates:
        base_pattern = _to_reload_pattern(path=path, repo_root=repo_root)
        patterns.append(base_pattern)
        patterns.append(f"{base_pattern}/*")
        patterns.append(f"{base_pattern}/**")
        patterns.append(f"{base_pattern}/**/*")
    return patterns


def build_uvicorn_kwargs(
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    reload_enabled: bool = True,
) -> dict[str, Any]:
    repo_root = resolve_repo_root()
    kwargs: dict[str, Any] = {
        "app": APP_IMPORT,
        "host": str(host).strip() or DEFAULT_HOST,
        "port": int(port),
        "reload": bool(reload_enabled),
    }
    if reload_enabled:
        kwargs["reload_dirs"] = resolve_reload_dirs(repo_root)
        kwargs["reload_excludes"] = resolve_reload_excludes(repo_root)
    return kwargs


def emit_startup_banner(*, host: str, port: int, reload_enabled: bool) -> None:
    repo_root = resolve_repo_root()
    print(
        f"[backend] Starting dev server on http://{host}:{int(port)} "
        f"(reload={'on' if reload_enabled else 'off'})",
        flush=True,
    )
    print(f"[backend] Workspace: {repo_root}", flush=True)
    if reload_enabled:
        reload_dirs = resolve_reload_dirs(repo_root)
        if reload_dirs:
            print(
                "[backend] Reload watch dirs: " + ", ".join(reload_dirs),
                flush=True,
            )
    print("[backend] Waiting for uvicorn startup...", flush=True)


def parse_args() -> Any:
    parser = ArgumentParser(description="Run the backend development server.")
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--reload", dest="reload_enabled", action="store_true")
    parser.add_argument("--no-reload", dest="reload_enabled", action="store_false")
    parser.set_defaults(reload_enabled=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    emit_startup_banner(
        host=str(args.host).strip() or DEFAULT_HOST,
        port=int(args.port),
        reload_enabled=bool(args.reload_enabled),
    )
    uvicorn.run(
        **build_uvicorn_kwargs(
            host=args.host,
            port=args.port,
            reload_enabled=bool(args.reload_enabled),
        )
    )


if __name__ == "__main__":
    main()
