"""Lazy production imports for split RAG validation tests."""

from __future__ import annotations

from importlib import import_module


def _load_attr(module_name: str, attr_name: str):
    return getattr(import_module(module_name), attr_name)


_map_upload_summary = _load_attr("apps.backend.app.api.routes.metadata", "_map_upload_summary")
_parse_row_preview = _load_attr("apps.backend.app.api.routes.metadata", "_parse_row_preview")
_build_citations_and_cited_sources = _load_attr(
    "apps.backend.app.api.routes.questions",
    "_build_citations_and_cited_sources",
)
_extract_latest_conversation_scope_from_messages = _load_attr(
    "apps.backend.app.api.routes.questions",
    "_extract_latest_conversation_scope_from_messages",
)
_load_visible_scope_options = _load_attr("apps.backend.app.api.routes.questions", "_load_visible_scope_options")

QAGraphNodes = _load_attr("apps.backend.app.agent.nodes", "QAGraphNodes")
_build_retrieval_question = _load_attr("apps.backend.app.agent.nodes", "_build_retrieval_question")
GraphSynthesis = _load_attr("apps.backend.app.agent.router", "GraphSynthesis")
LLMResult = _load_attr("apps.backend.app.agent.contracts", "LLMResult")
HybridAnswerTool = _load_attr("apps.backend.app.agent.tools.hybrid_answer_tool", "HybridAnswerTool")
VisualInspectionResult = _load_attr(
    "apps.backend.app.agent.tools.multimodal_tool",
    "VisualInspectionResult",
)

EvidenceItem = _load_attr("apps.backend.app.api.contracts.questions", "EvidenceItem")
Settings = _load_attr("apps.backend.app.core.config", "Settings")

ArchiveMetadataEntry = _load_attr("apps.backend.app.rag.facts_query_service", "ArchiveMetadataEntry")
FactResolution = _load_attr("apps.backend.app.rag.facts_query_service", "FactResolution")
QuestionFactResolver = _load_attr("apps.backend.app.rag.facts_query_service", "QuestionFactResolver")
QuestionClassifier = _load_attr("apps.backend.app.rag.question_classifier", "QuestionClassifier")
repair_document_file_name = _load_attr("apps.backend.app.rag.display_text", "repair_document_file_name")

ParsedQuestionSelectors = _load_attr("apps.backend.app.rag.query_selectors", "ParsedQuestionSelectors")
build_effective_selector_question = _load_attr(
    "apps.backend.app.rag.query_selectors",
    "build_effective_selector_question",
)
merge_question_selectors = _load_attr("apps.backend.app.rag.query_selectors", "merge_question_selectors")
parse_question_selectors = _load_attr("apps.backend.app.rag.query_selectors", "parse_question_selectors")

QuestionScopeResolver = _load_attr("apps.backend.app.rag.scope_resolver", "QuestionScopeResolver")
ScopeResolutionError = _load_attr("apps.backend.app.rag.scope_resolver", "ScopeResolutionError")
extract_candidate_archive_slugs_from_question = _load_attr(
    "apps.backend.app.rag.scope_resolver",
    "extract_candidate_archive_slugs_from_question",
)
extract_candidate_codes_from_question = _load_attr(
    "apps.backend.app.rag.scope_resolver",
    "extract_candidate_codes_from_question",
)
extract_candidate_file_names_from_question = _load_attr(
    "apps.backend.app.rag.scope_resolver",
    "extract_candidate_file_names_from_question",
)

OracleVectorSearchResult = _load_attr(
    "apps.backend.app.rag.retrieval.oracle_vector_search",
    "OracleVectorSearchResult",
)
RetrievalPipelineService = _load_attr(
    "apps.backend.app.rag.retrieval.query_service",
    "RetrievalPipelineService",
)
RetrievalResult = _load_attr("apps.backend.app.rag.retrieval.query_service", "RetrievalResult")
concept_coverage_score = _load_attr("apps.backend.app.rag.retrieval.query_service", "concept_coverage_score")
extract_explicit_file_references = _load_attr(
    "apps.backend.app.rag.retrieval.query_service",
    "extract_explicit_file_references",
)
extract_query_concepts = _load_attr("apps.backend.app.rag.retrieval.query_service", "extract_query_concepts")
question_requests_full_document_coverage = _load_attr(
    "apps.backend.app.rag.retrieval.query_service",
    "question_requests_full_document_coverage",
)
question_requests_representative_details = _load_attr(
    "apps.backend.app.rag.retrieval.query_service",
    "question_requests_representative_details",
)
question_requires_visual_grounding = _load_attr(
    "apps.backend.app.rag.retrieval.query_service",
    "question_requires_visual_grounding",
)
token_keys_are_related = _load_attr("apps.backend.app.rag.retrieval.query_service", "token_keys_are_related")
tokenize_text = _load_attr("apps.backend.app.rag.retrieval.query_service", "tokenize_text")

extract_document_code_from_filename = _load_attr(
    "apps.backend.app.ingest.document_metadata",
    "extract_document_code_from_filename",
)
FileMetadata = _load_attr("apps.backend.app.ingest.document_metadata", "FileMetadata")
_extract_secondary_identifier = _load_attr(
    "apps.backend.app.ingest.rag_enrichment",
    "_extract_secondary_identifier",
)
build_file_group_key = _load_attr("apps.backend.app.ingest.rag_enrichment", "build_file_group_key")

ArchiveMetadataRepository = _load_attr(
    "apps.backend.app.repositories.archive_metadata_repository",
    "ArchiveMetadataRepository",
)
build_oracle_text_contains_query = _load_attr(
    "apps.backend.app.repositories.repository_utils",
    "build_oracle_text_contains_query",
)

LoadedWorkbookSheet = _load_attr(
    "apps.backend.app.services.metadata_normalization_service",
    "LoadedWorkbookSheet",
)
MetadataWorkbookNormalizationError = _load_attr(
    "apps.backend.app.services.metadata_normalization_service",
    "MetadataWorkbookNormalizationError",
)
normalize_metadata_workbook_to_csv = _load_attr(
    "apps.backend.app.services.metadata_normalization_service",
    "normalize_metadata_workbook_to_csv",
)
MetadataUploadValidationError = _load_attr(
    "apps.backend.app.services.metadata_upload_service",
    "MetadataUploadValidationError",
)

EmbeddingService = _load_attr("apps.backend.app.rag.embedding_service", "EmbeddingService")
NomicLocalMultimodalProvider = _load_attr(
    "apps.backend.app.rag.embedding_service",
    "NomicLocalMultimodalProvider",
)

__all__ = [
    name
    for name in globals()
    if not name.startswith("__") and name not in {"import_module"}
]
