"""Servicios de agentes y orquestador de consulta RAG con runtime LangGraph."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.backend.app.contracts.questions import EvidenceItem
from apps.backend.app.core.config import Settings, get_settings
from apps.backend.app.agent.contracts import LLMResult, QueryExecutionResult
from apps.backend.app.agent.router import (
    GraphCollaboration,
    GraphIntentRouter,
    GraphSearchResponder,
    GraphSynthesis,
)
from apps.backend.app.integrations.generative_ai import OCIGenerativeAIService
from apps.backend.app.services.runtime_config_service import ConfigService

@dataclass(slots=True)
class QAPlan:
    strategy: str
    selected_provider: str
    top_k: int


class SupervisorAgent:
    """Planificador de estrategia de respuesta."""

    def create_plan(
        self,
        *,
        question: str,
        requested_top_k: int,
        question_class: str = "extractive",
    ) -> QAPlan:
        complexity_terms = ("compare", "analyze", "summarize", "timeline", "difference")
        normalized = question.lower()
        is_complex = len(question.split()) > 20 or any(token in normalized for token in complexity_terms)
        if question_class in {"analytics", "inventory", "metadata_comparison"}:
            strategy = "facts-first"
        elif question_class == "visual_consistency":
            strategy = "multimodal-grounded"
        elif question_class in {"versioned", "temporal", "exhaustive_synthesis"} or is_complex:
            strategy = "deep-reasoning"
        else:
            strategy = "fast-grounded"
        selected_provider = "gemini-config-model"
        return QAPlan(strategy=strategy, selected_provider=selected_provider, top_k=max(1, requested_top_k))


class AnalysisAgent:
    """Filtro pre-sintesis (actualmente passthrough)."""

    def run(self, *, evidence: list[EvidenceItem]) -> list[EvidenceItem]:
        return evidence


class SynthesisAgent:
    """Sintesis principal via OCI para ruta DOCUMENT."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        config_service: ConfigService | None = None,
        oci_provider: OCIGenerativeAIService | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.config_service = config_service
        self.oci_provider = oci_provider or OCIGenerativeAIService(
            settings=self.settings,
            config_service=self.config_service,
        )
        self._synthesis_chain = GraphSynthesis(self.oci_provider)

    def run(
        self,
        *,
        question: str,
        evidence: list[EvidenceItem],
        strategy: str,
        visual_context: str = "",
        summary_mode: str = "default",
        selected_docs_count: int = 0,
        fact_context: str = "",
        question_class: str = "extractive",
    ) -> LLMResult:
        return self._synthesis_chain.synthesize(
            question=question,
            evidence=evidence,
            strategy=strategy,
            visual_context=visual_context,
            summary_mode=summary_mode,
            selected_docs_count=selected_docs_count,
            fact_context=fact_context,
            question_class=question_class,
        )


class QueryRouterOrSupervisor:
    def __init__(
        self,
        *,
        supervisor: SupervisorAgent,
        retrieval_tool: Any,
        analysis_agent: AnalysisAgent,
        answer_agent: SynthesisAgent,
        hybrid_answer_tool: Any,
        oci_provider: OCIGenerativeAIService | None = None,
        intent_router: GraphIntentRouter | None = None,
        casual_responder: GraphSearchResponder | None = None,
    ) -> None:
        self.supervisor = supervisor
        self.retrieval_tool = retrieval_tool
        self.analysis_agent = analysis_agent
        self.answer_agent = answer_agent
        self.hybrid_answer_tool = hybrid_answer_tool
        effective_provider = oci_provider or OCIGenerativeAIService(
            settings=get_settings(),
            config_service=None,
        )
        self._collaboration = GraphCollaboration(effective_provider)
        self._intent_router = intent_router or GraphIntentRouter(effective_provider)
        self._casual_responder = casual_responder or GraphSearchResponder(effective_provider)

    def warmup(self) -> None:
        self.retrieval_tool.warmup()

    def _run_langchain_collaboration(
        self,
        *,
        question: str,
        evidence: list[EvidenceItem],
        strategy: str,
    ) -> list[str]:
        return self._collaboration.confidence_notes(
            question=question,
            evidence=evidence,
            strategy=strategy,
        )

    def run(
        self,
        *,
        question: str,
        file_ids: list[int] | None = None,
        top_k: int = 5,
    ) -> QueryExecutionResult:
        safe_file_ids = list(file_ids or [])
        route = self._intent_router.classify(question=question, file_ids=safe_file_ids)
        if route == GraphIntentRouter.SEARCH_ROUTE:
            casual_answer = self._casual_responder.respond(question=question)
            return QueryExecutionResult(
                strategy="search",
                selected_provider="supervisor-search",
                evidence=[],
                answer=casual_answer,
                answer_mode="small_talk",
                visual_confirmation_used=False,
                analyzed_pages=[],
                confidence_notes=["Ruta Supervisor: SEARCH."],
                ocr_vs_visual_discrepancies=[],
            )
        plan = self.supervisor.create_plan(question=question, requested_top_k=top_k)
        retrieval = self.retrieval_tool.retrieve(
            question=question,
            user_id=None,
            file_ids=safe_file_ids,
            top_k=plan.top_k,
        )
        analyzed_evidence = self.analysis_agent.run(evidence=retrieval.evidence)
        chain_notes = self._run_langchain_collaboration(
            question=question,
            evidence=analyzed_evidence,
            strategy=plan.strategy,
        )
        hybrid_answer = self.hybrid_answer_tool.answer(
            question=question,
            evidence=analyzed_evidence,
            strategy=plan.strategy,
        )
        if chain_notes:
            hybrid_answer.confidence_notes.extend(chain_notes)
        return QueryExecutionResult(
            strategy=plan.strategy,
            selected_provider=plan.selected_provider,
            evidence=analyzed_evidence,
            answer=hybrid_answer.llm_result,
            answer_mode=hybrid_answer.answer_mode,
            visual_confirmation_used=hybrid_answer.visual_confirmation_used,
            analyzed_pages=hybrid_answer.analyzed_pages,
            confidence_notes=hybrid_answer.confidence_notes,
            ocr_vs_visual_discrepancies=hybrid_answer.ocr_vs_visual_discrepancies,
        )

