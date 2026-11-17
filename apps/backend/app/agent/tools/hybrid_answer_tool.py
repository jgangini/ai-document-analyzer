"""Tool para consolidar evidencia y generar respuesta final."""

from __future__ import annotations

import re
from typing import Any
import unicodedata

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.core.config import Settings
from apps.backend.app.agent.contracts import HybridAnswerResult, LLMResult, VisualInspectionResult
from apps.backend.app.rag.retrieval.query_service import question_requests_full_document_coverage


class HybridAnswerTool:
    """Tool de consolidacion/sintesis para flujo QA."""

    VISUAL_QUERY_TERMS = (
        "monto",
        "fecha",
        "registro",
        "repertorio",
        "fojas",
        "inscripcion",
        "hipoteca",
    )

    name: str = "hybrid_answer_consolidation"
    description: str = (
        "Consolidate selected document evidence (OCR + optional visual checks) and produce "
        "a grounded final answer."
    )
    result_as_answer: bool = True

    def __init__(
        self,
        *,
        settings: Settings,
        page_vision_tool: Any,
        synthesis_agent,
        **data,
    ) -> None:
        del data
        self.settings = settings
        self.page_vision_tool = page_vision_tool
        self.synthesis_agent = synthesis_agent

    def answer(
        self,
        *,
        question: str,
        evidence: list[EvidenceItem],
        strategy: str,
        visual_result: VisualInspectionResult | None = None,
        summary_mode: str = "default",
        selected_docs_count: int = 0,
        question_class: str = "extractive",
        fact_context_text: str = "",
        answer_override: str | None = None,
    ) -> HybridAnswerResult:
        evidence_limit = max(1, int(self.settings.answer_max_evidence))
        per_document_mode = str(summary_mode or "").strip().lower() == "per_document"
        full_document_mode = bool(
            question_requests_full_document_coverage(question)
            and len({int(item.file_id) for item in evidence if int(item.file_id) > 0}) <= 1
        )
        selected_evidence = list(
            evidence if (per_document_mode or full_document_mode) else evidence[:evidence_limit]
        )
        use_visual = (
            False
            if answer_override or per_document_mode or full_document_mode
            else self._should_use_visual(question=question, evidence=selected_evidence)
        )
        resolved_visual_result = VisualInspectionResult(
            used=False,
            analyzed_pages=[],
            visual_context="",
            confidence_notes=[],
            ocr_vs_visual_discrepancies=[],
        )
        if visual_result is not None:
            resolved_visual_result = visual_result
        elif use_visual:
            resolved_visual_result = self.page_vision_tool.analyze(question=question, evidence=selected_evidence)

        if answer_override:
            llm_result = self._build_answer_override_result(
                answer_text=answer_override,
                evidence=selected_evidence,
                question_class=question_class,
            )
        else:
            llm_result = self.synthesis_agent.run(
                question=question,
                evidence=selected_evidence,
                strategy=strategy,
                visual_context=resolved_visual_result.visual_context if resolved_visual_result.used else "",
                summary_mode=summary_mode,
                selected_docs_count=selected_docs_count,
                fact_context=fact_context_text,
                question_class=question_class,
            )
            llm_result = self._apply_deterministic_overrides(
                question=question,
                evidence=selected_evidence,
                llm_result=llm_result,
                confidence_notes=resolved_visual_result.confidence_notes,
            )
            llm_result = self._prepend_metadata_table_when_available(
                llm_result=llm_result,
                fact_context_text=fact_context_text,
                evidence=selected_evidence,
            )

        confidence_notes = list(resolved_visual_result.confidence_notes)
        if fact_context_text:
            confidence_notes.append("Facts layer aporto contexto estructurado antes de la sintesis.")
            if selected_evidence and self._build_metadata_context_table(fact_context_text=fact_context_text):
                confidence_notes.append("Metadata table was preserved before the document-grounded synthesis.")
        if answer_override:
            confidence_notes.append("La respuesta final fue resuelta de forma deterministica desde la facts layer.")
        if selected_evidence:
            confidence_notes.append(
                f"Mejor score de retrieval: {selected_evidence[0].score:.4f} en pagina {selected_evidence[0].page_number}."
            )
        if full_document_mode and selected_evidence:
            ordered_pages = sorted({int(item.page_number) for item in selected_evidence if int(item.page_number) > 0})
            confidence_notes.append(
                "Cobertura de documento completo: "
                f"{len(ordered_pages)} paginas OCR enviadas a la sintesis "
                f"({', '.join(str(page) for page in ordered_pages[:20])}"
                f"{'...' if len(ordered_pages) > 20 else ''})."
            )

        return HybridAnswerResult(
            llm_result=llm_result,
            answer_mode=str(question_class or "extractive"),
            visual_confirmation_used=resolved_visual_result.used,
            analyzed_pages=resolved_visual_result.analyzed_pages,
            confidence_notes=confidence_notes,
            ocr_vs_visual_discrepancies=resolved_visual_result.ocr_vs_visual_discrepancies,
        )

    @staticmethod
    def _build_answer_override_result(
        *,
        answer_text: str,
        evidence: list[EvidenceItem],
        question_class: str,
    ) -> LLMResult:
        citation_numbers = sorted(
            {
                int(item.source_number)
                for item in evidence
                if int(item.source_number) > 0
            }
        )
        normalized_answer = str(answer_text or "").strip()
        return LLMResult(
            answer_text=normalized_answer,
            executive_summary=normalized_answer,
            key_points=[normalized_answer] if normalized_answer else [],
            obligations=[],
            citation_source_numbers=citation_numbers,
            model_used=f"facts-layer:{question_class or 'extractive'}",
        )

    @classmethod
    def _prepend_metadata_table_when_available(
        cls,
        *,
        llm_result: LLMResult,
        fact_context_text: str,
        evidence: list[EvidenceItem],
    ) -> LLMResult:
        if not evidence:
            return llm_result
        metadata_table = cls._build_metadata_context_table(fact_context_text=fact_context_text)
        if not metadata_table:
            return llm_result
        answer_text = str(llm_result.answer_text or "").strip()
        if cls._answer_already_contains_metadata_table(answer_text=answer_text):
            return llm_result
        merged_answer = "\n\n".join(part for part in (metadata_table, answer_text) if part.strip()).strip()
        return llm_result.__class__(
            answer_text=merged_answer,
            executive_summary=llm_result.executive_summary,
            key_points=list(llm_result.key_points),
            obligations=list(llm_result.obligations),
            citation_source_numbers=list(llm_result.citation_source_numbers),
            model_used=llm_result.model_used,
        )

    @classmethod
    def _build_metadata_context_table(cls, *, fact_context_text: str) -> str:
        metadata_lines = cls._extract_metadata_context_lines(
            fact_context_text=fact_context_text,
            heading="Resolved metadata facts:",
        )
        if not metadata_lines:
            metadata_lines = cls._extract_metadata_context_lines(
                fact_context_text=fact_context_text,
                heading="Archive metadata context:",
            )
        rows: list[tuple[str, dict[str, str]]] = []
        headers: list[str] = []
        for line in metadata_lines:
            match = re.match(r"^([^:]+):\s+(.+)$", line)
            if match is None:
                continue
            archive_slug = match.group(1).strip()
            if not archive_slug or archive_slug.lower().endswith("context"):
                continue
            fields: dict[str, str] = {}
            for raw_pair in match.group(2).split(";"):
                if "=" not in raw_pair:
                    continue
                field_name, field_value = raw_pair.split("=", 1)
                field_name = field_name.strip()
                field_value = field_value.strip()
                if not field_name or not field_value:
                    continue
                fields[field_name] = field_value
                if field_name not in headers:
                    headers.append(field_name)
            if fields:
                rows.append((archive_slug, fields))
        if not rows or not headers:
            return ""
        bounded_headers = headers[:10]
        table_lines = [
            "| " + " | ".join(cls._escape_markdown_table_cell(value) for value in ("Archivo", *bounded_headers)) + " |",
            "| " + " | ".join("---" for _ in ("Archivo", *bounded_headers)) + " |",
        ]
        for archive_slug, fields in rows:
            values = [archive_slug, *[fields.get(header, "") for header in bounded_headers]]
            table_lines.append(
                "| " + " | ".join(cls._escape_markdown_table_cell(value) for value in values) + " |"
            )
        return "Metadata resuelta:\n\n" + "\n".join(table_lines)

    @staticmethod
    def _extract_metadata_context_lines(*, fact_context_text: str, heading: str) -> list[str]:
        lines: list[str] = []
        capture = False
        for raw_line in str(fact_context_text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line == heading:
                capture = True
                continue
            if capture and (
                line.endswith("context:")
                or line.startswith("Resolved metadata ")
                or line.startswith("Document inventory ")
            ):
                break
            if capture:
                lines.append(line)
        return lines

    @classmethod
    def _answer_already_contains_metadata_table(cls, *, answer_text: str) -> bool:
        normalized = cls._normalize(answer_text)
        return bool(
            "metadata resuelta" in normalized
            or re.search(r"\|\s*archivo\s*\|", normalized) is not None
        )

    @staticmethod
    def _escape_markdown_table_cell(value: object) -> str:
        return str(value or "").replace("|", "\\|").replace("\n", " ").strip()

    def _apply_deterministic_overrides(
        self,
        *,
        question: str,
        evidence: list[EvidenceItem],
        llm_result: LLMResult,
        confidence_notes: list[str],
    ) -> LLMResult:
        if not evidence:
            return llm_result

        normalized_question = self._normalize(question)
        combined_text = "\n".join(item.summary_text or "" for item in evidence)

        if "derechos" in normalized_question and any(token in normalized_question for token in ("total", "sum", "sumado")):
            amounts = self._extract_right_amounts(combined_text)
            if amounts:
                total = sum(amounts)
                total_display = self._format_chilean_amount(total)
                answer_text = f"El total sumado de los derechos identificados es {total_display}."
                confidence_notes.append(f"Los montos de derechos se sumaron aritméticamente: {total_display}.")
                return llm_result.__class__(
                    answer_text=answer_text,
                    executive_summary=answer_text,
                    key_points=list(llm_result.key_points),
                    obligations=list(llm_result.obligations),
                    citation_source_numbers=list(llm_result.citation_source_numbers),
                    model_used=llm_result.model_used,
                )

        if "fecha" in normalized_question and "practic" in normalized_question:
            match = re.search(
                r"fecha\s+(\d{1,2}\s+de\s+[a-záéíóúñ]+\s+de\s+\d{4})",
                combined_text,
                flags=re.IGNORECASE,
            )
            if match:
                date_text = match.group(1)
                answer_text = f"La inscripción fue practicada con fecha {date_text}."
                return llm_result.__class__(
                    answer_text=answer_text,
                    executive_summary=answer_text,
                    key_points=list(llm_result.key_points),
                    obligations=list(llm_result.obligations),
                    citation_source_numbers=list(llm_result.citation_source_numbers),
                    model_used=llm_result.model_used,
                )

        if "fojas" in normalized_question and "hipotec" in normalized_question:
            match = re.search(
                r"Registro de Hipotecas y Grav[áa]menes\s+Fojas\s+([0-9\.\,]+)\s+n[úu]mero\s+([0-9\.\,]+)",
                combined_text,
                flags=re.IGNORECASE,
            )
            if match:
                fojas = match.group(1).strip()
                numero = match.group(2).strip()
                answer_text = (
                    f"En el Registro de Hipotecas y Gravámenes figura a fojas {fojas}, número {numero}."
                )
                return llm_result.__class__(
                    answer_text=answer_text,
                    executive_summary=answer_text,
                    key_points=list(llm_result.key_points),
                    obligations=list(llm_result.obligations),
                    citation_source_numbers=list(llm_result.citation_source_numbers),
                    model_used=llm_result.model_used,
                )

        return llm_result

    @staticmethod
    def _normalize(text: str) -> str:
        normalized = unicodedata.normalize("NFKD", text or "")
        return "".join(ch for ch in normalized if not unicodedata.combining(ch)).lower()

    @staticmethod
    def _extract_right_amounts(text: str) -> list[int]:
        amounts: list[int] = []
        for match in re.finditer(
            r"Derechos?\s*\$?\s*([0-9][0-9\.\,]*)",
            text,
            flags=re.IGNORECASE,
        ):
            raw = match.group(1)
            digits = re.sub(r"[^0-9]", "", raw)
            if digits:
                amounts.append(int(digits))
        return amounts

    @staticmethod
    def _format_chilean_amount(value: int) -> str:
        return f"${value:,}".replace(",", ".")

    def _should_use_visual(self, *, question: str, evidence: list[EvidenceItem]) -> bool:
        normalized_question = question.lower()
        if any(token in normalized_question for token in self.VISUAL_QUERY_TERMS):
            return True
        return any(self._is_low_signal_evidence(item) for item in evidence)

    @staticmethod
    def _is_low_signal_evidence(item: EvidenceItem) -> bool:
        summary = (item.summary_text or "").strip().lower()
        generic_summary = summary.startswith("page ") and " from " in summary
        return bool(generic_summary or len(summary) < 80)

