from __future__ import annotations

import pytest

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_extract_candidate_codes_from_question_ignores_single_letter_tokens() -> None:
    codes = extract_candidate_codes_from_question(
        "Genera un analisis de RM797 y RM798, pero no del decreto N667."
    )
    assert codes == ["RM797", "RM798"]

def test_extract_candidate_codes_from_question_ignores_pdf_basenames() -> None:
    codes = extract_candidate_codes_from_question(
        "Compara AI041_Carta_Aviso_Cesin_Contrato_Alba_ATC.pdf y "
        "ATC-Comunicacin_Entel_Chile_1275126_Sitios.pdf."
    )
    assert codes == []

def test_extract_candidate_file_names_from_question_preserves_pdf_names() -> None:
    file_names = extract_candidate_file_names_from_question(
        "Analiza todo el documento AI041.pdf y comparalo con AI041_Modificacion.pdf."
    )

    assert file_names == ["AI041.pdf", "AI041_Modificacion.pdf"]

def test_scope_resolver_uses_manual_scope_first() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Genera un analisis de los contratos seleccionados",
        user_id=7,
        file_ids=[104, 101],
        allow_inferred_scope=True,
    )
    assert resolution.scope_origin == "manual"
    assert resolution.file_ids == [104, 101]
    assert resolution.ignored_inferred_scope is False

def test_scope_resolver_requests_accessible_scope_queries() -> None:
    repository = _RecordingScopeRepository()
    resolver = QuestionScopeResolver(repository)
    resolution = resolver.resolve(
        question="Genera un analisis de RM797",
        user_id=7,
        file_ids=[104, 101, 102],
        allow_inferred_scope=True,
    )
    assert resolution.scope_origin == "inferred"
    assert resolution.file_ids == [101, 102]
    assert ("filter_file_ids_for_user", True) in repository.calls
    assert ("list_distinct_document_codes_for_user", True) in repository.calls

def test_scope_resolver_prefers_exact_pdf_filename_over_document_code() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Analiza todo el documento AI041.pdf y muestra sus campos clave.",
        user_id=7,
        file_ids=[],
        allow_inferred_scope=True,
    )

    assert resolution.scope_origin == "manual"
    assert resolution.scope_document_codes == []
    assert resolution.file_ids == [101]
    assert resolution.resolved_scope_file_count == 1
    assert resolution.ignored_inferred_scope is True

def test_scope_resolver_narrows_manual_scope_by_archive_slug() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Compara RM797_ID_1668 con RM797_ID_5515",
        user_id=7,
        file_ids=[104, 101, 102],
        allow_inferred_scope=True,
    )
    assert resolution.scope_origin == "metadata"
    assert resolution.scope_archive_slugs == ["RM797_ID_1668", "RM797_ID_5515"]
    assert resolution.file_ids == [101, 102]
    assert resolution.ignored_inferred_scope is False

def test_scope_resolver_narrows_manual_scope_by_document_code() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Genera un analisis de RM797",
        user_id=7,
        file_ids=[104, 101, 102],
        allow_inferred_scope=True,
    )
    assert resolution.scope_origin == "inferred"
    assert resolution.scope_document_codes == ["RM797"]
    assert resolution.file_ids == [101, 102]
    assert resolution.ignored_inferred_scope is False

def test_scope_resolver_infers_scope_from_multiple_codes() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Compara los contratos de RM797 con RM798",
        user_id=7,
        file_ids=[],
        allow_inferred_scope=True,
    )
    assert resolution.scope_origin == "inferred"
    assert resolution.scope_document_codes == ["RM797", "RM798"]
    assert resolution.file_ids == [101, 102, 103, 104]

def test_extract_candidate_archive_slugs_from_question_dedupes_extensions() -> None:
    archive_slugs = extract_candidate_archive_slugs_from_question(
        "Compara RM797_ID_1668.zip con rm797_id_1668.pdf y RM797_ID_5515"
    )
    assert archive_slugs == ["RM797_ID_1668", "RM797_ID_5515"]

def test_parse_question_selectors_extracts_inline_metadata_file_and_column_scope() -> None:
    parsed = parse_question_selectors(
        question="@metadata /file:RM797_ID_1668 /col:Estado Contrato compara vigencia y cesion",
        available_archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
        available_metadata_fields=["Estado Contrato", "Cesion a Terceros"],
    )

    assert parsed.cleaned_question == "compara vigencia y cesion"
    assert parsed.metadata_mode == "metadata_first"
    assert parsed.archive_slugs == ["RM797_ID_1668"]
    assert parsed.metadata_fields == ["Estado Contrato"]

def test_merge_question_selectors_combines_structured_and_inline_scope() -> None:
    merged = merge_question_selectors(
        question="/file:RM797_ID_1668 compara contratos",
        request_metadata_mode="auto",
        request_archive_slugs=["RM797_ID_5515"],
        request_metadata_fields=["Estado Contrato"],
        available_archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
        available_metadata_fields=["Estado Contrato", "Forma de Pago"],
    )

    assert merged.cleaned_question == "compara contratos"
    assert merged.metadata_mode == "metadata_first"
    assert merged.archive_slugs == ["RM797_ID_5515", "RM797_ID_1668"]
    assert merged.metadata_fields == ["Estado Contrato"]

def test_build_effective_selector_question_allows_metadata_selector_only_lookup() -> None:
    merged = merge_question_selectors(
        question='/file:AI041_ID_49 /col:"Renta o Precio Vigente"',
        request_metadata_mode="auto",
        request_archive_slugs=[],
        request_metadata_fields=[],
        available_archive_slugs=["AI041_ID_49", "LA122_ID_3979"],
        available_metadata_fields=["Estado Contrato", "Renta o Precio Vigente"],
    )

    assert merged.cleaned_question == ""
    assert merged.metadata_mode == "metadata_first"
    assert merged.archive_slugs == ["AI041_ID_49"]
    assert merged.metadata_fields == ["Renta o Precio Vigente"]
    assert (
        build_effective_selector_question(merged)
        == "Muestra los valores de metadata seleccionados para los archivos seleccionados."
    )

def test_build_effective_selector_question_rejects_empty_non_selector_input() -> None:
    assert (
        build_effective_selector_question(
            ParsedQuestionSelectors(cleaned_question="", metadata_mode="auto", archive_slugs=[], metadata_fields=[])
        )
        == ""
    )

def test_scope_resolver_infers_scope_from_archive_slugs() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Compara RM797_ID_1668 con RM797_ID_5515",
        user_id=7,
        file_ids=[],
        allow_inferred_scope=True,
    )
    assert resolution.scope_origin == "metadata"
    assert resolution.scope_archive_slugs == ["RM797_ID_1668", "RM797_ID_5515"]
    assert resolution.file_ids == [101, 102]

def test_scope_resolver_applies_structured_archive_slug_scope_without_question_hints() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Profundiza en estos contratos",
        user_id=7,
        file_ids=[],
        archive_slugs=["rm797_id_5515.zip"],
        allow_inferred_scope=False,
    )

    assert resolution.scope_origin == "metadata"
    assert resolution.scope_archive_slugs == ["RM797_ID_5515"]
    assert resolution.file_ids == [102]

def test_scope_resolver_raises_when_structured_archive_slug_is_outside_manual_scope() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    with pytest.raises(ScopeResolutionError) as exc_info:
        resolver.resolve(
            question="Profundiza en este archivo",
            user_id=7,
            file_ids=[103, 104],
            archive_slugs=["RM797_ID_1668"],
            allow_inferred_scope=True,
        )

    assert exc_info.value.status_code == 404
    assert "RM797_ID_1668" in str(exc_info.value)

def test_scope_resolver_inherits_previous_conversation_scope_for_deictic_follow_up() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="De estos 5 sitios cuales son sus ultimos documentos firmados?",
        user_id=7,
        file_ids=[],
        allow_inferred_scope=True,
        conversation_file_ids=[101, 102, 101],
        conversation_archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
    )
    assert resolution.scope_origin == "conversation"
    assert resolution.file_ids == [101, 102]
    assert resolution.scope_archive_slugs == ["RM797_ID_1668", "RM797_ID_5515"]

def test_scope_resolver_inherits_previous_conversation_scope_for_singular_follow_up() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Sobre ese mismo archivo, cita que dice la ultima modificacion sobre el acceso al terreno.",
        user_id=7,
        file_ids=[],
        allow_inferred_scope=True,
        conversation_file_ids=[101],
        conversation_archive_slugs=["RM797_ID_1668"],
    )
    assert resolution.scope_origin == "conversation"
    assert resolution.file_ids == [101]
    assert resolution.scope_archive_slugs == ["RM797_ID_1668"]

def test_scope_resolver_inherits_previous_scope_for_whole_document_follow_up() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Genera una lista valor de cada campo que consideres relevante para revisar todo el documento.",
        user_id=7,
        file_ids=[],
        allow_inferred_scope=True,
        conversation_file_ids=[102],
        conversation_archive_slugs=["RM797_ID_5515"],
    )

    assert resolution.scope_origin == "conversation"
    assert resolution.file_ids == [102]
    assert resolution.scope_archive_slugs == ["RM797_ID_5515"]

def test_scope_resolver_inherits_previous_scope_for_other_document_follow_up() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="¿y en el otro documento?",
        user_id=7,
        file_ids=[],
        allow_inferred_scope=True,
        conversation_file_ids=[101, 102],
        conversation_archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
    )

    assert resolution.scope_origin == "conversation"
    assert resolution.file_ids == [101, 102]
    assert resolution.scope_archive_slugs == ["RM797_ID_1668", "RM797_ID_5515"]

def test_conversation_scoped_question_carries_previous_turn_context() -> None:
    contextual = QAGraphNodes._build_conversation_scoped_question(
        question="¿y en el otro documento?",
        archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
        chat_history=[
            {"role": "user", "content": "¿Hay penalización por pago atrasado de renta? RM797"},
            {"role": "assistant", "content": "No se especifica penalización por pago atrasado de renta."},
        ],
    )

    assert "Follow-up question: ¿y en el otro documento?" in contextual
    assert "Previous user question: ¿Hay penalización por pago atrasado de renta? RM797" in contextual
    assert "RM797_ID_5515" in contextual

def test_scope_resolver_does_not_inherit_previous_scope_for_unrelated_question() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    resolution = resolver.resolve(
        question="Cuantos contratos estan vencidos?",
        user_id=7,
        file_ids=[],
        allow_inferred_scope=True,
        conversation_file_ids=[101, 102],
        conversation_archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
    )
    assert resolution.scope_origin == "global"
    assert resolution.file_ids == []

def test_scope_resolver_raises_when_archive_slug_is_missing() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    with pytest.raises(ScopeResolutionError) as exc_info:
        resolver.resolve(
            question="Compara RM797_ID_1668 con RM999_ID_1",
            user_id=7,
            file_ids=[],
            allow_inferred_scope=True,
        )
    assert exc_info.value.status_code == 404
    assert "RM999_ID_1" in str(exc_info.value)

def test_scope_resolver_raises_when_any_code_is_missing() -> None:
    resolver = QuestionScopeResolver(_StubScopeRepository())
    with pytest.raises(ScopeResolutionError) as exc_info:
        resolver.resolve(
            question="Compara RM797 con RM999",
            user_id=7,
            file_ids=[],
            allow_inferred_scope=True,
        )
    assert exc_info.value.status_code == 404
    assert "RM999" in str(exc_info.value)
