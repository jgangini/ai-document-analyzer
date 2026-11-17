from __future__ import annotations

from datetime import date
import json

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_scope_options_preserve_metadata_upload_csv_column_order() -> None:
    repository = _StubArchiveMetadataFileRepository(
        [
            {
                "file_id": 101,
                "archive_slug": "AI041_ID_49",
                "column_names_json": json.dumps(
                    [
                        "file",
                        "Id",
                        "Usuario",
                        "Codigo de Sitio",
                        "Nombre de Sitio",
                        "Clasificación de Sitio",
                        "Monto",
                    ],
                    ensure_ascii=False,
                ),
                "metadata_json": json.dumps(
                    {
                        "file": "AI041_ID_49",
                        "fields": {
                            "Monto": 123,
                            "Id": 49,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        file_rows=[
            {
                "file_id": 101,
                "archive_slug": "AI041_ID_49",
            }
        ],
    )

    options = _load_visible_scope_options(repository=repository, user_id=7)

    assert options.metadata_fields == [
        "Id",
        "Usuario",
        "Codigo de Sitio",
        "Nombre de Sitio",
        "Clasificación de Sitio",
        "Monto",
    ]

def test_cited_sources_include_snippets_for_chat_page_preview() -> None:
    evidence = [
        _make_evidence_item(
            file_id=101,
            file_name="RM797-Contrato_2.pdf",
            source_number=1,
            page_number=8,
            summary_text="QUINTO: El precio de arrendamiento se pagara en las condiciones pactadas.",
        ),
        _make_evidence_item(
            file_id=102,
            file_name="RM797_Rectificacion.pdf",
            source_number=2,
            page_number=3,
            summary_text="Rectificacion de antecedentes generales del contrato.",
        ),
    ]

    citations, cited_sources = _build_citations_and_cited_sources(
        analyzed_evidence=evidence,
        citation_numbers=[1],
    )

    assert citations[0].snippet.startswith("QUINTO")
    assert cited_sources[0].snippet.startswith("QUINTO")

def test_metadata_upload_summary_mapping_preserves_csv_column_order() -> None:
    summary = _map_upload_summary(
        {
            "metadata_upload_id": "upload-1",
            "source_file_name": "metadata.csv",
            "display_name": "Contracts metadata",
            "description": "Dynamic CSV",
            "metadata_status": "active",
            "column_names_json": json.dumps(["file", "Id", "Banco", "Monto"], ensure_ascii=False),
            "total_rows": 2,
            "row_count": 2,
            "matched_files_count": 1,
            "unmatched_files_count": 1,
            "linked_documents_count": 6,
            "metadata_upload_created": date(2026, 4, 21),
            "metadata_upload_updated": date(2026, 4, 22),
        }
    )

    assert summary.columns == ["file", "Id", "Banco", "Monto"]
    assert summary.display_name == "Contracts metadata"
    assert summary.matched_files_count == 1
    assert summary.linked_documents_count == 6

def test_metadata_row_preview_handles_dynamic_fields() -> None:
    row = _parse_row_preview(
        {
            "file_key": "LA122_ID_3979",
            "row_json": json.dumps(
                {
                    "file": "LA122_ID_3979",
                    "fields": {
                        "Campo Arbitrario": "valor",
                        "Monto": 1200,
                    },
                },
                ensure_ascii=False,
            ),
        }
    )

    assert row.file == "LA122_ID_3979"
    assert row.fields == {"Campo Arbitrario": "valor", "Monto": 1200}

def test_extract_latest_conversation_scope_from_messages_uses_latest_usable_scope_and_derives_archive_slugs() -> None:
    extracted = _extract_latest_conversation_scope_from_messages(
        conversation_messages=[
            {
                "session_id": 51,
                "turn_index": 1,
                "role": "assistant",
                "retrieval_metadata": {
                    "scope_file_ids": [101],
                    "question_class": "metadata_comparison",
                    "answer_mode": "facts-first",
                },
            },
            {
                "session_id": 88,
                "turn_index": 2,
                "role": "assistant",
                "retrieval_metadata": {
                    "scope_file_ids": [101, 102],
                    "question_class": "analytics",
                    "answer_mode": "facts-first",
                },
            },
            {
                "session_id": 88,
                "turn_index": 2,
                "role": "user",
                "content": "De estos 5 sitios cuales son sus ultimos documentos firmados?",
            },
        ],
        archive_slug_map_resolver=lambda file_ids: {
            101: "RM797_ID_1668",
            102: "RM797_ID_5515",
        },
    )
    assert extracted["conversation_scope_file_ids"] == [101, 102]
    assert extracted["conversation_scope_archive_slugs"] == ["RM797_ID_1668", "RM797_ID_5515"]
    assert extracted["conversation_scope_turn_index"] == 2
    assert extracted["conversation_scope_question_class"] == "analytics"
    assert extracted["conversation_scope_answer_mode"] == "facts-first"
