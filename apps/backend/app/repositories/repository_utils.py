"""Utilidades compartidas para repositorios SQL."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import re
import time
from typing import Any, TypeVar

from apps.backend.app.core.database import DatabaseManager

T = TypeVar("T")

_ORACLE_INDEX_NAME_RE = re.compile(
    r"index\s+\"?((?:[A-Za-z][A-Za-z0-9_$#]*\.)?[A-Za-z][A-Za-z0-9_$#]*)\"?",
    flags=re.IGNORECASE,
)
_ORACLE_IDENTIFIER_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]*$")
_ORACLE_TEXT_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_ORACLE_TEXT_STOPWORDS = {
    "a",
    "al",
    "an",
    "and",
    "con",
    "de",
    "del",
    "el",
    "en",
    "esta",
    "este",
    "la",
    "las",
    "los",
    "o",
    "or",
    "para",
    "por",
    "que",
    "se",
    "the",
    "un",
    "una",
    "y",
}


def _escape_oracle_text_term(term: str) -> str:
    normalized = str(term or "").strip()
    if not normalized:
        return ""
    # Treat every token as a literal term so Oracle Text does not parse archive
    # slugs, reserved words, or metadata fragments as query syntax.
    escaped = normalized.replace("\\", "\\\\").replace("}", "}}")
    return f"{{{escaped}}}"


def non_empty_string(value: str | None, *, default_value: str) -> str:
    normalized = (value or "").strip()
    return normalized if normalized else default_value


def status_to_code(status: str) -> int:
    mapping = {
        "pending": 1,
        "registered": 1,
        "processing": 2,
        "completed": 3,
        "failed": -1,
    }
    return mapping.get((status or "").strip().lower(), 1)


def code_to_status(state_code: int | None) -> str:
    mapping = {
        1: "registered",
        2: "processing",
        3: "completed",
        -1: "failed",
        0: "disabled",
    }
    return mapping.get(int(state_code or 1), "registered")


def read_lob(value: Any) -> Any:
    if hasattr(value, "read"):
        return value.read()
    return value


def build_file_access_scope_condition(
    *,
    alias: str = "",
    user_param: str = "user_id",
    include_shared: bool = False,
) -> str:
    prefix = f"{alias}." if alias else ""
    owner_condition = f"{prefix}user_id = :{user_param}"
    if not include_shared:
        return owner_condition
    return (
        f"({owner_condition} OR "
        f"(:{user_param} > 0 AND LOWER(NVL({prefix}access_scope, 'private')) = 'all'))"
    )


def row_to_dict(cursor: Any, row: tuple[Any, ...]) -> dict[str, Any]:
    columns = [item[0].lower() for item in cursor.description]
    payload: dict[str, Any] = {}
    for index, column in enumerate(columns):
        payload[column] = read_lob(row[index])
    return payload


def build_oracle_text_contains_query(
    text: str | None,
    *,
    minimum_token_length: int = 2,
    stopwords: set[str] | None = None,
) -> str:
    active_stopwords = {item.strip().lower() for item in (stopwords or _ORACLE_TEXT_STOPWORDS) if item.strip()}
    tokens = {
        token.strip().lower()
        for token in _ORACLE_TEXT_TOKEN_RE.findall(str(text or "").lower())
        if len(token.strip()) >= int(minimum_token_length) and token.strip().lower() not in active_stopwords
    }
    return " OR ".join(
        escaped
        for escaped in (_escape_oracle_text_term(token) for token in sorted(tokens))
        if escaped
    )


def is_retryable_database_error(error: Any) -> bool:
    error_text = str(error or "").lower()
    hints = (
        "ora-00060",
        "ora-12860",
        "dpy-4011",
        "dpy-1001",
        "closed the connection",
        "connection has been closed",
    )
    return any(hint in error_text for hint in hints)


def is_oracle_text_loading_error(error: Any) -> bool:
    error_text = str(error or "").lower()
    if "ora-29861" not in error_text or "domain index" not in error_text:
        return False
    return "loading" in error_text or "currently not usable" in error_text


def _normalize_oracle_index_name(value: str | None) -> str | None:
    parts = [segment.strip() for segment in str(value or "").replace('"', "").split(".") if segment.strip()]
    if not parts:
        return None
    normalized: list[str] = []
    for part in parts:
        if not _ORACLE_IDENTIFIER_RE.fullmatch(part):
            return None
        normalized.append(part.upper())
    return ".".join(normalized)


def extract_oracle_index_names(error: Any) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for match in _ORACLE_INDEX_NAME_RE.finditer(str(error or "")):
        normalized = _normalize_oracle_index_name(match.group(1))
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _oracle_text_sync_type(cursor: Any, *, index_name: str) -> str | None:
    short_name = str(index_name or "").split(".")[-1].strip().upper()
    if not short_name:
        return None
    try:
        cursor.execute(
            """
            SELECT idx_sync_type, idx_maintenance_type
            FROM ctx_user_indexes
            WHERE idx_name = :idx_name
            FETCH FIRST 1 ROWS ONLY
            """,
            idx_name=short_name,
        )
        row = cursor.fetchone()
    except Exception:
        return None
    if not row:
        return None
    sync_type = str(read_lob(row[0]) or "").strip().upper()
    maintenance_type = str(read_lob(row[1]) or "").strip().upper() if len(row) > 1 else ""
    if maintenance_type == "AUTO":
        return "AUTO"
    return sync_type or None


def _oracle_text_rebuild_parameters(*, sync_type: str | None) -> str:
    normalized = str(sync_type or "").strip().upper()
    if normalized == "AUTO":
        return "REPLACE METADATA MAINTENANCE AUTO"
    if normalized == "ON COMMIT" or normalized.startswith("EVERY"):
        return "REPLACE METADATA SYNC(MANUAL) MAINTENANCE AUTO"
    return "REPLACE METADATA MAINTENANCE AUTO"


def repair_oracle_text_indexes(
    *,
    db_manager: DatabaseManager,
    candidate_index_names: Sequence[str] | None = None,
    error: Any | None = None,
) -> list[str]:
    merged_names = list(candidate_index_names or []) + extract_oracle_index_names(error)
    ordered_names: list[str] = []
    seen: set[str] = set()
    for raw_name in merged_names:
        normalized = _normalize_oracle_index_name(raw_name)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        ordered_names.append(normalized)
    if not ordered_names:
        return []

    connection = db_manager.get_connection()
    cursor = connection.cursor()
    repaired: list[str] = []
    try:
        for index_name in ordered_names:
            parameters = _oracle_text_rebuild_parameters(
                sync_type=_oracle_text_sync_type(cursor, index_name=index_name)
            )
            try:
                cursor.execute(
                    f"ALTER INDEX {index_name} REBUILD PARAMETERS('{parameters}')"
                )
                repaired.append(index_name)
            except Exception:
                continue
        return repaired
    finally:
        try:
            cursor.close()
        except Exception:
            pass
        try:
            connection.close()
        except Exception:
            pass


def execute_with_oracle_text_repair(
    *,
    db_manager: DatabaseManager,
    operation: Callable[[], T],
    candidate_index_names: Sequence[str] | None = None,
    max_attempts: int = 2,
    sleep_seconds: float = 0.25,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if not is_oracle_text_loading_error(exc) or attempt >= max_attempts:
                raise
            repair_oracle_text_indexes(
                db_manager=db_manager,
                candidate_index_names=candidate_index_names,
                error=exc,
            )
            time.sleep(float(max(0.0, sleep_seconds)) * attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Oracle Text repair retry exhausted without returning a result.")


def execute_with_retryable_database_operation(
    *,
    db_manager: DatabaseManager,
    operation: Callable[[], T],
    candidate_index_names: Sequence[str] | None = None,
    max_attempts: int = 3,
    text_repair_sleep_seconds: float = 0.25,
    retry_sleep_seconds: float = 1.0,
) -> T:
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if is_oracle_text_loading_error(exc):
                repair_oracle_text_indexes(
                    db_manager=db_manager,
                    candidate_index_names=candidate_index_names,
                    error=exc,
                )
                if attempt >= max_attempts:
                    raise
                time.sleep(float(max(0.0, text_repair_sleep_seconds)) * attempt)
                continue
            if not is_retryable_database_error(exc) or attempt >= max_attempts:
                raise
            time.sleep(float(max(0.0, retry_sleep_seconds)) * attempt)
    if last_error is not None:
        raise last_error
    raise RuntimeError("Retryable database operation exhausted without returning a result.")
