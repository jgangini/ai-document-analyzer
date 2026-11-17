from __future__ import annotations

from datetime import date
import json

import pytest

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_question_fact_resolver_answers_dynamic_runtime_metadata_lookup() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 501,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_5515",
                            "fields": {
                                "Segmento Comercial": "Retail Corporativo",
                                "Responsable Comercial": "Camila Soto",
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
        question="Para RM797_ID_5515, cual es el Segmento Comercial y el Responsable Comercial?",
        user_id=7,
        file_ids=[501],
    )

    assert resolution.narrowed_file_ids == [501]
    assert resolution.answer_override is not None
    assert "| Segmento Comercial | Retail Corporativo |" in resolution.answer_override
    assert "| Responsable Comercial | Camila Soto |" in resolution.answer_override
    assert resolution.facts_used_count == 2

def test_question_fact_resolver_answers_dynamic_metadata_aggregate_from_runtime_schema() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 601,
                    "archive_slug": "RM797_ID_1668",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_1668",
                            "fields": {
                                "Segmento Comercial": "Retail",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 602,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_5515",
                            "fields": {
                                "Segmento Comercial": "Industrial",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 603,
                    "archive_slug": "LA122_ID_3979",
                    "metadata_json": json.dumps(
                        {
                            "file": "LA122_ID_3979",
                            "fields": {
                                "Segmento Comercial": "Retail",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="analytics",
        question="Segun la metadata, cuantos segmentos comerciales hay?",
        user_id=7,
        file_ids=[],
    )

    assert resolution.answer_override is not None
    assert "hay 2 valores distintos de Segmento Comercial" in resolution.answer_override
    assert "Retail" in resolution.answer_override
    assert "Industrial" in resolution.answer_override
    assert resolution.facts_used_count == 3
    assert resolution.narrowed_file_ids == [601, 602, 603]

def test_question_fact_resolver_summarizes_patterns_for_requested_dynamic_metadata_fields() -> None:
    rows = []
    for index in range(1, 11):
        rows.append(
            {
                "file_id": 800 + index,
                "archive_slug": f"CASE_ID_{index}",
                "metadata_json": json.dumps(
                    {
                        "file": f"CASE_ID_{index}",
                        "fields": {
                            "Región": "Region Metropolitana de Santiago" if index <= 9 else "Region de Valparaiso",
                            "Comuna": "Santiago" if index <= 8 else "Valparaiso",
                            "Tipo de Sitio": "Macro" if index <= 7 else "Indoor",
                            "Tipo de Contrato": "Arriendo" if index <= 8 else "Compra-Venta",
                        },
                    },
                    ensure_ascii=False,
                ),
            }
        )
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(rows),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question="Existen patrones relevantes por region, comuna, tipo de sitio o tipo de contrato?",
        user_id=7,
        file_ids=[],
        metadata_mode="metadata_first",
        metadata_fields=["Región", "Comuna", "Tipo de Sitio", "Tipo de Contrato"],
    )

    assert resolution.answer_override is not None
    assert "Patrones relevantes" in resolution.answer_override
    assert "8 expedientes" in resolution.answer_override
    assert "Arriendos" in resolution.answer_override
    assert "Compra-Venta" in resolution.answer_override

def test_question_fact_resolver_answers_dynamic_duplicate_metadata_aggregate_from_runtime_schema() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 701,
                    "archive_slug": "RM797_ID_1668",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_1668",
                            "fields": {
                                "Segmento Comercial": "Retail",
                                "Folio Interno": "F-01",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 702,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_5515",
                            "fields": {
                                "Segmento Comercial": "Retail",
                                "Folio Interno": "F-02",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 703,
                    "archive_slug": "LA122_ID_3979",
                    "metadata_json": json.dumps(
                        {
                            "file": "LA122_ID_3979",
                            "fields": {
                                "Segmento Comercial": "Industrial",
                                "Folio Interno": "F-03",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="analytics",
        question="Segun la metadata, que segmentos comerciales tienen mas de un folio interno?",
        user_id=7,
        file_ids=[],
    )

    assert resolution.answer_override is not None
    assert "Segmento Comercial" in resolution.answer_override
    assert "Folio Interno" in resolution.answer_override
    assert "Retail: F-01, F-02" in resolution.answer_override
    assert resolution.facts_used_count == 2
    assert resolution.narrowed_file_ids == [701, 702]

def test_question_fact_resolver_confirms_expected_metadata_value() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 102,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_5515",
                            "fields": {
                                "Id": 5515,
                                "Forma de Pago": "Deposito",
                                "Estado Contrato": "Terminado",
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
        question="Filtra por file RM797_ID_5515 y revisa si la Forma de Pago reportada en metadata es Deposito.",
        user_id=7,
        file_ids=[102],
    )

    assert resolution.answer_override == "Si, en la metadata de RM797_ID_5515 Forma de Pago es Deposito."
    assert resolution.facts_used_count == 1

def test_question_fact_resolver_routes_uncovered_metadata_question_to_document_followup() -> None:
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
                                "Renta o Precio Vigente": 442,
                                "Pago Anticipado": False,
                                "Periodo de Pago": "Anual",
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
                                "Renta o Precio Vigente": 45,
                                "Pago Anticipado": False,
                                "Periodo de Pago": "Mensual",
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
        question="¿Hay penalización por pago atrasado de renta? RM797",
        user_id=7,
        file_ids=[101, 102],
    )

    assert resolution.narrowed_file_ids == [101, 102]
    assert resolution.answer_override is None
    assert resolution.document_phase_required is True
    assert resolution.answerability_route == "hybrid"
    assert "Resolved metadata facts:" in resolution.fact_context_text
    assert "RM797_ID_1668: Renta o Precio Vigente=442" in resolution.fact_context_text
    assert "RM797_ID_5515: Renta o Precio Vigente=45" in resolution.fact_context_text
    assert any("not cover the whole question" in note for note in resolution.confidence_notes)

def test_question_fact_resolver_uses_agnostic_metadata_coverage_for_document_followup() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 201,
                    "archive_slug": "OP123_ID_A",
                    "metadata_json": json.dumps(
                        {
                            "file": "OP123_ID_A",
                            "fields": {
                                "Fecha de Entrega": "10/01/2026",
                                "Estado del Proceso": "Aprobado",
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
        question="¿Hay justificación por retraso en la entrega? OP123",
        user_id=7,
        file_ids=[201],
    )

    assert resolution.narrowed_file_ids == [201]
    assert resolution.answer_override is None
    assert resolution.document_phase_required is True
    assert resolution.answerability_route == "hybrid"
    assert "OP123_ID_A: Fecha de Entrega=10/01/2026" in resolution.fact_context_text

def test_resolve_facts_keeps_retrieval_open_when_metadata_needs_documents() -> None:
    class _FactResolver:
        def resolve(self, **kwargs: object) -> FactResolution:
            del kwargs
            return FactResolution(
                narrowed_file_ids=[201],
                fact_context_text="Resolved metadata facts:\nOP123_ID_A: Fecha de Entrega=10/01/2026",
                answer_override=None,
                facts_used_count=1,
                metadata_phase_used=True,
                resolved_archive_slugs=["OP123_ID_A"],
                resolved_metadata_fields=["Fecha de Entrega"],
                document_phase_required=True,
                answerability_route="hybrid",
            )

    nodes = QAGraphNodes(
        intent_router=object(),
        casual_responder=object(),
        supervisor=object(),
        scope_resolver=object(),
        question_classifier=object(),
        fact_resolver=_FactResolver(),
        retrieval_tool=object(),
        analysis_agent=object(),
        hybrid_answer_tool=object(),
        page_vision_tool=object(),
        repository=object(),
    )

    patch = nodes.resolve_facts(
        {
            "question": "¿Hay justificación por retraso en la entrega? OP123",
            "original_question": "¿Hay justificación por retraso en la entrega? OP123",
            "question_class": "metadata_comparison",
            "user_id": 7,
            "file_ids": [201],
            "top_k": 5,
        }
    )

    assert patch["answer_override"] is None
    assert patch["answerability_route"] == "hybrid"

def test_question_fact_resolver_dedupes_repeated_archive_metadata_rows() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 7,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_5515",
                            "fields": {
                                "Forma de Pago": "Deposito",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 8,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {
                            "file": "RM797_ID_5515",
                            "fields": {
                                "Forma de Pago": "Deposito",
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
        question="Filtra por file RM797_ID_5515 y revisa la Forma de Pago reportada en metadata.",
        user_id=7,
        file_ids=[7, 8],
    )

    assert resolution.narrowed_file_ids == [7]
    assert resolution.answer_override == (
        "En la metadata de RM797_ID_5515:\n\n"
        "| Campo | Valor |\n"
        "| --- | --- |\n"
        "| Forma de Pago | Deposito |"
    )
    assert resolution.facts_used_count == 1

def test_question_fact_resolver_compares_metadata_between_files() -> None:
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
                                "Forma de Pago": "Transferencia Electronica",
                                "Estado Contrato": "Vigente",
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
                                "Forma de Pago": "Deposito",
                                "Estado Contrato": "Terminado",
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
            "Compara la metadata de los archivos RM797_ID_1668 y RM797_ID_5515 "
            "para Forma de Pago y Estado Contrato."
        ),
        user_id=7,
        file_ids=[101, 102],
    )

    assert resolution.narrowed_file_ids == [101, 102]
    assert resolution.answer_override is not None
    assert "| Archivo | Estado Contrato | Forma de Pago |" in resolution.answer_override
    assert "| RM797_ID_1668 | Vigente | Transferencia Electronica |" in resolution.answer_override
    assert "| RM797_ID_5515 | Terminado | Deposito |" in resolution.answer_override
    assert resolution.facts_used_count == 4
