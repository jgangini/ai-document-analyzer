from __future__ import annotations

from datetime import date
import json

import pytest

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_question_fact_resolver_routes_interpretive_archive_comparison_to_document_followup() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 91,
                    "archive_slug": "AI041_ID_49",
                    "metadata_json": json.dumps(
                        {
                            "file": "AI041_ID_49",
                            "fields": {
                                "Estado Contrato": "Vigente",
                                "Forma de Pago": "Vale Vista",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 92,
                    "archive_slug": "AT565_ID_3820",
                    "metadata_json": json.dumps(
                        {
                            "file": "AT565_ID_3820",
                            "fields": {
                                "Estado Contrato": "Vigente",
                                "Forma de Pago": "Deposito",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 101,
                    "archive_slug": "RM797_ID_1668",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_1668",
                            "fields": {
                                "Estado Contrato": "desconocido",
                                "Fecha de Término del Contrato": "10/12/2025",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 102,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_5515",
                            "fields": {
                                "Estado Contrato": "Terminado",
                                "Fecha de Término del Contrato": "22/07/2025",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question=(
            "Compara RM797_ID_1668 y RM797_ID_5515 en Estado Contrato y Fecha de Término del Contrato; "
            "indica si ambos casos parecen vigentes o si hay diferencias claras entre los dos folios."
        ),
        user_id=7,
        file_ids=[91, 92, 101, 102],
    )

    assert resolution.narrowed_file_ids == [101, 102]
    assert resolution.answer_override is None
    assert "Resolved metadata facts:" in resolution.fact_context_text
    assert "RM797_ID_1668:" in resolution.fact_context_text
    assert "Estado Contrato=desconocido" in resolution.fact_context_text
    assert "RM797_ID_5515:" in resolution.fact_context_text
    assert "Estado Contrato=Terminado" in resolution.fact_context_text
    assert "AI041_ID_49" not in resolution.fact_context_text
    assert "AT565_ID_3820" not in resolution.fact_context_text
    assert (
        "Metadata rows matched, but the comparative question requires documentary grounding before drawing conclusions."
        in resolution.confidence_notes
    )
    assert "Archive metadata enriched the structured context for retrieval." in resolution.confidence_notes

def test_question_fact_resolver_routes_metadata_vs_documents_question_to_document_followup() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 301,
                    "archive_slug": "TSM10_ID_20441",
                    "metadata_json": json.dumps(
                        {
                            "file": "TSM10_ID_20441",
                            "fields": {
                                "Estado Contrato": "Vigente",
                                "Revision Final": "Cifrado",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="analytics",
        question="La metadata coincide con lo que dicen los documentos contractuales vigentes?",
        user_id=7,
        file_ids=[301],
        metadata_fields=["Estado Contrato", "Revision Final"],
    )

    assert resolution.answer_override is None
    assert resolution.document_phase_required is True
    assert resolution.narrowed_file_ids == [301]
    assert "Resolved metadata facts:" in resolution.fact_context_text
    assert "TSM10_ID_20441: Estado Contrato=Vigente" in resolution.fact_context_text

def test_question_fact_resolver_does_not_short_circuit_ocr_content_request_to_quality_review() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 301,
                    "archive_slug": "AI041_ID_49",
                    "metadata_json": json.dumps(
                        {
                            "file": "AI041_ID_49",
                            "fields": {
                                "Codigo de Sitio": "AI041",
                                "Direccion": "Av. Costanera Sur 2760",
                                "Renta o Precio Vigente": "14 UF mensuales",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            file_rows=[
                {
                    "file_id": 301,
                    "archive_slug": "AI041_ID_49",
                    "file_input_file_name": "AI041_CONTRATO.pdf",
                    "file_code": "AI041",
                    "file_state": 3,
                    "file_page_count": 18,
                }
            ],
            page_quality_rows=[
                {
                    "file_id": 301,
                    "archive_slug": "AI041_ID_49",
                    "file_name": "AI041_CONTRATO.pdf",
                    "status": "completed",
                    "file_page_count": 18,
                    "indexed_pages_count": 18,
                    "encrypted_or_unreadable_pages_count": 0,
                    "low_ocr_pages_count": 1,
                    "blank_pages_count": 0,
                    "avg_ocr_confidence": 0.61,
                    "avg_text_quality": 0.45,
                    "ocr_methods": ["docling_rapidocr"],
                    "visual_flags": ["low_ocr_confidence"],
                }
            ],
        ),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question=(
            "Usar @metadata y /file:AI041_ID_49. Segun el OCR del documento, resume de que trata "
            "el contrato y menciona las partes principales, la direccion o sitio y la renta si aparece."
        ),
        user_id=7,
        file_ids=[301],
        metadata_mode="metadata_first",
    )

    assert resolution.answer_override is None
    assert resolution.document_phase_required is True
    assert resolution.metadata_only_reason == ""
    assert resolution.narrowed_file_ids == [301]
    assert "Archive metadata context:" in resolution.fact_context_text
    assert "Renta o Precio Vigente=14 UF mensuales" in resolution.fact_context_text

def test_question_fact_resolver_extracts_date_field_when_question_text_is_garbled() -> None:
    metadata_rows = [
        ArchiveMetadataEntry(
            file_id=101,
            archive_slug="RM797_ID_1668",
            fields={
                "Estado Contrato": "desconocido",
                "Fecha de Término del Contrato": "10/12/2025",
            },
        ),
        ArchiveMetadataEntry(
            file_id=102,
            archive_slug="RM797_ID_5515",
            fields={
                "Estado Contrato": "Terminado",
                "Fecha de Término del Contrato": "22/07/2025",
            },
        ),
    ]

    requested_fields = QuestionFactResolver._extract_requested_metadata_fields(
        question=(
            "Compara RM797_ID_1668 y RM797_ID_5515 en Estado Contrato y "
            "Fecha de T?rmino del Contrato."
        ),
        metadata_rows=metadata_rows,
    )

    assert "Estado Contrato" in requested_fields
    assert "Fecha de Término del Contrato" in requested_fields

def test_question_fact_resolver_routes_missing_metadata_comparison_to_document_followup() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 101,
                    "archive_slug": "RM797_ID_1668",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_1668",
                            "fields": {
                                "Fecha de TÃ©rmino del Contrato": "10/12/2025",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 102,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_5515",
                            "fields": {
                                "Estado Contrato": "Terminado",
                                "Fecha de TÃ©rmino del Contrato": "22/07/2025",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question="Compara RM797_ID_1668 y RM797_ID_5515 en Estado Contrato y Fecha de TÃ©rmino del Contrato.",
        user_id=7,
        file_ids=[101, 102],
    )

    assert resolution.narrowed_file_ids == [101, 102]
    assert resolution.answer_override is None
    assert "Resolved metadata facts:" in resolution.fact_context_text
    assert "RM797_ID_1668: Fecha de TÃ©rmino del Contrato=10/12/2025" in resolution.fact_context_text
    assert "RM797_ID_5515:" in resolution.fact_context_text
    assert "Estado Contrato=Terminado" in resolution.fact_context_text
    assert (
        "Metadata rows matched partially, but missing values require documentary evidence before concluding the comparison."
        in resolution.confidence_notes
    )
    assert "Archive metadata enriched the structured context for retrieval." in resolution.confidence_notes

def test_question_fact_resolver_validates_multiple_expected_values_for_single_archive() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 91,
                    "archive_slug": "AI041_ID_49",
                    "metadata_json": json.dumps(
                        {
                            "file": "AI041_ID_49",
                            "fields": {
                                "Estado Contrato": "Vigente",
                                "Pago Anticipado": True,
                                "Forma de Pago": "Vale Vista",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question=(
            "Usando metadata de AI041_ID_49, valida si Estado Contrato es Vigente, "
            "Pago Anticipado es SI y Forma de Pago es Vale Vista."
        ),
        user_id=7,
        file_ids=[91],
    )

    assert resolution.answer_override is not None
    assert "| Estado Contrato | Vigente | coincide |" in resolution.answer_override
    assert "| Pago Anticipado | SI | coincide |" in resolution.answer_override
    assert "| Forma de Pago | Vale Vista | coincide |" in resolution.answer_override
    assert resolution.facts_used_count == 3

def test_question_fact_resolver_keeps_metadata_as_context_for_mixed_document_question() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 91,
                    "archive_slug": "AI041_ID_49",
                    "metadata_json": json.dumps(
                        {
                            "file": "AI041_ID_49",
                            "fields": {
                                "Estado Contrato": "Vigente",
                                "Forma de Pago": "Vale Vista",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question=(
            "Usando metadata y documentos de AI041_ID_49, valida si el Estado Contrato es Vigente "
            "y respaldalo con AI041.pdf."
        ),
        user_id=7,
        file_ids=[91],
    )

    assert resolution.narrowed_file_ids == [91]
    assert resolution.answer_override is None
    assert "Resolved metadata facts:" in resolution.fact_context_text
    assert "AI041_ID_49: Estado Contrato=Vigente" in resolution.fact_context_text

def test_question_fact_resolver_raises_when_metadata_is_requested_but_unavailable() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository([]),
    )

    with pytest.raises(ScopeResolutionError) as exc_info:
        resolver.resolve(
            question_class="extractive",
            question="Consulta con metadata sobre el propietario",
            user_id=7,
            file_ids=[91],
            metadata_mode="metadata_first",
        )

    assert exc_info.value.status_code == 404
    assert "No metadata is available" in str(exc_info.value)

def test_question_fact_resolver_raises_when_structured_metadata_field_is_unknown() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 91,
                    "archive_slug": "AI041_ID_49",
                    "metadata_json": json.dumps(
                        {
                            "file": "AI041_ID_49",
                            "fields": {
                                "Estado Contrato": "Vigente",
                                "Forma de Pago": "Vale Vista",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ]
        ),
    )

    with pytest.raises(ScopeResolutionError) as exc_info:
        resolver.resolve(
            question_class="extractive",
            question="Consulta el valor solicitado",
            user_id=7,
            file_ids=[91],
            metadata_fields=["Columna Inexistente"],
        )

    assert exc_info.value.status_code == 404
    assert "Columna Inexistente" in str(exc_info.value)

def test_question_fact_resolver_uses_structured_metadata_fields_for_metadata_first_lookup() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 91,
                    "archive_slug": "AI041_ID_49",
                    "metadata_json": json.dumps(
                        {
                            "file": "AI041_ID_49",
                            "fields": {
                                "Estado Contrato": "Vigente",
                                "Forma de Pago": "Vale Vista",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            file_rows=[
                {
                    "file_id": 91,
                    "archive_slug": "AI041_ID_49",
                    "file_input_file_name": "AI041.pdf",
                    "file_state": 3,
                    "file_page_count": 18,
                },
                {
                    "file_id": 92,
                    "archive_slug": "AI041_ID_49",
                    "file_input_file_name": "AI041_anexo.pdf",
                    "file_state": 3,
                    "file_page_count": 6,
                },
            ],
        ),
    )

    resolution = resolver.resolve(
        question_class="extractive",
        question="Dime el valor actual",
        user_id=7,
        file_ids=[91],
        metadata_mode="metadata_first",
        archive_slugs=["AI041_ID_49"],
        metadata_fields=["Estado Contrato"],
    )

    assert resolution.answer_override == (
        "En la metadata de AI041_ID_49:\n\n"
        "| Campo | Valor |\n"
        "| --- | --- |\n"
        "| Estado Contrato | Vigente |"
    )
    assert "Documentos asociados" not in (resolution.answer_override or "")
    assert resolution.metadata_phase_used is True
    assert resolution.resolved_archive_slugs == ["AI041_ID_49"]
    assert resolution.resolved_metadata_fields == ["Estado Contrato"]
    assert resolution.metadata_only_reason == "metadata_fields_sufficient"
