import logging
from typing import List, Optional

from apps.backend.app.core.config import Settings
from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.core.security import get_password_hash, verify_password

logger = logging.getLogger(__name__)


class UserService:
    def __init__(self, db_manager: DatabaseManager, settings: Settings):
        self.db_manager = db_manager
        self.settings = settings

    def list_groups(self) -> List[dict]:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT user_group_id, user_group_name
                FROM user_group
                WHERE user_group_state = 1
                ORDER BY user_group_id
                """
            )
            return [{"user_group_id": row[0], "user_group_name": row[1]} for row in cursor.fetchall()]
        finally:
            cursor.close()
            conn.close()

    def ensure_admin(self, user_id: int) -> None:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT user_group_id FROM users WHERE user_id = :user_id",
                user_id=user_id,
            )
            row = cursor.fetchone()
            if not row or row[0] != 0:
                raise PermissionError("Access denied. Administrators only.")
        finally:
            cursor.close()
            conn.close()

    def list_users(self, current_user_id: int) -> List[dict]:
        self.ensure_admin(current_user_id)
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                SELECT u.user_id, u.user_username, u.user_name, u.user_last_name,
                       u.user_group_id, ug.user_group_name, u.user_last_login, u.user_created
                FROM users u
                JOIN user_group ug ON u.user_group_id = ug.user_group_id
                WHERE u.user_state = 1
                ORDER BY u.user_created DESC
                """
            )
            return [
                {
                    "user_id": row[0],
                    "username": row[1],
                    "name": row[2],
                    "last_name": row[3],
                    "group_id": row[4],
                    "group_name": row[5],
                    "last_login": row[6],
                    "created": row[7],
                }
                for row in cursor.fetchall()
            ]
        finally:
            cursor.close()
            conn.close()

    def create_user(
        self,
        requester_id: int,
        username: str,
        password: str,
        name: str,
        last_name: str,
        group_id: int = 1,
    ) -> None:
        self.ensure_admin(requester_id)
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT COUNT(*) FROM users WHERE user_username = :username",
                username=username,
            )
            if cursor.fetchone()[0] > 0:
                raise ValueError("User already exists")
            hashed = get_password_hash(password)
            cursor.execute(
                """
                INSERT INTO users (user_group_id, user_username, user_password, user_name, user_last_name)
                VALUES (:group_id, :username, :password, :name, :last_name)
                """,
                group_id=group_id,
                username=username,
                password=hashed,
                name=name,
                last_name=last_name,
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def delete_user(self, requester_id: int, target_user_id: int) -> None:
        self.ensure_admin(requester_id)
        if target_user_id == 0:
            raise ValueError("Cannot delete the initial administrator user")
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "UPDATE users SET user_state = 0 WHERE user_id = :user_id",
                user_id=target_user_id,
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def get_user_info(self, user_id: int) -> Optional[dict]:
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

    def update_profile(self, user_id: int, name: str, last_name: str) -> None:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE users
                SET user_name = :name, user_last_name = :last_name
                WHERE user_id = :user_id
                """,
                name=name,
                last_name=last_name,
                user_id=user_id,
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

    def change_password(self, user_id: int, current_password: str, new_password: str) -> None:
        conn = self.db_manager.get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute(
                "SELECT user_password FROM users WHERE user_id = :user_id",
                user_id=user_id,
            )
            row = cursor.fetchone()
            if not row:
                raise ValueError("User not found")
            if not verify_password(current_password, row[0]):
                raise ValueError("Current password is incorrect")
            new_hashed = get_password_hash(new_password)
            cursor.execute(
                """
                UPDATE users SET user_password = :password WHERE user_id = :user_id
                """,
                password=new_hashed,
                user_id=user_id,
            )
            conn.commit()
        finally:
            cursor.close()
            conn.close()

