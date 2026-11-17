"""Document scope resolution before retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import re
import time
from typing import Protocol
import unicodedata

from apps.backend.app.services.metadata_keys import canonicalize_file_key

CODE_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]+", re.UNICODE)
DOCUMENT_CODE_PATTERN = re.compile(r"^[A-Z]{2,24}[A-Z0-9_-]*\d[A-Z0-9_-]*$")
QUESTION_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
EXPLICIT_FILE_REFERENCE_PATTERN = re.compile(
    r"(?<!\S)(?:[\w.-]+(?:\s\([\w.-]+\))?)\.pdf\b",
    re.IGNORECASE | re.UNICODE,
)


def normalize_document_code(value: str) -> str:
    return str(value or "").strip().upper()


def extract_candidate_codes_from_question(question: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_token in CODE_TOKEN_PATTERN.findall(str(question or "")):
        token = normalize_document_code(raw_token)
        if not token or token in seen:
            continue
        if "_" in token or "-" in token:
            continue
        if not DOCUMENT_CODE_PATTERN.fullmatch(token):
            continue
        seen.add(token)
        ordered.append(token)
    return ordered


def extract_candidate_archive_slugs_from_question(question: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for raw_token in CODE_TOKEN_PATTERN.findall(str(question or "")):
        token = canonicalize_file_key(raw_token.strip())
        normalized = token.upper()
        if not token or "_ID_" not in normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(token)
    return ordered


def extract_candidate_file_names_from_question(question: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in EXPLICIT_FILE_REFERENCE_PATTERN.finditer(str(question or "")):
        candidate = str(match.group(0) or "").strip().strip("`\"'")
        if not candidate:
            continue
        normalized = unicodedata.normalize("NFKD", candidate)
        normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch)).casefold()
        normalized = re.sub(r"\s+", " ", normalized).strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(candidate)
    return ordered


class ScopeRepository(Protocol):
    def filter_file_ids_for_user(
        self,
        *,
        user_id: int,
        file_ids: list[int],
        include_shared: bool = False,
    ) -> list[int]:
        ...

    def list_distinct_document_codes_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[str]:
        ...

    def list_file_ids_for_document_codes(
        self,
        *,
        user_id: int,
        document_codes: list[str],
        include_shared: bool = False,
    ) -> list[int]:
        ...

    def list_known_archive_slugs_for_user(
        self,
        *,
        user_id: int,
        include_shared: bool = False,
    ) -> list[str]:
        ...

    def list_file_ids_for_archive_slugs(
        self,
        *,
        user_id: int,
        archive_slugs: list[str],
        include_shared: bool = False,
    ) -> list[int]:
        ...

    def list_file_ids_for_input_filenames(
        self,
        *,
        user_id: int,
        file_names: list[str],
        file_ids: list[int] | None = None,
        include_shared: bool = False,
    ) -> list[int]:
        ...

    def count_files_for_user(self, *, user_id: int, include_shared: bool = False) -> int:
        ...


class ScopeResolutionError(RuntimeError):
    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = int(status_code)


@dataclass(slots=True)
class ScopeResolution:
    file_ids: list[int]
    scope_origin: str
    scope_document_codes: list[str]
    scope_archive_slugs: list[str]
    resolved_scope_file_count: int
    scope_resolution_ms: int
    ignored_inferred_scope: bool


class QuestionScopeResolver:
    def __init__(self, repository: ScopeRepository) -> None:
        self.repository = repository

    @staticmethod
    def _normalize_question_text(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", str(value or ""))
        compact = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        return compact.lower().strip()

    @classmethod
    def _question_references_previous_scope(cls, question: str) -> bool:
        normalized = cls._normalize_question_text(question)
        tokens = set(QUESTION_TOKEN_PATTERN.findall(normalized))
        if not tokens:
            return False
        reference_phrases = (
            "de estos",
            "de estas",
            "de esos",
            "de esas",
            "de los anteriores",
            "de las anteriores",
            "de los mismos",
            "de las mismas",
            "de este archivo",
            "de esta archivo",
            "de ese archivo",
            "de esa archivo",
            "de este documento",
            "de ese documento",
            "de este mismo archivo",
            "de esta misma archivo",
            "de ese mismo archivo",
            "de esa misma archivo",
            "sobre este archivo",
            "sobre ese archivo",
            "sobre este documento",
            "sobre ese documento",
            "sobre este mismo archivo",
            "sobre ese mismo archivo",
            "todo el documento",
            "todo este documento",
            "todo ese documento",
            "el documento completo",
            "del documento completo",
            "de los listados",
            "de las listadas",
            "de los mencionados",
            "de las mencionadas",
            "en el otro documento",
            "en la otra documento",
            "en el otro archivo",
            "en la otra archivo",
            "del otro documento",
            "de la otra documento",
            "del otro archivo",
            "de la otra archivo",
            "sobre el otro documento",
            "sobre la otra documento",
            "sobre el otro archivo",
            "sobre la otra archivo",
        )
        if any(phrase in normalized for phrase in reference_phrases):
            return True
        reference_tokens = {
            "estos",
            "estas",
            "este",
            "esta",
            "esos",
            "esas",
            "ese",
            "esa",
            "anteriores",
            "anterior",
            "previos",
            "previas",
            "previo",
            "previa",
            "mismos",
            "mismas",
            "mismo",
            "misma",
            "listados",
            "listadas",
            "listado",
            "listada",
            "mencionados",
            "mencionadas",
            "mencionado",
            "mencionada",
            "devueltos",
            "devueltas",
            "devuelto",
            "devuelta",
            "otro",
            "otra",
            "otros",
            "otras",
        }
        scope_nouns = {
            "archivos",
            "archivo",
            "documentos",
            "documento",
            "folios",
            "folio",
            "casos",
            "caso",
            "resultados",
            "resultado",
            "zip",
        }
        if tokens & reference_tokens and tokens & scope_nouns:
            return True
        if re.search(
            r"\b(?:estos|estas|esos|esas)\s+\d+\s+(?:archivos|documentos|folios|casos)\b",
            normalized,
        ):
            return True
        if re.search(
            r"\b(?:este|esta|ese|esa)\s+(?:(?:mismo|misma|anterior|previo|previa|mencionado|mencionada|listado|listada|devuelto|devuelta)\s+)?(?:archivo|documento|folio|caso|resultado|zip)\b",
            normalized,
        ):
            return True
        if "sus" in tokens and any(
            token in normalized
            for token in (
                "ultim",
                "ultimo",
                "ultimos",
                "ultima",
                "ultimas",
                "firmad",
                "suscrit",
                "document",
                "archiv",
                "modific",
                "version",
                "clausul",
            )
        ):
            return True
        return False

    @staticmethod
    def _normalize_archive_slugs(values: list[str] | None) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw_value in list(values or []):
            normalized = canonicalize_file_key(str(raw_value or "").strip())
            normalized_key = normalized.lower()
            if not normalized or normalized_key in seen:
                continue
            seen.add(normalized_key)
            ordered.append(normalized)
        return ordered

    @staticmethod
    def _dedupe_positive_ids(file_ids: list[int] | None) -> list[int]:
        seen: set[int] = set()
        ordered: list[int] = []
        for raw_value in list(file_ids or []):
            value = int(raw_value)
            if value <= 0 or value in seen:
                continue
            seen.add(value)
            ordered.append(value)
        return ordered

    @staticmethod
    def _filter_to_allowed_ids(*, ordered_ids: list[int], allowed_ids: list[int]) -> list[int]:
        allowed = {int(file_id) for file_id in list(allowed_ids or []) if int(file_id) > 0}
        if not allowed:
            return []
        return [int(file_id) for file_id in list(ordered_ids or []) if int(file_id) in allowed]

    def resolve(
        self,
        *,
        question: str,
        user_id: int,
        file_ids: list[int] | None,
        archive_slugs: list[str] | None = None,
        allow_inferred_scope: bool = True,
        conversation_file_ids: list[int] | None = None,
        conversation_archive_slugs: list[str] | None = None,
    ) -> ScopeResolution:
        started_at = time.perf_counter()
        safe_user_id = int(user_id)
        requested_file_ids = self._dedupe_positive_ids(file_ids)
        conversation_scope_file_ids = self._dedupe_positive_ids(conversation_file_ids)
        conversation_scope_archive_slugs = self._normalize_archive_slugs(conversation_archive_slugs)
        requested_archive_slugs = self._normalize_archive_slugs(archive_slugs)
        hard_archive_scope = bool(requested_archive_slugs)
        candidate_codes = [] if hard_archive_scope else extract_candidate_codes_from_question(question)
        candidate_file_names = [] if hard_archive_scope else extract_candidate_file_names_from_question(question)
        candidate_archive_slugs = (
            list(requested_archive_slugs)
            if requested_archive_slugs
            else extract_candidate_archive_slugs_from_question(question)
        )

        if requested_file_ids:
            accessible_file_ids = self.repository.filter_file_ids_for_user(
                user_id=safe_user_id,
                file_ids=requested_file_ids,
                include_shared=True,
            )
            if not accessible_file_ids:
                raise ScopeResolutionError(
                    "No accessible documents were found for the provided file_ids.",
                    status_code=404,
                )
            if candidate_archive_slugs and (allow_inferred_scope or hard_archive_scope):
                available_archive_slugs = self.repository.list_known_archive_slugs_for_user(
                    user_id=safe_user_id,
                    include_shared=True,
                )
                normalized_archive_map = {
                    canonicalize_file_key(archive_slug).lower(): canonicalize_file_key(archive_slug)
                    for archive_slug in available_archive_slugs
                    if canonicalize_file_key(archive_slug)
                }
                matched_archive_slugs = [
                    normalized_archive_map[candidate.lower()]
                    for candidate in candidate_archive_slugs
                    if candidate.lower() in normalized_archive_map
                ]
                missing_archive_slugs = [
                    candidate
                    for candidate in candidate_archive_slugs
                    if candidate.lower() not in normalized_archive_map
                ]
                if missing_archive_slugs:
                    joined_archive_slugs = ", ".join(missing_archive_slugs)
                    raise ScopeResolutionError(
                        f"No accessible documents were found for archive_slug(s): {joined_archive_slugs}.",
                        status_code=404,
                    )
                resolved_file_ids = self.repository.list_file_ids_for_archive_slugs(
                    user_id=safe_user_id,
                    archive_slugs=matched_archive_slugs,
                    include_shared=True,
                )
                bounded_file_ids = self._filter_to_allowed_ids(
                    ordered_ids=accessible_file_ids,
                    allowed_ids=resolved_file_ids,
                )
                if not bounded_file_ids:
                    joined_archive_slugs = ", ".join(matched_archive_slugs)
                    raise ScopeResolutionError(
                        (
                            "No accessible documents were found for archive_slug(s) within the provided "
                            f"file_ids: {joined_archive_slugs}."
                        ),
                        status_code=404,
                    )
                return ScopeResolution(
                    file_ids=bounded_file_ids,
                    scope_origin="metadata",
                    scope_document_codes=[],
                    scope_archive_slugs=matched_archive_slugs,
                    resolved_scope_file_count=len(bounded_file_ids),
                    scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    ignored_inferred_scope=False,
                )
            if allow_inferred_scope and candidate_file_names:
                resolved_file_ids = self.repository.list_file_ids_for_input_filenames(
                    user_id=safe_user_id,
                    file_names=candidate_file_names,
                    file_ids=accessible_file_ids,
                    include_shared=True,
                )
                bounded_file_ids = self._filter_to_allowed_ids(
                    ordered_ids=accessible_file_ids,
                    allowed_ids=resolved_file_ids,
                )
                if not bounded_file_ids:
                    joined_file_names = ", ".join(candidate_file_names)
                    raise ScopeResolutionError(
                        (
                            "No accessible documents were found for input filename(s) within the provided "
                            f"file_ids: {joined_file_names}."
                        ),
                        status_code=404,
                    )
                return ScopeResolution(
                    file_ids=bounded_file_ids,
                    scope_origin="manual",
                    scope_document_codes=[],
                    scope_archive_slugs=[],
                    resolved_scope_file_count=len(bounded_file_ids),
                    scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    ignored_inferred_scope=False,
                )
            if allow_inferred_scope and candidate_codes:
                available_codes = self.repository.list_distinct_document_codes_for_user(
                    user_id=safe_user_id,
                    include_shared=True,
                )
                normalized_map = {
                    normalize_document_code(code): normalize_document_code(code)
                    for code in available_codes
                    if normalize_document_code(code)
                }
                matched_codes = [code for code in candidate_codes if code in normalized_map]
                missing_codes = [code for code in candidate_codes if code not in normalized_map]
                if missing_codes:
                    joined_codes = ", ".join(missing_codes)
                    raise ScopeResolutionError(
                        f"No accessible documents were found for code(s): {joined_codes}.",
                        status_code=404,
                    )
                resolved_file_ids = self.repository.list_file_ids_for_document_codes(
                    user_id=safe_user_id,
                    document_codes=matched_codes,
                    include_shared=True,
                )
                bounded_file_ids = self._filter_to_allowed_ids(
                    ordered_ids=accessible_file_ids,
                    allowed_ids=resolved_file_ids,
                )
                if not bounded_file_ids:
                    joined_codes = ", ".join(matched_codes)
                    raise ScopeResolutionError(
                        (
                            "No accessible documents were found for code(s) within the provided file_ids: "
                            f"{joined_codes}."
                        ),
                        status_code=404,
                    )
                return ScopeResolution(
                    file_ids=bounded_file_ids,
                    scope_origin="inferred",
                    scope_document_codes=matched_codes,
                    scope_archive_slugs=[],
                    resolved_scope_file_count=len(bounded_file_ids),
                    scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    ignored_inferred_scope=False,
                )
            return ScopeResolution(
                file_ids=accessible_file_ids,
                scope_origin="manual",
                scope_document_codes=[],
                scope_archive_slugs=[],
                resolved_scope_file_count=len(accessible_file_ids),
                scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                ignored_inferred_scope=bool(candidate_codes),
            )

        if not allow_inferred_scope and not hard_archive_scope:
            return ScopeResolution(
                file_ids=[],
                scope_origin="global",
                scope_document_codes=[],
                scope_archive_slugs=[],
                resolved_scope_file_count=self.repository.count_files_for_user(
                    user_id=safe_user_id,
                    include_shared=True,
                ),
                scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                ignored_inferred_scope=False,
            )

        if (
            not requested_file_ids
            and not candidate_codes
            and not candidate_file_names
            and not candidate_archive_slugs
            and self._question_references_previous_scope(question)
            and (conversation_scope_file_ids or conversation_scope_archive_slugs)
        ):
            resolved_file_ids = list(conversation_scope_file_ids)
            if not resolved_file_ids and conversation_scope_archive_slugs:
                resolved_file_ids = self.repository.list_file_ids_for_archive_slugs(
                    user_id=safe_user_id,
                    archive_slugs=conversation_scope_archive_slugs,
                    include_shared=True,
                )
            accessible_file_ids = self.repository.filter_file_ids_for_user(
                user_id=safe_user_id,
                file_ids=resolved_file_ids,
                include_shared=True,
            ) if resolved_file_ids else []
            if accessible_file_ids:
                if not conversation_scope_archive_slugs:
                    get_archive_slug_map = getattr(self.repository, "get_archive_slug_map_for_file_ids", None)
                    if callable(get_archive_slug_map):
                        archive_slug_map = get_archive_slug_map(
                            user_id=safe_user_id,
                            file_ids=accessible_file_ids,
                            include_shared=True,
                        )
                        conversation_scope_archive_slugs = self._normalize_archive_slugs(
                            list(archive_slug_map.values())
                        )
                return ScopeResolution(
                    file_ids=accessible_file_ids,
                    scope_origin="conversation",
                    scope_document_codes=[],
                    scope_archive_slugs=conversation_scope_archive_slugs,
                    resolved_scope_file_count=len(accessible_file_ids),
                    scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                    ignored_inferred_scope=False,
                )

        if candidate_archive_slugs:
            available_archive_slugs = self.repository.list_known_archive_slugs_for_user(
                user_id=safe_user_id,
                include_shared=True,
            )
            normalized_archive_map = {
                canonicalize_file_key(archive_slug).lower(): canonicalize_file_key(archive_slug)
                for archive_slug in available_archive_slugs
                if canonicalize_file_key(archive_slug)
            }
            matched_archive_slugs = [
                normalized_archive_map[candidate.lower()]
                for candidate in candidate_archive_slugs
                if candidate.lower() in normalized_archive_map
            ]
            missing_archive_slugs = [
                candidate
                for candidate in candidate_archive_slugs
                if candidate.lower() not in normalized_archive_map
            ]
            if missing_archive_slugs:
                joined_archive_slugs = ", ".join(missing_archive_slugs)
                raise ScopeResolutionError(
                    f"No accessible documents were found for archive_slug(s): {joined_archive_slugs}.",
                    status_code=404,
                )
            resolved_file_ids = self.repository.list_file_ids_for_archive_slugs(
                user_id=safe_user_id,
                archive_slugs=matched_archive_slugs,
                include_shared=True,
            )
            if not resolved_file_ids:
                joined_archive_slugs = ", ".join(matched_archive_slugs)
                raise ScopeResolutionError(
                    f"No accessible documents were found for archive_slug(s): {joined_archive_slugs}.",
                    status_code=404,
                )
            return ScopeResolution(
                file_ids=resolved_file_ids,
                scope_origin="metadata",
                scope_document_codes=[],
                scope_archive_slugs=matched_archive_slugs,
                resolved_scope_file_count=len(resolved_file_ids),
                scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                ignored_inferred_scope=bool(candidate_codes),
            )

        if candidate_file_names:
            resolved_file_ids = self.repository.list_file_ids_for_input_filenames(
                user_id=safe_user_id,
                file_names=candidate_file_names,
                include_shared=True,
            )
            if not resolved_file_ids:
                joined_file_names = ", ".join(candidate_file_names)
                raise ScopeResolutionError(
                    f"No accessible documents were found for input filename(s): {joined_file_names}.",
                    status_code=404,
                )
            return ScopeResolution(
                file_ids=resolved_file_ids,
                scope_origin="manual",
                scope_document_codes=[],
                scope_archive_slugs=[],
                resolved_scope_file_count=len(resolved_file_ids),
                scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                ignored_inferred_scope=bool(candidate_codes),
            )

        if not candidate_codes:
            return ScopeResolution(
                file_ids=[],
                scope_origin="global",
                scope_document_codes=[],
                scope_archive_slugs=[],
                resolved_scope_file_count=self.repository.count_files_for_user(
                    user_id=safe_user_id,
                    include_shared=True,
                ),
                scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                ignored_inferred_scope=False,
            )

        available_codes = self.repository.list_distinct_document_codes_for_user(
            user_id=safe_user_id,
            include_shared=True,
        )
        normalized_map = {
            normalize_document_code(code): normalize_document_code(code)
            for code in available_codes
            if normalize_document_code(code)
        }
        matched_codes = [code for code in candidate_codes if code in normalized_map]
        missing_codes = [code for code in candidate_codes if code not in normalized_map]

        if missing_codes:
            joined_codes = ", ".join(missing_codes)
            raise ScopeResolutionError(
                f"No accessible documents were found for code(s): {joined_codes}.",
                status_code=404,
            )

        if matched_codes:
            resolved_file_ids = self.repository.list_file_ids_for_document_codes(
                user_id=safe_user_id,
                document_codes=matched_codes,
                include_shared=True,
            )
            if not resolved_file_ids:
                joined_codes = ", ".join(matched_codes)
                raise ScopeResolutionError(
                    f"No accessible documents were found for code(s): {joined_codes}.",
                    status_code=404,
                )
            return ScopeResolution(
                file_ids=resolved_file_ids,
                scope_origin="inferred",
                scope_document_codes=matched_codes,
                scope_archive_slugs=[],
                resolved_scope_file_count=len(resolved_file_ids),
                scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
                ignored_inferred_scope=False,
            )

        return ScopeResolution(
            file_ids=[],
            scope_origin="global",
            scope_document_codes=[],
            scope_archive_slugs=[],
            resolved_scope_file_count=self.repository.count_files_for_user(
                user_id=safe_user_id,
                include_shared=True,
            ),
            scope_resolution_ms=max(0, int((time.perf_counter() - started_at) * 1000)),
            ignored_inferred_scope=False,
        )
