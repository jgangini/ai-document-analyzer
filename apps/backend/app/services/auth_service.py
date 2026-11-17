import oracledb
from datetime import timedelta
from typing import Optional

from apps.backend.app.core.config import Settings
from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.core.security import create_access_token, verify_password
from apps.backend.app.core.tracing import trace
from apps.backend.app.services.runtime_config_service import ConfigService


class AuthService:
    """User authentication service."""

    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        self.db_manager = db_manager
        self.settings = settings
        self.config_service = ConfigService(db_manager)

    def _resolve_session_timeout_minutes(self) -> int:
        default_minutes = int(self.settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        try:
            raw_value = self.config_service.get_value("app.session_timeout_minutes", str(default_minutes)).strip()
            resolved = int(raw_value)
            return max(1, resolved)
        except Exception:
            return default_minutes

    @trace
    def authenticate_user(self, username: str, password: str) -> Optional[dict]:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT u.user_id, u.user_username, u.user_password,
                       u.user_name, u.user_last_name,
                       u.user_group_id, ug.user_group_name
                FROM users u
                JOIN user_group ug ON u.user_group_id = ug.user_group_id
                WHERE u.user_username = :username AND u.user_state = 1
                """,
                username=username,
            )
            row = cursor.fetchone()
            if not row:
                return None
            user_id, user_username, hashed_password, name, last_name, group_id, group_name = row
            if not verify_password(password, hashed_password):
                return None
            cursor.execute(
                """
                UPDATE users SET user_last_login = SYSDATE
                WHERE user_id = :user_id
                """,
                user_id=user_id,
            )
            conn.commit()
            return {
                "user_id": user_id,
                "username": user_username,
                "name": name,
                "last_name": last_name,
                "email": user_username,
                "group_id": group_id,
                "group_name": group_name,
            }
        finally:
            cursor.close()
            conn.close()

    @trace
    def login(self, username: str, password: str) -> Optional[dict]:
        user = self.authenticate_user(username, password)
        if not user:
            return None
        session_timeout_minutes = self._resolve_session_timeout_minutes()
        access_token = create_access_token(
            data={"sub": user["username"], "user_id": user["user_id"]},
            settings=self.settings,
            expires_delta=timedelta(minutes=session_timeout_minutes),
        )
        return {"access_token": access_token, "token_type": "bearer", "user": user}

    def get_current_user_info(self, user_id: int) -> Optional[dict]:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT u.user_id, u.user_username, u.user_name, u.user_last_name,
                       u.user_group_id, ug.user_group_name
                FROM users u
                JOIN user_group ug ON u.user_group_id = ug.user_group_id
                WHERE u.user_id = :1 AND u.user_state = 1
                """,
                [user_id],
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "user_id": row[0],
                "username": row[1],
                "name": row[2],
                "last_name": row[3],
                "email": row[1],
                "group_id": row[4],
                "group_name": row[5],
            }
        finally:
            cursor.close()
            conn.close()
