"""SQL repository for persisted QA turns."""

from __future__ import annotations

import json

from apps.backend.app.core.database import DatabaseManager


class QASessionsRepository:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        self._supports_conversation_columns_cache: bool | None = None

    def _supports_conversation_columns(self) -> bool:
        if self._supports_conversation_columns_cache is not None:
            return self._supports_conversation_columns_cache
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
            self._supports_conversation_columns_cache = count == 2
            return self._supports_conversation_columns_cache
        finally:
            cursor.close()
            connection.close()

    def _serialize_retrieval_metadata(self, retrieval_metadata: dict) -> str:
        payload = dict(retrieval_metadata or {})
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def save_qa_session(
        self,
        *,
        user_id: int,
        file_id: int | None,
        conversation_id: int | None,
        question: str,
        retrieval_metadata: dict,
        answer: str,
        model_used: str,
    ) -> dict:
        if not self.db_manager.table_exists("qa_sessions"):
            return {}
        supports_conversation_columns = self._supports_conversation_columns()
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        turn_index = 0
        try:
            if supports_conversation_columns and conversation_id is not None:
                cursor.execute(
                    """
                    SELECT NVL(MAX(qa_sessions_turn_index), 0) + 1
                    FROM qa_sessions
                    WHERE qa_conversations_id = :conversation_id
                    """,
                    conversation_id=int(conversation_id),
                )
                turn_index = int(cursor.fetchone()[0] or 1)
            session_id_var = cursor.var(int)
            if supports_conversation_columns:
                cursor.execute(
                    """
                    INSERT INTO qa_sessions (
                        user_id,
                        file_id,
                        qa_conversations_id,
                        qa_sessions_turn_index,
                        qa_sessions_question,
                        qa_sessions_retrieval_metadata,
                        qa_sessions_answer,
                        qa_sessions_model_used
                    ) VALUES (
                        :user_id,
                        :file_id,
                        :conversation_id,
                        :turn_index,
                        :question,
                        :retrieval_metadata,
                        :answer,
                        :model_used
                    )
                    RETURNING qa_sessions_id INTO :session_id
                    """,
                    user_id=int(user_id),
                    file_id=int(file_id) if file_id is not None else None,
                    conversation_id=int(conversation_id) if conversation_id is not None else None,
                    turn_index=int(turn_index),
                    question=question,
                    retrieval_metadata=self._serialize_retrieval_metadata(retrieval_metadata),
                    answer=answer,
                    model_used=model_used[:255],
                    session_id=session_id_var,
                )
                if conversation_id is not None:
                    cursor.execute(
                        """
                        UPDATE qa_conversations
                        SET qa_conversations_updated = CURRENT_TIMESTAMP
                        WHERE qa_conversations_id = :conversation_id
                          AND user_id = :user_id
                        """,
                        conversation_id=int(conversation_id),
                        user_id=int(user_id),
                    )
            else:
                cursor.execute(
                    """
                    INSERT INTO qa_sessions (
                        user_id,
                        file_id,
                        qa_sessions_question,
                        qa_sessions_retrieval_metadata,
                        qa_sessions_answer,
                        qa_sessions_model_used
                    ) VALUES (
                        :user_id,
                        :file_id,
                        :question,
                        :retrieval_metadata,
                        :answer,
                        :model_used
                    )
                    RETURNING qa_sessions_id INTO :session_id
                    """,
                    user_id=int(user_id),
                    file_id=int(file_id) if file_id is not None else None,
                    question=question,
                    retrieval_metadata=self._serialize_retrieval_metadata(retrieval_metadata),
                    answer=answer,
                    model_used=model_used[:255],
                    session_id=session_id_var,
                )
            connection.commit()
            session_id = int(session_id_var.getvalue()[0])
            return {
                "qa_sessions_id": session_id,
                "qa_sessions_turn_index": int(turn_index),
                "qa_conversations_id": int(conversation_id) if conversation_id is not None else None,
            }
        except Exception:
            connection.rollback()
            return {}
        finally:
            cursor.close()
            connection.close()
