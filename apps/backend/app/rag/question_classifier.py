"""Heuristic question classification for RAG routing."""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata

QUESTION_CLASSES: tuple[str, ...] = (
    "extractive",
    "inventory",
    "metadata_comparison",
    "versioned",
    "temporal",
    "visual_consistency",
    "analytics",
    "exhaustive_synthesis",
)


@dataclass(slots=True)
class QuestionClassification:
    question_class: str
    rationale: str


class QuestionClassifier:
    _TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)
    _PDF_REFERENCE_PATTERN = re.compile(
        r"\b[\w().-]+(?:\s+[\w().-]+)*\.pdf\b",
        re.IGNORECASE | re.UNICODE,
    )
    _ARCHIVE_REFERENCE_PATTERN = re.compile(
        r"\b[\w-]+_id_[\w-]+\b",
        re.IGNORECASE | re.UNICODE,
    )

    @staticmethod
    def _normalize(value: str) -> str:
        normalized = unicodedata.normalize("NFKD", value or "")
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower().strip()

    @classmethod
    def _contains_any(cls, *, normalized: str, terms: tuple[str, ...]) -> bool:
        tokens = set(cls._TOKEN_PATTERN.findall(normalized))
        for term in terms:
            candidate = str(term or "").strip().lower()
            if not candidate:
                continue
            if " " in candidate:
                if candidate in normalized:
                    return True
                continue
            if candidate in tokens:
                return True
        return False

    @classmethod
    def _contains_pdf_reference(cls, *, question: str) -> bool:
        return cls._PDF_REFERENCE_PATTERN.search(str(question or "")) is not None

    @classmethod
    def _contains_archive_reference(cls, *, question: str) -> bool:
        return cls._ARCHIVE_REFERENCE_PATTERN.search(str(question or "")) is not None

    @classmethod
    def _contains_document_analysis_signal(cls, *, question: str, normalized: str) -> bool:
        if cls._contains_pdf_reference(question=question):
            return True
        return cls._contains_any(
            normalized=normalized,
            terms=(
                "linea de tiempo",
                "linea del tiempo",
                "timeline",
                "documento",
                "documentos",
                "documental",
                "documento base",
                "evidencia",
                "evidencia documental",
                "cita",
                "citas",
                "cita la clausula",
                "cita el pdf",
                "cita los pdfs",
                "cita el documento",
                "cita los documentos",
                "documentos relevantes",
                "pdf relevante",
                "pdfs mas relevantes",
                "sustenta",
                "respalda",
                "partes involucradas",
                "fechas clave",
                "hito",
                "hitos",
                "clausula",
                "claúsula",
                "contradicen",
                "contradiccion",
                "contradicción",
                "tipo de documento",
                "usando metadata y documentos",
            ),
        )

    @classmethod
    def _contains_content_filtered_document_selection(cls, *, normalized: str) -> bool:
        if not cls._contains_any(
            normalized=normalized,
            terms=("documento", "documentos", "archivo", "archivos", "pdf", "pdfs", "file", "files"),
        ):
            return False
        selection_pattern = (
            r"\b(?:que|cuales|lista|listame|muestra|muestrame|identifica|encuentra|"
            r"busca|filtra|dime|indica|which|what|list|show|find|identify)\b"
            r".{0,80}\b(?:documentos?|archivos?|pdfs?|files?)\b"
        )
        relative_selection_pattern = r"\b(?:documentos?|archivos?|pdfs?|files?)\b\s+(?:que|that|which)\b"
        if not (
            re.search(selection_pattern, normalized)
            or re.search(relative_selection_pattern, normalized)
        ):
            return False
        content_verb_pattern = (
            r"\b(?:documentos?|archivos?|pdfs?|files?)\b.{0,90}\b"
            r"(?:habla|hablan|trate|tratan|trata|menciona|mencionan|contiene|contienen|"
            r"incluye|incluyen|describe|describen|explica|explican|refiere|refieren|"
            r"aborda|abordan|cubre|cubren|mention|mentions|contain|contains|cover|covers|"
            r"discuss|discusses|describe|describes)\b"
        )
        topic_connector_pattern = (
            r"\b(?:documentos?|archivos?|pdfs?|files?)\b.{0,90}\b"
            r"(?:sobre|acerca de|respecto de|respecto a|referente a|en relacion con|"
            r"relacionad[oa]s con|vinculad[oa]s con|about|regarding|related to)\b"
        )
        return bool(
            re.search(content_verb_pattern, normalized)
            or re.search(topic_connector_pattern, normalized)
        )

    @classmethod
    def _contains_document_content_request(cls, *, normalized: str) -> bool:
        if cls._contains_content_filtered_document_selection(normalized=normalized):
            return True
        source_requested = cls._contains_any(
            normalized=normalized,
            terms=(
                "segun el ocr",
                "segun ocr",
                "ocr del documento",
                "texto ocr",
                "texto extraido",
                "texto del documento",
                "contenido del documento",
                "segun el documento",
                "segun los documentos",
                "segun el pdf",
                "segun los pdfs",
                "documento",
                "documentos",
                "pdf",
                "pdfs",
            ),
        )
        if not source_requested:
            return False
        return cls._contains_any(
            normalized=normalized,
            terms=(
                "resume",
                "resumen",
                "de que trata",
                "menciona",
                "identifica",
                "extrae",
                "campo",
                "campos",
                "cada campo",
                "campos relevantes",
                "clave valor",
                "key value",
                "lista valor",
                "valor",
                "valores",
                "revisar todo el documento",
                "todo el documento",
                "partes",
                "partes principales",
                "partes involucradas",
                "firmantes",
                "representantes",
                "direccion",
                "precio",
                "objeto",
            ),
        )

    @classmethod
    def _contains_latest_document_signal(cls, *, normalized: str) -> bool:
        latest_requested = cls._contains_any(
            normalized=normalized,
            terms=(
                "ultimo",
                "ultimos",
                "ultima",
                "ultimas",
                "mas reciente",
                "mas recientes",
            ),
        )
        if not latest_requested:
            return False
        document_family_requested = cls._contains_any(
            normalized=normalized,
            terms=(
                "documento",
                "documentos",
                "archivo",
                "archivos",
                "version",
                "versiones",
                "pdf",
                "pdfs",
            ),
        )
        if not document_family_requested:
            return False
        version_qualifier_requested = cls._contains_any(
            normalized=normalized,
            terms=(
                "firmado",
                "firmados",
                "firmada",
                "firmadas",
                "suscrito",
                "suscritos",
                "suscrita",
                "suscritas",
                "vigente",
                "vigentes",
            ),
        )
        if version_qualifier_requested:
            return True
        return (
            re.search(
                r"\bultim(?:o|a|os|as)\s+(?:documento|documentos|archivo|archivos|version|versiones|pdf|pdfs)\b",
                normalized,
            )
            is not None
        )

    @classmethod
    def _contains_inventory_request(cls, *, normalized: str) -> bool:
        explicit_phrases = (
            "lista todos los documentos",
            "lista todos los archivos",
            "lista de documentos",
            "lista de archivos",
            "lista los documentos",
            "lista los archivos",
            "listame los documentos",
            "listame los archivos",
            "muestrame los documentos",
            "muestrame los archivos",
            "muestrame todos los documentos",
            "muestrame todos los archivos",
            "que documentos tengo",
            "que archivos tengo",
            "cuales son los documentos",
            "cuales son los archivos",
            "inventario documental",
            "inventario de documentos",
            "inventario de archivos",
            "documentos asociados",
            "archivos asociados",
            "pdfs asociados",
            "documentos vinculados",
            "archivos vinculados",
            "documentos relacionados",
            "archivos relacionados",
        )
        explicit_listing_requested = cls._contains_any(normalized=normalized, terms=explicit_phrases)
        if cls._contains_content_filtered_document_selection(normalized=normalized):
            return False
        if cls._contains_any(
            normalized=normalized,
            terms=(
                "cita",
                "citas",
                "evidencia",
                "evidencia documental",
                "pdf relevantes",
                "documento base",
                "de donde fue extraido",
                "dato clave",
                "datos clave",
                "campo",
                "campos",
                "cada campo",
                "campos relevantes",
                "clave valor",
                "key value",
                "lista valor",
                "valor",
                "valores",
                "gobierna",
                "rige",
                "representante",
                "representantes",
                "quien firma",
                "quienes firman",
            ),
        ):
            return False
        if explicit_listing_requested:
            return True
        if cls._contains_any(
            normalized=normalized,
            terms=(
                "compara",
                "comparar",
                "comparacion",
                "diferencia",
                "diferencias",
                "metadata",
                "metadatos",
                "versiones documentales",
                "mas versiones",
                "mayor a menor",
                "ordena",
                "ordenalos",
            ),
        ):
            return False
        has_document_noun = cls._contains_any(
            normalized=normalized,
            terms=("documento", "documentos", "archivo", "archivos", "pdf", "pdfs", "files"),
        )
        has_listing_signal = cls._contains_any(
            normalized=normalized,
            terms=("asociados", "vinculados", "relacionados", "inventario", "listado", "lista", "listar", "muestrame", "mostrar", "catalogo"),
        )
        has_possession_signal = cls._contains_any(
            normalized=normalized,
            terms=("tengo", "cargados", "cargado", "subidos", "disponibles", "procesados"),
        )
        return has_document_noun and (has_listing_signal or has_possession_signal)

    def classify(self, *, question: str) -> QuestionClassification:
        normalized = self._normalize(question)
        if not normalized:
            return QuestionClassification(question_class="extractive", rationale="empty-default")

        if self._contains_inventory_request(normalized=normalized):
            return QuestionClassification(question_class="inventory", rationale="document-inventory")

        visual_requested = self._contains_any(
            normalized=normalized,
            terms=(
                "muestrame la firma",
                "firma del representante",
                "firma",
                "imagen",
                "imagenes",
                "sello",
                "tabla",
                "tablas",
                "diagrama",
                "grafico",
                "gráfico",
            ),
        )
        signature_date_requested = self._contains_any(
            normalized=normalized,
            terms=("fecha de firma", "fechas de firma", "fecha firma", "fechas firma"),
        )
        if visual_requested and not signature_date_requested:
            return QuestionClassification(question_class="visual_consistency", rationale="visual-hints")

        comparison_requested = self._contains_any(
            normalized=normalized,
            terms=(
                "compara",
                "comparar",
                "comparacion",
                "comparación",
                "diferencia",
                "diferencias",
                "versus",
                " entre documentos",
                "entre archivos",
                "barrer documentos",
            ),
        )
        metadata_prompt = self._contains_any(
            normalized=normalized,
            terms=("metadata", "metadatos"),
        )
        explicit_archive_reference = self._contains_archive_reference(question=question)
        quality_review_requested = self._contains_any(
            normalized=normalized,
            terms=(
                "revision humana",
                "requiere revision",
                "ocr",
                "cifrado",
                "cifrados",
                "no validable",
                "inconsistencia",
                "inconsistencias",
                "ambiguedad",
                "ambigüedad",
                "contradiccion",
                "contradicción",
                "ausencia",
                "calidad",
            ),
        )
        aggregate_requested = self._contains_any(
            normalized=normalized,
            terms=(
                "cuantos",
                "cuantas",
                "cuenta de",
                "cantidad de",
                "mas de un",
                "mas de una",
                "multiples",
                "repetidos",
                "duplicados",
                "mas versiones documentales",
                "versiones documentales",
                "pdfs asociados",
                "mayor a menor",
                "ordena",
                "ordenalos",
                "top",
            ),
        )
        metadata_focus = self._contains_any(
            normalized=normalized,
            terms=(
                "metadata",
                "metadatos",
                "campo",
                "campos",
                "columna",
                "columnas",
                "atributo",
                "atributos",
                "valor",
                "valores",
                "csv",
                "tabla",
            ),
        )
        metadata_validation_requested = (metadata_focus or metadata_prompt or explicit_archive_reference) and self._contains_any(
            normalized=normalized,
            terms=(
                "valida",
                "validar",
                "validacion",
                "confirma",
                "confirmar",
                "confirma si",
                "coherente",
                "coherentes",
                "coherencia",
                "consistente",
                "consistentes",
            ),
        )
        generic_metadata_aggregate_requested = metadata_prompt and (
            aggregate_requested
            or self._contains_any(
                normalized=normalized,
                terms=(
                    "cuales",
                    "lista",
                    "listame",
                    "muestrame",
                    "ordena",
                    "top",
                    "mas de un",
                    "mas de una",
                    "multiples",
                    "repetidos",
                    "duplicados",
                ),
            )
            or re.search(r"\bque\b.+\b(?:hay|existen|tienen?)\b", normalized) is not None
        )
        citation_requested = self._contains_any(
            normalized=normalized,
            terms=(
                "cita",
                "citas",
                "cita la clausula",
                "cita el pdf",
                "cita los pdfs",
                "cita el documento",
                "cita los documentos",
                "documentos relevantes",
                "pdf relevante",
                "pdfs mas relevantes",
                "sustenta",
                "respalda",
                "evidencia documental",
                "evidencia del documento",
            ),
        )
        versioned_requested = self._contains_any(
            normalized=normalized,
            terms=(
                "ultima modificacion",
                "ultima version",
                "ultimas modificaciones",
                "modificaciones tiene",
                "que cambio",
                "que cambios",
            ),
        ) or self._contains_latest_document_signal(normalized=normalized)
        generic_metadata_lookup_requested = self._contains_any(
            normalized=normalized,
            terms=(
                "cual",
                "cuales",
                "quien",
                "quienes",
                "donde",
                "cuando",
                "indica",
                "muestra",
                "revisa",
                "consulta",
                "detalle",
            ),
        )
        if not generic_metadata_lookup_requested and explicit_archive_reference:
            generic_metadata_lookup_requested = (
                re.search(
                    r"\bque\b(?:(?:\s+\w+){0,6})\b(?:es|son|tiene|tienen|corresponde|aparece|figura)\b",
                    normalized,
                )
                is not None
            )
        document_grounding_requested = citation_requested or self._contains_pdf_reference(question=question) or self._contains_any(
            normalized=normalized,
            terms=(
                "linea de tiempo",
                "linea del tiempo",
                "timeline",
                "documento base",
                "tipo de documento",
                "partes involucradas",
                "fechas clave",
                "hito",
                "hitos",
                "clausula",
                "que cambio",
                "que cambios",
            ),
        )
        document_analysis_requested = self._contains_document_analysis_signal(
            question=question,
            normalized=normalized,
        )
        document_content_requested = self._contains_document_content_request(normalized=normalized)

        if "si hoy es" in normalized or (
            self._contains_any(
                normalized=normalized,
                terms=("cuanto tiempo", "cuantos dias", "cuantas semanas", "cuantos meses"),
            )
            and self._contains_any(
                normalized=normalized,
                terms=("resta", "queda", "faltan", "vence", "vencimiento", "termina", "finaliza"),
            )
        ):
            return QuestionClassification(question_class="temporal", rationale="reference-date")

        if document_content_requested:
            return QuestionClassification(question_class="exhaustive_synthesis", rationale="document-content-request")

        if quality_review_requested and (metadata_prompt or explicit_archive_reference or metadata_focus):
            return QuestionClassification(question_class="metadata_comparison", rationale="docling-quality-review")

        if metadata_validation_requested and not citation_requested and not comparison_requested:
            return QuestionClassification(question_class="metadata_comparison", rationale="metadata-validation")

        if comparison_requested and (metadata_focus or metadata_prompt) and document_grounding_requested:
            return QuestionClassification(
                question_class="exhaustive_synthesis",
                rationale="document-grounded-comparison",
            )

        if comparison_requested and metadata_focus and self._contains_any(
            normalized=normalized,
            terms=(
                "campo",
                "campos",
                "columna",
                "columnas",
                "atributo",
                "atributos",
                "valor",
                "valores",
            ),
        ):
            return QuestionClassification(
                question_class="metadata_comparison",
                rationale="structured-metadata-comparison",
            )

        if aggregate_requested and (
            metadata_focus
            or metadata_prompt
            or self._contains_any(
                normalized=normalized,
                terms=(
                    "versiones documentales",
                    "pdfs asociados",
                    "campo",
                    "campos",
                    "columna",
                    "columnas",
                    "atributo",
                    "atributos",
                ),
            )
        ):
            return QuestionClassification(question_class="analytics", rationale="count-or-aggregate")

        if generic_metadata_aggregate_requested:
            return QuestionClassification(question_class="analytics", rationale="dynamic-metadata-aggregate")

        if versioned_requested and not comparison_requested:
            return QuestionClassification(question_class="versioned", rationale="versioned-clause")

        if self._contains_any(
            normalized=normalized,
            terms=("linea de tiempo", "linea del tiempo", "timeline", "reconstruye", "hitos"),
        ):
            return QuestionClassification(question_class="exhaustive_synthesis", rationale="timeline-synthesis")

        if document_grounding_requested or (document_analysis_requested and comparison_requested and not metadata_focus):
            return QuestionClassification(
                question_class="exhaustive_synthesis",
                rationale="document-grounded-comparison",
            )

        if comparison_requested and (metadata_focus or metadata_prompt or explicit_archive_reference):
            return QuestionClassification(question_class="metadata_comparison", rationale="comparison-or-sweep")

        if (
            explicit_archive_reference
            and generic_metadata_lookup_requested
            and not document_grounding_requested
            and not document_analysis_requested
            and not comparison_requested
        ):
            return QuestionClassification(question_class="metadata_comparison", rationale="archive-scoped-metadata")

        if (metadata_focus or metadata_prompt) and not document_analysis_requested and not citation_requested and not aggregate_requested:
            return QuestionClassification(question_class="metadata_comparison", rationale="metadata-focused")

        if versioned_requested:
            return QuestionClassification(question_class="versioned", rationale="versioned-clause")

        if aggregate_requested:
            return QuestionClassification(question_class="analytics", rationale="count-or-aggregate")

        if self._contains_any(
            normalized=normalized,
            terms=(
                "genera un analisis",
                "analiza",
                "analisis",
                "resume",
                "resumen",
            ),
        ):
            return QuestionClassification(question_class="exhaustive_synthesis", rationale="open-ended-multi-doc")

        return QuestionClassification(question_class="extractive", rationale="default-extractive")
