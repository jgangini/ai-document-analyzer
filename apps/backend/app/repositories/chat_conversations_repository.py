"""SQL repository for QA chat conversations."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.repositories.repository_utils import read_lob


class QAConversationsRepository:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        self._supports_session_link_cache: bool | None = None

    def _supports_session_link(self) -> bool:
        if self._supports_session_link_cache is not None:
            return self._supports_session_link_cache
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT COUNT(*)
                FROM user_tab_cols
                WHERE table_name = 'QA_SESSIONS'
                  AND column_name IN ('QA_CONVERSATIONS_ID', 'QA_SESSIONS_TURN_INDEX')
                """
            )
            count = int(cursor.fetchone()[0] or 0)
            self._supports_session_link_cache = count == 2
            return self._supports_session_link_cache
        finally:
            cursor.close()
            connection.close()

    def create_conversation(self, *, user_id: int, title: str | None = None) -> dict[str, Any]:
        if not self.db_manager.table_exists("qa_conversations"):
            return {}
        normalized_title = (title or "").strip() or "New chat"
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            conversation_id_var = cursor.var(int)
            created_var = cursor.var(datetime)
            updated_var = cursor.var(datetime)
            cursor.execute(
                """
                INSERT INTO qa_conversations (
                    user_id,
                    qa_conversations_title
                ) VALUES (
                    :user_id,
                    :title
                )
                RETURNING qa_conversations_id, qa_conversations_created, qa_conversations_updated
                INTO :conversation_id, :created_at, :updated_at
                """,
                user_id=int(user_id),
                title=normalized_title[:255],
                conversation_id=conversation_id_var,
                created_at=created_var,
                updated_at=updated_var,
            )
            connection.commit()
            return {
                "qa_conversations_id": int(conversation_id_var.getvalue()[0]),
                "qa_conversations_title": normalized_title[:255],
                "qa_conversations_created": created_var.getvalue()[0],
                "qa_conversations_updated": updated_var.getvalue()[0],
            }
        finally:
            cursor.close()
            connection.close()

    def get_conversation(self, *, user_id: int, conversation_id: int) -> dict[str, Any] | None:
        if not self.db_manager.table_exists("qa_conversations"):
            return None
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    qa_conversations_id,
                    user_id,
                    qa_conversations_title,
                    qa_conversations_state,
                    qa_conversations_created,
                    qa_conversations_updated
                FROM qa_conversations
                WHERE qa_conversations_id = :conversation_id
                  AND user_id = :user_id
                  AND qa_conversations_state = 1
                FETCH FIRST 1 ROWS ONLY
                """,
                conversation_id=int(conversation_id),
                user_id=int(user_id),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "qa_conversations_id": int(row[0]),
                "user_id": int(row[1]),
                "qa_conversations_title": str(read_lob(row[2]) or ""),
                "qa_conversations_state": int(row[3]),
                "qa_conversations_created": row[4],
                "qa_conversations_updated": row[5],
            }
        finally:
            cursor.close()
            connection.close()

    def list_conversations(self, *, user_id: int, search: str | None = None) -> list[dict[str, Any]]:
        if not self.db_manager.table_exists("qa_conversations"):
            return []
        supports_session_link = self._supports_session_link()
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            search_filter = f"%{(search or '').strip().lower()}%" if (search or "").strip() else None
            if supports_session_link and self.db_manager.table_exists("qa_sessions"):
                cursor.execute(
                    """
                    SELECT
                        c.qa_conversations_id,
                        c.qa_conversations_title,
                        c.qa_conversations_created,
                        NVL(
                            (
                                SELECT MAX(s.qa_sessions_created)
                                FROM qa_sessions s
                                WHERE s.qa_conversations_id = c.qa_conversations_id
                            ),
                            c.qa_conversations_updated
                        ) AS qa_conversations_last_activity,
                        (
                            SELECT COUNT(*)
                            FROM qa_sessions s
                            WHERE s.qa_conversations_id = c.qa_conversations_id
                        ) AS turns,
                        (
                            SELECT s.qa_sessions_answer
                            FROM qa_sessions s
                            WHERE s.qa_conversations_id = c.qa_conversations_id
                            ORDER BY s.qa_sessions_turn_index DESC, s.qa_sessions_created DESC, s.qa_sessions_id DESC
                            FETCH FIRST 1 ROWS ONLY
                        ) AS last_answer
                    FROM qa_conversations c
                    WHERE c.user_id = :user_id
                      AND c.qa_conversations_state = 1
                      AND (:search_filter IS NULL OR LOWER(c.qa_conversations_title) LIKE :search_filter)
                    ORDER BY qa_conversations_last_activity DESC, c.qa_conversations_created DESC
                    """,
                    user_id=int(user_id),
                    search_filter=search_filter,
                )
            else:
                cursor.execute(
                    """
                    SELECT
                        c.qa_conversations_id,
                        c.qa_conversations_title,
                        c.qa_conversations_created,
                        c.qa_conversations_updated,
                        0 AS turns,
                        '' AS last_answer
                    FROM qa_conversations c
                    WHERE c.user_id = :user_id
                      AND c.qa_conversations_state = 1
                      AND (:search_filter IS NULL OR LOWER(c.qa_conversations_title) LIKE :search_filter)
                    ORDER BY c.qa_conversations_updated DESC, c.qa_conversations_created DESC
                    """,
                    user_id=int(user_id),
                    search_filter=search_filter,
                )
            rows = cursor.fetchall()
            payload: list[dict[str, Any]] = []
            for row in rows:
                preview = str(read_lob(row[5]) or "").strip()
                payload.append(
                    {
                        "qa_conversations_id": int(row[0]),
                        "qa_conversations_title": str(read_lob(row[1]) or ""),
                        "qa_conversations_created": row[2],
                        "qa_conversations_updated": row[3],
                        "turns": int(row[4] or 0),
                        "last_message_preview": preview[:280],
                    }
                )
            return payload
        finally:
            cursor.close()
            connection.close()

    def rename_conversation(self, *, user_id: int, conversation_id: int, title: str) -> bool:
        if not self.db_manager.table_exists("qa_conversations"):
            return False
        normalized_title = (title or "").strip()
        if not normalized_title:
            return False
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE qa_conversations
                SET qa_conversations_title = :title
                WHERE qa_conversations_id = :conversation_id
                  AND user_id = :user_id
                  AND qa_conversations_state = 1
                """,
                title=normalized_title[:255],
                conversation_id=int(conversation_id),
                user_id=int(user_id),
            )
            updated = cursor.rowcount > 0
            connection.commit()
            return bool(updated)
        finally:
            cursor.close()
            connection.close()

    def delete_conversation(self, *, user_id: int, conversation_id: int) -> bool:
        if not self.db_manager.table_exists("qa_conversations"):
            return False
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE qa_conversations
                SET qa_conversations_state = 0
                WHERE qa_conversations_id = :conversation_id
                  AND user_id = :user_id
                  AND qa_conversations_state = 1
                """,
                conversation_id=int(conversation_id),
                user_id=int(user_id),
            )
            deleted = cursor.rowcount > 0
            connection.commit()
            return bool(deleted)
        finally:
            cursor.close()
            connection.close()

    def list_messages(self, *, user_id: int, conversation_id: int) -> list[dict[str, Any]]:
        if not self.db_manager.table_exists("qa_sessions"):
            return []
        if not self._supports_session_link():
            return []
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                SELECT
                    qa_sessions_id,
                    qa_sessions_turn_index,
                    qa_sessions_question,
                    qa_sessions_answer,
                    qa_sessions_retrieval_metadata,
                    qa_sessions_model_used,
                    qa_sessions_created,
                    file_id
                FROM qa_sessions
                WHERE user_id = :user_id
                  AND qa_conversations_id = :conversation_id
                  AND qa_sessions_state = 1
                ORDER BY qa_sessions_turn_index ASC, qa_sessions_created ASC, qa_sessions_id ASC
                """,
                user_id=int(user_id),
                conversation_id=int(conversation_id),
            )
            rows = cursor.fetchall()
            messages: list[dict[str, Any]] = []
            for row in rows:
                session_id = int(row[0])
                turn_index = int(row[1] or 0)
                question = str(read_lob(row[2]) or "")
                answer = str(read_lob(row[3]) or "")
                raw_metadata = read_lob(row[4]) or "{}"
                try:
                    retrieval_metadata = json.loads(str(raw_metadata))
                except Exception:
                    retrieval_metadata = {}
                session_file_id = int(row[7]) if len(row) > 7 and row[7] is not None else None
                if session_file_id and "scope_file_id" not in retrieval_metadata:
                    retrieval_metadata = dict(retrieval_metadata, scope_file_id=session_file_id)
                model_used = str(read_lob(row[5]) or "")
                created_at = row[6]
                messages.append(
                    {
                        "message_id": f"{session_id}:user",
                        "session_id": session_id,
                        "turn_index": turn_index,
                        "role": "user",
                        "content": question,
                        "created_at": created_at,
                        "model_used": model_used,
                        "retrieval_metadata": retrieval_metadata,
                    }
                )
                messages.append(
                    {
                        "message_id": f"{session_id}:assistant",
                        "session_id": session_id,
                        "turn_index": turn_index,
                        "role": "assistant",
                        "content": answer,
                        "created_at": created_at,
                        "model_used": model_used,
                        "retrieval_metadata": retrieval_metadata,
                    }
                )
            return messages
        finally:
            cursor.close()
            connection.close()
