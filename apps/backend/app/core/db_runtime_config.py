import json
import logging
import os
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

REQUIRED_DB_KEYS = (
    "user",
    "password",
    "dsn",
    "wallet_path",
    "wallet_password",
)


class RuntimeDBConfigStore:
    """Persist DB connection chosen in setup wizard."""

    def __init__(self, config_path: Path):
        self.config_path = config_path

    def load(self) -> dict[str, str] | None:
        if not self.config_path.exists():
            return None

        raw = self.config_path.read_text(encoding="utf-8")
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ValueError("Runtime DB config must be a JSON object.")

        data = {key: str(payload.get(key, "")).strip() for key in REQUIRED_DB_KEYS}
        if any(not value for value in data.values()):
            return None
        return data

    def save(self, config: dict[str, str]) -> None:
        payload = {key: str(config.get(key, "")).strip() for key in REQUIRED_DB_KEYS}
        missing = [key for key, value in payload.items() if not value]
        if missing:
            raise ValueError(f"Missing runtime DB config fields: {', '.join(missing)}")

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.config_path.with_suffix(self.config_path.suffix + ".tmp")
        tmp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        self._restrict_permissions(tmp_path)
        tmp_path.replace(self.config_path)
        self._restrict_permissions(self.config_path)

    def _restrict_permissions(self, path: Path) -> None:
        try:
            if os.name == "nt":
                os.chmod(path, stat.S_IREAD | stat.S_IWRITE)
            else:
                os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError as exc:
            logger.debug("Could not tighten permissions on %s: %s", path, exc)

