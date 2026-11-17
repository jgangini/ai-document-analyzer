from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from apps.backend.app.core import oci_db_config
from apps.backend.app.services.bootstrap_service import SetupService


class _StubCursor:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def execute(self, _query: str) -> None:
        return None

    def fetchall(self) -> list[tuple[str, str]]:
        return list(self._rows)

    def close(self) -> None:
        return None


class _StubConnection:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def cursor(self) -> _StubCursor:
        return _StubCursor(self._rows)

    def close(self) -> None:
        return None


class _StubDbManager:
    def __init__(self, rows: list[tuple[str, str]]) -> None:
        self._rows = rows

    def get_connection(self) -> _StubConnection:
        return _StubConnection(self._rows)


def test_load_oci_config_resolves_windows_key_file_from_backend_keys_dir(tmp_path, monkeypatch) -> None:
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir(parents=True)
    (keys_dir / "key.pem").write_text("PRIVATE KEY", encoding="utf-8")
    missing_absolute_key = str((tmp_path / "moved" / "key.pem").resolve())

    monkeypatch.setattr(
        oci_db_config,
        "get_settings",
        lambda: SimpleNamespace(root_dir=tmp_path, keys_dir=keys_dir),
        raising=False,
    )

    db_manager = _StubDbManager(
        [
            ("oci.user", "ocid1.user"),
            ("oci.fingerprint", "fp"),
            ("oci.tenancy", "ocid1.tenancy"),
            ("oci.region", "us-chicago-1"),
            ("oci.key_file", missing_absolute_key),
        ]
    )

    config = oci_db_config.load_oci_config(db_manager)

    assert config is not None
    assert config["key_content"] == "PRIVATE KEY"


def test_setup_service_resolves_windows_key_file_to_backend_keys_dir(tmp_path, monkeypatch) -> None:
    keys_dir = tmp_path / "keys"
    keys_dir.mkdir(parents=True)
    (keys_dir / "key.pem").write_text("PRIVATE KEY", encoding="utf-8")
    monkeypatch.setattr(SetupService, "_resolve_backend_root", staticmethod(lambda: Path(tmp_path)))

    service = SetupService(db_manager=SimpleNamespace())

    resolved = service._resolve_oci_key_file_path(str((tmp_path / "moved" / "key.pem").resolve()))

    assert resolved == str((tmp_path / "keys" / "key.pem").resolve())
