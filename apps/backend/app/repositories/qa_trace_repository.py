"""Oracle persistence for local QA graph traces and evaluation runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.repositories.repository_utils import row_to_dict


class QATraceRepository:
    def __init__(self, db_manager: DatabaseManager) -> None:
        self.db_manager = db_manager
        self._trace_tables_available: bool | None = None

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value if value is not None else {}, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _stored_text(value: Any, *, default: str = "none") -> str:
        normalized = str(value or "").strip()
        return normalized if normalized else default

    @staticmethod
    def _parse_json(value: Any) -> Any:
        if isinstance(value, (dict, list)):
            return value
        try:
            return json.loads(str(value or "{}"))
        except Exception:
            return {}

    @staticmethod
    def _limit(value: int | None, *, default: int = 25, maximum: int = 200) -> int:
        try:
            parsed = int(value or default)
        except (TypeError, ValueError):
            parsed = default
        return max(1, min(maximum, parsed))

    @staticmethod
    def _to_iso(value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "")

    def _tables_available(self) -> bool:
        if self._trace_tables_available is not None:
            return self._trace_tables_available
        self._trace_tables_available = self.db_manager.table_exists("qa_trace_runs") and self.db_manager.table_exists(
            "qa_trace_steps"
        )
        return self._trace_tables_available

    def _required_tables_available(self, *table_names: str) -> bool:
        return all(self.db_manager.table_exists(table_name) for table_name in table_names)

    def _trace_exists(self, trace_id: str | None) -> bool:
        normalized_trace_id = str(trace_id or "").strip()
        if not normalized_trace_id or not self._tables_available():
            return False
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                "SELECT 1 FROM qa_trace_runs WHERE qa_trace_id = :trace_id FETCH FIRST 1 ROWS ONLY",
                trace_id=normalized_trace_id,
            )
            return cursor.fetchone() is not None
        finally:
            cursor.close()
            connection.close()

    def start_run(
        self,
        *,
        trace_id: str,
        thread_id: str,
        user_id: int | None,
        conversation_id: int | None,
        question: str,
        run_metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self._tables_available():
            return
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO qa_trace_runs (
                    qa_trace_id,
                    qa_trace_thread_id,
                    user_id,
                    qa_conversations_id,
                    qa_trace_question,
                    qa_trace_status,
                    qa_trace_answerability_route,
                    qa_trace_answer,
                    qa_trace_error,
                    qa_trace_metadata
                ) VALUES (
                    :trace_id,
                    :thread_id,
                    :user_id,
                    :conversation_id,
                    :question,
                    'running',
                    'pending',
                    'pending',
                    'none',
                    :run_metadata
                )
                """,
                trace_id=trace_id,
                thread_id=thread_id,
                user_id=int(user_id) if user_id is not None else None,
                conversation_id=int(conversation_id) if conversation_id is not None else None,
                question=self._stored_text(question, default="pending"),
                run_metadata=self._json(run_metadata or {}),
            )
            connection.commit()
        except Exception:
            connection.rollback()
        finally:
            cursor.close()
            connection.close()

    def record_step(
        self,
        *,
        trace_id: str,
        node_key: str,
        status: str,
        payload: dict[str, Any] | None = None,
        state_patch: dict[str, Any] | None = None,
        duration_ms: int | None = None,
        error: str | None = None,
    ) -> None:
        if not self._tables_available():
            return
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO qa_trace_steps (
                    qa_trace_id,
                    qa_trace_step_node,
                    qa_trace_step_status,
                    qa_trace_step_payload,
                    qa_trace_step_state_patch,
                    qa_trace_step_duration_ms,
                    qa_trace_step_error
                ) VALUES (
                    :trace_id,
                    :node_key,
                    :status,
                    :payload,
                    :state_patch,
                    :duration_ms,
                    :error
                )
                """,
                trace_id=trace_id,
                node_key=self._stored_text(node_key, default="graph"),
                status=self._stored_text(status, default="info"),
                payload=self._json(payload or {}),
                state_patch=self._json(state_patch or {}),
                duration_ms=int(duration_ms) if duration_ms is not None else None,
                error=self._stored_text(error, default="none"),
            )
            connection.commit()
        except Exception:
            connection.rollback()
        finally:
            cursor.close()
            connection.close()

    def finish_run(
        self,
        *,
        trace_id: str,
        status: str,
        answerability_route: str = "",
        answer_text: str = "",
        cited_sources_count: int = 0,
        evidence_sources_count: int = 0,
        run_metadata: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if not self._tables_available():
            return
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE qa_trace_runs
                SET qa_trace_status = :status,
                    qa_trace_answerability_route = :answerability_route,
                    qa_trace_answer = :answer_text,
                    qa_trace_cited_sources_count = :cited_sources_count,
                    qa_trace_evidence_sources_count = :evidence_sources_count,
                    qa_trace_metadata = :run_metadata,
                    qa_trace_error = :error,
                    qa_trace_finished = CURRENT_TIMESTAMP
                WHERE qa_trace_id = :trace_id
                """,
                trace_id=trace_id,
                status=status,
                answerability_route=self._stored_text(answerability_route, default="none"),
                answer_text=self._stored_text(answer_text, default="none"),
                cited_sources_count=int(cited_sources_count),
                evidence_sources_count=int(evidence_sources_count),
                run_metadata=self._json(run_metadata or {}),
                error=self._stored_text(error, default="none"),
            )
            connection.commit()
        except Exception:
            connection.rollback()
        finally:
            cursor.close()
            connection.close()

    def get_overview(self, *, user_id: int | None) -> dict[str, Any]:
        if not self._tables_available():
            return {
                "trace_count": 0,
                "completed_count": 0,
                "failed_count": 0,
                "running_count": 0,
                "avg_cited_sources": 0.0,
                "avg_evidence_sources": 0.0,
                "routes": [],
                "recent_feedback_count": 0,
                "eval_case_count": 0,
                "eval_run_count": 0,
            }
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            params = {"user_id": int(user_id) if user_id is not None else None}
            cursor.execute(
                """
                SELECT
                    COUNT(*) AS trace_count,
                    SUM(CASE WHEN qa_trace_status = 'completed' THEN 1 ELSE 0 END) AS completed_count,
                    SUM(CASE WHEN qa_trace_status = 'failed' THEN 1 ELSE 0 END) AS failed_count,
                    SUM(CASE WHEN qa_trace_status = 'running' THEN 1 ELSE 0 END) AS running_count,
                    AVG(qa_trace_cited_sources_count) AS avg_cited_sources,
                    AVG(qa_trace_evidence_sources_count) AS avg_evidence_sources
                FROM qa_trace_runs
                WHERE (:user_id IS NULL OR user_id = :user_id)
                """,
                params,
            )
            row = row_to_dict(cursor, cursor.fetchone())
            cursor.execute(
                """
                SELECT qa_trace_answerability_route AS route, COUNT(*) AS count
                FROM qa_trace_runs
                WHERE (:user_id IS NULL OR user_id = :user_id)
                GROUP BY qa_trace_answerability_route
                ORDER BY COUNT(*) DESC
                """,
                params,
            )
            routes = [row_to_dict(cursor, route_row) for route_row in cursor.fetchall()]
            recent_feedback_count = 0
            if self._required_tables_available("qa_feedback_events"):
                cursor.execute(
                    """
                    SELECT COUNT(*)
                    FROM qa_feedback_events
                    WHERE (:user_id IS NULL OR user_id = :user_id)
                    """,
                    params,
                )
                recent_feedback_count = int((cursor.fetchone() or [0])[0] or 0)
            eval_case_count = 0
            eval_run_count = 0
            if self._required_tables_available("qa_eval_cases", "qa_eval_runs"):
                cursor.execute("SELECT COUNT(*) FROM qa_eval_cases WHERE qa_eval_case_state = 1")
                eval_case_count = int((cursor.fetchone() or [0])[0] or 0)
                cursor.execute("SELECT COUNT(*) FROM qa_eval_runs")
                eval_run_count = int((cursor.fetchone() or [0])[0] or 0)
            return {
                "trace_count": int(row.get("trace_count") or 0),
                "completed_count": int(row.get("completed_count") or 0),
                "failed_count": int(row.get("failed_count") or 0),
                "running_count": int(row.get("running_count") or 0),
                "avg_cited_sources": float(row.get("avg_cited_sources") or 0.0),
                "avg_evidence_sources": float(row.get("avg_evidence_sources") or 0.0),
                "routes": [
                    {
                        "route": str(item.get("route") or "unclassified"),
                        "count": int(item.get("count") or 0),
                    }
                    for item in routes
                ],
                "recent_feedback_count": recent_feedback_count,
                "eval_case_count": eval_case_count,
                "eval_run_count": eval_run_count,
                **self._checkpoint_counts(cursor),
            }
        finally:
            cursor.close()
            connection.close()

    def _checkpoint_counts(self, cursor: Any) -> dict[str, int]:
        if not self._required_tables_available("agent_threads", "agent_checkpoints", "agent_checkpoint_writes"):
            return {
                "checkpoint_thread_count": 0,
                "checkpoint_count": 0,
                "checkpoint_write_count": 0,
            }
        cursor.execute("SELECT COUNT(*) FROM agent_threads")
        thread_count = int((cursor.fetchone() or [0])[0] or 0)
        cursor.execute("SELECT COUNT(*) FROM agent_checkpoints")
        checkpoint_count = int((cursor.fetchone() or [0])[0] or 0)
        cursor.execute("SELECT COUNT(*) FROM agent_checkpoint_writes")
        write_count = int((cursor.fetchone() or [0])[0] or 0)
        return {
            "checkpoint_thread_count": thread_count,
            "checkpoint_count": checkpoint_count,
            "checkpoint_write_count": write_count,
        }

    def list_trace_runs(self, *, user_id: int | None, limit: int = 25) -> list[dict[str, Any]]:
        if not self._tables_available():
            return []
        row_limit = self._limit(limit)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    qa_trace_id,
                    qa_trace_thread_id,
                    user_id,
                    qa_conversations_id,
                    qa_trace_question,
                    qa_trace_status,
                    qa_trace_answerability_route,
                    qa_trace_answer,
                    qa_trace_cited_sources_count,
                    qa_trace_evidence_sources_count,
                    qa_trace_metadata,
                    qa_trace_error,
                    qa_trace_started,
                    qa_trace_finished
                FROM qa_trace_runs
                WHERE (:user_id IS NULL OR user_id = :user_id)
                ORDER BY qa_trace_started DESC
                FETCH FIRST {row_limit} ROWS ONLY
                """,
                user_id=int(user_id) if user_id is not None else None,
            )
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()
        return [self._normalize_trace_run(row) for row in rows]

    def get_trace_steps(self, *, trace_id: str, user_id: int | None, limit: int = 200) -> list[dict[str, Any]]:
        if not self._tables_available():
            return []
        row_limit = self._limit(limit, default=200, maximum=500)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    s.qa_trace_step_id,
                    s.qa_trace_id,
                    s.qa_trace_step_node,
                    s.qa_trace_step_status,
                    s.qa_trace_step_payload,
                    s.qa_trace_step_state_patch,
                    s.qa_trace_step_duration_ms,
                    s.qa_trace_step_error,
                    s.qa_trace_step_created
                FROM qa_trace_steps s
                JOIN qa_trace_runs r ON r.qa_trace_id = s.qa_trace_id
                WHERE s.qa_trace_id = :trace_id
                  AND (:user_id IS NULL OR r.user_id = :user_id)
                ORDER BY s.qa_trace_step_created ASC, s.qa_trace_step_id ASC
                FETCH FIRST {row_limit} ROWS ONLY
                """,
                trace_id=str(trace_id or "").strip(),
                user_id=int(user_id) if user_id is not None else None,
            )
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()
        return [self._normalize_trace_step(row) for row in rows]

    def record_feedback_event(
        self,
        *,
        user_id: int | None,
        conversation_id: int | None,
        trace_id: str | None,
        event_type: str,
        value: str,
        assistant_message_id: str,
        user_prompt: str,
        assistant_answer: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        if not self._required_tables_available("qa_feedback_events"):
            return None
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            event_id_var = cursor.var(int)
            created_var = cursor.var(datetime)
            cursor.execute(
                """
                INSERT INTO qa_feedback_events (
                    user_id,
                    qa_conversations_id,
                    qa_trace_id,
                    qa_feedback_event_type,
                    qa_feedback_value,
                    qa_feedback_assistant_message_id,
                    qa_feedback_user_prompt,
                    qa_feedback_assistant_answer,
                    qa_feedback_metadata
                ) VALUES (
                    :user_id,
                    :conversation_id,
                    :trace_id,
                    :event_type,
                    :value,
                    :assistant_message_id,
                    :user_prompt,
                    :assistant_answer,
                    :metadata
                )
                RETURNING qa_feedback_event_id, qa_feedback_created INTO :event_id, :created
                """,
                user_id=int(user_id) if user_id is not None else None,
                conversation_id=int(conversation_id) if conversation_id is not None else None,
                trace_id=(str(trace_id or "").strip() if self._trace_exists(trace_id) else None),
                event_type=self._stored_text(event_type, default="event")[:64],
                value=self._stored_text(value, default="none")[:64],
                assistant_message_id=self._stored_text(assistant_message_id, default="none")[:128],
                user_prompt=self._stored_text(user_prompt, default="none"),
                assistant_answer=self._stored_text(assistant_answer, default="none"),
                metadata=self._json(metadata or {}),
                event_id=event_id_var,
                created=created_var,
            )
            connection.commit()
            return {
                "feedback_event_id": int(event_id_var.getvalue()[0]),
                "created_at": self._to_iso(created_var.getvalue()[0]),
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def list_feedback_events(self, *, user_id: int | None, limit: int = 25) -> list[dict[str, Any]]:
        if not self._required_tables_available("qa_feedback_events"):
            return []
        row_limit = self._limit(limit)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    qa_feedback_event_id,
                    user_id,
                    qa_conversations_id,
                    qa_trace_id,
                    qa_feedback_event_type,
                    qa_feedback_value,
                    qa_feedback_assistant_message_id,
                    qa_feedback_user_prompt,
                    qa_feedback_assistant_answer,
                    qa_feedback_metadata,
                    qa_feedback_created
                FROM qa_feedback_events
                WHERE (:user_id IS NULL OR user_id = :user_id)
                ORDER BY qa_feedback_created DESC
                FETCH FIRST {row_limit} ROWS ONLY
                """,
                user_id=int(user_id) if user_id is not None else None,
            )
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()
        return [self._normalize_feedback_event(row) for row in rows]

    def create_eval_case(
        self,
        *,
        name: str,
        category: str,
        question: str,
        expected: dict[str, Any],
        source: str,
    ) -> dict[str, Any]:
        if not self._required_tables_available("qa_eval_cases"):
            raise RuntimeError("Evaluation tables are not installed.")
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            case_id_var = cursor.var(int)
            created_var = cursor.var(datetime)
            cursor.execute(
                """
                INSERT INTO qa_eval_cases (
                    qa_eval_case_name,
                    qa_eval_case_category,
                    qa_eval_case_question,
                    qa_eval_case_expected,
                    qa_eval_case_source
                ) VALUES (
                    :name,
                    :category,
                    :question,
                    :expected,
                    :source
                )
                RETURNING qa_eval_case_id, qa_eval_case_created INTO :case_id, :created
                """,
                name=self._stored_text(name, default="Untitled evaluation case")[:255],
                category=self._stored_text(category, default="manual")[:64],
                question=self._stored_text(question, default="pending"),
                expected=self._json(expected or {}),
                source=self._stored_text(source, default="manual")[:255],
                case_id=case_id_var,
                created=created_var,
            )
            connection.commit()
            return {
                "eval_case_id": int(case_id_var.getvalue()[0]),
                "name": self._stored_text(name, default="Untitled evaluation case"),
                "category": self._stored_text(category, default="manual"),
                "question": self._stored_text(question, default="pending"),
                "expected": dict(expected or {}),
                "source": self._stored_text(source, default="manual"),
                "created_at": self._to_iso(created_var.getvalue()[0]),
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def list_eval_cases(self, *, limit: int = 100) -> list[dict[str, Any]]:
        if not self._required_tables_available("qa_eval_cases"):
            return []
        row_limit = self._limit(limit, default=100, maximum=500)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    qa_eval_case_id,
                    qa_eval_case_name,
                    qa_eval_case_category,
                    qa_eval_case_question,
                    qa_eval_case_expected,
                    qa_eval_case_source,
                    qa_eval_case_created
                FROM qa_eval_cases
                WHERE qa_eval_case_state = 1
                ORDER BY qa_eval_case_created DESC
                FETCH FIRST {row_limit} ROWS ONLY
                """
            )
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()
        return [self._normalize_eval_case(row) for row in rows]

    def get_eval_cases_by_ids(self, *, case_ids: list[int]) -> list[dict[str, Any]]:
        if not self._required_tables_available("qa_eval_cases"):
            return []
        normalized_ids = [int(item) for item in list(case_ids or []) if int(item) > 0]
        if not normalized_ids:
            return []
        placeholders = ", ".join(f":case_id_{index}" for index, _ in enumerate(normalized_ids))
        params = {f"case_id_{index}": case_id for index, case_id in enumerate(normalized_ids)}
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    qa_eval_case_id,
                    qa_eval_case_name,
                    qa_eval_case_category,
                    qa_eval_case_question,
                    qa_eval_case_expected,
                    qa_eval_case_source,
                    qa_eval_case_created
                FROM qa_eval_cases
                WHERE qa_eval_case_state = 1
                  AND qa_eval_case_id IN ({placeholders})
                ORDER BY qa_eval_case_id ASC
                """,
                params,
            )
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()
        return [self._normalize_eval_case(row) for row in rows]

    def create_eval_run(self, *, name: str, metadata: dict[str, Any] | None = None) -> int:
        if not self._required_tables_available("qa_eval_runs"):
            raise RuntimeError("Evaluation tables are not installed.")
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            run_id_var = cursor.var(int)
            cursor.execute(
                """
                INSERT INTO qa_eval_runs (
                    qa_eval_run_name,
                    qa_eval_run_status,
                    qa_eval_run_metadata
                ) VALUES (
                    :name,
                    'running',
                    :metadata
                )
                RETURNING qa_eval_run_id INTO :run_id
                """,
                name=self._stored_text(name, default="Evaluation run")[:255],
                metadata=self._json(metadata or {}),
                run_id=run_id_var,
            )
            connection.commit()
            return int(run_id_var.getvalue()[0])
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def finish_eval_run(self, *, run_id: int, status: str, metadata: dict[str, Any] | None = None) -> None:
        if not self._required_tables_available("qa_eval_runs"):
            return
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                UPDATE qa_eval_runs
                SET qa_eval_run_status = :status,
                    qa_eval_run_metadata = :metadata,
                    qa_eval_run_finished = CURRENT_TIMESTAMP
                WHERE qa_eval_run_id = :run_id
                """,
                run_id=int(run_id),
                status=self._stored_text(status, default="completed")[:32],
                metadata=self._json(metadata or {}),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def insert_eval_result(
        self,
        *,
        run_id: int,
        case_id: int,
        trace_id: str | None,
        status: str,
        score: float,
        details: dict[str, Any],
    ) -> None:
        if not self._required_tables_available("qa_eval_results"):
            return
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                """
                INSERT INTO qa_eval_results (
                    qa_eval_run_id,
                    qa_eval_case_id,
                    qa_trace_id,
                    qa_eval_result_status,
                    qa_eval_result_score,
                    qa_eval_result_details
                ) VALUES (
                    :run_id,
                    :case_id,
                    :trace_id,
                    :status,
                    :score,
                    :details
                )
                """,
                run_id=int(run_id),
                case_id=int(case_id),
                trace_id=(str(trace_id or "").strip() if self._trace_exists(trace_id) else None),
                status=self._stored_text(status, default="review")[:32],
                score=float(max(0.0, min(1.0, score))),
                details=self._json(details or {}),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            cursor.close()
            connection.close()

    def list_eval_runs(self, *, limit: int = 25) -> list[dict[str, Any]]:
        if not self._required_tables_available("qa_eval_runs"):
            return []
        row_limit = self._limit(limit)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    r.qa_eval_run_id,
                    r.qa_eval_run_name,
                    r.qa_eval_run_status,
                    r.qa_eval_run_metadata,
                    r.qa_eval_run_started,
                    r.qa_eval_run_finished,
                    NVL(stats.result_count, 0) AS result_count,
                    NVL(stats.avg_score, 0) AS avg_score,
                    NVL(stats.passed_count, 0) AS passed_count
                FROM qa_eval_runs r
                LEFT JOIN (
                    SELECT
                        qa_eval_run_id,
                        COUNT(qa_eval_result_id) AS result_count,
                        AVG(qa_eval_result_score) AS avg_score,
                        SUM(CASE WHEN qa_eval_result_status = 'passed' THEN 1 ELSE 0 END) AS passed_count
                    FROM qa_eval_results
                    GROUP BY qa_eval_run_id
                ) stats ON stats.qa_eval_run_id = r.qa_eval_run_id
                ORDER BY r.qa_eval_run_started DESC
                FETCH FIRST {row_limit} ROWS ONLY
                """
            )
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()
        return [self._normalize_eval_run(row) for row in rows]

    def list_eval_results(self, *, run_id: int, limit: int = 100) -> list[dict[str, Any]]:
        if not self._required_tables_available("qa_eval_results"):
            return []
        row_limit = self._limit(limit, default=100, maximum=500)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    er.qa_eval_result_id,
                    er.qa_eval_run_id,
                    er.qa_eval_case_id,
                    c.qa_eval_case_name,
                    c.qa_eval_case_question,
                    er.qa_trace_id,
                    er.qa_eval_result_status,
                    er.qa_eval_result_score,
                    er.qa_eval_result_details,
                    er.qa_eval_result_created
                FROM qa_eval_results er
                JOIN qa_eval_cases c ON c.qa_eval_case_id = er.qa_eval_case_id
                WHERE er.qa_eval_run_id = :run_id
                ORDER BY er.qa_eval_result_created ASC
                FETCH FIRST {row_limit} ROWS ONLY
                """,
                run_id=int(run_id),
            )
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()
        return [self._normalize_eval_result(row) for row in rows]

    def list_checkpoint_threads(self, *, limit: int = 25) -> list[dict[str, Any]]:
        if not self._required_tables_available("agent_threads", "agent_checkpoints", "agent_checkpoint_writes"):
            return []
        row_limit = self._limit(limit)
        connection = self.db_manager.get_connection()
        cursor = connection.cursor()
        try:
            cursor.execute(
                f"""
                SELECT
                    t.agent_threads_thread_id,
                    t.agent_threads_updated,
                    t.agent_threads_created,
                    COUNT(DISTINCT c.agent_checkpoints_id) AS checkpoint_count,
                    COUNT(DISTINCT w.agent_checkpoint_writes_id) AS write_count,
                    MAX(c.agent_checkpoints_created) AS last_checkpoint_at,
                    COUNT(DISTINCT r.qa_trace_id) AS trace_count,
                    (
                        SELECT rr.qa_trace_id
                        FROM qa_trace_runs rr
                        WHERE rr.qa_trace_thread_id = t.agent_threads_thread_id
                        ORDER BY rr.qa_trace_started DESC
                        FETCH FIRST 1 ROWS ONLY
                    ) AS latest_trace_id,
                    (
                        SELECT DBMS_LOB.SUBSTR(rr.qa_trace_question, 1000, 1)
                        FROM qa_trace_runs rr
                        WHERE rr.qa_trace_thread_id = t.agent_threads_thread_id
                        ORDER BY rr.qa_trace_started DESC
                        FETCH FIRST 1 ROWS ONLY
                    ) AS latest_question
                FROM agent_threads t
                LEFT JOIN agent_checkpoints c
                    ON c.agent_threads_thread_id = t.agent_threads_thread_id
                LEFT JOIN agent_checkpoint_writes w
                    ON w.agent_threads_thread_id = t.agent_threads_thread_id
                LEFT JOIN qa_trace_runs r
                    ON r.qa_trace_thread_id = t.agent_threads_thread_id
                GROUP BY
                    t.agent_threads_thread_id,
                    t.agent_threads_updated,
                    t.agent_threads_created
                ORDER BY t.agent_threads_updated DESC
                FETCH FIRST {row_limit} ROWS ONLY
                """
            )
            rows = [row_to_dict(cursor, row) for row in cursor.fetchall()]
        finally:
            cursor.close()
            connection.close()
        return [self._normalize_checkpoint_thread(row) for row in rows]

    def _normalize_trace_run(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "trace_id": str(row.get("qa_trace_id") or ""),
            "thread_id": str(row.get("qa_trace_thread_id") or ""),
            "user_id": int(row.get("user_id") or 0) or None,
            "conversation_id": int(row.get("qa_conversations_id") or 0) or None,
            "question": str(row.get("qa_trace_question") or ""),
            "status": str(row.get("qa_trace_status") or ""),
            "answerability_route": str(row.get("qa_trace_answerability_route") or ""),
            "answer_preview": str(row.get("qa_trace_answer") or "")[:600],
            "cited_sources_count": int(row.get("qa_trace_cited_sources_count") or 0),
            "evidence_sources_count": int(row.get("qa_trace_evidence_sources_count") or 0),
            "metadata": self._parse_json(row.get("qa_trace_metadata")),
            "error": str(row.get("qa_trace_error") or ""),
            "started_at": self._to_iso(row.get("qa_trace_started")),
            "finished_at": self._to_iso(row.get("qa_trace_finished")),
        }

    def _normalize_trace_step(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "step_id": int(row.get("qa_trace_step_id") or 0),
            "trace_id": str(row.get("qa_trace_id") or ""),
            "node": str(row.get("qa_trace_step_node") or ""),
            "status": str(row.get("qa_trace_step_status") or ""),
            "payload": self._parse_json(row.get("qa_trace_step_payload")),
            "state_patch": self._parse_json(row.get("qa_trace_step_state_patch")),
            "duration_ms": int(row.get("qa_trace_step_duration_ms") or 0),
            "error": str(row.get("qa_trace_step_error") or ""),
            "created_at": self._to_iso(row.get("qa_trace_step_created")),
        }

    def _normalize_feedback_event(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "feedback_event_id": int(row.get("qa_feedback_event_id") or 0),
            "user_id": int(row.get("user_id") or 0) or None,
            "conversation_id": int(row.get("qa_conversations_id") or 0) or None,
            "trace_id": str(row.get("qa_trace_id") or ""),
            "event_type": str(row.get("qa_feedback_event_type") or ""),
            "value": str(row.get("qa_feedback_value") or ""),
            "assistant_message_id": str(row.get("qa_feedback_assistant_message_id") or ""),
            "user_prompt": str(row.get("qa_feedback_user_prompt") or ""),
            "assistant_answer_preview": str(row.get("qa_feedback_assistant_answer") or "")[:600],
            "metadata": self._parse_json(row.get("qa_feedback_metadata")),
            "created_at": self._to_iso(row.get("qa_feedback_created")),
        }

    def _normalize_eval_case(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "eval_case_id": int(row.get("qa_eval_case_id") or 0),
            "name": str(row.get("qa_eval_case_name") or ""),
            "category": str(row.get("qa_eval_case_category") or ""),
            "question": str(row.get("qa_eval_case_question") or ""),
            "expected": self._parse_json(row.get("qa_eval_case_expected")),
            "source": str(row.get("qa_eval_case_source") or ""),
            "created_at": self._to_iso(row.get("qa_eval_case_created")),
        }

    def _normalize_eval_run(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "eval_run_id": int(row.get("qa_eval_run_id") or 0),
            "name": str(row.get("qa_eval_run_name") or ""),
            "status": str(row.get("qa_eval_run_status") or ""),
            "metadata": self._parse_json(row.get("qa_eval_run_metadata")),
            "started_at": self._to_iso(row.get("qa_eval_run_started")),
            "finished_at": self._to_iso(row.get("qa_eval_run_finished")),
            "result_count": int(row.get("result_count") or 0),
            "avg_score": float(row.get("avg_score") or 0.0),
            "passed_count": int(row.get("passed_count") or 0),
        }

    def _normalize_eval_result(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "eval_result_id": int(row.get("qa_eval_result_id") or 0),
            "eval_run_id": int(row.get("qa_eval_run_id") or 0),
            "eval_case_id": int(row.get("qa_eval_case_id") or 0),
            "case_name": str(row.get("qa_eval_case_name") or ""),
            "question": str(row.get("qa_eval_case_question") or ""),
            "trace_id": str(row.get("qa_trace_id") or ""),
            "status": str(row.get("qa_eval_result_status") or ""),
            "score": float(row.get("qa_eval_result_score") or 0.0),
            "details": self._parse_json(row.get("qa_eval_result_details")),
            "created_at": self._to_iso(row.get("qa_eval_result_created")),
        }

    def _normalize_checkpoint_thread(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "thread_id": str(row.get("agent_threads_thread_id") or ""),
            "checkpoint_count": int(row.get("checkpoint_count") or 0),
            "write_count": int(row.get("write_count") or 0),
            "trace_count": int(row.get("trace_count") or 0),
            "latest_trace_id": str(row.get("latest_trace_id") or ""),
            "latest_question": str(row.get("latest_question") or ""),
            "last_checkpoint_at": self._to_iso(row.get("last_checkpoint_at")),
            "created_at": self._to_iso(row.get("agent_threads_created")),
            "updated_at": self._to_iso(row.get("agent_threads_updated")),
        }
