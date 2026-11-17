from __future__ import annotations

import json
from pathlib import Path

import uvicorn

from apps.backend.app.dev.server_runner import (
    build_uvicorn_kwargs,
    resolve_reload_dirs,
    resolve_reload_excludes,
    resolve_repo_root,
)


def test_resolve_repo_root_points_to_workspace_root() -> None:
    repo_root = resolve_repo_root()
    assert (repo_root / "apps" / "backend" / "app").exists()
    assert (repo_root / "scripts").exists()


def test_reload_dirs_are_limited_to_backend_source_directories() -> None:
    repo_root = resolve_repo_root()
    reload_dirs = resolve_reload_dirs(repo_root)
    expected = {
        str(repo_root / "apps" / "backend" / "app"),
        str(repo_root / "apps" / "backend" / "db"),
    }
    assert set(reload_dirs) == expected


def test_reload_excludes_cover_runtime_directories() -> None:
    repo_root = resolve_repo_root()
    excludes = resolve_reload_excludes(repo_root)
    expected_prefixes = [
        "apps/backend/data",
        "apps/backend/logs",
        "apps/backend/wallet",
        "apps/backend/keys",
        "tests_docs",
    ]
    for prefix in expected_prefixes:
        assert any(item.startswith(prefix) for item in excludes)
    assert all(not Path(item).is_absolute() for item in excludes)


def test_build_uvicorn_kwargs_includes_reload_configuration() -> None:
    kwargs = build_uvicorn_kwargs(reload_enabled=True)
    assert kwargs["app"] == "apps.backend.app.main:app"
    assert kwargs["reload"] is True
    assert kwargs["reload_dirs"]
    assert kwargs["reload_excludes"]


def test_build_uvicorn_kwargs_without_reload_omits_watch_configuration() -> None:
    kwargs = build_uvicorn_kwargs(reload_enabled=False)
    assert kwargs["reload"] is False
    assert "reload_dirs" not in kwargs
    assert "reload_excludes" not in kwargs


def test_build_uvicorn_kwargs_create_valid_config() -> None:
    kwargs = build_uvicorn_kwargs(reload_enabled=True)
    config = uvicorn.Config(**kwargs)
    assert config.reload is True


def test_dev_start_project_runs_cleanup_before_parallel_services() -> None:
    repo_root = resolve_repo_root()
    tasks_path = repo_root / ".vscode" / "tasks.json"
    cleanup_script = repo_root / "scripts" / "dev-cleanup.ps1"

    payload = json.loads(tasks_path.read_text(encoding="utf-8"))
    tasks_by_label = {str(item["label"]): item for item in list(payload.get("tasks") or [])}

    assert cleanup_script.exists()
    assert "Dev: Cleanup Zombies" in tasks_by_label
    assert "Dev: Start Services" in tasks_by_label
    assert "Dev: Start Project" in tasks_by_label
    assert "Dev: Backend (Reload)" in tasks_by_label

    cleanup_task = tasks_by_label["Dev: Cleanup Zombies"]
    assert "dev-cleanup.ps1" in str(cleanup_task.get("command") or "")

    backend_task = tasks_by_label["Dev: Backend"]
    assert "--no-reload" in str(backend_task.get("command") or "")

    backend_reload_task = tasks_by_label["Dev: Backend (Reload)"]
    assert "--reload" in str(backend_reload_task.get("command") or "")

    start_services_task = tasks_by_label["Dev: Start Services"]
    assert start_services_task.get("dependsOrder") == "parallel"
    assert set(start_services_task.get("dependsOn") or []) == {"Dev: Backend", "Dev: Frontend"}

    start_project_task = tasks_by_label["Dev: Start Project"]
    assert start_project_task.get("dependsOrder") == "sequence"
    assert list(start_project_task.get("dependsOn") or []) == [
        "Dev: Cleanup Zombies",
        "Dev: Start Services",
    ]
