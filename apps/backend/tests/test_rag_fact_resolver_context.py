from __future__ import annotations

from datetime import date
import json

import pytest

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_question_fact_resolver_keeps_only_matching_archive_context_for_broad_manual_scope() -> None:
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
            ]
        ),
    )

    resolution = resolver.resolve(
        question_class="metadata_comparison",
        question=(
            "Usando metadata y documentos de AT565_ID_3820, valida si el Estado Contrato es Vigente "
            "y respaldalo con AT565.PDF."
        ),
        user_id=7,
        file_ids=[91, 92],
    )

    assert resolution.narrowed_file_ids == [92]
    assert resolution.answer_override is None
    assert "AT565_ID_3820: Estado Contrato=Vigente" in resolution.fact_context_text
    assert "AI041_ID_49" not in resolution.fact_context_text

def test_question_fact_resolver_expands_document_evidence_scope_to_all_matching_archive_files() -> None:
    resolver = QuestionFactResolver(
        repository=object(),
        file_repository=_StubArchiveMetadataFileRepository(
            [
                {
                    "file_id": 91,
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
                    "file_id": 93,
                    "archive_slug": "AI041_ID_49",
                    "metadata_json": json.dumps(
                        {
                            "file": "AI041_ID_49",
                            "fields": {
                                "Estado Contrato": "Vigente",
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
            "Usando metadata y documentos de AT565_ID_3820, valida si el Estado Contrato es Vigente "
            "y respaldalo con AT565.PDF."
        ),
        user_id=7,
        file_ids=[91, 92, 93],
    )

    assert resolution.narrowed_file_ids == [91, 92]
    assert resolution.answer_override is None
    assert "AT565_ID_3820: Estado Contrato=Vigente" in resolution.fact_context_text

def test_question_fact_resolver_flags_missing_metadata_in_single_field_comparison() -> None:
    answer = QuestionFactResolver._build_metadata_answer(
        question="Compara RM797_ID_1668 y RM797_ID_5515 en Estado Contrato.",
        metadata_rows=[
            ArchiveMetadataEntry(
                file_id=101,
                archive_slug="RM797_ID_1668",
                fields={"Fecha de Término del Contrato": "10/12/2025"},
            ),
            ArchiveMetadataEntry(
                file_id=102,
                archive_slug="RM797_ID_5515",
                fields={"Estado Contrato": "Terminado"},
            ),
        ],
        requested_fields=["Estado Contrato"],
        compare_requested=True,
    )

    assert answer == (
        "Estado Contrato por archivo:\n\n"
        "| Archivo | Estado Contrato |\n"
        "| --- | --- |\n"
        "| RM797_ID_5515 | Terminado |\n\n"
        "Falta metadata para: RM797_ID_1668."
    )

def test_question_fact_resolver_formats_single_field_listing_as_markdown_table() -> None:
    answer = QuestionFactResolver._build_metadata_answer(
        question="Lista la",
        metadata_rows=[
            ArchiveMetadataEntry(
                file_id=101,
                archive_slug="AI041_ID_49",
                fields={"Renta o Precio Vigente": "420"},
            ),
            ArchiveMetadataEntry(
                file_id=102,
                archive_slug="RM797_ID_1668",
                fields={"Renta o Precio Vigente": "442"},
            ),
        ],
        requested_fields=["Renta o Precio Vigente"],
        compare_requested=False,
    )

    assert answer == (
        "Renta o Precio Vigente por archivo:\n\n"
        "| Archivo | Renta o Precio Vigente |\n"
        "| --- | --- |\n"
        "| AI041_ID_49 | 420 |\n"
        "| RM797_ID_1668 | 442 |"
    )
    assert "; " not in answer

def test_question_fact_resolver_marks_missing_metadata_in_multi_field_comparison() -> None:
    answer = QuestionFactResolver._build_metadata_answer(
        question=(
            "Compara RM797_ID_1668 y RM797_ID_5515 en Estado Contrato y Fecha de Término del Contrato."
        ),
        metadata_rows=[
            ArchiveMetadataEntry(
                file_id=101,
                archive_slug="RM797_ID_1668",
                fields={"Fecha de Término del Contrato": "10/12/2025"},
            ),
            ArchiveMetadataEntry(
                file_id=102,
                archive_slug="RM797_ID_5515",
                fields={
                    "Estado Contrato": "Terminado",
                    "Fecha de Término del Contrato": "22/07/2025",
                },
            ),
        ],
        requested_fields=["Estado Contrato", "Fecha de Término del Contrato"],
        compare_requested=True,
    )

    assert answer == (
        "Comparacion de metadata:\n\n"
        "| Archivo | Estado Contrato | Fecha de Término del Contrato |\n"
        "| --- | --- | --- |\n"
        "| RM797_ID_1668 | sin metadata | 10/12/2025 |\n"
        "| RM797_ID_5515 | Terminado | 22/07/2025 |"
    )

def test_fact_resolver_expands_archive_scope_with_shared_documents() -> None:
    class _SharedArchiveMapRepository:
        def __init__(self) -> None:
            self.include_shared_seen: bool | None = None

        def get_archive_slug_map_for_file_ids(
            self,
            *,
            user_id: int,
            file_ids: list[int],
            include_shared: bool = False,
        ) -> dict[int, str]:
            del user_id
            self.include_shared_seen = include_shared
            return {int(file_id): "LA122_ID_3979" for file_id in file_ids}

    file_repository = _SharedArchiveMapRepository()
    resolver = QuestionFactResolver(repository=object(), file_repository=file_repository)

    expanded = resolver._expand_document_evidence_file_ids(
        user_id=7,
        candidate_file_ids=[201, 202, 203, 204, 205, 206],
        metadata_rows=[
            ArchiveMetadataEntry(
                file_id=201,
                archive_slug="LA122_ID_3979",
                fields={"Estado Contrato": "Vigente"},
            )
        ],
    )

    assert file_repository.include_shared_seen is True
    assert expanded == [201, 202, 203, 204, 205, 206]

def test_archive_metadata_context_prioritizes_dynamic_fields_before_context_cutoff() -> None:
    class _StubRepository:
        def get_archive_metadata_for_file_ids(
            self,
            *,
            user_id: int,
            file_ids: list[int],
            include_shared: bool = False,
        ) -> list[dict[str, object]]:
            del user_id, file_ids, include_shared
            fields = {f"Campo Flexible {index}": f"valor largo {index}" for index in range(80)}
            fields.update(
                {
                    "Renta o Precio Vigente": 504,
                    "Tipo de Moneda": "UF",
                    "Fecha de Término del Contrato": "01/08/2027",
                    "Estado Contrato": "Terminado",
                    "Estado Actividad": "Inactivo",
                }
            )
            return [
                {
                    "archive_slug": "LA122_ID_3979",
                    "metadata_json": json.dumps({"file": "LA122_ID_3979", "fields": fields}, ensure_ascii=False),
                }
            ]

    resolver = QuestionFactResolver(repository=object(), file_repository=_StubRepository())

    context = resolver._build_archive_metadata_context(user_id=7, file_ids=[501])

    assert "Renta o Precio Vigente=504" in context
    assert "Tipo de Moneda=UF" in context
    assert "Fecha de Término del Contrato=01/08/2027" in context
    assert "Estado Contrato=Terminado" in context
    assert "Estado Actividad=Inactivo" in context

def test_fact_context_summary_prioritizes_dynamic_metadata_values_before_truncation() -> None:
    filler = "; ".join(f"Campo Flexible {index}=valor largo {index}" for index in range(80))
    fact_context = (
        "Archive metadata context:\n"
        "LA122_ID_3979: "
        f"{filler}; "
        "Renta o Precio Vigente=504; Tipo de Moneda=UF; "
        "Fecha de Inicio de Vigencia del Contrato=01/08/2025; "
        "Fecha de Término del Contrato=01/08/2027; "
        "Estado Contrato=Terminado; Estado Actividad=Inactivo\n"
        "Document inventory context:\n"
        "- file_id=501 archive=LA122_ID_3979 file=LA122_Modificacion.pdf status=completed pages=8"
    )

    summary = GraphSynthesis._extract_fact_context_summary(fact_context)

    assert "Renta o Precio Vigente=504" in summary
    assert "Tipo de Moneda=UF" in summary
    assert "Fecha de Inicio de Vigencia del Contrato=01/08/2025" in summary
    assert "Fecha de Término del Contrato=01/08/2027" in summary
    assert "Estado Contrato=Terminado" in summary
    assert "Estado Actividad=Inactivo" in summary
