import logging
import os
import re
from pathlib import Path, PureWindowsPath
from typing import Dict, List

import oci
import oracledb
from oci.generative_ai import GenerativeAiClient
from oci.object_storage import ObjectStorageClient

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.core.security import get_password_hash
from apps.backend.app.core.tracing import trace

logger = logging.getLogger(__name__)


class SetupService:
    """Initial setup service (database, OCI, admin user)."""

    _PREFERRED_WALLET_DSN_SUFFIXES = (
        "_medium",
        "_high",
        "_tp",
        "_low",
        "_tpurgent",
    )

    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager

    @staticmethod
    def _resolve_backend_root() -> Path:
        # .../apps/backend/app/services/bootstrap_service.py -> .../apps/backend
        return Path(__file__).resolve().parents[2]

    @staticmethod
    def _normalize_oci_config_value(value: object) -> str:
        if value is None:
            return ""
        if hasattr(value, "read"):
            try:
                value = value.read()
            except Exception:
                return ""
        return str(value).strip()

    @classmethod
    def _select_preferred_wallet_dsn(cls, aliases: list[str]) -> str:
        if not aliases:
            return ""

        for suffix in cls._PREFERRED_WALLET_DSN_SUFFIXES:
            for alias in aliases:
                if alias.lower().endswith(suffix):
                    return alias
        return aliases[0]

    def _resolve_oci_cli_config_path(self) -> Path:
        settings = getattr(self.db_manager, "settings", None)
        if settings is not None and hasattr(settings, "oci_config_file"):
            return Path(settings.oci_config_file)
        return self._resolve_backend_root() / "keys" / "config"

    def _resolve_bootstrap_sql_dir(self) -> Path:
        return self._resolve_backend_root() / "db" / "bootstrap" / "sql"

    def _resolve_oci_key_file_path(self, key_file_value: str) -> str:
        raw_value = (key_file_value or "").strip()
        if not raw_value:
            return ""
        key_file_path = Path(raw_value)
        backend_root = self._resolve_backend_root()
        bundled_key_candidate = (backend_root / "keys" / PureWindowsPath(raw_value).name).resolve()
        if key_file_path.is_absolute():
            if key_file_path.exists():
                return str(key_file_path)
            if bundled_key_candidate.exists():
                return str(bundled_key_candidate)
            return str(key_file_path)
        windows_path = PureWindowsPath(raw_value)
        if windows_path.drive:
            return str(bundled_key_candidate)
        return str((backend_root / raw_value).resolve())

    def _write_oci_cli_config_file(self, *, config_values: dict[str, str]) -> None:
        required = ("user", "fingerprint", "tenancy", "region", "key_file")
        missing = [key for key in required if not (config_values.get(key) or "").strip()]
        if missing:
            raise ValueError(
                f"Missing OCI values for config file generation: {', '.join(missing)}"
            )

        config_path = self._resolve_oci_cli_config_path()
        config_path.parent.mkdir(parents=True, exist_ok=True)
        file_content = (
            "[DEFAULT]\n"
            f"user={config_values['user']}\n"
            f"fingerprint={config_values['fingerprint']}\n"
            f"tenancy={config_values['tenancy']}\n"
            f"region={config_values['region']}\n"
            f"key_file={config_values['key_file']}\n"
        )
        config_path.write_text(file_content, encoding="utf-8")

    def _load_saved_oci_config_values(self) -> dict[str, str]:
        conn = self._get_direct_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT config_key, config_value
                FROM config
                WHERE config_key IN (
                    'oci.user',
                    'oci.fingerprint',
                    'oci.tenancy',
                    'oci.region',
                    'oci.key_file'
                )
                """
            )
            values: dict[str, str] = {}
            for key, value in cursor.fetchall():
                normalized_key = str(key).replace("oci.", "").strip()
                values[normalized_key] = self._normalize_oci_config_value(value)
            if values.get("key_file"):
                values["key_file"] = self._resolve_oci_key_file_path(values["key_file"])
            return values
        finally:
            cursor.close()
            conn.close()

    def _get_direct_connection(
        self,
        *,
        wallet_path: str | None = None,
        wallet_password: str | None = None,
        user: str | None = None,
        password: str | None = None,
        dsn: str | None = None,
    ):
        config = self.db_manager.resolve_connection_config(
            wallet_path=wallet_path,
            wallet_password=wallet_password,
            user=user,
            password=password,
            dsn=dsn,
        )
        connection_kwargs = {
            "user": config["user"],
            "password": config["password"],
            "dsn": config["dsn"],
        }
        if config["wallet_path"]:
            connection_kwargs["config_dir"] = config["wallet_path"]
            connection_kwargs["wallet_location"] = config["wallet_path"]
        if config["wallet_password"]:
            connection_kwargs["wallet_password"] = config["wallet_password"]
        return oracledb.connect(**connection_kwargs)

    @staticmethod
    def _summarize_oracle_connect_error(error: Exception) -> str | None:
        message = str(error)
        compact = " | ".join(part.strip() for part in message.splitlines() if part.strip())

        if "DPY-6001" in message or "ORA-12514" in message:
            return (
                "Oracle service is not registered (DPY-6001/ORA-12514). "
                "Validate wallet files and DSN alias selected in setup. "
                f"Raw: {compact}"
            )
        if "ORA-01017" in message:
            return (
                "Oracle credentials are invalid (ORA-01017). "
                "Validate username/password configured in setup for the current wallet. "
                f"Raw: {compact}"
            )
        if "DPY-4011" in message:
            return (
                "Oracle network handshake failed (DPY-4011). "
                "Validate wallet certificates and network connectivity. "
                f"Raw: {compact}"
            )
        if "DPY-6005" in message:
            return (
                "Oracle connection failed (DPY-6005). "
                "Validate wallet path, wallet password, DSN alias, and DB credentials. "
                f"Raw: {compact}"
            )
        return None

    @trace
    def check_setup_status(self) -> bool:
        try:
            if self.db_manager is None:
                return False
            conn = self._get_direct_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT config_value FROM config
                WHERE config_key = 'wizard.completed'
                """
            )
            row = cursor.fetchone()
            if row and row[0]:
                value = row[0]
                if hasattr(value, "read"):
                    value = value.read()
                cursor.close()
                conn.close()
                logger.debug("check_setup_status: wizard.completed = '%s'", value)
                return value == "true"
            cursor.close()
            conn.close()
            logger.debug("check_setup_status: wizard.completed not found")
            return False
        except Exception as e:
            error_str = str(e)
            if "ORA-00942" in error_str or "does not exist" in error_str:
                logger.info("Config table not found - setup not completed yet")
            elif oracle_error := self._summarize_oracle_connect_error(e):
                logger.error("check_setup_status connectivity error: %s", oracle_error)
            else:
                logger.exception("check_setup_status error: %s", e)
            return False

    def test_db_connection(self, wallet_path: str, wallet_password: str, user: str, password: str, dsn: str) -> dict:
        try:
            tnsnames_path = os.path.join(wallet_path, "tnsnames.ora")
            if not os.path.exists(tnsnames_path):
                return {
                    "success": False,
                    "message": f"tnsnames.ora not found in {wallet_path}",
                }
            connection = oracledb.connect(
                user=user,
                password=password,
                dsn=dsn,
                config_dir=wallet_path,
                wallet_location=wallet_path,
                wallet_password=wallet_password,
            )
            cursor = connection.cursor()
            cursor.execute("SELECT USER FROM DUAL")
            db_user = cursor.fetchone()[0]
            cursor.execute(
                """
                SELECT privilege FROM user_sys_privs
                WHERE privilege = 'CREATE TABLE'
                """
            )
            has_create_table = cursor.fetchone() is not None
            cursor.close()
            connection.close()
            if not has_create_table:
                return {
                    "success": False,
                    "message": f"User {db_user} does not have CREATE TABLE privilege",
                }
            return {
                "success": True,
                "message": "Database connection successful",
                "connected_user": db_user,
            }
        except Exception as e:
            error_str = str(e)
            if not (wallet_password or "").strip() and (
                "DPY-6000" in error_str
                or "DPY-4011" in error_str
                or "ORA-12506" in error_str
                or "ORA-12514" in error_str
            ):
                return {
                    "success": False,
                    "message": (
                        "Wallet password is required for this connection. "
                        "Please provide the password used when downloading the wallet."
                    ),
                }
            return {"success": False, "message": f"Connection error: {error_str}"}

    def save_runtime_db_config(
        self,
        *,
        wallet_path: str,
        wallet_password: str,
        user: str,
        password: str,
        dsn: str,
    ) -> None:
        self.db_manager.save_runtime_connection_config(
            wallet_path=wallet_path,
            wallet_password=wallet_password,
            user=user,
            password=password,
            dsn=dsn,
        )

    def list_wallet_dsns(self, wallet_path: str) -> dict:
        try:
            tnsnames_path = Path(wallet_path) / "tnsnames.ora"
            if not tnsnames_path.exists():
                return {
                    "success": False,
                    "message": f"tnsnames.ora not found in {wallet_path}",
                    "dsns": [],
                    "selected_dsn": "",
                }
            content = tnsnames_path.read_text(encoding="utf-8", errors="ignore")
            aliases: list[str] = []
            for match in re.finditer(r"^\s*([A-Za-z0-9_.-]+)\s*=", content, re.MULTILINE):
                alias = match.group(1).strip()
                if alias and alias not in aliases:
                    aliases.append(alias)
            if not aliases:
                return {
                    "success": False,
                    "message": "No TNS aliases found in tnsnames.ora",
                    "dsns": [],
                    "selected_dsn": "",
                }
            selected_dsn = self._select_preferred_wallet_dsn(aliases)
            return {
                "success": True,
                "message": "TNS aliases loaded successfully",
                "dsns": aliases,
                "selected_dsn": selected_dsn,
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Error reading tnsnames.ora: {str(e)}",
                "dsns": [],
                "selected_dsn": "",
            }

    @trace
    def execute_setup_scripts(
        self,
        *,
        wallet_path: str | None = None,
        wallet_password: str | None = None,
        user: str | None = None,
        password: str | None = None,
        dsn: str | None = None,
    ) -> dict:
        conn = self._get_direct_connection(
            wallet_path=wallet_path,
            wallet_password=wallet_password,
            user=user,
            password=password,
            dsn=dsn,
        )
        cursor = conn.cursor()
        setup_dir = self._resolve_bootstrap_sql_dir()
        sql_files = sorted(setup_dir.glob("*.sql"))
        discovered = [f.name for f in sql_files]
        executed = []
        errors = []
        if not sql_files:
            cursor.close()
            conn.close()
            return {
                "success": False,
                "discovered": discovered,
                "executed": executed,
                "errors": [{"file": str(setup_dir), "error": "No SQL setup scripts found."}],
                "message": f"No setup scripts found in {setup_dir}",
            }
        for sql_file in sql_files:
            logger.debug("Executing script: %s", sql_file.name)
            try:
                with open(sql_file, "r", encoding="utf-8") as f:
                    content = f.read()
                statements = re.split(r"(?m)^\s*--\s*$", content)
                for stmt in statements:
                    stmt = stmt.strip()
                    if not stmt or stmt.upper() == "COMMIT":
                        continue
                    lines = [
                        line for line in stmt.splitlines()
                        if line.strip() and not line.strip().startswith("--")
                    ]
                    clean_stmt = "\n".join(lines).strip()
                    if not clean_stmt:
                        continue
                    if clean_stmt.endswith(";"):
                        clean_stmt = clean_stmt[:-1].strip()
                    elif clean_stmt.endswith("/"):
                        clean_stmt = clean_stmt[:-1].strip()
                    if not clean_stmt:
                        continue
                    try:
                        preview = clean_stmt[:80].replace("\n", " ")
                        logger.debug("Executing: %s...", preview)
                        cursor.execute(clean_stmt)
                    except Exception as e:
                        error_str = str(e)
                        if any(code in error_str for code in ["ORA-00955", "ORA-00001", "ORA-01408", "ORA-04080"]):
                            logger.warning("Object already exists, skipping")
                        else:
                            logger.error("Statement failed: %s", error_str)
                            raise
                conn.commit()
                logger.info("Script %s completed successfully", sql_file.name)
                executed.append(sql_file.name)
            except Exception as e:
                conn.rollback()
                logger.error("Script %s failed: %s", sql_file.name, e)
                errors.append({"file": sql_file.name, "error": str(e)})

        cursor.close()
        conn.close()
        success = len(errors) == 0 and len(executed) == len(sql_files)
        return {
            "success": success,
            "discovered": discovered,
            "executed": executed,
            "errors": errors,
            "message": f"{len(executed)}/{len(sql_files)} scripts executed successfully.",
        }

    @trace
    def create_admin_user(
        self,
        email: str,
        admin_password: str,
        *,
        wallet_path: str | None = None,
        wallet_password: str | None = None,
        user: str | None = None,
        db_password: str | None = None,
        dsn: str | None = None,
    ) -> bool:
        conn = self._get_direct_connection(
            wallet_path=wallet_path,
            wallet_password=wallet_password,
            user=user,
            password=db_password,
            dsn=dsn,
        )
        cursor = conn.cursor()
        try:
            hashed_password = get_password_hash(admin_password)
            cursor.execute("SELECT COUNT(*) FROM users WHERE user_id = 0")
            count = cursor.fetchone()[0]
            if count > 0:
                cursor.execute(
                    """
                    UPDATE users
                    SET user_username = :username,
                        user_password = :password
                    WHERE user_id = 0
                    """,
                    username=email,
                    password=hashed_password,
                )
            else:
                cursor.execute(
                    """
                    INSERT INTO users (
                        user_id, user_group_id, user_username, user_password,
                        user_name, user_last_name
                    ) VALUES (
                        0, 0, :username, :password,
                        'Administrator', 'System'
                    )
                    """,
                    username=email,
                    password=hashed_password,
                )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.exception("Error creating admin user: %s", e)
            return False
        finally:
            cursor.close()
            conn.close()

    def update_admin_password(self, new_password: str) -> bool:
        conn = self._get_direct_connection()
        cursor = conn.cursor()
        try:
            hashed_password = get_password_hash(new_password)
            cursor.execute(
                """
                UPDATE users SET user_password = :hashed_password
                WHERE user_id = 0
                """,
                hashed_password=hashed_password,
            )
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error("Error updating admin password: %s", e)
            return False
        finally:
            cursor.close()
            conn.close()

    def save_oci_config(self, config: dict) -> bool:
        conn = self._get_direct_connection()
        cursor = conn.cursor()
        try:
            config_items = [
                ("oci.compartment_id", config.get("compartment_id", ""), "oci"),
                ("oci.user", config.get("user", ""), "oci"),
                ("oci.fingerprint", config.get("fingerprint", ""), "oci"),
                ("oci.tenancy", config.get("tenancy", ""), "oci"),
                ("oci.region", config.get("region", ""), "oci"),
                ("oci.key_file", config.get("key_file", ""), "oci"),
                ("oci.namespace", config.get("namespace", ""), "oci"),
                ("oci.bucket_name", config.get("bucket_name", ""), "oci"),
            ]
            for key, value, category in config_items:
                cursor.execute(
                    """
                    MERGE INTO config sc
                    USING DUAL ON (sc.config_key = :key)
                    WHEN MATCHED THEN
                        UPDATE SET sc.config_value = :value, sc.config_updated = SYSDATE
                    WHEN NOT MATCHED THEN
                        INSERT (config_key, config_value, config_type, config_category)
                        VALUES (:key, :value, 'string', :category)
                    """,
                    key=key,
                    value=value,
                    category=category,
                )
            conn.commit()
            oci_file_values = {
                "user": self._normalize_oci_config_value(config.get("user", "")),
                "fingerprint": self._normalize_oci_config_value(config.get("fingerprint", "")),
                "tenancy": self._normalize_oci_config_value(config.get("tenancy", "")),
                "region": self._normalize_oci_config_value(config.get("region", "")),
                "key_file": self._resolve_oci_key_file_path(
                    self._normalize_oci_config_value(config.get("key_file", ""))
                ),
            }
            try:
                self._write_oci_cli_config_file(config_values=oci_file_values)
            except Exception as file_error:
                logger.error(
                    "OCI config was saved in DB but keys/config generation failed: %s",
                    file_error,
                )
                return False
            return True
        except Exception as e:
            conn.rollback()
            logger.error("Error saving OCI config: %s", e)
            return False
        finally:
            cursor.close()
            conn.close()

    def test_oci_connection(self, config: dict) -> dict:
        try:
            with open(config["key_file"], "r") as f:
                key_content = f.read()
            oci_config = {
                "user": config["user"],
                "key_content": key_content,
                "fingerprint": config["fingerprint"],
                "tenancy": config["tenancy"],
                "region": config["region"],
            }
            identity_client = oci.identity.IdentityClient(oci_config)
            compartment = identity_client.get_compartment(config["compartment_id"])
            return {
                "success": True,
                "message": f"Successful connection to compartment: {compartment.data.name}",
                "compartment_name": compartment.data.name,
            }
        except Exception as e:
            return {"success": False, "message": f"OCI connection error: {str(e)}"}

    def test_object_storage(self, namespace: str, bucket_name: str) -> dict:
        try:
            logger.debug("test_object_storage: namespace=%s, bucket=%s", namespace, bucket_name)
            if not namespace or not bucket_name:
                return {"success": False, "message": "Namespace and bucket name are required"}
            conn = self._get_direct_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT config_key, config_value
                FROM config
                WHERE config_key IN ('oci.user', 'oci.fingerprint', 'oci.tenancy',
                                      'oci.region', 'oci.key_file', 'oci.compartment_id')
                """
            )
            oci_config_data = {}
            for row in cursor.fetchall():
                key = row[0].replace("oci.", "")
                value = row[1]
                if hasattr(value, "read"):
                    value = value.read()
                oci_config_data[key] = value
            cursor.close()
            conn.close()
            required = ["user", "fingerprint", "tenancy", "region", "key_file", "compartment_id"]
            missing = [k for k in required if k not in oci_config_data or not oci_config_data.get(k)]
            if missing:
                return {
                    "success": False,
                    "message": f"Please save API Key configuration first. Missing: {', '.join(missing)}",
                }
            compartment_id = oci_config_data["compartment_id"]
            with open(oci_config_data["key_file"], "r") as f:
                key_content = f.read()
            oci_config = {
                "user": oci_config_data["user"],
                "key_content": key_content,
                "fingerprint": oci_config_data["fingerprint"],
                "tenancy": oci_config_data["tenancy"],
                "region": oci_config_data["region"],
            }
            os_client = ObjectStorageClient(oci_config)
            try:
                os_client.get_namespace()
            except Exception as e:
                return {"success": False, "message": f"Invalid namespace: {str(e)}"}
            try:
                bucket = os_client.get_bucket(namespace, bucket_name)
                if bucket.data.compartment_id != compartment_id:
                    return {
                        "success": False,
                        "message": f"Bucket '{bucket_name}' exists but is not in the configured compartment",
                    }
            except Exception as e:
                error_str = str(e)
                if "NotAuthorizedOrNotFound" in error_str or "404" in error_str:
                    return {
                        "success": False,
                        "message": f"Bucket '{bucket_name}' not found or not accessible in the specified compartment",
                    }
                return {"success": False, "message": f"Error accessing bucket: {error_str}"}
            return {"success": True, "message": f"Successful connection to bucket: {bucket_name} in compartment"}
        except Exception as e:
            logger.exception("test_object_storage failed: %s", e)
            return {"success": False, "message": f"Error validating Object Storage: {str(e)}"}

    def list_genai_models(self) -> dict:
        try:
            conn = self._get_direct_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT config_key, config_value
                FROM config
                WHERE config_key IN ('oci.user', 'oci.fingerprint', 'oci.tenancy',
                                      'oci.region', 'oci.key_file', 'oci.compartment_id')
                """
            )
            oci_config_data = {}
            for row in cursor.fetchall():
                key = row[0].replace("oci.", "")
                value = row[1]
                if hasattr(value, "read"):
                    value = value.read()
                oci_config_data[key] = value
            cursor.close()
            conn.close()
            required = ["user", "fingerprint", "tenancy", "region", "key_file", "compartment_id"]
            missing = [k for k in required if k not in oci_config_data or not oci_config_data.get(k)]
            if missing:
                return {
                    "success": False,
                    "message": f"Save API Key configuration first. Missing: {', '.join(missing)}",
                    "generative_models": [],
                    "embedding_models": [],
                }
            with open(oci_config_data["key_file"], "r") as f:
                key_content = f.read()
            oci_config = {
                "user": oci_config_data["user"],
                "key_content": key_content,
                "fingerprint": oci_config_data["fingerprint"],
                "tenancy": oci_config_data["tenancy"],
                "region": oci_config_data["region"],
            }
            compartment_id = oci_config_data["compartment_id"]
            genai_client = GenerativeAiClient(oci_config)
            generative_models = []
            embedding_models = []
            try:
                gen_resp = genai_client.list_models(
                    compartment_id=compartment_id,
                    capability=["TEXT_GENERATION", "TEXT_SUMMARIZATION"],
                    lifecycle_state="ACTIVE",
                    limit=100,
                )
                items = getattr(gen_resp, "data", None) and getattr(gen_resp.data, "items", None) or []
                generative_models = [
                    {"id": m.id, "display_name": getattr(m, "display_name", None) or m.id}
                    for m in items
                ]
            except Exception as e:
                logger.warning("list_models TEXT_GENERATION failed: %s", e)
            # Embeddings OCI no forman parte del enfoque actual (Nomic local CPU).
            embedding_models = []
            return {
                "success": True,
                "generative_models": generative_models,
                "embedding_models": embedding_models,
            }
        except Exception as e:
            logger.exception("list_genai_models failed: %s", e)
            return {
                "success": False,
                "message": str(e),
                "generative_models": [],
                "embedding_models": [],
            }

    def test_generative_ai(self, inference_url: str, generative_model: str) -> dict:
        try:
            if not inference_url or not inference_url.strip():
                return {"success": False, "message": "Inference URL is required"}
            url = inference_url.strip()
            if not url.startswith(("http://", "https://")):
                url = "https://" + url
            from urllib.error import HTTPError, URLError
            from urllib.parse import urlparse
            from urllib.request import urlopen

            parsed = urlparse(url)
            base_url = f"{parsed.scheme}://{parsed.netloc}"
            test_url = base_url.rstrip("/") + "/" if not base_url.endswith("/") else base_url
            try:
                with urlopen(test_url, timeout=10) as _:
                    pass
            except HTTPError:
                pass
            except (URLError, OSError) as e:
                return {"success": False, "message": f"Inference endpoint unreachable: {str(e)}"}
            if not generative_model or not generative_model.strip():
                return {"success": False, "message": "Generative AI model name is required"}
            return {
                "success": True,
                "message": "Generative AI configuration validated successfully. Inference endpoint is reachable.",
            }
        except Exception as e:
            logger.exception("test_generative_ai failed: %s", e)
            return {"success": False, "message": f"Error validating Generative AI: {str(e)}"}

    def save_generative_ai_config(self, config: dict) -> bool:
        conn = self._get_direct_connection()
        cursor = conn.cursor()
        try:
            config_items = [
                ("genai.inference_url", config.get("inference_url", ""), "genai"),
                ("genai.model", config.get("generative_model", ""), "genai"),
            ]
            for key, value, category in config_items:
                cursor.execute(
                    """
                    MERGE INTO config sc
                    USING DUAL ON (sc.config_key = :key)
                    WHEN MATCHED THEN
                        UPDATE SET sc.config_value = :value, sc.config_updated = SYSDATE
                    WHEN NOT MATCHED THEN
                        INSERT (config_key, config_value, config_type, config_category)
                        VALUES (:key, :value, 'string', :category)
                    """,
                    key=key,
                    value=value,
                    category=category,
                )
            # Embeddings ya no se configuran en OCI: se fuerzan siempre a Nomic local.
            cursor.execute("DELETE FROM config WHERE config_key = 'genai.embedding'")
            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            logger.error("Error saving Generative AI config: %s", e)
            return False
        finally:
            cursor.close()
            conn.close()

    def complete_setup(self) -> bool:
        conn = self._get_direct_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE config
                SET config_value = 'true', config_updated = SYSDATE
                WHERE config_key = 'wizard.completed'
                """
            )
            conn.commit()
            try:
                oci_config_values = self._load_saved_oci_config_values()
                if oci_config_values:
                    self._write_oci_cli_config_file(config_values=oci_config_values)
            except Exception as file_error:
                logger.error("Could not generate keys/config during complete_setup: %s", file_error)
                return False
            return True
        except Exception as e:
            conn.rollback()
            logger.error("Error completing setup: %s", e)
            return False
        finally:
            cursor.close()
            conn.close()
