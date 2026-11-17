from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from apps.backend.app.ingest.docling_document_service import DoclingPageResult
from apps.backend.app.ingest.document_ingest_service import IngestionService
from apps.backend.app.ingest.document_metadata import FileMetadata
from apps.backend.app.ingest.ocr_types import PageOCRResult
from apps.backend.app.ingest.rag_enrichment import PageRAGEnrichment


def test_process_rendered_pages_skips_image_embeddings_when_visual_enrichment_is_disabled(
    tmp_path: Path,
) -> None:
    service = object.__new__(IngestionService)
    image_embedding_calls: list[tuple[Path, str]] = []
    page_embedding_calls: list[dict[str, object]] = []
    added_pages: list[dict[str, object]] = []

    image_path = tmp_path / "page-1.png"
    image_path.write_bytes(b"stub-image")

    service.settings = SimpleNamespace(
        data_dir=tmp_path,
        embedding_model_name="nomic-embed-vision-v1.5",
    )
    service.page_visual_enricher = SimpleNamespace(
        enrich_page=lambda **kwargs: PageRAGEnrichment(
            visual_summary="table like layout",
            layout_json="{}",
            search_text="page search text",
            visual_flags=["possible_table"],
            text_quality=0.95,
        )
    )
    service.object_storage = SimpleNamespace(
        upload_file=lambda path, **kwargs: {"object_name": f"obj/{Path(path).name}"}
    )
    service.repository = SimpleNamespace(
        add_page=lambda **kwargs: (added_pages.append(dict(kwargs)), {"file_pages_id": 11})[1],
        add_embedding=lambda **kwargs: page_embedding_calls.append(dict(kwargs)),
    )
    service.embedding_service = SimpleNamespace(
        embed_document_text=lambda text: [0.1, 0.2, 0.3],
        embed_image=lambda image_path, context_text: (
            image_embedding_calls.append((Path(image_path), str(context_text))),
            ([0.9, 0.8], "image summary"),
        )[1],
    )

    leading_page_texts, telemetry = IngestionService._process_rendered_pages(
        service,
        rendered_pages=[
            {
                "page_number": 1,
                "image_path": image_path,
                "width": 100,
                "height": 100,
            }
        ],
        page_analysis_by_number={
            1: DoclingPageResult(
                page_number=1,
                ocr_result=PageOCRResult(
                    raw_ocr_text="Contrato de arrendamiento",
                    normalized_text="Contrato de arrendamiento",
                    markdown_text="## Contrato\n\nContrato de arrendamiento",
                    detected_blocks_json="[]",
                    table_extraction_json="[]",
                    ocr_confidence=0.93,
                    extraction_method="docling_rapidocr",
                ),
                visual_summary="Docling text blocks: 4. Tables detected: 1.",
                layout_json="{}",
                visual_flags=["contains_table"],
            )
        },
        pdf_path=tmp_path / "doc.pdf",
        file_id=7,
        user_id=3,
        file_hash="abc123",
        user_scope="user-3",
        archive_prefix="user-3/archive/source",
        archive_slug="AI041_ID_49",
        metadata_override=None,
        enable_page_image_embeddings=False,
    )

    assert leading_page_texts == ["Contrato de arrendamiento"]
    assert telemetry["page_text_embeddings_written"] == 1
    assert telemetry["page_image_embeddings_written"] == 0
    assert image_embedding_calls == []
    assert len(added_pages) == 1
    assert added_pages[0]["ocr_text"] == "Contrato de arrendamiento"
    assert added_pages[0]["markdown_text"] == "## Contrato\n\nContrato de arrendamiento"
    assert len(page_embedding_calls) == 1
    assert page_embedding_calls[0]["modality"] == "ocr_text"
    assert page_embedding_calls[0]["summary_text"] == "Contrato de arrendamiento"


def test_process_rendered_pages_passes_docling_context_into_visual_enrichment(tmp_path: Path) -> None:
    service = object.__new__(IngestionService)
    captured_enrichment_kwargs: list[dict[str, object]] = []

    image_path = tmp_path / "page-1.png"
    image_path.write_bytes(b"stub-image")

    service.settings = SimpleNamespace(
        data_dir=tmp_path,
        embedding_model_name="nomic-embed-vision-v1.5",
    )
    service.page_visual_enricher = SimpleNamespace(
        enrich_page=lambda **kwargs: (
            captured_enrichment_kwargs.append(dict(kwargs)),
            PageRAGEnrichment(
                visual_summary=str(kwargs.get("base_visual_summary") or ""),
                layout_json="{}",
                search_text="page search text",
                visual_flags=list(kwargs.get("base_visual_flags") or []),
                text_quality=0.81,
            ),
        )[1]
    )
    service.object_storage = SimpleNamespace(
        upload_file=lambda path, **kwargs: {"object_name": f"obj/{Path(path).name}"}
    )
    service.repository = SimpleNamespace(
        add_page=lambda **kwargs: {"file_pages_id": 33},
        add_embedding=lambda **kwargs: None,
    )
    service.embedding_service = SimpleNamespace(
        embed_document_text=lambda text: [0.1, 0.2, 0.3],
        embed_image=lambda image_path, context_text: ([0.9, 0.8], "image summary"),
    )

    IngestionService._process_rendered_pages(
        service,
        rendered_pages=[
            {
                "page_number": 1,
                "image_path": image_path,
                "width": 100,
                "height": 100,
            }
        ],
        page_analysis_by_number={
            1: DoclingPageResult(
                page_number=1,
                ocr_result=PageOCRResult(
                    raw_ocr_text="Firma del representante",
                    normalized_text="Firma del representante",
                    markdown_text="Firma del representante",
                    detected_blocks_json='[{"type":"picture"}]',
                    table_extraction_json="[]",
                    ocr_confidence=0.76,
                    extraction_method="docling_rapidocr",
                ),
                visual_summary="Signature-like region detected.",
                layout_json='{"labels":["signature_like"],"contains_picture":true}',
                visual_flags=["contains_picture", "possible_signature"],
            )
        },
        pdf_path=tmp_path / "doc.pdf",
        file_id=7,
        user_id=3,
        file_hash="abc123",
        user_scope="user-3",
        archive_prefix="user-3/archive/source",
        archive_slug="AI041_ID_49",
        metadata_override=None,
        enable_page_image_embeddings=False,
    )

    assert len(captured_enrichment_kwargs) == 1
    assert captured_enrichment_kwargs[0]["base_visual_summary"] == "Signature-like region detected."
    assert captured_enrichment_kwargs[0]["base_layout_payload"] == {
        "labels": ["signature_like"],
        "contains_picture": True,
    }
    assert captured_enrichment_kwargs[0]["base_visual_flags"] == ["contains_picture", "possible_signature"]


def test_process_rendered_pages_skips_text_embeddings_for_blank_ocr_pages(tmp_path: Path) -> None:
    service = object.__new__(IngestionService)
    page_embedding_calls: list[dict[str, object]] = []
    added_pages: list[dict[str, object]] = []

    image_path = tmp_path / "page-1.png"
    image_path.write_bytes(b"stub-image")

    service.settings = SimpleNamespace(
        data_dir=tmp_path,
        embedding_model_name="nomic-embed-vision-v1.5",
    )
    service.page_visual_enricher = SimpleNamespace(
        enrich_page=lambda **kwargs: PageRAGEnrichment(
            visual_summary="",
            layout_json="{}",
            search_text="page search text",
            visual_flags=["closing_page"],
            text_quality=0.0,
        )
    )
    service.object_storage = SimpleNamespace(
        upload_file=lambda path, **kwargs: {"object_name": f"obj/{Path(path).name}"}
    )
    service.repository = SimpleNamespace(
        add_page=lambda **kwargs: (added_pages.append(dict(kwargs)), {"file_pages_id": 22})[1],
        add_embedding=lambda **kwargs: page_embedding_calls.append(dict(kwargs)),
    )
    service.embedding_service = SimpleNamespace(
        embed_document_text=lambda text: (_ for _ in ()).throw(
            AssertionError("Blank OCR pages should not request text embeddings.")
        ),
        embed_image=lambda image_path, context_text: (_ for _ in ()).throw(
            AssertionError("Image embeddings are disabled in this test.")
        ),
    )

    leading_page_texts, telemetry = IngestionService._process_rendered_pages(
        service,
        rendered_pages=[
            {
                "page_number": 1,
                "image_path": image_path,
                "width": 100,
                "height": 100,
            }
        ],
        page_analysis_by_number={
            1: DoclingPageResult(
                page_number=1,
                ocr_result=PageOCRResult(
                    raw_ocr_text="",
                    normalized_text="",
                    markdown_text="",
                    detected_blocks_json="[]",
                    table_extraction_json="[]",
                    ocr_confidence=0.0,
                    extraction_method="docling_rapidocr",
                ),
                visual_summary="",
                layout_json="{}",
                visual_flags=["closing_page"],
            )
        },
        pdf_path=tmp_path / "doc.pdf",
        file_id=7,
        user_id=3,
        file_hash="abc123",
        user_scope="user-3",
        archive_prefix="user-3/archive/source",
        archive_slug="RS072_ID_4405",
        metadata_override=None,
        enable_page_image_embeddings=False,
    )

    assert leading_page_texts == []
    assert telemetry["blank_ocr_pages_count"] == 1
    assert telemetry["page_text_embeddings_written"] == 0
    assert telemetry["page_image_embeddings_written"] == 0
    assert len(added_pages) == 1
    assert added_pages[0]["ocr_text"] == ""
    assert page_embedding_calls == []


def test_process_rendered_pages_writes_image_embeddings_for_docling_visual_pages(tmp_path: Path) -> None:
    service = object.__new__(IngestionService)
    page_embedding_calls: list[dict[str, object]] = []

    image_path = tmp_path / "page-1.png"
    image_path.write_bytes(b"stub-image")

    service.settings = SimpleNamespace(
        data_dir=tmp_path,
        embedding_model_name="nomic-embed-vision-v1.5",
    )
    service.page_visual_enricher = SimpleNamespace(
        enrich_page=lambda **kwargs: PageRAGEnrichment(
            visual_summary=str(kwargs.get("base_visual_summary") or ""),
            layout_json="{}",
            search_text="page search text",
            visual_flags=list(kwargs.get("base_visual_flags") or []),
            text_quality=0.72,
        )
    )
    service.object_storage = SimpleNamespace(
        upload_file=lambda path, **kwargs: {"object_name": f"obj/{Path(path).name}"}
    )
    service.repository = SimpleNamespace(
        add_page=lambda **kwargs: {"file_pages_id": 44},
        add_embedding=lambda **kwargs: page_embedding_calls.append(dict(kwargs)),
    )
    service.embedding_service = SimpleNamespace(
        embed_document_text=lambda text: [0.1, 0.2, 0.3],
        embed_image=lambda image_path, context_text: ([0.9, 0.8, 0.7], "image summary"),
    )

    _, telemetry = IngestionService._process_rendered_pages(
        service,
        rendered_pages=[
            {
                "page_number": 1,
                "image_path": image_path,
                "width": 100,
                "height": 100,
            }
        ],
        page_analysis_by_number={
            1: DoclingPageResult(
                page_number=1,
                ocr_result=PageOCRResult(
                    raw_ocr_text="Firma del representante",
                    normalized_text="Firma del representante",
                    markdown_text="Firma del representante",
                    detected_blocks_json="[]",
                    table_extraction_json="[]",
                    ocr_confidence=0.76,
                    extraction_method="docling_rapidocr",
                ),
                visual_summary="Visual regions detected: 1. Signature-like region detected.",
                layout_json="{}",
                visual_flags=["contains_picture", "possible_signature"],
            )
        },
        pdf_path=tmp_path / "doc.pdf",
        file_id=7,
        user_id=3,
        file_hash="abc123",
        user_scope="user-3",
        archive_prefix="user-3/archive/source",
        archive_slug="AI041_ID_49",
        metadata_override=None,
        enable_page_image_embeddings=True,
    )

    assert telemetry["page_text_embeddings_written"] == 1
    assert telemetry["page_image_embeddings_written"] == 1
    assert [call["modality"] for call in page_embedding_calls] == ["ocr_text", "page_image"]


def test_finalize_document_rag_skips_structured_fact_writes_when_disabled() -> None:
    service = object.__new__(IngestionService)
    page_update_calls: list[dict[str, object]] = []
    file_embedding_calls: list[dict[str, object]] = []

    page_rows = [
        {
            "file_pages_id": 21,
            "file_pages_number": 1,
            "file_pages_ocr_text": "Contrato principal con canon mensual.",
            "file_pages_visual_summary": "",
            "file_pages_layout_json": "{}",
            "file_pages_visual_flags": "possible_table",
            "file_pages_text_quality": 0.92,
        },
        {
            "file_pages_id": 22,
            "file_pages_number": 2,
            "file_pages_ocr_text": "Firma del representante y clausulas de termino.",
            "file_pages_visual_summary": "",
            "file_pages_layout_json": "{}",
            "file_pages_visual_flags": "possible_signature",
            "file_pages_text_quality": 0.88,
        },
    ]

    service.repository = SimpleNamespace(
        get_pages_by_file=lambda file_id: list(page_rows),
        file_pages=SimpleNamespace(
            update_page_rag_enrichment=lambda **kwargs: page_update_calls.append(dict(kwargs))
        ),
        file_embeddings=SimpleNamespace(
            add_or_replace_embedding=lambda **kwargs: file_embedding_calls.append(dict(kwargs))
        ),
        document_facts=SimpleNamespace(
            upsert_file_group=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("Structured fact writes should be skipped when disabled.")
            ),
            upsert_file_profile=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("Structured fact writes should be skipped when disabled.")
            ),
            replace_file_entities=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("Structured fact writes should be skipped when disabled.")
            ),
            replace_file_attributes=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("Structured fact writes should be skipped when disabled.")
            ),
            replace_file_links=lambda **kwargs: (_ for _ in ()).throw(
                AssertionError("Structured fact writes should be skipped when disabled.")
            ),
        ),
    )
    service.settings = SimpleNamespace(embedding_model_name="nomic-embed-vision-v1.5")
    service.document_fact_extractor = SimpleNamespace(
        extract=lambda **kwargs: (_ for _ in ()).throw(
            AssertionError("DocumentFactExtractor.extract should not run when disabled.")
        )
    )
    service.embedding_service = SimpleNamespace(embed_document_text=lambda text: [0.1, 0.2, 0.3])

    IngestionService._finalize_document_rag(
        service,
        file_id=7,
        user_id=3,
        file_name="AI041.pdf",
        archive_slug="AI041_ID_49",
        document_metadata=FileMetadata(
            document_code="AI041",
            document_code_source="filename_rule",
        ),
        metadata_context={
            "search_text": "owner=ENTEL site=AI041_ID_49",
            "fields": {"Owner": "ENTEL"},
        },
        structured_facts_enabled=False,
    )

    assert len(page_update_calls) == 2
    assert all("owner=ENTEL site=AI041_ID_49" in str(call["search_text"]) for call in page_update_calls)
    assert len(file_embedding_calls) == 1
    assert "owner=ENTEL site=AI041_ID_49" in str(file_embedding_calls[0]["search_text"])
    assert file_embedding_calls[0]["archive_slug"] == "AI041_ID_49"
