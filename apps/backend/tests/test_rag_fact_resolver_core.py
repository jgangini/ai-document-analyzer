from __future__ import annotations

from datetime import date
import json

import pytest

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_parse_reference_date_from_question() -> None:
    resolved = QuestionFactResolver._parse_reference_date(
        "Â¿CuÃ¡nto tiempo le queda de vigencia al contrato? Si hoy es 20 de Marzo 2026"
    )
    assert resolved == date(2026, 3, 20)

def test_question_fact_resolver_answers_metadata_lookup_from_csv() -> None:
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
                                "Comuna": "Las Condes",
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
        question="Filtra por file RM797_ID_5515 y revisa la Forma de Pago reportada en metadata.",
        user_id=7,
        file_ids=[102],
    )

    assert resolution.narrowed_file_ids == [102]
    assert resolution.answer_override == (
        "En la metadata de RM797_ID_5515:\n\n"
        "| Campo | Valor |\n"
        "| --- | --- |\n"
        "| Forma de Pago | Deposito |"
    )
    assert resolution.facts_used_count == 1
    assert "RM797_ID_5515: Forma de Pago=Deposito" in resolution.fact_context_text

def test_question_fact_resolver_keeps_metadata_first_file_inventory_open_for_document_modification_reasoning() -> None:
    class _MetadataAndInventoryRepository(_StubArchiveMetadataFileRepository):
        def get_archive_slug_map_for_file_ids(
            self,
            *,
            user_id: int,
            file_ids: list[int],
            include_shared: bool = False,
        ) -> dict[int, str]:
            del user_id, include_shared
            allowed = {int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0}
            return {
                int(row.get("file_id") or 0): str(row.get("archive_slug") or "")
                for row in self.file_rows
                if int(row.get("file_id") or 0) in allowed and str(row.get("archive_slug") or "").strip()
            }

    file_rows = [
        {
            "file_id": file_id,
            "archive_slug": "LA122_ID_3979",
            "file_input_file_name": file_name,
            "file_code": "LA122",
            "file_state": 3,
            "file_page_count": pages,
        }
        for file_id, file_name, pages in (
            (201, "LA122_Contrato_Base.pdf", 10),
            (202, "LA122_Modificacion_1.pdf", 12),
            (203, "LA122_Modificacion_2.pdf", 8),
            (204, "LA122_Anexo_Canon.pdf", 4),
            (205, "LA122_Acta_Entrega.pdf", 3),
            (206, "LA122_Carta_Aviso.pdf", 2),
        )
    ]
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_MetadataAndInventoryRepository(
            [
                {
                    "file_id": 201,
                    "archive_slug": "LA122_ID_3979",
                    "metadata_json": json.dumps(
                        {
                            "file": "LA122_ID_3979",
                            "fields": {
                                "Codigo de Sitio": "LA122",
                                "Tipo de Contrato": "Arriendo",
                                "Estado Contrato": "Vigente",
                            },
                        },
                        ensure_ascii=False,
                    ),
                }
            ],
            file_rows=file_rows,
        ),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question="Que documentos integran el expediente y cuales modifican el contrato base?",
        user_id=7,
        file_ids=[201, 202, 203, 204, 205, 206],
        metadata_mode="metadata_first",
        archive_slugs=["LA122_ID_3979"],
    )

    assert resolution.answer_override is None
    assert resolution.document_phase_required is True
    assert resolution.narrowed_file_ids == [201, 202, 203, 204, 205, 206]
    assert "Document inventory context" in resolution.fact_context_text
    assert "LA122_Contrato_Base.pdf" in resolution.fact_context_text
    assert "LA122_Modificacion_1.pdf" in resolution.fact_context_text
    assert "LA122_Carta_Aviso.pdf" in resolution.fact_context_text

def test_question_fact_resolver_keeps_document_grounded_scope_within_requested_file_ids() -> None:
    class _StubFactsRepository:
        def list_group_ids_for_file_ids(
            self,
            *,
            user_id: int,
            file_ids: list[int],
            include_shared: bool = False,
        ) -> list[int]:
            assert user_id == 7
            assert file_ids == [101, 102]
            assert include_shared is True
            return [11, 12]

        def list_file_ids_for_group_ids(
            self,
            *,
            user_id: int,
            group_ids: list[int],
            current_only: bool,
            include_shared: bool = False,
        ) -> list[int]:
            assert user_id == 7
            assert group_ids == [11, 12]
            assert current_only is False
            assert include_shared is True
            return [101, 999, 102, 998]

    resolver = QuestionFactResolver(
        repository=_StubFactsRepository(),
        file_repository=_StubArchiveMetadataFileRepository([]),
    )

    resolution = resolver.resolve(
        question_class="exhaustive_synthesis",
        question="Compara RM797_ID_1668 y RM797_ID_5515 usando metadata y documentos.",
        user_id=7,
        file_ids=[101, 102],
    )

    assert resolution.narrowed_file_ids == [101, 102]
    assert resolution.file_group_ids == [11, 12]
    assert resolution.facts_used_count == 2

def test_question_fact_resolver_returns_document_inventory_from_files_repository() -> None:
    file_repository = _RecordingInventoryFileRepository(
        [
            {
                "file_id": 201,
                "archive_slug": "AI041_ID_49",
                "file_input_file_name": "AI041.pdf",
                "file_code": "AI041",
                "file_state": 3,
                "file_page_count": 18,
            },
            {
                "file_id": 202,
                "archive_slug": "RM797_ID_1668",
                "file_input_file_name": "RM797_contrato.pdf",
                "file_code": "RM797",
                "file_state": 2,
                "file_page_count": 12,
            },
        ]
    )
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=file_repository,
    )

    resolution = resolver.resolve(
        question_class="inventory",
        question="Listame todos los documentos que tengo disponibles.",
        user_id=7,
        file_ids=[],
    )

    assert resolution.answer_override is not None
    assert "Documentos disponibles (2)" in resolution.answer_override
    assert "| # | Archivo | Documento | Codigo | Estado | Paginas |" in resolution.answer_override
    assert "| 1 | AI041_ID_49 | AI041.pdf | AI041 | completed | 18 |" in resolution.answer_override
    assert "| 2 | RM797_ID_1668 | RM797_contrato.pdf | RM797 | processing | 12 |" in resolution.answer_override
    assert resolution.facts_used_count == 2
    assert file_repository.include_shared_calls == [True]

def test_question_fact_resolver_routes_content_filtered_document_selection_to_retrieval() -> None:
    file_repository = _RecordingInventoryFileRepository(
        [
            {
                "file_id": 201,
                "archive_slug": "OP100_ID_1",
                "file_input_file_name": "OP100_manual.pdf",
                "file_code": "OP100",
                "file_state": 3,
                "file_page_count": 18,
            },
            {
                "file_id": 202,
                "archive_slug": "OP200_ID_2",
                "file_input_file_name": "OP200_anexo.pdf",
                "file_code": "OP200",
                "file_state": 3,
                "file_page_count": 9,
            },
        ]
    )
    resolver = QuestionFactResolver(repository=object(), file_repository=file_repository)

    resolution = resolver.resolve(
        question_class="inventory",
        question="Lista los documentos que mencionan cumplimiento operativo.",
        user_id=7,
        file_ids=[201, 202],
    )

    assert resolution.answer_override is None
    assert resolution.narrowed_file_ids == [201, 202]
    assert resolution.document_phase_required is True
    assert resolution.answerability_route == "documents"
    assert "Documentos disponibles" not in resolution.fact_context_text
    assert file_repository.include_shared_calls == []

def test_question_fact_resolver_prefers_associated_documents_over_inherited_metadata_field() -> None:
    file_repository = _StubArchiveMetadataFileRepository(
        [
            {
                "file_id": 201,
                "archive_slug": "AI041_ID_49",
                "metadata_json": json.dumps(
                    {
                        "file": "AI041_ID_49",
                        "fields": {
                            "Renta o Precio Vigente": "420",
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        file_rows=[
            {
                "file_id": 201,
                "archive_slug": "AI041_ID_49",
                "file_input_file_name": "AI041.pdf",
                "file_code": "AI041",
                "file_state": 3,
                "file_page_count": 18,
            },
            {
                "file_id": 202,
                "archive_slug": "AI041_ID_49",
                "file_input_file_name": "AI041_Modificacion_1.pdf",
                "file_code": "AI041",
                "file_state": 3,
                "file_page_count": 6,
            },
        ],
    )
    resolver = QuestionFactResolver(repository=object(), file_repository=file_repository)

    resolution = resolver.resolve(
        question_class="extractive",
        question="Segun AI041_ID_49 cuales son sus documentos asociados?",
        user_id=7,
        file_ids=[201, 202],
        metadata_mode="auto",
        archive_slugs=["AI041_ID_49"],
        metadata_fields=["Renta o Precio Vigente"],
    )

    assert resolution.answer_override is not None
    assert "Documentos asociados a AI041_ID_49 (2)" in resolution.answer_override
    assert "AI041.pdf" in resolution.answer_override
    assert "AI041_Modificacion_1.pdf" in resolution.answer_override
    assert "Renta o Precio Vigente" not in resolution.answer_override
    assert "420" not in resolution.answer_override

def test_question_fact_resolver_keeps_inventory_as_context_when_question_requires_document_reasoning() -> None:
    file_repository = _RecordingInventoryFileRepository(
        [
            {
                "file_id": 201,
                "archive_slug": "LA122_ID_3979",
                "file_input_file_name": "LA122.PDF",
                "file_code": "LA122",
                "file_state": 3,
                "file_page_count": 10,
            },
            {
                "file_id": 202,
                "archive_slug": "LA122_ID_3979",
                "file_input_file_name": "LA122_Modificacion.pdf",
                "file_code": "LA122",
                "file_state": 3,
                "file_page_count": 12,
            },
            {
                "file_id": 203,
                "archive_slug": "LA122_ID_3979",
                "file_input_file_name": "LA122_Modificacion_2.pdf",
                "file_code": "LA122",
                "file_state": 3,
                "file_page_count": 8,
            },
        ]
    )
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=file_repository,
    )

    resolution = resolver.resolve(
        question_class="inventory",
        question=(
            "Que documentos integran el expediente y cuales son los que modifican el contrato base? "
            "Lista los nombres exactos de los PDF relevantes y cita la evidencia documental."
        ),
        user_id=7,
        file_ids=[201, 202, 203],
    )

    assert resolution.answer_override is None
    assert resolution.document_phase_required is True
    assert resolution.narrowed_file_ids == [201, 202, 203]
    assert "Documentos disponibles (3)" in resolution.fact_context_text
    assert "LA122_Modificacion.pdf" in resolution.fact_context_text

def test_question_fact_resolver_answers_global_multi_contract_site_question_from_metadata() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 101,
                    "archive_slug": "LA122_ID_18467",
                    "metadata_json": json.dumps(
                        {"file": "LA122_ID_18467", "fields": {"Codigo de Sitio": "LA122", "Id": "18467"}},
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 102,
                    "archive_slug": "LA122_ID_3979",
                    "metadata_json": json.dumps(
                        {"file": "LA122_ID_3979", "fields": {"Codigo de Sitio": "LA122", "Id": "3979"}},
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 103,
                    "archive_slug": "RM797_ID_1668",
                    "metadata_json": json.dumps(
                        {"file": "RM797_ID_1668", "fields": {"Codigo de Sitio": "RM797", "Id": "1668"}},
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 104,
                    "archive_slug": "RM797_ID_5515",
                    "metadata_json": json.dumps(
                        {"file": "RM797_ID_5515", "fields": {"Codigo de Sitio": "RM797", "Id": "5515"}},
                        ensure_ascii=False,
                    ),
                },
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question="Usando toda la metadata cargada, que sitios tienen mas de un ID de contrato?",
        user_id=7,
        file_ids=[],
    )

    assert resolution.answer_override is not None
    assert "LA122: 18467, 3979" in resolution.answer_override
    assert "RM797: 1668, 5515" in resolution.answer_override
    assert resolution.facts_used_count == 4

def test_question_fact_resolver_prefers_requested_metadata_fields_over_generic_aggregate_counts() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 101,
                    "archive_slug": "ESTAN041_ID_14010",
                    "metadata_json": json.dumps(
                        {
                            "file": "ESTAN041_ID_14010",
                            "fields": {
                                "Nombre de Propietario Principal": "MINISTERIO DE BIENES NACIONALES",
                                "Nombre Beneficiario": "MINISTERIO DE BIENES NACIONALES",
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
                {
                    "file_id": 102,
                    "archive_slug": "ZU163_ID_3630",
                    "metadata_json": json.dumps(
                        {
                            "file": "ZU163_ID_3630",
                            "fields": {
                                "Nombre de Propietario Principal": "ATC SITIOS CHILE S.A.",
                                "Nombre Beneficiario": "MINISTERIO DE BIENES NACIONALES",
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
        question="Que contratos comparten el mismo propietario principal o beneficiario?",
        user_id=7,
        file_ids=[101, 102],
        metadata_fields=["Nombre de Propietario Principal", "Nombre Beneficiario"],
    )

    assert resolution.answer_override is not None
    assert "| Archivo | Nombre de Propietario Principal | Nombre Beneficiario |" in resolution.answer_override
    assert "| ESTAN041_ID_14010 | MINISTERIO DE BIENES NACIONALES | MINISTERIO DE BIENES NACIONALES |" in resolution.answer_override
    assert "| ZU163_ID_3630 | ATC SITIOS CHILE S.A. | MINISTERIO DE BIENES NACIONALES |" in resolution.answer_override
    assert "hay 2 beneficiarios distintos" not in resolution.answer_override
