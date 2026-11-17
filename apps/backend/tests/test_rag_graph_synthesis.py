from __future__ import annotations

from types import MethodType

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_graph_synthesis_per_document_uses_inventory_for_missing_evidence() -> None:
    synthesis = GraphSynthesis(provider=object())
    evidence = [
        _make_evidence_item(
            file_id=201,
            file_name="LA122.PDF",
            page_id=1,
            source_number=1,
            summary_text="Contrato base con condiciones originales.",
        ),
        _make_evidence_item(
            file_id=203,
            file_name="LA122_Modificacion_2.pdf",
            page_id=3,
            source_number=3,
            summary_text="Segunda modificacion con cambios de renta.",
        ),
    ]
    fact_context = "\n".join(
        [
            "Document inventory context:",
            "- file_id=201 archive=LA122_ID_3979 file=LA122.PDF status=completed pages=10",
            "- file_id=202 archive=LA122_ID_3979 file=LA122_Modificacion.pdf status=completed pages=12",
            "- file_id=203 archive=LA122_ID_3979 file=LA122_Modificacion_2.pdf status=completed pages=8",
        ]
    )

    result = synthesis.synthesize(
        question="Que documentos integran el expediente?",
        evidence=evidence,
        strategy="deep-reasoning",
        summary_mode="per_document",
        selected_docs_count=3,
        fact_context=fact_context,
        question_class="exhaustive_synthesis",
    )

    assert "Inventario documental completo" in result.answer_text
    assert "LA122.PDF" in result.answer_text
    assert "LA122_Modificacion.pdf" in result.answer_text
    assert "LA122_Modificacion_2.pdf" in result.answer_text
    assert "sin evidencia OCR suficiente" in result.answer_text
    assert "Se resumieron 2 de 3" not in result.answer_text

def test_graph_synthesis_per_document_formats_document_inventory_as_readable_markdown() -> None:
    synthesis = GraphSynthesis(provider=object())
    evidence = [
        _make_evidence_item(
            file_id=201,
            file_name="LA122.PDF",
            page_id=1,
            source_number=1,
            summary_text=(
                "Contrato base con condiciones originales sobre renta, plazo y autorizaciones. "
                "DECIMO CUARTO: texto OCR largo que no debe convertir la respuesta en una sabana."
            ),
        ),
        _make_evidence_item(
            file_id=202,
            file_name="LA122_Modificacion.pdf",
            page_id=2,
            source_number=2,
            summary_text="Modificacion del contrato de arrendamiento que ajusta condiciones del contrato base.",
        ),
    ]
    fact_context = "\n".join(
        [
            "Archive metadata context:",
            (
                "LA122_ID_3979: Estado Contrato=Vigente; Estado Actividad=Activo; "
                "Revision Final=REVISADO OK; Renta o Precio Vigente=504; Tipo de Moneda=UF; "
                "Fecha de Inicio de Vigencia del Contrato=01/08/2025; "
                "Fecha de Termino del Contrato=01/08/2027; Nombre de Propietario Principal=TRANSPORTES COSTANERA S.A."
            ),
            "Document inventory context:",
            "- file_id=201 archive=LA122_ID_3979 file=LA122.PDF status=completed pages=10",
            "- file_id=202 archive=LA122_ID_3979 file=LA122_Modificacion.pdf status=completed pages=12",
        ]
    )

    result = synthesis.synthesize(
        question="Que documentos integran el expediente y cuales modifican el contrato base?",
        evidence=evidence,
        strategy="deep-reasoning",
        summary_mode="per_document",
        selected_docs_count=2,
        fact_context=fact_context,
        question_class="exhaustive_synthesis",
    )

    assert "## Resumen" in result.answer_text
    assert "## Metadata clave" in result.answer_text
    assert "## Documentos del expediente" in result.answer_text
    assert "## Documentos que modifican o complementan el contrato base" in result.answer_text
    assert "**LA122.PDF**" in result.answer_text
    assert "**LA122_Modificacion.pdf**" in result.answer_text
    assert "[1]" not in result.answer_text
    assert "[2]" not in result.answer_text
    assert "sabana" not in result.answer_text
    assert result.citation_source_numbers == [1, 2]

def test_graph_synthesis_per_document_surfaces_broad_metadata_context() -> None:
    synthesis = GraphSynthesis(provider=object())
    evidence = [
        _make_evidence_item(
            file_id=201,
            file_name="LA122.PDF",
            page_id=1,
            source_number=1,
            summary_text="Contrato base con condiciones originales.",
        )
    ]
    fields_before_key_facts = "; ".join(f"Campo Auxiliar {index}=valor {index}" for index in range(1, 16))
    fact_context = "\n".join(
        [
            "Archive metadata context:",
            (
                "LA122_ID_3979: "
                f"{fields_before_key_facts}; "
                "Renta o Precio Vigente=504; Tipo de Moneda=UF; Periodo de Pago=Anual; "
                "Fecha de Inicio de Vigencia del Contrato=01/08/2025; "
                "Fecha de Termino del Contrato=01/08/2027"
            ),
            "Document inventory context:",
            "- file_id=201 archive=LA122_ID_3979 file=LA122.PDF status=completed pages=10",
        ]
    )

    result = synthesis.synthesize(
        question="Cual es el instrumento vigente que gobierna cada variable critica del expediente?",
        evidence=evidence,
        strategy="deep-reasoning",
        summary_mode="per_document",
        selected_docs_count=1,
        fact_context=fact_context,
        question_class="exhaustive_synthesis",
    )

    assert "Metadata estructurada" in result.answer_text
    assert "504" in result.answer_text
    assert "UF" in result.answer_text
    assert "01/08/2025" in result.answer_text
    assert "01/08/2027" in result.answer_text

def test_graph_synthesis_per_document_surfaces_resolved_metadata_facts() -> None:
    synthesis = GraphSynthesis(provider=object())
    evidence = [
        _make_evidence_item(
            file_id=301,
            file_name="RM797_-_Contrato_2.pdf",
            page_id=1,
            source_number=1,
            summary_text="Contrato con evidencia documental.",
        )
    ]

    result = synthesis.synthesize(
        question="De donde fue extraido cada dato clave utilizado en la respuesta?",
        evidence=evidence,
        strategy="deep-reasoning",
        summary_mode="per_document",
        selected_docs_count=1,
        fact_context=(
            "Resolved metadata facts:\n"
            "RM797_ID_5515: Estado Contrato=Terminado; Estado Actividad=Inactivo"
        ),
        question_class="exhaustive_synthesis",
    )

    assert "Metadata estructurada" in result.answer_text
    assert "Estado Contrato=Terminado" in result.answer_text
    assert "Estado Actividad=Inactivo" in result.answer_text

def test_graph_synthesis_per_document_keeps_representative_window() -> None:
    synthesis = GraphSynthesis(provider=object())
    filler = " ".join(f"texto{index}" for index in range(180))
    representative_text = (
        f"{filler} comparecen: por una parte SOCIEDAD TRANSPORTES COSTANERA S.A., "
        "representada por don MARIO CARLOS PACHECO VAZQUEZ y por dona "
        "JANETTE LUCILA MANSILLA TOLEDO; y por la otra ENTEL PCS TELECOMUNICACIONES S.A., "
        "representada por don FRANCISCO JAVIER SPRENGER ARROYO. "
        f"{filler}"
    )
    evidence = [
        _make_evidence_item(
            file_id=202,
            file_name="LA122_Modificacion.pdf",
            page_id=2,
            source_number=2,
            summary_text=representative_text,
        )
    ]

    result = synthesis.synthesize(
        question="Que personas o representantes aparecen con facultades para firmar?",
        evidence=evidence,
        strategy="deep-reasoning",
        summary_mode="per_document",
        selected_docs_count=1,
        fact_context="",
        question_class="exhaustive_synthesis",
    )

    assert "MARIO CARLOS PACHECO VAZQUEZ" in result.answer_text
    assert "JANETTE LUCILA MANSILLA TOLEDO" in result.answer_text
    assert "FRANCISCO JAVIER SPRENGER ARROYO" in result.answer_text

def test_graph_synthesis_per_document_metadata_question_uses_llm_not_inventory_answer() -> None:
    class _ResolvedConfig:
        model_id = "stub-model"

    class _StubProvider:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        def is_available(self) -> bool:
            return True

        def invoke_text(self, *, prompt: str, model_id: str | None = None) -> str:
            del model_id
            self.prompts.append(prompt)
            return (
                "ANSWER:\n"
                "Metadata resuelta:\n\n"
                "| Archivo | Estado Contrato | Renta o Precio Vigente |\n"
                "| --- | --- | --- |\n"
                "| RM797_ID_1668 | Vigente | 442 |\n"
                "| RM797_ID_5515 | Terminado | 45 |\n\n"
                "Con esa metadata como contexto, la evidencia documental permite responder "
                "la pregunta sin mostrar el inventario interno del expediente.\n"
                "EXECUTIVE_SUMMARY: Respuesta mixta generada con metadata y evidencia documental.\n"
                "KEY_POINTS:\n"
                "- Metadata usada como contexto.\n"
                "- Evidencia documental usada para la conclusion.\n"
                "OBLIGATIONS:\n"
                "CITATIONS: 1,2"
            )

        def resolve_config(self) -> _ResolvedConfig:
            return _ResolvedConfig()

    provider = _StubProvider()
    synthesis = GraphSynthesis(provider=provider)

    result = synthesis.synthesize(
        question="¿Hay penalización por pago atrasado de renta? RM797",
        evidence=[
            _make_evidence_item(
                file_id=301,
                file_name="RM797-Contrato_2.pdf",
                page_id=8001,
                page_number=8,
                source_number=1,
                summary_text="Clausula con condiciones de pago y efectos del atraso.",
            ),
            _make_evidence_item(
                file_id=302,
                file_name="RM797_Rectificacion.pdf",
                page_id=3001,
                page_number=3,
                source_number=2,
                summary_text="Rectificacion relacionada con antecedentes del mismo expediente.",
            ),
        ],
        strategy="deep-reasoning",
        summary_mode="per_document",
        selected_docs_count=2,
        fact_context=(
            "Resolved metadata facts:\n"
            "RM797_ID_1668: Estado Contrato=Vigente; Renta o Precio Vigente=442\n"
            "RM797_ID_5515: Estado Contrato=Terminado; Renta o Precio Vigente=45\n"
            "Document inventory context:\n"
            "- file_id=301 archive=RM797_ID_1668 file=RM797-Contrato_2.pdf status=completed pages=12\n"
            "- file_id=302 archive=RM797_ID_5515 file=RM797_Rectificacion.pdf status=completed pages=3"
        ),
        question_class="metadata_comparison",
    )

    assert provider.prompts
    assert result.model_used == "langgraph-oci-synthesis:stub-model"
    assert "Metadata resuelta" in result.answer_text
    assert "Inventario documental completo" not in result.answer_text
    assert "## Documentos del expediente" not in result.answer_text
    assert "Lectura OCR" not in result.answer_text
    assert result.citation_source_numbers == [1, 2]

def test_graph_synthesis_retries_tabular_request_when_first_answer_lacks_markdown_table() -> None:
    class _ResolvedConfig:
        model_id = "stub-model"

    class _StubProvider:
        def __init__(self) -> None:
            self.prompts: list[str] = []
            self.responses = [
                (
                    "A continuacion se presenta una tabla con campos relevantes, pero sin tabla real.\n"
                    "EXECUTIVE_SUMMARY: resumen interno\n"
                    "KEY_POINTS:\n"
                    "- punto\n"
                    "CITATIONS: 1,2"
                ),
                (
                    "ANSWER:\n"
                    "| Campo | Valor | Fuente | Nota |\n"
                    "| --- | --- | --- | --- |\n"
                    "| Tipo de Documento | Contrato de arrendamiento y servidumbres | AI041.pdf - page 1 | Extraido del encabezado contractual |\n"
                    "| Renta Anual | 200 UF | AI041.pdf - page 7 | Pago anual anticipado |\n"
                    "EXECUTIVE_SUMMARY: Tabla de campos clave generada desde evidencia OCR.\n"
                    "KEY_POINTS:\n"
                    "- Tipo de documento identificado\n"
                    "- Renta anual identificada\n"
                    "OBLIGATIONS:\n"
                    "- Pago anual anticipado\n"
                    "CITATIONS: 1,2"
                ),
            ]

        def is_available(self) -> bool:
            return True

        def invoke_text(self, *, prompt: str, model_id: str | None = None) -> str:
            del model_id
            self.prompts.append(prompt)
            return self.responses.pop(0)

        def resolve_config(self) -> _ResolvedConfig:
            return _ResolvedConfig()

    provider = _StubProvider()
    synthesis = GraphSynthesis(provider=provider)

    result = synthesis.synthesize(
        question=(
            "Analiza todo el documento AI041.pdf y muestra todos los campos que consideres "
            "relevantes en una tabla con sus referencias por pagina."
        ),
        evidence=[
            _make_evidence_item(
                file_id=701,
                file_name="AI041.pdf",
                page_id=9001,
                page_number=1,
                source_number=1,
                summary_text="Contrato de arrendamiento y servidumbres.",
            ),
            _make_evidence_item(
                file_id=701,
                file_name="AI041.pdf",
                page_id=9007,
                page_number=7,
                source_number=2,
                summary_text="Renta anual de 200 Unidades de Fomento, pagadera en forma anual anticipada.",
            ),
        ],
        strategy="deep-reasoning",
        question_class="exhaustive_synthesis",
    )

    assert len(provider.prompts) == 2
    assert "faltaba una tabla Markdown valida" in provider.prompts[1]
    assert "| Campo | Valor | Fuente | Nota |" in result.answer_text
    assert "| Renta Anual | 200 UF | AI041.pdf - page 7 | Pago anual anticipado |" in result.answer_text
    assert "EXECUTIVE_SUMMARY" not in result.answer_text
    assert result.executive_summary == "Tabla de campos clave generada desde evidencia OCR."
    assert result.citation_source_numbers == [1, 2]

def test_graph_synthesis_extracts_raw_answer_without_internal_sections() -> None:
    raw_text = (
        "A continuacion se presenta el resultado solicitado.\n"
        "EXECUTIVE_SUMMARY: este texto no debe mostrarse dentro de ANSWER\n"
        "CITATIONS: 1"
    )

    assert (
        GraphSynthesis._extract_answer_section_or_raw(raw_text)
        == "A continuacion se presenta el resultado solicitado."
    )

def test_repair_document_file_name_handles_resciliacion_loss() -> None:
    repaired = repair_document_file_name("RM797_-_Resciliacin_Arrendamiento_Finiquito_y_Pago.pdf")

    assert repaired == "RM797_-_Resciliacion_Arrendamiento_Finiquito_y_Pago.pdf"

def test_markdown_selector_expected_terms_normalize_repaired_filenames_and_slashes() -> None:
    from apps.backend.tests.run_rag_markdown_selector_battery import _expected_terms_report

    matched, missing = _expected_terms_report(
        answer_text=(
            "Estado Contrato: Terminado; Estado Actividad: Inactivo. "
            "Documento: AI041_Carta_Aviso_Cesion_Contrato_Alba_ATC.pdf."
        ),
        expected_terms=(
            "Terminado/Inactivo",
            "AI041_Carta_Aviso_Cesin_Contrato_Alba_ATC.pdf",
        ),
    )

    assert matched == [
        "Terminado/Inactivo",
        "AI041_Carta_Aviso_Cesin_Contrato_Alba_ATC.pdf",
    ]
    assert missing == []

def test_hybrid_answer_tool_keeps_all_evidence_for_per_document_mode() -> None:
    class _StubSynthesisAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run(self, **kwargs) -> LLMResult:
            self.calls.append(dict(kwargs))
            evidence = list(kwargs["evidence"])
            names = ", ".join(item.file_name for item in evidence)
            return LLMResult(
                answer_text=names,
                executive_summary=names,
                key_points=[names],
                obligations=[],
                citation_source_numbers=[int(item.source_number) for item in evidence],
                model_used="stub-synthesis",
            )

    class _StubPageVisionTool:
        def analyze(self, **kwargs) -> VisualInspectionResult:
            raise AssertionError("visual analysis is not expected in this test")

    synthesis_agent = _StubSynthesisAgent()
    tool = HybridAnswerTool(
        settings=Settings(_env_file=None, ANSWER_MAX_EVIDENCE=3),
        page_vision_tool=_StubPageVisionTool(),
        synthesis_agent=synthesis_agent,
    )
    evidence = [
        _make_evidence_item(file_id=file_id, file_name=f"doc-{file_id}.pdf", source_number=file_id)
        for file_id in range(1, 7)
    ]

    result = tool.answer(
        question="Lista los documentos seleccionados.",
        evidence=evidence,
        strategy="deep-reasoning",
        summary_mode="per_document",
        selected_docs_count=6,
        question_class="exhaustive_synthesis",
    )

    assert len(synthesis_agent.calls) == 1
    assert len(synthesis_agent.calls[0]["evidence"]) == 6
    assert "doc-6.pdf" in result.llm_result.answer_text
    assert result.llm_result.citation_source_numbers == [1, 2, 3, 4, 5, 6]

def test_hybrid_answer_tool_keeps_all_evidence_for_explicit_full_document_request() -> None:
    class _StubSynthesisAgent:
        def __init__(self) -> None:
            self.calls: list[dict[str, object]] = []

        def run(self, **kwargs) -> LLMResult:
            self.calls.append(dict(kwargs))
            evidence = list(kwargs["evidence"])
            pages = ", ".join(str(item.page_number) for item in evidence)
            return LLMResult(
                answer_text=pages,
                executive_summary=pages,
                key_points=[pages],
                obligations=[],
                citation_source_numbers=[int(item.source_number) for item in evidence],
                model_used="stub-synthesis",
            )

    class _StubPageVisionTool:
        def analyze(self, **kwargs) -> VisualInspectionResult:
            raise AssertionError("visual analysis is not expected in this test")

    synthesis_agent = _StubSynthesisAgent()
    tool = HybridAnswerTool(
        settings=Settings(_env_file=None, ANSWER_MAX_EVIDENCE=3),
        page_vision_tool=_StubPageVisionTool(),
        synthesis_agent=synthesis_agent,
    )
    evidence = [
        _make_evidence_item(
            file_id=701,
            file_name="AI041.pdf",
            page_id=9000 + page_number,
            source_number=page_number,
            page_number=page_number,
            summary_text=f"Texto OCR pagina {page_number}.",
        )
        for page_number in range(1, 7)
    ]

    result = tool.answer(
        question="Analiza todo el documento AI041.pdf y muestrame una lista completa clave valor.",
        evidence=evidence,
        strategy="deep-reasoning",
        summary_mode="default",
        selected_docs_count=1,
        question_class="exhaustive_synthesis",
    )

    assert len(synthesis_agent.calls) == 1
    assert len(synthesis_agent.calls[0]["evidence"]) == 6
    assert result.llm_result.answer_text == "1, 2, 3, 4, 5, 6"
    assert any("Cobertura de documento completo: 6 paginas" in note for note in result.confidence_notes)

def test_hybrid_answer_tool_prepends_metadata_table_for_mixed_document_answer() -> None:
    class _StubSynthesisAgent:
        def run(self, **kwargs) -> LLMResult:
            del kwargs
            return LLMResult(
                answer_text=(
                    "## Metadata clave\n"
                    "Metadata estructurada priorizada desde el CSV.\n\n"
                    "No hay evidencia suficiente en los documentos provistos que especifique una penalizacion "
                    "por pago atrasado de renta."
                ),
                executive_summary="No se encontro penalizacion documental.",
                key_points=["No se encontro penalizacion documental."],
                obligations=[],
                citation_source_numbers=[1, 2],
                model_used="stub-synthesis",
            )

    class _StubPageVisionTool:
        def analyze(self, **kwargs) -> VisualInspectionResult:
            raise AssertionError("visual analysis is not expected in this test")

    tool = HybridAnswerTool(
        settings=Settings(_env_file=None, ANSWER_MAX_EVIDENCE=5),
        page_vision_tool=_StubPageVisionTool(),
        synthesis_agent=_StubSynthesisAgent(),
    )

    result = tool.answer(
        question="Hay penalizacion por pago atrasado de renta? RM797",
        evidence=[
            _make_evidence_item(
                file_id=101,
                file_name="RM797-Contrato_2.pdf",
                source_number=1,
                page_number=8,
                summary_text=(
                    "El contrato detalla el valor de la renta y la forma de pago, pero este extracto OCR "
                    "no describe multas por retraso."
                ),
            ),
            _make_evidence_item(
                file_id=102,
                file_name="RM797_Rectificacion.pdf",
                source_number=2,
                page_number=3,
                summary_text=(
                    "La rectificacion confirma antecedentes del contrato y mantiene referencias de pago, "
                    "sin describir una penalizacion por mora."
                ),
            ),
        ],
        strategy="fast-grounded",
        question_class="metadata_comparison",
        fact_context_text=(
            "Resolved metadata facts:\n"
            "RM797_ID_1668: Renta o Precio Vigente=442; Pago Anticipado=NO; Periodo de Pago=Anual\n"
            "RM797_ID_5515: Renta o Precio Vigente=45; Pago Anticipado=NO; Periodo de Pago=Mensual\n"
            "Archive metadata context:\n"
            "RM797_ID_1668: Estado Contrato=Vigente"
        ),
    )

    assert result.llm_result.answer_text.startswith(
        "Metadata resuelta:\n\n"
        "| Archivo | Renta o Precio Vigente | Pago Anticipado | Periodo de Pago |\n"
        "| --- | --- | --- | --- |\n"
        "| RM797_ID_1668 | 442 | NO | Anual |\n"
        "| RM797_ID_5515 | 45 | NO | Mensual |"
    )
    assert "No hay evidencia suficiente en los documentos provistos" in result.llm_result.answer_text
    assert result.llm_result.citation_source_numbers == [1, 2]
    assert any("Metadata table" in note for note in result.confidence_notes)

def test_representative_excerpt_stitches_people_names_across_pages() -> None:
    items = GraphSynthesis._build_per_document_items(
        [
            EvidenceItem(
                source_number=1,
                file_id=501,
                file_name="LA122_Modificacion.pdf",
                archive_slug="LA122_ID_3979",
                page_id=5011,
                page_number=1,
                score=0.95,
                summary_text=(
                    "comparecen SOCIEDAD TRANSPORTES COSTANERA S.A., representada por "
                    "don MARIO CARLOS PACHECO VAZQUEZ y por dona JANETTE LUCILA MANSILLA"
                ),
                image_path_local="",
            ),
            EvidenceItem(
                source_number=2,
                file_id=501,
                file_name="LA122_Modificacion.pdf",
                archive_slug="LA122_ID_3979",
                page_id=5012,
                page_number=2,
                score=0.60,
                summary_text=(
                    "TOLEDO, chilena, y por la otra ENTEL PCS TELECOMUNICACIONES S.A., "
                    "representada por don FRANCISCO JAVIER SPRENGER ARROYO."
                ),
                image_path_local="",
            ),
        ],
        question="Que personas o representantes aparecen con facultades para firmar?",
    )

    assert len(items) == 1
    excerpt = str(items[0]["summary_excerpt"])
    assert "JANETTE LUCILA MANSILLA" in excerpt
    assert "TOLEDO" in excerpt
    assert "FRANCISCO JAVIER SPRENGER ARROYO" in excerpt
