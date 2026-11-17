"""Hybrid retrieval service with per-page multimodal fusion."""

from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
import time
import unicodedata

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.core.config import get_settings
from apps.backend.app.core.database import DatabaseManager
from apps.backend.app.rag.embedding_service import EmbeddingService
from apps.backend.app.rag.reranker_service import HybridLocalOnnxRerankService
from apps.backend.app.rag.scope_resolver import extract_candidate_archive_slugs_from_question
from apps.backend.app.rag.retrieval.oracle_vector_search import (
    OracleDocumentSearchResult,
    OracleVectorSearchResult,
    OracleVectorStore,
)
from apps.backend.app.repositories.file_repository import FileRepository
from apps.backend.app.services.metadata_keys import canonicalize_file_key

TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
EXPLICIT_FILE_REFERENCE_PATTERN = re.compile(
    r"(?<!\S)(?:[\w.-]+(?:\s\([\w.-]+\))?)\.pdf\b",
    re.IGNORECASE | re.UNICODE,
)
RRF_K = 60
MAX_CANDIDATES = 2000
MMR_LAMBDA = 0.75
MMR_POOL_MULTIPLIER = 3
MAX_MMR_POOL = 1200
LOW_OCR_CONFIDENCE_THRESHOLD = 0.78
IMAGE_SCORE_ADVANTAGE_FACTOR = 1.12

VISUAL_HINT_TERMS = (
    "tabla",
    "tablas",
    "table",
    "tables",
    "firma",
    "firmas",
    "signature",
    "signatures",
    "sello",
    "stamp",
    "diagrama",
    "diagram",
    "grafico",
    "chart",
    "imagen",
    "image",
    "visual",
    "columna",
    "column",
    "fila",
    "row",
)

QUERY_CONCEPT_STOPWORDS = {
    "a",
    "al",
    "an",
    "and",
    "archivo",
    "archivos",
    "con",
    "contiene",
    "contienen",
    "cual",
    "cuales",
    "de",
    "del",
    "documento",
    "documentos",
    "el",
    "en",
    "esta",
    "este",
    "habla",
    "hablan",
    "indica",
    "indican",
    "la",
    "lista",
    "listar",
    "las",
    "los",
    "menciona",
    "mencionan",
    "o",
    "or",
    "para",
    "por",
    "que",
    "se",
    "sobre",
    "the",
    "un",
    "una",
    "y",
}


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    compact = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    compact = compact.lower()
    compact = re.sub(r"[_/\\\-]+", " ", compact)
    compact = re.sub(r"[^\w\s]+", " ", compact)
    return " ".join(compact.split())


def tokenize_text(value: str) -> list[str]:
    return TOKEN_PATTERN.findall(_normalize_text(value))


def token_jaccard_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def extract_query_concepts(question: str) -> list[str]:
    seen: set[str] = set()
    concepts: list[str] = []
    for token in tokenize_text(question):
        if len(token) < 3 or token in QUERY_CONCEPT_STOPWORDS or token in seen:
            continue
        seen.add(token)
        concepts.append(token)
    return concepts


def token_match_keys(token: str) -> set[str]:
    normalized = _normalize_text(token)
    if not normalized or " " in normalized:
        return set()
    keys = {normalized}
    if len(normalized) > 4 and normalized.endswith("s"):
        keys.add(normalized[:-1])
    for suffix in (
        "aciones",
        "acion",
        "ando",
        "iendo",
        "ados",
        "adas",
        "idos",
        "idas",
        "ado",
        "ada",
        "ido",
        "ida",
        "ar",
        "er",
        "ir",
    ):
        if len(normalized) > len(suffix) + 3 and normalized.endswith(suffix):
            keys.add(normalized[: -len(suffix)])
            break
    if len(normalized) > 5 and normalized[-1] in {"a", "e", "o"}:
        keys.add(normalized[:-1])
    return {key for key in keys if len(key) >= 3}


def build_token_match_index(tokens: list[str]) -> set[str]:
    indexed: set[str] = set()
    for token in tokens:
        indexed.update(token_match_keys(token))
    return indexed


def token_keys_are_related(left: str, right: str) -> bool:
    left_value = _normalize_text(left)
    right_value = _normalize_text(right)
    if left_value == right_value:
        return True
    if len(left_value) < 5 or len(right_value) < 5:
        return False
    if left_value.endswith(right_value) or right_value.endswith(left_value):
        return True
    suffix_len = 0
    for index in range(1, min(len(left_value), len(right_value)) + 1):
        if left_value[-index] != right_value[-index]:
            break
        suffix_len = index
    if suffix_len >= 4 and suffix_len >= min(len(left_value), len(right_value)) - 1:
        return True
    length_ratio = min(len(left_value), len(right_value)) / max(len(left_value), len(right_value))
    return length_ratio >= 0.78 and SequenceMatcher(None, left_value, right_value).ratio() >= 0.90


def concept_match_count(query_concepts: list[str], evidence_tokens: list[str]) -> int:
    if not query_concepts or not evidence_tokens:
        return 0
    evidence_index = build_token_match_index(evidence_tokens)
    matched = 0
    for concept in query_concepts:
        concept_keys = token_match_keys(concept)
        if concept_keys & evidence_index:
            matched += 1
            continue
        if any(
            token_keys_are_related(concept_key, evidence_key)
            for concept_key in concept_keys
            for evidence_key in evidence_index
        ):
            matched += 1
    return matched


def concept_coverage_score(query_concepts: list[str], evidence_tokens: list[str]) -> float:
    if not query_concepts or not evidence_tokens:
        return 0.0
    matched = concept_match_count(query_concepts, evidence_tokens)
    return float(matched / max(1, len(query_concepts)))


def question_requires_visual_grounding(question: str) -> bool:
    tokens = set(tokenize_text(question))
    return any(term in tokens for term in VISUAL_HINT_TERMS)


def question_requests_representative_details(question: str) -> bool:
    tokens = set(tokenize_text(question))
    return any(
        term in tokens
        for term in (
            "persona",
            "personas",
            "representante",
            "representantes",
            "representacion",
            "facultad",
            "facultades",
            "firmar",
            "firma",
            "comparecen",
            "comparece",
            "consentir",
        )
    )


def question_requests_full_document_coverage(question: str) -> bool:
    normalized = _normalize_text(question)
    if not normalized:
        return False
    full_document_phrases = (
        "todo el documento",
        "todo este documento",
        "todo ese documento",
        "documento completo",
        "analiza todo",
        "revisa todo",
        "revision completa",
        "lista completa",
        "todos los campos",
        "cada campo",
        "campos mas importantes",
        "campos clave",
        "clave valor",
        "key value",
    )
    return any(phrase in normalized for phrase in full_document_phrases)


def extract_explicit_file_references(question: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for match in EXPLICIT_FILE_REFERENCE_PATTERN.finditer(str(question or "")):
        candidate = str(match.group(0) or "").strip().strip("`\"'")
        if not candidate:
            continue
        normalized = _normalize_text(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(candidate)
    return ordered


@dataclass(slots=True)
class CandidateRecord:
    evidence: EvidenceItem
    text: str = ""
    tokens: list[str] = field(default_factory=list)
    text_summary: str = ""
    image_summary: str = ""
    text_score: float | None = None
    image_score: float | None = None
    lexical_score: float | None = None
    fused_score: float = 0.0


@dataclass(slots=True)
class DocumentCandidateRecord:
    file_id: int
    file_name: str
    file_code: str | None
    summary_text: str = ""
    search_text: str = ""
    dense_score: float | None = None
    lexical_score: float | None = None
    fused_score: float = 0.0


@dataclass(slots=True)
class RetrievalResult:
    evidence: list[EvidenceItem]
    telemetry: dict[str, object] = field(default_factory=dict)


class RetrievalPipelineService:
    def __init__(
        self,
        *,
        db_manager: DatabaseManager | None = None,
        embedding_service: EmbeddingService,
        rerank_service: HybridLocalOnnxRerankService | None = None,
    ) -> None:
        self.db_manager = db_manager
        self.embedding_service = embedding_service
        self.repository = FileRepository(db_manager) if db_manager is not None else None
        self.settings = get_settings()
        self.oracle_vector_store = OracleVectorStore(db_manager) if db_manager is not None else None
        self.rerank_service = rerank_service or HybridLocalOnnxRerankService(self.settings)

    def warmup(self) -> None:
        self.rerank_service.ensure_available()

    def _resolve_runtime_int(self, key: str, default_value: int, *, minimum: int = 1) -> int:
        resolved = int(default_value)
        runtime_reader = getattr(self.settings, "_runtime_config_int", None)
        if callable(runtime_reader):
            try:
                resolved = int(runtime_reader(key, int(default_value)))
            except Exception:
                resolved = int(default_value)
        return max(int(minimum), resolved)

    @staticmethod
    def _elapsed_ms(started_at: float) -> int:
        return max(0, int((time.perf_counter() - started_at) * 1000))

    @staticmethod
    def _is_scoped_origin(scope_origin: str) -> bool:
        return str(scope_origin or "").strip().lower() in {"manual", "inferred", "metadata", "conversation"}

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

    def _resolve_doc_shortlist_limit(self, *, question_class: str, scope_origin: str) -> int:
        if question_class == "analytics":
            return 0
        if self._is_scoped_origin(scope_origin):
            return self._resolve_runtime_int("rag.retrieval.doc_shortlist_scoped", 12, minimum=1)
        return self._resolve_runtime_int("rag.retrieval.doc_shortlist_global", 20, minimum=1)

    def _shortlist_documents(
        self,
        *,
        question: str,
        query_vector: list[float],
        user_id: int | None,
        file_ids: list[int] | None,
        priority_file_ids: list[int] | None = None,
        shortlist_limit: int,
    ) -> list[int]:
        if user_id is None:
            return [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        safe_file_ids = [int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0]
        priority_ids = self._dedupe_positive_ids(priority_file_ids)
        if safe_file_ids and priority_ids:
            allowed = set(safe_file_ids)
            priority_ids = [file_id for file_id in priority_ids if file_id in allowed]
        if shortlist_limit <= 0:
            return self._dedupe_positive_ids(priority_ids + safe_file_ids)
        if safe_file_ids and len(safe_file_ids) <= shortlist_limit:
            return self._dedupe_positive_ids(priority_ids + safe_file_ids)[:shortlist_limit]
        dense_candidates = self._retrieve_document_dense_candidates(
            query_vector=query_vector,
            user_id=user_id,
            file_ids=safe_file_ids or None,
            candidate_limit=max(shortlist_limit * 2, shortlist_limit),
        )
        lexical_candidates = self._retrieve_document_lexical_candidates(
            question=question,
            user_id=user_id,
            file_ids=safe_file_ids or None,
            candidate_limit=max(shortlist_limit * 2, shortlist_limit),
        )
        fused = self._fuse_document_candidates(
            dense_candidates=dense_candidates,
            lexical_candidates=lexical_candidates,
            limit=shortlist_limit,
        )
        shortlisted = [int(item.file_id) for item in fused[:shortlist_limit] if int(item.file_id) > 0]
        if safe_file_ids:
            shortlisted = [file_id for file_id in shortlisted if file_id in set(safe_file_ids)]
        shortlisted = self._dedupe_positive_ids(priority_ids + shortlisted)
        return shortlisted[:shortlist_limit] or safe_file_ids

    def _resolve_page_candidate_limit(
        self,
        *,
        question_class: str,
        scope_origin: str,
        safe_top_k: int,
        max_candidates: int,
        candidate_k: int | None,
    ) -> int:
        if candidate_k is not None:
            return min(max(1, int(candidate_k)), max_candidates)
        if question_class == "analytics":
            base = safe_top_k
        else:
            if self._is_scoped_origin(scope_origin):
                base = self._resolve_runtime_int(
                    "rag.retrieval.page_pool_scoped",
                    36,
                    minimum=safe_top_k,
                )
            else:
                base = self._resolve_runtime_int(
                    "rag.retrieval.page_pool_global",
                    60,
                    minimum=safe_top_k,
                )
        return min(max(base, safe_top_k), max_candidates)

    def _resolve_rerank_pool_limit(self, *, question_class: str, scope_origin: str) -> int:
        if question_class == "analytics":
            return 8
        if self._is_scoped_origin(scope_origin):
            return self._resolve_runtime_int("rag.retrieval.rerank_scoped", 24, minimum=1)
        return self._resolve_runtime_int("rag.retrieval.rerank_global", 32, minimum=1)

    def _metadata_prefilter_file_ids(
        self,
        *,
        question: str,
        user_id: int | None,
        file_ids: list[int] | None,
        limit: int,
    ) -> list[int]:
        if self.repository is None or user_id is None:
            return []
        safe_limit = max(2, int(limit))
        matches = self.repository.search_file_ids_by_metadata_query(
            user_id=user_id,
            query_text=question,
            file_ids=file_ids,
            limit=safe_limit,
            include_shared=True,
        )
        concept_matches = self._metadata_concept_file_ids(
            question=question,
            user_id=user_id,
            file_ids=file_ids,
            limit=safe_limit,
        )
        return self._dedupe_positive_ids(concept_matches + matches)[:safe_limit]

    def _metadata_concept_file_ids(
        self,
        *,
        question: str,
        user_id: int | None,
        file_ids: list[int] | None,
        limit: int,
    ) -> list[int]:
        if self.repository is None or user_id is None:
            return []
        query_concepts = extract_query_concepts(question)
        if not query_concepts:
            return []
        safe_file_ids = self._dedupe_positive_ids(file_ids)
        if safe_file_ids:
            metadata_loader = getattr(self.repository, "get_archive_metadata_for_file_ids", None)
            if not callable(metadata_loader):
                return []
            rows = metadata_loader(
                user_id=int(user_id),
                file_ids=safe_file_ids,
                include_shared=True,
            )
        else:
            metadata_loader = getattr(self.repository, "list_archive_metadata_for_user", None)
            if not callable(metadata_loader):
                return []
            rows = metadata_loader(user_id=int(user_id), include_shared=True)
        if not rows:
            return []

        minimum_matches = 1 if len(query_concepts) == 1 else 2
        scored_archive_slugs: list[tuple[str, float, int]] = []
        seen_slugs: set[str] = set()
        for row in rows:
            archive_slug = str(row.get("archive_slug") or "").strip()
            normalized_slug = self._normalize_archive_slug(archive_slug)
            if not normalized_slug or normalized_slug in seen_slugs:
                continue
            text = " ".join(
                str(row.get(key) or "")
                for key in ("archive_slug", "metadata_search_text", "metadata_json")
            )
            tokens = tokenize_text(text)
            matched = concept_match_count(query_concepts, tokens)
            if matched < minimum_matches:
                continue
            coverage = matched / max(1, len(query_concepts))
            scored_archive_slugs.append((archive_slug, float(coverage), int(matched)))
            seen_slugs.add(normalized_slug)

        if not scored_archive_slugs:
            return []
        scored_archive_slugs.sort(key=lambda item: (item[2], item[1], item[0]), reverse=True)
        selected_slugs = [item[0] for item in scored_archive_slugs[: max(1, int(limit))]]

        archive_id_loader = getattr(self.repository, "list_file_ids_for_archive_slugs", None)
        archive_map_loader = getattr(self.repository, "get_archive_slug_map_for_file_ids", None)
        if not callable(archive_id_loader):
            return []
        expanded_ids = self._dedupe_positive_ids(
            archive_id_loader(
                user_id=int(user_id),
                archive_slugs=selected_slugs,
                include_shared=True,
            )
        )
        if safe_file_ids:
            allowed = set(safe_file_ids)
            expanded_ids = [file_id for file_id in expanded_ids if file_id in allowed]
        if not expanded_ids:
            return []
        if not callable(archive_map_loader):
            return expanded_ids[: max(1, int(limit))]

        archive_map = archive_map_loader(
            user_id=int(user_id),
            file_ids=expanded_ids,
            include_shared=True,
        )
        ordered: list[int] = []
        for archive_slug in selected_slugs:
            normalized_slug = self._normalize_archive_slug(archive_slug)
            for file_id in expanded_ids:
                if file_id in ordered:
                    continue
                if self._normalize_archive_slug(archive_map.get(int(file_id))) == normalized_slug:
                    ordered.append(int(file_id))
        for file_id in expanded_ids:
            if file_id not in ordered:
                ordered.append(int(file_id))
        return ordered[: max(1, int(limit))]

    def _resolve_explicit_file_scope(
        self,
        *,
        question: str,
        user_id: int | None,
        file_ids: list[int] | None,
    ) -> tuple[list[int], list[str]]:
        if self.repository is None or user_id is None:
            return [], []
        explicit_refs = extract_explicit_file_references(question)
        if not explicit_refs:
            return [], []
        matched_file_ids = self.repository.list_file_ids_for_input_filenames(
            user_id=user_id,
            file_names=explicit_refs,
            file_ids=file_ids,
            include_shared=True,
        )
        return self._dedupe_positive_ids(matched_file_ids), explicit_refs

    @staticmethod
    def _normalize_archive_slug(value: str | None) -> str:
        return canonicalize_file_key(str(value or "")).lower()

    @classmethod
    def _normalize_archive_slug_order(cls, archive_slugs: list[str] | None) -> list[str]:
        seen: set[str] = set()
        ordered: list[str] = []
        for raw_value in list(archive_slugs or []):
            normalized = cls._normalize_archive_slug(raw_value)
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _resolve_explicit_archive_scope(
        self,
        *,
        question: str,
        archive_slugs: list[str] | None,
        user_id: int | None,
        file_ids: list[int] | None,
    ) -> tuple[list[str], dict[int, str], list[int]]:
        if self.repository is None or user_id is None:
            return [], {}, []
        explicit_archive_refs = [
            canonicalize_file_key(str(value or "").strip())
            for value in list(archive_slugs or [])
            if canonicalize_file_key(str(value or "").strip())
        ] or extract_candidate_archive_slugs_from_question(question)
        if not explicit_archive_refs:
            return [], {}, []
        scoped_file_ids = self._dedupe_positive_ids(file_ids)
        if not scoped_file_ids:
            scoped_file_ids = self.repository.list_file_ids_for_archive_slugs(
                user_id=user_id,
                archive_slugs=explicit_archive_refs,
                include_shared=True,
            )
        archive_slug_map = self.repository.get_archive_slug_map_for_file_ids(
            user_id=user_id,
            file_ids=scoped_file_ids,
            include_shared=True,
        )
        if not archive_slug_map:
            return [], {}, scoped_file_ids
        available_archive_map = {
            self._normalize_archive_slug(archive_slug): canonicalize_file_key(archive_slug)
            for archive_slug in archive_slug_map.values()
            if self._normalize_archive_slug(archive_slug)
        }
        matched_archive_slugs: list[str] = []
        for archive_slug in explicit_archive_refs:
            normalized = self._normalize_archive_slug(archive_slug)
            resolved = available_archive_map.get(normalized)
            if not resolved or normalized in {
                self._normalize_archive_slug(item) for item in matched_archive_slugs
            }:
                continue
            matched_archive_slugs.append(resolved)
        return matched_archive_slugs, archive_slug_map, scoped_file_ids

    @classmethod
    def _rebalance_file_ids_by_archive_scope(
        cls,
        *,
        ranked_file_ids: list[int],
        file_archive_map: dict[int, str],
        preferred_archive_slugs: list[str],
        limit: int,
    ) -> list[int]:
        safe_limit = max(1, int(limit))
        archive_order = cls._normalize_archive_slug_order(preferred_archive_slugs)
        if not archive_order:
            return cls._dedupe_positive_ids(ranked_file_ids)[:safe_limit]

        deduped_file_ids = cls._dedupe_positive_ids(ranked_file_ids)
        if not deduped_file_ids:
            return []

        buckets: dict[str, list[int]] = {archive_slug: [] for archive_slug in archive_order}
        for file_id in deduped_file_ids:
            archive_slug = cls._normalize_archive_slug(file_archive_map.get(int(file_id)))
            if archive_slug and archive_slug in buckets:
                buckets[archive_slug].append(int(file_id))

        selected: list[int] = []
        while len(selected) < safe_limit:
            added_this_round = False
            for archive_slug in archive_order:
                bucket = buckets.get(archive_slug) or []
                if not bucket:
                    continue
                selected.append(bucket.pop(0))
                added_this_round = True
                if len(selected) >= safe_limit:
                    break
            if not added_this_round:
                break

        seen_selected = set(selected)
        leftovers = [file_id for file_id in deduped_file_ids if file_id not in seen_selected]
        return (selected + leftovers)[:safe_limit]

    @staticmethod
    def _evidence_identity(item: EvidenceItem) -> tuple[int, int]:
        return (int(item.file_id), int(item.page_id))

    @classmethod
    def _prioritize_candidate_pool_by_archive_scope(
        cls,
        *,
        candidates: list[CandidateRecord],
        preferred_archive_slugs: list[str],
        file_archive_map: dict[int, str],
        min_pages_per_archive: int,
    ) -> list[CandidateRecord]:
        archive_order = cls._normalize_archive_slug_order(preferred_archive_slugs)
        if not archive_order:
            return list(candidates)

        quota = max(1, int(min_pages_per_archive or 0))
        preserved: list[CandidateRecord] = []
        preserved_keys: set[tuple[int, int]] = set()
        for _ in range(quota):
            for archive_slug in archive_order:
                best_candidate: CandidateRecord | None = None
                best_key: tuple[int, int] | None = None
                for candidate in candidates:
                    key = (int(candidate.evidence.file_id), int(candidate.evidence.page_id))
                    if key in preserved_keys:
                        continue
                    candidate_archive_slug = cls._normalize_archive_slug(
                        file_archive_map.get(int(candidate.evidence.file_id))
                    )
                    if candidate_archive_slug != archive_slug:
                        continue
                    if best_candidate is None or float(candidate.fused_score) > float(best_candidate.fused_score):
                        best_candidate = candidate
                        best_key = key
                if best_candidate is None or best_key is None:
                    continue
                preserved.append(best_candidate)
                preserved_keys.add(best_key)

        ordered: list[CandidateRecord] = []
        seen_ordered: set[tuple[int, int]] = set()
        for collection in (preserved, candidates):
            for item in collection:
                key = (int(item.evidence.file_id), int(item.evidence.page_id))
                if key in seen_ordered:
                    continue
                seen_ordered.add(key)
                ordered.append(item)
        return ordered

    @classmethod
    def _prioritize_final_evidence_by_archive_scope(
        cls,
        *,
        reranked: list[EvidenceItem],
        candidate_pool: list[EvidenceItem],
        preferred_archive_slugs: list[str],
        file_archive_map: dict[int, str],
        min_pages_per_archive: int,
        desired_final: int,
    ) -> list[EvidenceItem]:
        safe_limit = max(1, int(desired_final))
        archive_order = cls._normalize_archive_slug_order(preferred_archive_slugs)
        if not archive_order:
            return list(reranked[:safe_limit])

        quota = max(1, int(min_pages_per_archive or 0))
        combined = list(reranked)
        seen_combined = {cls._evidence_identity(item) for item in combined}
        for item in candidate_pool:
            key = cls._evidence_identity(item)
            if key in seen_combined:
                continue
            seen_combined.add(key)
            combined.append(item)

        preserved: list[EvidenceItem] = []
        preserved_keys: set[tuple[int, int]] = set()
        for _ in range(quota):
            for archive_slug in archive_order:
                best_item: EvidenceItem | None = None
                best_key: tuple[int, int] | None = None
                for item in combined:
                    key = cls._evidence_identity(item)
                    if key in preserved_keys:
                        continue
                    item_archive_slug = cls._normalize_archive_slug(file_archive_map.get(int(item.file_id)))
                    if item_archive_slug != archive_slug:
                        continue
                    if best_item is None or float(item.score) > float(best_item.score):
                        best_item = item
                        best_key = key
                if best_item is None or best_key is None:
                    continue
                preserved.append(best_item)
                preserved_keys.add(best_key)

        ordered: list[EvidenceItem] = []
        seen_ordered: set[tuple[int, int]] = set()
        for collection in (preserved, reranked, candidate_pool):
            for item in collection:
                key = cls._evidence_identity(item)
                if key in seen_ordered:
                    continue
                seen_ordered.add(key)
                ordered.append(item)
                if len(ordered) >= safe_limit:
                    return ordered[:safe_limit]
        return ordered[:safe_limit]

    def retrieve(
        self,
        *,
        question: str,
        user_id: int | None = None,
        file_ids: list[int] | None = None,
        archive_slugs: list[str] | None = None,
        top_k: int = 5,
        candidate_k: int | None = None,
        min_pages_per_selected_doc: int = 0,
        summary_mode: str = "default",
        question_class: str = "extractive",
        scope_origin: str = "global",
    ) -> RetrievalResult:
        total_started_at = time.perf_counter()
        safe_top_k = max(1, int(top_k))
        max_candidates = self._resolve_runtime_int("rag.retrieval.max_candidates", MAX_CANDIDATES, minimum=40)
        safe_summary_mode = str(summary_mode or "default").strip().lower()
        safe_file_ids = self._dedupe_positive_ids(file_ids)
        safe_user_id = int(user_id) if user_id is not None else None
        safe_min_pages_per_doc = max(0, int(min_pages_per_selected_doc or 0))
        full_document_coverage_requested = question_requests_full_document_coverage(question)
        full_document_page_limit = min(
            self._resolve_runtime_int("rag.retrieval.full_document_page_limit", 80, minimum=1),
            240,
        )
        if question_requests_representative_details(question):
            safe_min_pages_per_doc = max(safe_min_pages_per_doc, 2)
        effective_scope_origin = str(scope_origin or "global").strip().lower() or "global"
        adjacent_page_candidates_count = 0

        query_embedding_started = time.perf_counter()
        query_vector = self.embedding_service.embed_query_text(text=question)
        query_embedding_ms = self._elapsed_ms(query_embedding_started)

        doc_shortlist_limit = self._resolve_doc_shortlist_limit(
            question_class=question_class,
            scope_origin=effective_scope_origin,
        )
        explicit_archive_requested = bool(
            self._normalize_archive_slug_order(archive_slugs)
            or extract_candidate_archive_slugs_from_question(question)
        )
        metadata_prefilter_started = time.perf_counter()
        metadata_prefilter_ids = (
            []
            if explicit_archive_requested
            else self._metadata_prefilter_file_ids(
                question=question,
                user_id=safe_user_id,
                file_ids=safe_file_ids or None,
                limit=max(doc_shortlist_limit * 3, safe_top_k * 4, 40),
            )
        )
        metadata_prefilter_ms = self._elapsed_ms(metadata_prefilter_started)
        base_file_ids = list(safe_file_ids)
        metadata_prefilter_scopes_retrieval = bool(
            metadata_prefilter_ids
            and (
                safe_file_ids
                or question_class == "metadata_comparison"
                or self._is_scoped_origin(effective_scope_origin)
            )
        )
        if metadata_prefilter_scopes_retrieval:
            base_file_ids = list(metadata_prefilter_ids)
            if not safe_file_ids:
                effective_scope_origin = "metadata"

        explicit_file_scope_started = time.perf_counter()
        explicit_file_ids, explicit_file_refs = self._resolve_explicit_file_scope(
            question=question,
            user_id=safe_user_id,
            file_ids=base_file_ids or safe_file_ids or None,
        )
        explicit_file_scope_ms = self._elapsed_ms(explicit_file_scope_started)
        if explicit_file_ids:
            base_file_ids = list(explicit_file_ids)
            safe_min_pages_per_doc = max(safe_min_pages_per_doc, 1)
            if full_document_coverage_requested:
                safe_min_pages_per_doc = max(safe_min_pages_per_doc, full_document_page_limit)
                safe_top_k = max(safe_top_k, len(explicit_file_ids) * safe_min_pages_per_doc)

        explicit_archive_scope_started = time.perf_counter()
        explicit_archive_slugs, archive_slug_map, resolved_archive_file_ids = self._resolve_explicit_archive_scope(
            question=question,
            archive_slugs=archive_slugs,
            user_id=safe_user_id,
            file_ids=base_file_ids or safe_file_ids or None,
        )
        explicit_archive_scope_ms = self._elapsed_ms(explicit_archive_scope_started)
        archive_scope_active = bool(explicit_archive_slugs)
        if resolved_archive_file_ids and not base_file_ids:
            base_file_ids = list(resolved_archive_file_ids)
            if not safe_file_ids:
                effective_scope_origin = "metadata"

        safe_candidate_k = self._resolve_page_candidate_limit(
            question_class=question_class,
            scope_origin=effective_scope_origin,
            safe_top_k=safe_top_k,
            max_candidates=max_candidates,
            candidate_k=candidate_k,
        )
        rerank_pool_limit = self._resolve_rerank_pool_limit(
            question_class=question_class,
            scope_origin=effective_scope_origin,
        )
        max_mmr_pool = min(
            self._resolve_runtime_int("rag.retrieval.max_mmr_pool", MAX_MMR_POOL, minimum=safe_top_k),
            max(rerank_pool_limit, safe_top_k),
        )

        doc_search_started = time.perf_counter()
        shortlist_bypassed_for_archive_scope = False
        if archive_scope_active and base_file_ids and len(base_file_ids) <= max(doc_shortlist_limit * 2, 24):
            shortlisted_file_ids = []
            effective_file_ids = list(base_file_ids)
            shortlist_bypassed_for_archive_scope = True
        else:
            shortlisted_file_ids = self._shortlist_documents(
                question=question,
                query_vector=query_vector,
                user_id=safe_user_id,
                file_ids=base_file_ids or None,
                priority_file_ids=metadata_prefilter_ids,
                shortlist_limit=doc_shortlist_limit,
            )
            if archive_scope_active and archive_slug_map:
                ranked_candidates = list(shortlisted_file_ids)
                for file_id in list(base_file_ids or []):
                    if int(file_id) not in ranked_candidates:
                        ranked_candidates.append(int(file_id))
                shortlisted_file_ids = self._rebalance_file_ids_by_archive_scope(
                    ranked_file_ids=ranked_candidates,
                    file_archive_map=archive_slug_map,
                    preferred_archive_slugs=explicit_archive_slugs,
                    limit=doc_shortlist_limit,
                )
            effective_file_ids = shortlisted_file_ids or base_file_ids
        doc_search_ms = self._elapsed_ms(doc_search_started)

        use_image_retrieval = bool(
            question_class == "visual_consistency"
            or question_requires_visual_grounding(question)
        )

        page_search_started = time.perf_counter()
        text_candidates = self._retrieve_dense_candidates(
            query_vector=query_vector,
            user_id=safe_user_id,
            file_ids=effective_file_ids or None,
            modality="ocr_text",
            candidate_limit=safe_candidate_k,
        )
        image_candidates = (
            self._retrieve_dense_candidates(
                query_vector=query_vector,
                user_id=safe_user_id,
                file_ids=effective_file_ids or None,
                modality="page_image",
                candidate_limit=safe_candidate_k,
            )
            if use_image_retrieval
            else []
        )
        lexical_candidates = self._retrieve_lexical_candidates(
            question=question,
            user_id=safe_user_id,
            file_ids=effective_file_ids or None,
            candidate_limit=safe_candidate_k,
        )
        fused_candidates = self._fuse_candidates(
            question=question,
            text_candidates=text_candidates,
            image_candidates=image_candidates,
            lexical_candidates=lexical_candidates,
        )
        candidate_pool = self._select_diverse_candidates(
            candidates=fused_candidates,
            top_k=safe_top_k,
            max_mmr_pool=max_mmr_pool,
        )
        if effective_file_ids and safe_min_pages_per_doc > 0:
            evidence_expansion_candidates = self._build_per_doc_evidence_expansion_candidates(
                question=question,
                user_id=safe_user_id,
                selected_file_ids=effective_file_ids,
                max_pages_per_doc=safe_min_pages_per_doc if full_document_coverage_requested else 3,
                preserve_page_order=full_document_coverage_requested,
            )
            candidate_pool = self._enforce_per_document_quota(
                candidates=candidate_pool,
                fused_candidates=fused_candidates,
                evidence_expansion_candidates=evidence_expansion_candidates,
                selected_file_ids=effective_file_ids,
                min_pages_per_doc=safe_min_pages_per_doc,
            )
        if question_requests_representative_details(question):
            adjacent_page_candidates = self._build_adjacent_page_candidates(
                user_id=safe_user_id,
                selected_evidence=[item.evidence for item in candidate_pool],
                selected_file_ids=effective_file_ids,
            )
            adjacent_page_candidates_count = len(adjacent_page_candidates)
            seen_candidate_pages = {
                (int(item.evidence.file_id), int(item.evidence.page_id))
                for item in candidate_pool
            }
            for candidate in adjacent_page_candidates:
                key = (int(candidate.evidence.file_id), int(candidate.evidence.page_id))
                if key in seen_candidate_pages:
                    continue
                seen_candidate_pages.add(key)
                candidate_pool.append(candidate)
        if archive_scope_active and archive_slug_map:
            candidate_pool = self._prioritize_candidate_pool_by_archive_scope(
                candidates=candidate_pool,
                preferred_archive_slugs=explicit_archive_slugs,
                file_archive_map=archive_slug_map,
                min_pages_per_archive=1,
            )
        page_search_ms = self._elapsed_ms(page_search_started)

        desired_final = safe_top_k
        if safe_summary_mode == "per_document" and effective_file_ids and safe_min_pages_per_doc > 0:
            desired_final = max(safe_top_k, len(effective_file_ids) * safe_min_pages_per_doc)

        rerank_started = time.perf_counter()
        rerank_input = list(candidate_pool[: max(rerank_pool_limit, desired_final)])
        should_bypass_rerank = bool(
            (question_class == "metadata_comparison" and len(rerank_input) <= 12)
            or (self._is_scoped_origin(effective_scope_origin) and len(rerank_input) <= max(15, desired_final * 3))
        )
        if should_bypass_rerank or not rerank_input:
            reranked = [
                item.evidence.model_copy(update={"source_number": index})
                for index, item in enumerate(rerank_input[:desired_final], start=1)
            ]
        else:
            reranked = self.rerank_service.rerank(
                question=question,
                evidence=[item.evidence for item in rerank_input],
                top_k=desired_final,
            )
        rerank_ms = 0 if should_bypass_rerank or not rerank_input else self._elapsed_ms(rerank_started)
        limited = reranked[:desired_final]
        if effective_file_ids and safe_min_pages_per_doc > 0:
            limited = self._enforce_final_evidence_quota(
                reranked=limited,
                candidate_pool=[item.evidence for item in candidate_pool],
                selected_file_ids=effective_file_ids,
                min_pages_per_doc=safe_min_pages_per_doc,
                desired_final=desired_final,
            )
        if archive_scope_active and archive_slug_map:
            limited = self._prioritize_final_evidence_by_archive_scope(
                reranked=limited,
                candidate_pool=[item.evidence for item in candidate_pool],
                preferred_archive_slugs=explicit_archive_slugs,
                file_archive_map=archive_slug_map,
                min_pages_per_archive=1,
                desired_final=desired_final,
            )
        if full_document_coverage_requested and explicit_file_ids:
            explicit_file_order = {
                int(file_id): index
                for index, file_id in enumerate(explicit_file_ids)
                if int(file_id) > 0
            }
            limited = sorted(
                limited,
                key=lambda item: (
                    explicit_file_order.get(int(item.file_id), len(explicit_file_order)),
                    int(item.page_number),
                    int(item.page_id),
                ),
            )

        retrieval_route = "global_semantic"
        if effective_scope_origin == "metadata" and question_class == "metadata_comparison":
            retrieval_route = "metadata-first"
        elif self._is_scoped_origin(effective_scope_origin):
            retrieval_route = "scoped_rag"

        return RetrievalResult(
            evidence=[item.model_copy(update={"source_number": index}) for index, item in enumerate(limited, start=1)],
            telemetry={
                "retrieval_route": retrieval_route,
                "effective_scope_origin": effective_scope_origin,
                "metadata_prefilter_count": len(metadata_prefilter_ids),
                "metadata_prefilter_ms": metadata_prefilter_ms,
                "metadata_prefilter_applied": bool(metadata_prefilter_ids),
                "explicit_file_refs_count": len(explicit_file_refs),
                "explicit_file_scope_count": len(explicit_file_ids),
                "explicit_file_scope_ms": explicit_file_scope_ms,
                "explicit_file_scope_applied": bool(explicit_file_ids),
                "full_document_coverage_requested": bool(
                    full_document_coverage_requested and explicit_file_ids
                ),
                "full_document_page_limit": int(full_document_page_limit),
                "explicit_archive_refs_count": len(explicit_archive_slugs),
                "explicit_archive_scope_ms": explicit_archive_scope_ms,
                "explicit_archive_scope_applied": archive_scope_active,
                "query_embedding_ms": query_embedding_ms,
                "doc_search_ms": doc_search_ms,
                "page_search_ms": page_search_ms,
                "rerank_ms": rerank_ms,
                "retrieval_total_ms": self._elapsed_ms(total_started_at),
                "image_retrieval_enabled": use_image_retrieval,
                "text_candidates_count": len(text_candidates),
                "image_candidates_count": len(image_candidates),
                "page_text_count": len(text_candidates),
                "page_image_count": len(image_candidates),
                "oracle_text_count": len(lexical_candidates),
                "doc_shortlist_count": len(effective_file_ids),
                "doc_shortlist_limit": doc_shortlist_limit,
                "fused_pages_count": len(fused_candidates),
                "adjacent_page_candidates_count": adjacent_page_candidates_count,
                "page_candidate_limit": safe_candidate_k,
                "rerank_count": len(rerank_input),
                "doc_shortlist_bypassed_for_archive_scope": shortlist_bypassed_for_archive_scope,
                "evidence_recall_proxy": round(min(1.0, len(limited) / max(1, len(candidate_pool))), 4),
            },
        )

    def _retrieve_dense_candidates(
        self,
        *,
        query_vector: list[float],
        user_id: int | None,
        file_ids: list[int] | None,
        modality: str,
        candidate_limit: int,
    ) -> list[OracleVectorSearchResult]:
        if self.oracle_vector_store is None:
            raise RuntimeError("OracleVectorStore no disponible para retrieval denso.")
        return self.oracle_vector_store.similarity_search(
            query_vector=query_vector,
            user_id=user_id,
            file_ids=file_ids,
            modality=modality,
            top_k=candidate_limit,
            include_shared=True,
        )

    def _retrieve_lexical_candidates(
        self,
        *,
        question: str,
        user_id: int | None,
        file_ids: list[int] | None,
        candidate_limit: int,
    ) -> list[dict]:
        if self.repository is None or user_id is None:
            return []
        return self.repository.search_lexical_pages(
            user_id=user_id,
            question=question,
            file_ids=file_ids,
            limit=candidate_limit,
            include_shared=True,
        )

    def _retrieve_document_dense_candidates(
        self,
        *,
        query_vector: list[float],
        user_id: int | None,
        file_ids: list[int] | None,
        candidate_limit: int,
    ) -> list[OracleDocumentSearchResult]:
        if self.oracle_vector_store is None:
            raise RuntimeError("OracleVectorStore no disponible para retrieval documental.")
        return self.oracle_vector_store.document_similarity_search(
            query_vector=query_vector,
            user_id=user_id,
            file_ids=file_ids,
            top_k=candidate_limit,
            include_shared=True,
        )

    def _retrieve_document_lexical_candidates(
        self,
        *,
        question: str,
        user_id: int | None,
        file_ids: list[int] | None,
        candidate_limit: int,
    ) -> list[dict]:
        if self.repository is None or user_id is None:
            return []
        return self.repository.search_lexical_documents(
            user_id=user_id,
            question=question,
            file_ids=file_ids,
            limit=candidate_limit,
            include_shared=True,
        )

    @staticmethod
    def _fuse_document_candidates(
        *,
        dense_candidates: list[OracleDocumentSearchResult],
        lexical_candidates: list[dict],
        limit: int,
    ) -> list[DocumentCandidateRecord]:
        records: dict[int, DocumentCandidateRecord] = {}
        max_lexical_score = max((float(item.get("lexical_score") or 0.0) for item in lexical_candidates), default=0.0)
        for rank, candidate in enumerate(dense_candidates, start=1):
            record = records.get(int(candidate.file_id))
            if record is None:
                record = DocumentCandidateRecord(
                    file_id=int(candidate.file_id),
                    file_name=str(candidate.file_name or ""),
                    file_code=candidate.file_code,
                    summary_text=str(candidate.summary_text or ""),
                    search_text=str(candidate.search_text or ""),
                )
                records[int(candidate.file_id)] = record
            record.dense_score = max(float(candidate.score or 0.0), record.dense_score or float("-inf"))
            record.fused_score += 1.0 / (RRF_K + rank)
        for rank, candidate in enumerate(lexical_candidates, start=1):
            file_id = int(candidate.get("file_id") or 0)
            if file_id <= 0:
                continue
            record = records.get(file_id)
            if record is None:
                record = DocumentCandidateRecord(
                    file_id=file_id,
                    file_name=str(candidate.get("file_input_file_name") or ""),
                    file_code=(str(candidate.get("file_code") or "").strip().upper() or None),
                    summary_text=str(candidate.get("file_embeddings_summary") or ""),
                    search_text=str(candidate.get("file_embeddings_search_text") or ""),
                )
                records[file_id] = record
            lexical_score = float(candidate.get("lexical_score") or 0.0)
            record.lexical_score = max(lexical_score, record.lexical_score or float("-inf"))
            record.fused_score += 0.85 / (RRF_K + rank)
        results: list[DocumentCandidateRecord] = []
        for record in records.values():
            dense_score = None if record.dense_score in {float("-inf"), None} else record.dense_score
            lexical_score = None if record.lexical_score in {float("-inf"), None} else record.lexical_score
            if dense_score is not None:
                record.fused_score += max(dense_score, 0.0) * 0.10
            if lexical_score is not None and max_lexical_score > 0:
                record.fused_score += (lexical_score / max_lexical_score) * 0.10
            results.append(record)
        results.sort(key=lambda item: item.fused_score, reverse=True)
        return results[:limit]

    @staticmethod
    def _build_base_evidence_from_vector(item: OracleVectorSearchResult) -> EvidenceItem:
        return EvidenceItem(
            source_number=0,
            file_id=int(item.file_id),
            file_name=str(item.file_name or ""),
            archive_slug=str(item.archive_slug or ""),
            file_code=item.file_code,
            page_id=int(item.page_id),
            page_number=int(item.page_number),
            score=0.0,
            summary_text="",
            image_path_local=str(item.image_path_local or ""),
            object_name_page=str(item.object_name_page or ""),
            extraction_method=str(item.extraction_method or ""),
            ocr_confidence=item.ocr_confidence,
        )

    @staticmethod
    def _build_base_evidence_from_row(item: dict, *, score: float = 0.0, extraction_method: str = "") -> EvidenceItem:
        visual_summary = str(item.get("file_pages_visual_summary") or "").strip()
        ocr_text = str(item.get("file_pages_ocr_text") or "").strip()
        summary_text = visual_summary or ocr_text
        return EvidenceItem(
            source_number=0,
            file_id=int(item.get("file_id") or 0),
            file_name=str(item.get("file_input_file_name") or ""),
            archive_slug=str(item.get("archive_slug") or ""),
            file_code=(str(item.get("file_code") or "").strip().upper() or None),
            page_id=int(item.get("file_pages_id") or 0),
            page_number=int(item.get("file_pages_number") or 0),
            score=float(score),
            summary_text=summary_text[:4000],
            image_path_local=str(item.get("file_pages_image_path_local") or ""),
            object_name_page=str(item.get("file_pages_output_obj_name") or ""),
            extraction_method=str(item.get("file_pages_ocr_method") or extraction_method),
            ocr_confidence=(
                float(item["file_pages_ocr_confidence"])
                if item.get("file_pages_ocr_confidence") is not None
                else None
            ),
        )

    def _ensure_record_from_vector(
        self,
        *,
        records: dict[tuple[int, int], CandidateRecord],
        item: OracleVectorSearchResult,
    ) -> CandidateRecord:
        key = (int(item.file_id), int(item.page_id))
        record = records.get(key)
        if record is None:
            record = CandidateRecord(evidence=self._build_base_evidence_from_vector(item))
            records[key] = record
        return record

    def _ensure_record_from_row(
        self,
        *,
        records: dict[tuple[int, int], CandidateRecord],
        item: dict,
    ) -> CandidateRecord:
        key = (int(item.get("file_id") or 0), int(item.get("file_pages_id") or 0))
        record = records.get(key)
        if record is None:
            record = CandidateRecord(evidence=self._build_base_evidence_from_row(item))
            records[key] = record
        return record

    @staticmethod
    def _has_multimodal_conflict(text_summary: str, image_summary: str) -> bool:
        text_tokens = tokenize_text(text_summary)
        image_tokens = tokenize_text(image_summary)
        if not text_tokens or not image_tokens:
            return False
        return token_jaccard_similarity(text_tokens, image_tokens) < 0.12

    @staticmethod
    def _compose_summary(
        *,
        text_summary: str,
        image_summary: str,
        text_score: float | None,
        image_score: float | None,
        ocr_confidence: float | None,
    ) -> str:
        safe_text_summary = str(text_summary or "").strip()
        safe_image_summary = str(image_summary or "").strip()
        should_prefer_image = bool(
            safe_image_summary
            and (
                not safe_text_summary
                or (ocr_confidence is not None and ocr_confidence < LOW_OCR_CONFIDENCE_THRESHOLD)
                or (
                    image_score is not None
                    and (text_score is None or image_score > max(text_score, 0.0) * IMAGE_SCORE_ADVANTAGE_FACTOR)
                )
            )
        )
        if should_prefer_image:
            if safe_text_summary and safe_text_summary != safe_image_summary:
                return f"{safe_image_summary}\nOCR excerpt: {safe_text_summary[:1800]}".strip()[:4000]
            return safe_image_summary[:4000]
        return (safe_text_summary or safe_image_summary)[:4000]

    @staticmethod
    def _should_use_visual_check(
        *,
        question: str,
        text_score: float | None,
        image_score: float | None,
        ocr_confidence: float | None,
        text_summary: str,
        image_summary: str,
    ) -> bool:
        del ocr_confidence, text_summary, image_summary
        if (
            image_score is not None
            and image_score > 0
            and (text_score is None or image_score > max(text_score, 0.0) * IMAGE_SCORE_ADVANTAGE_FACTOR)
        ):
            return True
        return question_requires_visual_grounding(question)

    def _fuse_candidates(
        self,
        *,
        question: str,
        text_candidates: list[OracleVectorSearchResult],
        image_candidates: list[OracleVectorSearchResult],
        lexical_candidates: list[dict],
    ) -> list[CandidateRecord]:
        fused: dict[tuple[int, int], CandidateRecord] = {}
        max_lexical_score = max((float(item.get("lexical_score") or 0.0) for item in lexical_candidates), default=0.0)
        query_concepts = extract_query_concepts(question)

        for rank, candidate in enumerate(text_candidates, start=1):
            record = self._ensure_record_from_vector(records=fused, item=candidate)
            record.text_summary = str(candidate.summary_text or "").strip()
            record.text_score = max(float(candidate.score or 0.0), record.text_score or float("-inf"))
            record.fused_score += 1.0 / (RRF_K + rank)

        for rank, candidate in enumerate(image_candidates, start=1):
            record = self._ensure_record_from_vector(records=fused, item=candidate)
            record.image_summary = str(candidate.summary_text or "").strip()
            record.image_score = max(float(candidate.score or 0.0), record.image_score or float("-inf"))
            record.fused_score += 0.95 / (RRF_K + rank)

        for rank, candidate in enumerate(lexical_candidates, start=1):
            record = self._ensure_record_from_row(records=fused, item=candidate)
            lexical_score = float(candidate.get("lexical_score") or 0.0)
            if not record.text_summary:
                record.text_summary = str(candidate.get("file_pages_ocr_text") or "").strip()
            if not record.image_summary:
                record.image_summary = str(candidate.get("file_pages_visual_summary") or "").strip()
            record.lexical_score = max(lexical_score, record.lexical_score or float("-inf"))
            record.fused_score += 0.75 / (RRF_K + rank)

        results: list[CandidateRecord] = []
        for record in fused.values():
            text_score = None if record.text_score in {float("-inf"), None} else record.text_score
            image_score = None if record.image_score in {float("-inf"), None} else record.image_score
            lexical_score = None if record.lexical_score in {float("-inf"), None} else record.lexical_score
            if text_score is not None:
                record.fused_score += max(text_score, 0.0) * 0.05
            if image_score is not None:
                record.fused_score += max(image_score, 0.0) * 0.05
            if lexical_score is not None and max_lexical_score > 0:
                record.fused_score += (lexical_score / max_lexical_score) * 0.05
            summary_text = self._compose_summary(
                text_summary=record.text_summary,
                image_summary=record.image_summary,
                text_score=text_score,
                image_score=image_score,
                ocr_confidence=record.evidence.ocr_confidence,
            )
            needs_visual_check = self._should_use_visual_check(
                question=question,
                text_score=text_score,
                image_score=image_score,
                ocr_confidence=record.evidence.ocr_confidence,
                text_summary=record.text_summary,
                image_summary=record.image_summary,
            )
            record.text = summary_text
            record.tokens = tokenize_text(summary_text)
            coverage_score = concept_coverage_score(query_concepts, record.tokens)
            if coverage_score > 0:
                record.fused_score += coverage_score * 0.35
            if lexical_score is not None and query_concepts and coverage_score < 0.25:
                record.fused_score *= 0.65
            record.evidence = record.evidence.model_copy(
                update={
                    "summary_text": summary_text,
                    "score": float(record.fused_score),
                    "text_score": text_score,
                    "image_score": image_score,
                    "lexical_score": lexical_score,
                    "fused_score": float(record.fused_score),
                    "needs_visual_check": bool(needs_visual_check),
                }
            )
            results.append(record)

        return sorted(results, key=lambda item: item.fused_score, reverse=True)

    def _select_diverse_candidates(
        self,
        *,
        candidates: list[CandidateRecord],
        top_k: int,
        max_mmr_pool: int,
    ) -> list[CandidateRecord]:
        if not candidates:
            return []
        target_size = min(max(top_k * MMR_POOL_MULTIPLIER, top_k), max_mmr_pool)
        remaining = candidates[:]
        selected: list[CandidateRecord] = []
        while remaining and len(selected) < target_size:
            if not selected:
                selected.append(remaining.pop(0))
                continue
            best_index = 0
            best_score = float("-inf")
            for index, candidate in enumerate(remaining):
                diversity_penalty = max(
                    token_jaccard_similarity(candidate.tokens, selected_item.tokens)
                    for selected_item in selected
                )
                mmr_score = (MMR_LAMBDA * candidate.fused_score) - ((1 - MMR_LAMBDA) * diversity_penalty)
                if mmr_score > best_score:
                    best_score = mmr_score
                    best_index = index
            selected.append(remaining.pop(best_index))
        return selected

    def _build_per_doc_evidence_expansion_candidates(
        self,
        *,
        question: str,
        user_id: int | None,
        selected_file_ids: list[int],
        max_pages_per_doc: int = 3,
        preserve_page_order: bool = False,
    ) -> list[CandidateRecord]:
        if self.repository is None or user_id is None or not selected_file_ids:
            return []
        rows = self.repository.list_embeddings(
            file_ids=selected_file_ids,
            user_id=user_id,
            include_vectors=False,
            modalities=["ocr_text"],
            include_shared=True,
        )
        if not rows:
            return []
        query_tokens = tokenize_text(question) or ["_"]
        query_concepts = extract_query_concepts(question)
        per_doc_candidates: dict[int, list[CandidateRecord]] = {}
        for row in rows:
            file_id = int(row.get("file_id") or 0)
            if file_id <= 0:
                continue
            text = str(row.get("file_pages_ocr_text") or row.get("page_embeddings_summary") or "").strip()[:4000]
            tokens = tokenize_text(text) or ["_"]
            lexical_score = token_jaccard_similarity(query_tokens, tokens)
            coverage_score = concept_coverage_score(query_concepts, tokens)
            fused_score = max(float(lexical_score), coverage_score)
            candidate = CandidateRecord(
                evidence=self._build_base_evidence_from_row(
                    row,
                    score=float(fused_score),
                    extraction_method="per_doc_evidence_expansion",
                ).model_copy(
                    update={
                        "summary_text": text,
                        "lexical_score": float(lexical_score),
                        "fused_score": float(fused_score),
                    }
                ),
                text=text,
                tokens=tokens,
                text_summary=text,
                lexical_score=float(lexical_score),
                fused_score=float(fused_score),
            )
            per_doc_candidates.setdefault(file_id, []).append(candidate)
        selected: list[CandidateRecord] = []
        for file_id in selected_file_ids:
            candidates = sorted(
                per_doc_candidates.get(int(file_id), []),
                key=(
                    (lambda item: (int(item.evidence.page_number), int(item.evidence.page_id)))
                    if preserve_page_order
                    else (lambda item: float(item.fused_score))
                ),
                reverse=not preserve_page_order,
            )
            selected.extend(candidates[: max(1, int(max_pages_per_doc or 1))])
        return selected

    def _build_adjacent_page_candidates(
        self,
        *,
        user_id: int | None,
        selected_evidence: list[EvidenceItem],
        selected_file_ids: list[int],
    ) -> list[CandidateRecord]:
        if self.repository is None or user_id is None or not selected_evidence:
            return []
        selected_ids = self._dedupe_positive_ids(selected_file_ids) or self._dedupe_positive_ids(
            [int(item.file_id) for item in selected_evidence]
        )
        if not selected_ids:
            return []

        selected_page_numbers: dict[int, set[int]] = {}
        selected_page_ids: set[tuple[int, int]] = set()
        for item in selected_evidence:
            file_id = int(item.file_id)
            page_number = int(item.page_number)
            if file_id <= 0 or page_number <= 0:
                continue
            selected_page_numbers.setdefault(file_id, set()).add(page_number)
            selected_page_ids.add((file_id, int(item.page_id)))
        target_page_numbers: dict[int, set[int]] = {}
        for file_id, pages in selected_page_numbers.items():
            targets = target_page_numbers.setdefault(file_id, set())
            for page_number in pages:
                if page_number > 1:
                    targets.add(page_number - 1)
                targets.add(page_number + 1)
            targets.difference_update(pages)
        if not any(target_page_numbers.values()):
            return []

        try:
            rows = self.repository.list_embeddings(
                file_ids=selected_ids,
                user_id=int(user_id),
                include_vectors=False,
                modalities=["ocr_text"],
                include_shared=True,
            )
        except Exception:
            return []

        candidates: list[CandidateRecord] = []
        seen: set[tuple[int, int]] = set()
        for row in sorted(rows, key=lambda item: (int(item.get("file_id") or 0), int(item.get("file_pages_number") or 0))):
            file_id = int(row.get("file_id") or 0)
            page_number = int(row.get("file_pages_number") or 0)
            page_id = int(row.get("file_pages_id") or 0)
            if file_id <= 0 or page_number <= 0 or page_id <= 0:
                continue
            if page_number not in target_page_numbers.get(file_id, set()):
                continue
            key = (file_id, page_id)
            if key in seen or key in selected_page_ids:
                continue
            text = str(row.get("file_pages_ocr_text") or row.get("page_embeddings_summary") or "").strip()
            if not text:
                continue
            seen.add(key)
            evidence = self._build_base_evidence_from_row(
                row,
                score=0.01,
                extraction_method="adjacent_page_context",
            ).model_copy(
                update={
                    "summary_text": text[:4000],
                    "lexical_score": 0.0,
                    "fused_score": 0.01,
                }
            )
            candidates.append(
                CandidateRecord(
                    evidence=evidence,
                    text=text[:4000],
                    tokens=tokenize_text(text),
                    text_summary=text[:4000],
                    lexical_score=0.0,
                    fused_score=0.01,
                )
            )
        return candidates

    @staticmethod
    def _enforce_per_document_quota(
        *,
        candidates: list[CandidateRecord],
        fused_candidates: list[CandidateRecord],
        evidence_expansion_candidates: list[CandidateRecord],
        selected_file_ids: list[int],
        min_pages_per_doc: int,
    ) -> list[CandidateRecord]:
        if min_pages_per_doc <= 0 or not selected_file_ids:
            return candidates
        per_doc_quota = max(1, int(min_pages_per_doc))
        selected_ids = [int(file_id) for file_id in selected_file_ids if int(file_id) > 0]
        if not selected_ids:
            return candidates

        result = list(candidates)
        seen_pages = {(int(item.evidence.file_id), int(item.evidence.page_id)) for item in result}

        by_doc: dict[int, list[CandidateRecord]] = {}
        for item in fused_candidates:
            by_doc.setdefault(int(item.evidence.file_id), []).append(item)
        for item in evidence_expansion_candidates:
            by_doc.setdefault(int(item.evidence.file_id), []).append(item)

        def _doc_count(doc_id: int) -> int:
            return sum(1 for item in result if int(item.evidence.file_id) == doc_id)

        for doc_id in selected_ids:
            needed = per_doc_quota - _doc_count(doc_id)
            if needed <= 0:
                continue
            for candidate in by_doc.get(doc_id, []):
                if needed <= 0:
                    break
                key = (int(candidate.evidence.file_id), int(candidate.evidence.page_id))
                if key in seen_pages:
                    continue
                result.append(candidate)
                seen_pages.add(key)
                needed -= 1
        return result

    @staticmethod
    def _enforce_final_evidence_quota(
        *,
        reranked: list[EvidenceItem],
        candidate_pool: list[EvidenceItem],
        selected_file_ids: list[int],
        min_pages_per_doc: int,
        desired_final: int,
    ) -> list[EvidenceItem]:
        if min_pages_per_doc <= 0 or not selected_file_ids:
            return reranked
        per_doc_quota = max(1, int(min_pages_per_doc))
        selected_ids = [int(file_id) for file_id in selected_file_ids if int(file_id) > 0]
        if not selected_ids:
            return reranked

        result = list(reranked)
        seen_pages = {(int(item.file_id), int(item.page_id)) for item in result}

        pool_by_doc: dict[int, list[EvidenceItem]] = {}
        for item in candidate_pool:
            pool_by_doc.setdefault(int(item.file_id), []).append(item)

        def _count_for_doc(doc_id: int) -> int:
            return sum(1 for item in result if int(item.file_id) == doc_id)

        for doc_id in selected_ids:
            needed = per_doc_quota - _count_for_doc(doc_id)
            if needed <= 0:
                continue
            for candidate in pool_by_doc.get(doc_id, []):
                if needed <= 0:
                    break
                key = (int(candidate.file_id), int(candidate.page_id))
                if key in seen_pages:
                    continue
                result.append(candidate)
                seen_pages.add(key)
                needed -= 1

        if per_doc_quota > 1:
            for doc_id in selected_ids:
                adjacent_candidates = [
                    candidate
                    for candidate in pool_by_doc.get(doc_id, [])
                    if str(candidate.extraction_method or "") == "adjacent_page_context"
                ]
                if not adjacent_candidates:
                    continue
                for adjacent in adjacent_candidates:
                    adjacent_key = (int(adjacent.file_id), int(adjacent.page_id))
                    if adjacent_key in seen_pages:
                        continue
                    current_doc_items = [
                        (index, item)
                        for index, item in enumerate(result)
                        if int(item.file_id) == doc_id
                    ]
                    if len(current_doc_items) < per_doc_quota:
                        result.append(adjacent)
                        seen_pages.add(adjacent_key)
                        continue
                    anchor_index = current_doc_items[0][0]
                    replacement_index = None
                    for index, item in reversed(current_doc_items):
                        if index == anchor_index:
                            continue
                        if str(item.extraction_method or "") == "adjacent_page_context":
                            continue
                        replacement_index = index
                        break
                    if replacement_index is None:
                        continue
                    old_item = result[replacement_index]
                    seen_pages.discard((int(old_item.file_id), int(old_item.page_id)))
                    result[replacement_index] = adjacent
                    seen_pages.add(adjacent_key)

        if len(result) <= desired_final:
            return result
        preserved: list[EvidenceItem] = []
        indexed_result = list(enumerate(result))
        for doc_id in selected_ids:
            doc_items = [(index, item) for index, item in indexed_result if int(item.file_id) == doc_id]
            if not doc_items:
                continue
            anchor_index = doc_items[0][0]
            anchor_page = int(doc_items[0][1].page_number)
            doc_items.sort(
                key=lambda pair: (
                    0
                    if pair[0] == anchor_index
                    else (
                        1
                        if str(pair[1].extraction_method or "") == "adjacent_page_context"
                        else 2
                    ),
                    abs(int(pair[1].page_number) - anchor_page) if anchor_page > 0 else 0,
                    pair[0],
                )
            )
            for _, item in doc_items[:per_doc_quota]:
                preserved.append(item)
        preserved_keys = {(int(item.file_id), int(item.page_id)) for item in preserved}
        for item in result:
            key = (int(item.file_id), int(item.page_id))
            if key in preserved_keys:
                continue
            preserved.append(item)
            if len(preserved) >= desired_final:
                break
        return preserved[:desired_final]
