import json

from apps.backend.app.ingest.docling_document_service import DoclingDocumentService


def test_docling_page_result_reconstructs_markdown_when_page_export_is_empty() -> None:
    bucket = DoclingDocumentService._build_page_bucket(page=object())
    bucket["text_fragments"].extend(
        [
            "Contrato de servidumbre",
            "Comparecen las partes para suscribir el acuerdo.",
        ]
    )
    bucket["detected_blocks"].append({"type": "TextItem", "page_number": 2})

    page_result = DoclingDocumentService._build_page_result(
        page_number=2,
        bucket=bucket,
        total_pages=3,
    )

    assert "Contrato de servidumbre" in page_result.ocr_result.markdown_text
    assert "Comparecen las partes" in page_result.ocr_result.markdown_text
    assert "markdown_reconstructed_from_ocr" in page_result.visual_flags
    layout_payload = json.loads(page_result.layout_json)
    assert layout_payload["markdown_source"] == "ocr_text_reconstruction"


def test_docling_page_result_reconstructs_markdown_when_export_only_has_image_marker() -> None:
    bucket = DoclingDocumentService._build_page_bucket(page=object())
    bucket["markdown_text"] = "Document code ABC123\n\n<!-- image -->\n\npage 3 of 3"
    bucket["text_fragments"].append(
        "La pagina contiene un cuerpo documental extenso con obligaciones, fechas, "
        "partes intervinientes, terminos de pago y condiciones operativas que deben "
        "quedar disponibles para busqueda y lectura humana."
    )

    page_result = DoclingDocumentService._build_page_result(
        page_number=3,
        bucket=bucket,
        total_pages=3,
    )

    assert "<!-- image -->" not in page_result.ocr_result.markdown_text
    assert "cuerpo documental extenso" in page_result.ocr_result.markdown_text
    assert "markdown_reconstructed_from_ocr" in page_result.visual_flags
    layout_payload = json.loads(page_result.layout_json)
    assert layout_payload["markdown_source"] == "ocr_text_reconstruction"
