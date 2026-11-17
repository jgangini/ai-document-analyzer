import logging
from typing import Optional

import oracledb

from apps.backend.app.core.db_runtime_config import RuntimeDBConfigStore

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Singleton to manage connection pool to Autonomous Database."""

    _instance = None

    def __init__(self, settings):
        self.settings = settings
        self._pool: Optional[oracledb.ConnectionPool] = None
        self._initialized = False
        self._runtime_store = RuntimeDBConfigStore(settings.runtime_db_config_path)

    def _base_connection_config(self) -> dict[str, str]:
        return {
            "user": (self.settings.ADB_USER or "").strip(),
            "password": (self.settings.ADB_PASSWORD or "").strip(),
            "dsn": (self.settings.ADB_DSN or "").strip(),
            "wallet_path": (self.settings.ADB_WALLET_DIR or "").strip(),
            "wallet_password": (self.settings.ADB_WALLET_PASSWORD or "").strip(),
        }

    def resolve_connection_config(
        self,
        *,
        wallet_path: str | None = None,
        wallet_password: str | None = None,
        user: str | None = None,
        password: str | None = None,
        dsn: str | None = None,
    ) -> dict[str, str]:
        config = self._base_connection_config()
        try:
            runtime_config = self._runtime_store.load()
        except Exception as exc:
            logger.warning("Runtime DB config could not be loaded: %s", exc)
            runtime_config = None
        if runtime_config:
            config.update(runtime_config)

        overrides = {
            "wallet_path": wallet_path,
            "wallet_password": wallet_password,
            "user": user,
            "password": password,
            "dsn": dsn,
        }
        for key, value in overrides.items():
            if value is not None and str(value).strip():
                config[key] = str(value).strip()
        return config

    def save_runtime_connection_config(
        self,
        *,
        wallet_path: str,
        wallet_password: str,
        user: str,
        password: str,
        dsn: str,
    ) -> None:
        self._runtime_store.save(
            {
                "wallet_path": wallet_path,
                "wallet_password": wallet_password,
                "user": user,
                "password": password,
                "dsn": dsn,
            }
        )

        # Force pool re-init with the latest credentials from runtime config.
        self.close_pool()

    def init_pool(self):
        """Initialize connection pool (thin mode, no Oracle Client)."""
        if self._initialized:
            return
        try:
            config = self.resolve_connection_config()
            pool_kwargs = {
                "user": config["user"],
                "password": config["password"],
                "dsn": config["dsn"],
                "min": self.settings.ADB_POOL_MIN,
                "max": self.settings.ADB_POOL_MAX,
                "increment": self.settings.ADB_POOL_INCREMENT,
            }
            if config["wallet_path"]:
                pool_kwargs["config_dir"] = config["wallet_path"]
                pool_kwargs["wallet_location"] = config["wallet_path"]
            if config["wallet_password"]:
                pool_kwargs["wallet_password"] = config["wallet_password"]

            self._pool = oracledb.create_pool(**pool_kwargs)
            self._initialized = True
            logger.info("Database pool initialized: %s@%s", config["user"], config["dsn"])
        except Exception as e:
            logger.warning("Error initializing database pool: %s", e, exc_info=True)

    def get_connection(self):
        """Get connection from pool."""
        if not self._initialized:
            self.init_pool()
        if self._pool is None:
            raise Exception("Database pool not initialized. Please complete the initial setup.")
        return self._pool.acquire()

    def close_pool(self):
        """Close pool (on shutdown)."""
        if self._pool:
            self._pool.close()
            self._pool = None
            self._initialized = False

    def table_exists(self, table_name: str) -> bool:
        """Return whether a table exists in the current schema."""
        try:
            connection = self.get_connection()
        except Exception:
            return False
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM user_tables
                WHERE table_name = :table_name
                """,
                table_name=(table_name or "").upper(),
            )
            row = cursor.fetchone()
            return bool(row and int(row[0]) > 0)
        finally:
            cursor.close()
            connection.close()

    @classmethod
    def get_instance(cls, settings):
        """Get singleton instance."""
        if cls._instance is None:
            cls._instance = cls(settings)
        return cls._instance

