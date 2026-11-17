"""Tool multimodal para consultar preguntas de usuario sobre imagenes."""

from __future__ import annotations

from dataclasses import dataclass

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.core.config import Settings
from apps.backend.app.agent.contracts import VisualInspectionResult
from apps.backend.app.integrations.generative_ai import OCIGenerativeAIService
from apps.backend.app.services.runtime_config_service import ConfigService
from apps.backend.app.storage.object_storage_service import ObjectStorageService


@dataclass(slots=True)
class VisualPageFinding:
    page_number: int
    answer_candidate: str
    observed_text: str
    confidence_notes: list[str]
    ocr_vs_visual_discrepancies: list[str]


class PageVisionTool:
    """Consulta visual directa por pagina sobre objetos OCI."""

    def __init__(
        self,
        settings: Settings,
        config_service: ConfigService | None = None,
        oci_provider: OCIGenerativeAIService | None = None,
    ) -> None:
        self.settings = settings
        self.config_service = config_service
        self._provider = oci_provider or OCIGenerativeAIService(
            settings=settings,
            config_service=config_service,
        )
        self.object_storage = ObjectStorageService(settings)

    def is_available(self) -> bool:
        return self._provider.is_available()

    def analyze(
        self,
        *,
        question: str,
        evidence: list[EvidenceItem],
        require_visual: bool = False,
    ) -> VisualInspectionResult:
        provider = self.settings.visual_verifier_provider
        if provider != "oci" or not self.is_available():
            if not require_visual:
                return VisualInspectionResult(
                    used=False,
                    analyzed_pages=[],
                    visual_context="",
                    confidence_notes=[],
                    ocr_vs_visual_discrepancies=[],
                )
            raise RuntimeError("Verificacion multimodal no disponible: proveedor OCI no configurado.")

        findings: list[VisualPageFinding] = []
        analyzed_pages: list[int] = []
        for item in evidence[: max(1, self.settings.visual_analysis_top_k)]:
            if not item.object_name_page:
                continue
            try:
                finding = self._analyze_page(question=question, evidence_item=item)
                findings.append(finding)
                analyzed_pages.append(item.page_number)
            except Exception as exc:
                raise RuntimeError(f"Fallo verificacion multimodal en page_id={item.page_id}.") from exc

        if not findings:
            if not require_visual:
                return VisualInspectionResult(
                    used=False,
                    analyzed_pages=[],
                    visual_context="",
                    confidence_notes=[],
                    ocr_vs_visual_discrepancies=[],
                )
            raise RuntimeError("Verificacion multimodal obligatoria sin hallazgos utilizables.")

        visual_context_parts = []
        confidence_notes: list[str] = []
        discrepancies: list[str] = []
        for finding in findings:
            visual_context_parts.append(
                f"[Visual page {finding.page_number}] answer_candidate={finding.answer_candidate} observed_text={finding.observed_text}"
            )
            confidence_notes.extend(finding.confidence_notes)
            discrepancies.extend(finding.ocr_vs_visual_discrepancies)

        return VisualInspectionResult(
            used=True,
            analyzed_pages=analyzed_pages,
            visual_context="\n".join(visual_context_parts),
            confidence_notes=confidence_notes,
            ocr_vs_visual_discrepancies=discrepancies,
        )

    def _analyze_page(self, *, question: str, evidence_item: EvidenceItem) -> VisualPageFinding:
        data_uri = self.object_storage.get_object_data_uri(evidence_item.object_name_page)
        if not data_uri:
            raise RuntimeError("Page object data URI unavailable.")

        prompt = (
            "Eres un analista documental visual.\n"
            "Responde en texto plano (NO JSON).\n"
            "Primero da una respuesta breve y directa a la pregunta.\n"
            "Luego agrega una linea que inicie con 'EVIDENCIA:' con el texto visible que sustenta tu respuesta.\n"
            "Si no puedes confirmarlo visualmente, responde 'No visible en la imagen'.\n\n"
            f"Pregunta del usuario:\n{question}\n"
        )
        raw_answer = self._provider.invoke_multimodal_text(
            prompt=prompt,
            image_data_uri=data_uri,
        )
        answer_candidate, observed_text = self._split_visual_answer(raw_answer)
        return VisualPageFinding(
            page_number=evidence_item.page_number,
            answer_candidate=answer_candidate,
            observed_text=observed_text,
            confidence_notes=["Consulta visual directa aplicada sobre la imagen de la pagina."],
            ocr_vs_visual_discrepancies=[],
        )

    @staticmethod
    def _split_visual_answer(raw_answer: str) -> tuple[str, str]:
        text = str(raw_answer or "").strip()
        if not text:
            return "No visible en la imagen.", ""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        evidence_line = ""
        answer_lines: list[str] = []
        for line in lines:
            lowered = line.lower()
            if lowered.startswith("evidencia:"):
                evidence_line = line.split(":", 1)[1].strip() if ":" in line else ""
                continue
            if lowered.startswith("respuesta:"):
                content = line.split(":", 1)[1].strip() if ":" in line else ""
                if content:
                    answer_lines.append(content)
                continue
            answer_lines.append(line)
        answer_candidate = " ".join(answer_lines).strip() or text
        observed_text = evidence_line or answer_candidate
        return answer_candidate, observed_text
