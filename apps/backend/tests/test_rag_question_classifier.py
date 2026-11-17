from __future__ import annotations

from apps.backend.tests.rag_plan_modules import *

from apps.backend.tests.rag_plan_fixtures import *


def test_question_classifier_detects_temporal_question() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Â¿CuÃ¡nto tiempo le queda de vigencia al contrato? Si hoy es 20 de Marzo 2026",
    )
    assert result.question_class == "temporal"

def test_question_classifier_detects_document_inventory_request() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(question="Listame todos los documentos y archivos que tengo cargados.")
    assert result.question_class == "inventory"

def test_question_classifier_detects_associated_documents_request() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(question="Segun AI041_ID_49 cuales son sus documentos asociados?")
    assert result.question_class == "inventory"

def test_question_classifier_routes_content_filtered_document_selection_to_synthesis() -> None:
    classifier = QuestionClassifier()

    result = classifier.classify(question="Que documentos hablan sobre atraso de renta?")

    assert result.question_class == "exhaustive_synthesis"
    assert result.rationale == "document-content-request"

def test_question_classifier_does_not_treat_content_filtered_list_as_inventory() -> None:
    classifier = QuestionClassifier()

    result = classifier.classify(question="Lista los documentos que mencionan cumplimiento operativo.")

    assert result.question_class == "exhaustive_synthesis"
    assert result.rationale == "document-content-request"

def test_question_classifier_routes_key_value_document_follow_up_to_document_synthesis() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Genera una lista valor de cada campo que consideres relevante para revisar todo el documento."
    )

    assert result.question_class == "exhaustive_synthesis"

def test_question_classifier_detects_analytics_question_without_accent_dependency() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(question="Cuantos contratos estan vencidos?")
    assert result.question_class == "analytics"

def test_question_classifier_detects_metadata_comparison() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Compara la metadata y las diferencias entre archivos RM797_ID_1668 y RM797_ID_5515"
    )
    assert result.question_class == "metadata_comparison"

def test_question_classifier_routes_global_metadata_analytics_to_analytics() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Usando toda la metadata cargada, que sitios tienen mas de un ID de contrato?"
    )
    assert result.question_class == "analytics"

def test_question_classifier_routes_region_metadata_count_to_analytics() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Segun la metadata cuantos sitios hay en la region metropolitana de Santiago?"
    )
    assert result.question_class == "analytics"

def test_question_classifier_routes_entel_aggregate_with_document_hint_to_analytics() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Usando toda la metadata cargada, cuantos contratos vigentes fueron firmados por ENTEL PCS? Si puedes, contrastalo con evidencia documental."
    )
    assert result.question_class == "analytics"

def test_question_classifier_does_not_route_metadata_document_differences_to_inventory() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Comparando metadata CSV contra los documentos procesados, en que contratos detectas diferencias "
            "relevantes en estado, cesion a terceros y acceso?"
        )
    )
    assert result.question_class == "metadata_comparison"

def test_question_classifier_routes_document_inventory_reasoning_to_document_synthesis() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Que documentos integran el expediente y cuales son los que modifican el contrato base? "
            "Lista los nombres exactos de los PDF relevantes y cita la evidencia documental."
        )
    )
    assert result.question_class == "exhaustive_synthesis"

def test_question_classifier_routes_document_traceability_request_to_document_synthesis() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "De donde fue extraido cada dato clave utilizado en la respuesta? "
            "Lista los nombres exactos de los PDF relevantes y cita la evidencia documental."
        )
    )
    assert result.question_class == "exhaustive_synthesis"

def test_question_classifier_routes_pdf_timeline_to_document_synthesis() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Reconstruye la linea de tiempo documental de AI041_ID_49 usando AI041.pdf, "
            "AI041_Modificacin_1.pdf y AI041_Aclaracion_y_rectificacion.pdf."
        )
    )
    assert result.question_class == "exhaustive_synthesis"

def test_question_classifier_routes_mixed_metadata_and_documents_to_document_synthesis() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Compara RM797_ID_1668 y RM797_ID_5515 usando metadata y documentos; "
            "indica tipo de documento, partes involucradas y fechas clave."
        )
    )
    assert result.question_class == "exhaustive_synthesis"

def test_question_classifier_routes_cross_archive_comparison_with_citations_to_document_synthesis() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Compara RM797_ID_1668 y RM797_ID_5515 en estado, partes, forma de pago y fecha de termino. "
            "Usa metadata y documentos, y cita los PDFs mas relevantes."
        )
    )
    assert result.question_class == "exhaustive_synthesis"

def test_question_classifier_routes_versioned_clause_with_citation_to_versioned() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Para LA122_ID_3979, que dice el ultimo contrato vigente sobre cesion a terceros? "
            "Cita la clausula y el PDF."
        )
    )
    assert result.question_class == "versioned"

def test_question_classifier_routes_follow_up_latest_signed_documents_to_versioned() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="De estos 5 sitios cuales son sus ultimos documentos firmados?"
    )
    assert result.question_class == "versioned"

def test_question_classifier_routes_metadata_validation_with_documents_to_metadata_comparison() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Usando metadata y documentos de RM797_ID_1668, valida si el Estado Contrato es desconocido "
            "y confirma la Forma de Pago con evidencia."
        )
    )
    assert result.question_class == "metadata_comparison"

def test_question_classifier_routes_ocr_content_request_to_document_synthesis() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Usar @metadata y /file:AI041_ID_49. Segun el OCR del documento, resume de que trata "
            "el contrato y menciona las partes principales, la direccion o sitio y la renta si aparece."
        )
    )
    assert result.question_class == "exhaustive_synthesis"

def test_question_classifier_does_not_confuse_confirma_with_firma() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Usa la metadata para encontrar el file RM797_ID_1668 y confirma si el Estado Contrato "
            "es vigente; además indica la Comuna y la Dirección."
        )
    )
    assert result.question_class == "metadata_comparison"

def test_question_classifier_routes_beneficiary_rut_question_to_metadata_comparison() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Para RM797_ID_5515, quien recibe la renta y cual es su RUT?"
    )
    assert result.question_class == "metadata_comparison"

def test_question_classifier_routes_dynamic_archive_metadata_lookup_to_metadata_comparison() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Para RM797_ID_5515, cual es el Segmento Comercial y el Responsable Comercial?"
    )
    assert result.question_class == "metadata_comparison"

def test_question_classifier_routes_dynamic_metadata_aggregate_to_analytics() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question="Segun la metadata, cuantos segmentos comerciales hay?"
    )
    assert result.question_class == "analytics"

def test_question_requires_visual_grounding_uses_whole_tokens() -> None:
    assert question_requires_visual_grounding("Muéstrame la firma del representante.") is True
    assert question_requires_visual_grounding("Confirma la vigencia del contrato y la dirección.") is False

def test_question_requires_visual_grounding_does_not_trigger_for_pdf_mentions() -> None:
    assert question_requires_visual_grounding("Compara AI041.pdf y AI041_Modificacin_1.pdf.") is False

def test_question_classifier_does_not_route_signature_dates_to_visual_consistency() -> None:
    classifier = QuestionClassifier()
    result = classifier.classify(
        question=(
            "Compara AI041.pdf, AI041_Modificacin_1.pdf y AI041_Aclaracion_y_rectificacion.pdf dentro de "
            "AI041_ID_49; resume cambios de fechas de firma, notaria, repertorio y representantes, y cita cada PDF."
        )
    )
    assert result.question_class == "exhaustive_synthesis"
