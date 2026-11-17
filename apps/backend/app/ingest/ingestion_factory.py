"""Factory wiring for the document ingestion service."""

from __future__ import annotations

from functools import lru_cache
from importlib import import_module


def _load_attr(module_name: str, attr_name: str):
    return getattr(import_module(module_name), attr_name)


@lru_cache(maxsize=1)
def get_ingestion_service():
    get_settings = _load_attr("apps.backend.app.core.config", "get_settings")
    get_db_manager = _load_attr("apps.backend.app.core.session", "get_db_manager")
    ArchiveService = _load_attr("apps.backend.app.ingest.archive_service", "ArchiveService")
    DoclingDocumentService = _load_attr(
        "apps.backend.app.ingest.docling_document_service",
        "DoclingDocumentService",
    )
    IngestionService = _load_attr("apps.backend.app.ingest.document_ingest_service", "IngestionService")
    PDFService = _load_attr("apps.backend.app.ingest.pdf_service", "PDFService")
    EmbeddingService = _load_attr("apps.backend.app.rag.embedding_service", "EmbeddingService")
    ObjectStorageService = _load_attr(
        "apps.backend.app.storage.object_storage_service",
        "ObjectStorageService",
    )

    settings = get_settings()
    db_manager = get_db_manager()
    return IngestionService(
        settings=settings,
        db_manager=db_manager,
        archive_service=ArchiveService(settings),
        pdf_service=PDFService(settings),
        docling_document_service=DoclingDocumentService(settings),
        embedding_service=EmbeddingService(settings),
        object_storage=ObjectStorageService(settings),
    )
