from __future__ import annotations

from types import MethodType

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_retrieval_pipeline_treats_conversation_scope_as_scoped_origin() -> None:
    assert RetrievalPipelineService._is_scoped_origin("conversation") is True

def test_extract_explicit_file_references_preserves_each_pdf_once() -> None:
    assert extract_explicit_file_references(
        "Compara AI041.pdf, AI041_Modificacin_1.pdf y AI041.pdf dentro del mismo folio."
    ) == [
        "AI041.pdf",
        "AI041_Modificacin_1.pdf",
    ]

def test_retrieval_question_expands_hybrid_generically() -> None:
    expanded = _build_retrieval_question(
        question="¿Hay justificación por retraso en la entrega? OP123",
        answerability_route="hybrid",
    )

    assert "justificación por retraso en la entrega" in expanded
    assert "Busqueda documental ampliada" in expanded
    assert "equivalentes" in expanded
    assert "condiciones" in expanded
    assert "consecuencias" in expanded
    assert "ausencia de informacion relevante" in expanded

def test_retrieval_question_does_not_expand_metadata_queries() -> None:
    question = "Para RM797_ID_5515, quien recibe la renta y cual es su RUT?"

    assert _build_retrieval_question(
        question=question,
        answerability_route="metadata",
    ) == question

def test_retrieve_candidates_boosts_hybrid_coverage_generically() -> None:
    class _Plan:
        top_k = 5
        strategy = "fast-grounded"
        selected_provider = "stub"

    class _Supervisor:
        def __init__(self) -> None:
            self.question = ""

        def create_plan(self, **kwargs: object) -> _Plan:
            self.question = str(kwargs["question"])
            return _Plan()

    class _RetrievalTool:
        def __init__(self) -> None:
            self.kwargs: dict[str, object] = {}

        def retrieve(self, **kwargs: object) -> RetrievalResult:
            self.kwargs = dict(kwargs)
            return RetrievalResult(evidence=[], telemetry={"retrieval_route": "scoped_semantic"})

    supervisor = _Supervisor()
    retrieval_tool = _RetrievalTool()
    nodes = QAGraphNodes(
        intent_router=object(),
        casual_responder=object(),
        supervisor=supervisor,
        scope_resolver=object(),
        question_classifier=object(),
        fact_resolver=object(),
        retrieval_tool=retrieval_tool,
        analysis_agent=object(),
        hybrid_answer_tool=object(),
        page_vision_tool=object(),
        repository=object(),
    )

    patch = nodes.retrieve_candidates(
        {
            "question": "¿Hay justificación por retraso en la entrega? OP123",
            "top_k": 5,
            "candidate_k": 20,
            "min_pages_per_selected_doc": 0,
            "summary_mode": "default",
            "question_class": "metadata_comparison",
            "user_id": 7,
            "file_ids": [201, 202],
            "resolved_archive_slugs": ["OP123_ID_A", "OP123_ID_B"],
            "answerability_route": "hybrid",
            "scope_origin": "metadata",
        }
    )

    assert "Busqueda documental ampliada" in supervisor.question
    assert "justificación por retraso en la entrega" in supervisor.question
    assert retrieval_tool.kwargs["candidate_k"] == 80
    assert retrieval_tool.kwargs["min_pages_per_selected_doc"] == 2
    assert retrieval_tool.kwargs["summary_mode"] == "per_document"
    assert patch["candidate_k"] == 80
    assert patch["min_pages_per_selected_doc"] == 2
    assert patch["summary_mode"] == "per_document"
    assert any("generic per-document retrieval coverage" in note for note in patch["confidence_notes"])

def test_retrieval_metadata_prefilter_keeps_limit_sized_matches() -> None:
    class _StubRepository:
        def search_file_ids_by_metadata_query(
            self,
            *,
            user_id: int,
            query_text: str,
            file_ids: list[int] | None = None,
            limit: int = 20,
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, query_text, file_ids, limit, include_shared
            return list(range(1, 21))

    service = object.__new__(RetrievalPipelineService)
    service.repository = _StubRepository()

    matches = service._metadata_prefilter_file_ids(
        question="region metropolitana de santiago",
        user_id=7,
        file_ids=None,
        limit=20,
    )

    assert matches == list(range(1, 21))

def test_query_concept_coverage_matches_inflected_document_terms() -> None:
    concepts = extract_query_concepts("que documentos hablan sobre atraso de renta?")

    assert concepts == ["atraso", "renta"]
    assert concept_coverage_score(
        concepts,
        tokenize_text("Si Entel se atrasa o no paga la renta, procede el maximo interes legal."),
    ) == 1.0

def test_query_concept_coverage_uses_generic_near_token_relation() -> None:
    assert token_keys_are_related("aprobacion", "reaprobacion") is True
    assert token_keys_are_related("atraso", "retraso") is True
    assert token_keys_are_related("fecha", "ficha") is False
    assert concept_coverage_score(
        ["aprobacion"],
        tokenize_text("El documento contiene la reaprobacion operativa del proceso."),
    ) == 1.0

def test_retrieval_metadata_prefilter_uses_real_metadata_concepts_when_text_index_has_no_hits() -> None:
    class _StubRepository:
        def search_file_ids_by_metadata_query(
            self,
            *,
            user_id: int,
            query_text: str,
            file_ids: list[int] | None = None,
            limit: int = 20,
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, query_text, file_ids, limit, include_shared
            return []

        def list_archive_metadata_for_user(
            self,
            *,
            user_id: int,
            include_shared: bool = False,
        ) -> list[dict[str, object]]:
            del user_id, include_shared
            return [
                {
                    "file_id": 44,
                    "archive_slug": "LA382_ID_1142",
                    "metadata_search_text": (
                        "Indicar Otras Condiciones: Si Entel se atrasa o no paga la renta, "
                        "el arrendador tendra derecho a cobrar interes legal."
                    ),
                    "metadata_json": "{}",
                },
                {
                    "file_id": 69,
                    "archive_slug": "TSM10_ID_20441",
                    "metadata_search_text": "Renta o Precio Vigente: 300 UF",
                    "metadata_json": "{}",
                },
            ]

        def list_file_ids_for_archive_slugs(
            self,
            *,
            user_id: int,
            archive_slugs: list[str],
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, include_shared
            if archive_slugs == ["LA382_ID_1142"]:
                return [44, 45, 46, 47]
            return []

        def get_archive_slug_map_for_file_ids(
            self,
            *,
            user_id: int,
            file_ids: list[int],
            include_shared: bool = False,
        ) -> dict[int, str]:
            del user_id, include_shared
            return {int(file_id): "LA382_ID_1142" for file_id in file_ids}

    service = object.__new__(RetrievalPipelineService)
    service.repository = _StubRepository()

    matches = service._metadata_prefilter_file_ids(
        question="que documentos hablan sobre atraso de renta?",
        user_id=7,
        file_ids=None,
        limit=20,
    )

    assert matches == [44, 45, 46, 47]

def test_document_shortlist_keeps_metadata_priority_without_excluding_textual_matches() -> None:
    service = object.__new__(RetrievalPipelineService)

    def _dense_candidates(self, **kwargs):
        del self, kwargs
        return []

    def _lexical_candidates(self, **kwargs):
        del self, kwargs
        return [
            {
                "file_id": 99,
                "file_input_file_name": "textual-match.pdf",
                "file_code": "TX99",
                "file_embeddings_summary": "retardo o atraso de renta",
                "file_embeddings_search_text": "retardo o atraso de renta",
                "lexical_score": 3,
            }
        ]

    service._retrieve_document_dense_candidates = MethodType(_dense_candidates, service)
    service._retrieve_document_lexical_candidates = MethodType(_lexical_candidates, service)

    shortlisted = service._shortlist_documents(
        question="que documentos hablan sobre atraso de renta?",
        query_vector=[0.1, 0.2],
        user_id=7,
        file_ids=None,
        priority_file_ids=[44],
        shortlist_limit=3,
    )

    assert shortlisted == [44, 99]

def test_retrieval_explicit_archive_scope_is_not_narrowed_by_metadata_prefilter() -> None:
    class _StubEmbeddingService:
        def embed_query_text(self, *, text: str) -> list[float]:
            del text
            return [0.0, 0.1]

    class _StubRepository:
        def search_file_ids_by_metadata_query(
            self,
            *,
            user_id: int,
            query_text: str,
            file_ids: list[int] | None = None,
            limit: int = 20,
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, query_text, file_ids, limit, include_shared
            return [201]

        def list_file_ids_for_input_filenames(
            self,
            *,
            user_id: int,
            file_names: list[str],
            file_ids: list[int] | None = None,
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, file_names, file_ids, include_shared
            return []

        def list_file_ids_for_archive_slugs(
            self,
            *,
            user_id: int,
            archive_slugs: list[str],
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, archive_slugs, include_shared
            return [201, 202, 203, 204, 205, 206]

        def get_archive_slug_map_for_file_ids(
            self,
            *,
            user_id: int,
            file_ids: list[int],
            include_shared: bool = False,
        ) -> dict[int, str]:
            del user_id, include_shared
            return {int(file_id): "LA122_ID_3979" for file_id in file_ids}

        def search_lexical_pages(
            self,
            *,
            user_id: int,
            question: str,
            file_ids: list[int] | None = None,
            limit: int = 20,
            include_shared: bool = False,
        ) -> list[dict[str, object]]:
            del user_id, question, file_ids, limit, include_shared
            return []

        def list_embeddings(
            self,
            *,
            file_ids: list[int],
            user_id: int,
            include_vectors: bool = False,
            modalities: list[str] | None = None,
            include_shared: bool = False,
        ) -> list[dict[str, object]]:
            del file_ids, user_id, include_vectors, modalities, include_shared
            return []

    class _StubVectorStore:
        def similarity_search(
            self,
            *,
            query_vector: list[float],
            user_id: int | None = None,
            file_ids: list[int] | None = None,
            modality: str | None = None,
            top_k: int = 5,
            include_shared: bool = False,
        ) -> list[OracleVectorSearchResult]:
            del query_vector, user_id, top_k, include_shared
            if modality != "ocr_text":
                return []
            return [
                OracleVectorSearchResult(
                    file_id=int(file_id),
                    file_name=f"LA122_doc_{file_id}.pdf",
                    archive_slug="LA122_ID_3979",
                    file_code="LA122",
                    page_id=int(file_id) * 10,
                    page_number=1,
                    score=0.9,
                    summary_text=f"Evidencia del documento {file_id}.",
                    image_path_local="",
                    object_name_page="",
                    modality="ocr_text",
                    extraction_method="docling_rapidocr",
                    ocr_confidence=0.95,
                )
                for file_id in list(file_ids or [])
            ]

    service = object.__new__(RetrievalPipelineService)
    service.embedding_service = _StubEmbeddingService()
    service.repository = _StubRepository()
    service.oracle_vector_store = _StubVectorStore()
    service.rerank_service = object()
    service.settings = Settings(_env_file=None)

    result = service.retrieve(
        question="/file:LA122_ID_3979 Que documentos integran el expediente?",
        user_id=7,
        file_ids=[201, 202, 203, 204, 205, 206],
        archive_slugs=["LA122_ID_3979"],
        top_k=6,
        candidate_k=24,
        min_pages_per_selected_doc=1,
        summary_mode="per_document",
        question_class="exhaustive_synthesis",
        scope_origin="metadata",
    )

    assert result.telemetry["metadata_prefilter_applied"] is False
    assert result.telemetry["doc_shortlist_count"] == 6
    assert {item.file_id for item in result.evidence} == {201, 202, 203, 204, 205, 206}

def test_retrieval_explicit_pdf_full_document_request_keeps_all_pages_in_order() -> None:
    class _StubEmbeddingService:
        def embed_query_text(self, *, text: str) -> list[float]:
            del text
            return [0.0, 0.1]

    class _StubRepository:
        def search_file_ids_by_metadata_query(
            self,
            *,
            user_id: int,
            query_text: str,
            file_ids: list[int] | None = None,
            limit: int = 20,
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, query_text, file_ids, limit, include_shared
            return []

        def list_file_ids_for_input_filenames(
            self,
            *,
            user_id: int,
            file_names: list[str],
            file_ids: list[int] | None = None,
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, include_shared
            if "AI041.pdf" not in file_names:
                return []
            allowed = {int(file_id) for file_id in list(file_ids or []) if int(file_id) > 0}
            return [701] if not allowed or 701 in allowed else []

        def list_file_ids_for_archive_slugs(
            self,
            *,
            user_id: int,
            archive_slugs: list[str],
            include_shared: bool = False,
        ) -> list[int]:
            del user_id, archive_slugs, include_shared
            return []

        def get_archive_slug_map_for_file_ids(
            self,
            *,
            user_id: int,
            file_ids: list[int],
            include_shared: bool = False,
        ) -> dict[int, str]:
            del user_id, include_shared
            return {int(file_id): "AI041_ID_49" for file_id in file_ids}

        def search_lexical_pages(
            self,
            *,
            user_id: int,
            question: str,
            file_ids: list[int] | None = None,
            limit: int = 20,
            include_shared: bool = False,
        ) -> list[dict[str, object]]:
            del user_id, question, file_ids, limit, include_shared
            return []

        def list_embeddings(
            self,
            *,
            file_ids: list[int],
            user_id: int,
            include_vectors: bool = False,
            modalities: list[str] | None = None,
            include_shared: bool = False,
        ) -> list[dict[str, object]]:
            del user_id, include_vectors, modalities, include_shared
            if 701 not in {int(file_id) for file_id in file_ids}:
                return []
            return [
                {
                    "file_id": 701,
                    "file_pages_id": 9000 + page_number,
                    "file_pages_number": page_number,
                    "file_pages_image_path_local": "",
                    "file_pages_output_obj_name": "",
                    "file_pages_ocr_confidence": 0.96,
                    "file_pages_ocr_method": "docling_rapidocr",
                    "file_pages_ocr_text": f"Texto OCR pagina {page_number}.",
                    "file_pages_visual_summary": "",
                    "file_pages_search_text": f"Texto OCR pagina {page_number}.",
                    "file_input_file_name": "AI041.pdf",
                    "archive_slug": "AI041_ID_49",
                    "file_code": "AI041",
                }
                for page_number in range(1, 7)
            ]

    class _StubVectorStore:
        def similarity_search(
            self,
            *,
            query_vector: list[float],
            user_id: int | None = None,
            file_ids: list[int] | None = None,
            modality: str | None = None,
            top_k: int = 5,
            include_shared: bool = False,
        ) -> list[OracleVectorSearchResult]:
            del query_vector, user_id, top_k, include_shared
            if modality != "ocr_text" or 701 not in list(file_ids or []):
                return []
            return [
                OracleVectorSearchResult(
                    file_id=701,
                    file_name="AI041.pdf",
                    archive_slug="AI041_ID_49",
                    file_code="AI041",
                    page_id=9003,
                    page_number=3,
                    score=0.99,
                    summary_text="Texto OCR pagina 3.",
                    image_path_local="",
                    object_name_page="",
                    modality="ocr_text",
                    extraction_method="docling_rapidocr",
                    ocr_confidence=0.96,
                )
            ]

    service = object.__new__(RetrievalPipelineService)
    service.embedding_service = _StubEmbeddingService()
    service.repository = _StubRepository()
    service.oracle_vector_store = _StubVectorStore()
    service.rerank_service = object()
    service.settings = Settings(_env_file=None)

    question = "Analiza todo el documento AI041.pdf y muestrame una lista completa clave valor."
    result = service.retrieve(
        question=question,
        user_id=7,
        file_ids=[701],
        top_k=5,
        question_class="exhaustive_synthesis",
        scope_origin="manual",
    )

    assert question_requests_full_document_coverage(question) is True
    assert result.telemetry["explicit_file_scope_applied"] is True
    assert result.telemetry["full_document_coverage_requested"] is True
    assert [item.page_number for item in result.evidence] == [1, 2, 3, 4, 5, 6]

def test_representative_questions_request_extra_page_coverage() -> None:
    assert question_requests_representative_details(
        "Que personas o representantes aparecen con facultades para firmar?"
    )
    assert not question_requests_representative_details("Que documentos integran el expediente?")

def test_per_doc_default_value_keeps_multiple_pages_per_document_for_quota() -> None:
    class _StubRepository:
        def list_embeddings(
            self,
            *,
            file_ids: list[int],
            user_id: int,
            include_vectors: bool = False,
            modalities: list[str] | None = None,
            include_shared: bool = False,
        ) -> list[dict[str, object]]:
            del user_id, include_vectors, modalities, include_shared
            rows: list[dict[str, object]] = []
            for file_id in file_ids:
                rows.extend(
                    [
                        {
                            "file_id": file_id,
                            "file_input_file_name": f"doc-{file_id}.pdf",
                            "file_pages_id": int(file_id) * 10 + 1,
                            "file_pages_number": 1,
                            "file_pages_ocr_text": "comparecen representantes con facultades para firmar",
                            "file_pages_visual_summary": "",
                            "file_pages_image_path_local": "",
                            "file_pages_output_obj_name": "",
                            "file_pages_ocr_method": "docling_rapidocr",
                            "file_pages_ocr_confidence": 0.95,
                        },
                        {
                            "file_id": file_id,
                            "file_input_file_name": f"doc-{file_id}.pdf",
                            "file_pages_id": int(file_id) * 10 + 2,
                            "file_pages_number": 2,
                            "file_pages_ocr_text": "representada por segunda persona y mandato especial",
                            "file_pages_visual_summary": "",
                            "file_pages_image_path_local": "",
                            "file_pages_output_obj_name": "",
                            "file_pages_ocr_method": "docling_rapidocr",
                            "file_pages_ocr_confidence": 0.95,
                        },
                    ]
                )
            return rows

    service = object.__new__(RetrievalPipelineService)
    service.repository = _StubRepository()

    candidates = service._build_per_doc_evidence_expansion_candidates(
        question="Que personas o representantes aparecen con facultades para firmar?",
        user_id=7,
        selected_file_ids=[501],
    )

    assert [item.evidence.page_number for item in candidates if item.evidence.file_id == 501] == [1, 2]

def test_retrieval_builds_adjacent_pages_for_representative_boundary_context() -> None:
    class _StubRepository:
        def list_embeddings(
            self,
            *,
            file_ids: list[int],
            user_id: int,
            include_vectors: bool = False,
            modalities: list[str] | None = None,
            include_shared: bool = False,
        ) -> list[dict[str, object]]:
            del user_id, include_vectors, modalities, include_shared
            rows: list[dict[str, object]] = []
            for file_id in file_ids:
                rows.extend(
                    [
                        {
                            "file_id": file_id,
                            "file_input_file_name": "LA122_Modificacion.pdf",
                            "archive_slug": "LA122_ID_3979",
                            "file_pages_id": int(file_id) * 10 + 1,
                            "file_pages_number": 1,
                            "file_pages_ocr_text": "comparecen JANETTE LUCILA MANSILLA",
                            "file_pages_visual_summary": "",
                            "file_pages_image_path_local": "",
                            "file_pages_output_obj_name": "",
                            "file_pages_ocr_method": "docling_rapidocr",
                            "file_pages_ocr_confidence": 0.95,
                        },
                        {
                            "file_id": file_id,
                            "file_input_file_name": "LA122_Modificacion.pdf",
                            "archive_slug": "LA122_ID_3979",
                            "file_pages_id": int(file_id) * 10 + 2,
                            "file_pages_number": 2,
                            "file_pages_ocr_text": "TOLEDO, chilena, representada por FRANCISCO JAVIER SPRENGER ARROYO",
                            "file_pages_visual_summary": "",
                            "file_pages_image_path_local": "",
                            "file_pages_output_obj_name": "",
                            "file_pages_ocr_method": "docling_rapidocr",
                            "file_pages_ocr_confidence": 0.95,
                        },
                    ]
                )
            return rows

    service = object.__new__(RetrievalPipelineService)
    service.repository = _StubRepository()
    selected = [
        EvidenceItem(
            source_number=1,
            file_id=501,
            file_name="LA122_Modificacion.pdf",
            archive_slug="LA122_ID_3979",
            page_id=5011,
            page_number=1,
            score=0.95,
            summary_text="comparecen JANETTE LUCILA MANSILLA",
            image_path_local="",
        )
    ]

    candidates = service._build_adjacent_page_candidates(
        user_id=7,
        selected_evidence=selected,
        selected_file_ids=[501],
    )

    assert [item.evidence.page_number for item in candidates] == [2]
    assert "TOLEDO" in candidates[0].evidence.summary_text

def test_final_evidence_quota_preserves_multiple_pages_per_document_when_trimming() -> None:
    evidence = [
        EvidenceItem(
            source_number=index,
            file_id=file_id,
            file_name=f"doc-{file_id}.pdf",
            archive_slug="LA122_ID_3979",
            page_id=file_id * 10 + page,
            page_number=page,
            score=1.0 / index,
            summary_text=f"doc {file_id} page {page}",
            image_path_local="",
            extraction_method="adjacent_page_context" if page == 2 else "",
        )
        for index, (file_id, page) in enumerate(
            [
                (501, 1),
                (502, 1),
                (503, 1),
                (501, 3),
                (502, 3),
                (503, 3),
                (501, 2),
                (502, 2),
                (503, 2),
            ],
            start=1,
        )
    ]

    limited = RetrievalPipelineService._enforce_final_evidence_quota(
        reranked=evidence[:6],
        candidate_pool=evidence,
        selected_file_ids=[501, 502, 503],
        min_pages_per_doc=2,
        desired_final=6,
    )

    pages_by_doc = {
        file_id: [item.page_number for item in limited if item.file_id == file_id]
        for file_id in [501, 502, 503]
    }
    assert pages_by_doc == {501: [1, 2], 502: [1, 2], 503: [1, 2]}

def test_rebalance_file_ids_by_archive_scope_round_robins_archives() -> None:
    ranked_file_ids = [664, 665, 666, 668, 669, 670]
    file_archive_map = {
        664: "RM797_ID_1668",
        665: "RM797_ID_1668",
        666: "RM797_ID_1668",
        668: "RM797_ID_5515",
        669: "RM797_ID_5515",
        670: "RM797_ID_5515",
    }

    balanced = RetrievalPipelineService._rebalance_file_ids_by_archive_scope(
        ranked_file_ids=ranked_file_ids,
        file_archive_map=file_archive_map,
        preferred_archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
        limit=6,
    )

    assert balanced[:4] == [664, 668, 665, 669]

def test_prioritize_final_evidence_by_archive_scope_preserves_cross_archive_coverage() -> None:
    def _evidence(*, file_id: int, page_id: int, file_name: str, page_number: int) -> EvidenceItem:
        return EvidenceItem(
            source_number=0,
            file_id=file_id,
            file_name=file_name,
            file_code=None,
            page_id=page_id,
            page_number=page_number,
            score=0.9,
            summary_text=f"summary-{file_id}-{page_id}",
            image_path_local="",
            object_name_page="",
            extraction_method="ocr_text",
            ocr_confidence=0.99,
        )

    reranked = [
        _evidence(file_id=664, page_id=1, file_name="RM797_Contrato.pdf", page_number=1),
        _evidence(file_id=665, page_id=2, file_name="RM797_-_Decreto_MOP_Exento_N667.pdf", page_number=1),
        _evidence(file_id=666, page_id=3, file_name="RM797_-_Decreto_MOP_Exento_N668.pdf", page_number=1),
    ]
    candidate_pool = reranked + [
        _evidence(file_id=668, page_id=4, file_name="RM797_-_Contrato_2.pdf", page_number=1),
    ]
    file_archive_map = {
        664: "RM797_ID_1668",
        665: "RM797_ID_1668",
        666: "RM797_ID_1668",
        668: "RM797_ID_5515",
    }

    limited = RetrievalPipelineService._prioritize_final_evidence_by_archive_scope(
        reranked=reranked,
        candidate_pool=candidate_pool,
        preferred_archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
        file_archive_map=file_archive_map,
        min_pages_per_archive=1,
        desired_final=3,
    )

    assert len(limited) == 3
    leading_archives = {
        RetrievalPipelineService._normalize_archive_slug(file_archive_map[item.file_id])
        for item in limited[:2]
    }
    assert leading_archives == {"rm797_id_1668", "rm797_id_5515"}

def test_prioritize_candidate_pool_by_archive_scope_promotes_best_candidate_per_archive() -> None:
    def _candidate(*, file_id: int, page_id: int, file_name: str, score: float) -> object:
        evidence = EvidenceItem(
            source_number=0,
            file_id=file_id,
            file_name=file_name,
            file_code=None,
            page_id=page_id,
            page_number=1,
            score=score,
            summary_text=f"summary-{file_id}-{page_id}",
            image_path_local="",
            object_name_page="",
            extraction_method="ocr_text",
            ocr_confidence=0.99,
        )
        return type(
            "CandidateStub",
            (),
            {
                "evidence": evidence,
                "fused_score": score,
            },
        )()

    candidates = [
        _candidate(file_id=664, page_id=1, file_name="RM797_Contrato.pdf", score=0.50),
        _candidate(file_id=668, page_id=4, file_name="RM797_-_Contrato_2.pdf", score=0.91),
        _candidate(file_id=665, page_id=2, file_name="RM797_-_Decreto_MOP_Exento_N667.pdf", score=0.95),
    ]
    file_archive_map = {
        664: "RM797_ID_1668",
        665: "RM797_ID_1668",
        668: "RM797_ID_5515",
    }

    ordered = RetrievalPipelineService._prioritize_candidate_pool_by_archive_scope(
        candidates=candidates,
        preferred_archive_slugs=["RM797_ID_1668", "RM797_ID_5515"],
        file_archive_map=file_archive_map,
        min_pages_per_archive=1,
    )

    assert [item.evidence.file_id for item in ordered[:2]] == [665, 668]
