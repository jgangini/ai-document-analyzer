"""Deep Agents adapter restricted to ledger-backed evidence tools."""

from __future__ import annotations

from typing import Any

from apps.backend.app.evidence.repository import EvidenceLedgerRepository


DEEP_AGENT_SYSTEM_PROMPT = """
You are the document evidence orchestrator for AI Document Analyzer.
Use only the provided ledger tools as factual sources. Memory may preserve
conversation continuity, but it is never legal or documentary evidence.
If verified evidence is missing for a claim that requires citation, say that
the evidence is insufficient and request human review.
""".strip()


def build_document_deep_agent(*, ledger_repository: EvidenceLedgerRepository, model: Any | None = None):
    """Create a Deep Agent with no filesystem or shell tools.

    The caller is responsible for passing a production model/checkpointer.
    Import is delayed so local development works before the dependency is
    installed.
    """

    from deepagents import create_deep_agent

    def get_exact_unit_text(source_id: str, unit_id: str) -> dict[str, Any]:
        unit = ledger_repository.get_verified_unit(source_id=source_id, unit_id=unit_id)
        if unit is None:
            return {"found": False, "hash_verified": False}
        return {
            "found": True,
            "source_id": unit.source_id,
            "unit_id": unit.unit_id,
            "citation_label": unit.citation_label,
            "text": unit.text,
            "evidence_id": unit.evidence_id,
            "hash_verified": unit.hash_verified,
        }

    def validate_evidence_ids(evidence_ids: list[str]) -> dict[str, Any]:
        clean_ids = [str(item).strip() for item in list(evidence_ids or []) if str(item).strip()]
        invalid = [item for item in clean_ids if not item.startswith("ev_")]
        return {"valid": not invalid, "invalid": invalid, "checked": clean_ids}

    tools = [get_exact_unit_text, validate_evidence_ids]
    subagents = [
        {
            "name": "query-router",
            "description": "Classifies whether the user needs exact evidence, synthesis, or clarification.",
            "prompt": "Route the request. Do not answer from memory.",
        },
        {
            "name": "evidence-hash-auditor",
            "description": "Checks every cited evidence id and rejects unsupported claims.",
            "prompt": "Audit citations using only tool-returned evidence_id values.",
            "tools": [validate_evidence_ids],
        },
        {
            "name": "answer-writer",
            "description": "Writes concise answers grounded only in verified evidence.",
            "prompt": "Write the final answer with source labels and evidence ids.",
        },
    ]
    kwargs: dict[str, Any] = {
        "tools": tools,
        "system_prompt": DEEP_AGENT_SYSTEM_PROMPT,
        "subagents": subagents,
    }
    if model is not None:
        kwargs["model"] = model
    return create_deep_agent(**kwargs)
