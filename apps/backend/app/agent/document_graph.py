"""Builder del grafo QA documental."""

from __future__ import annotations

from langgraph.graph import END, START, StateGraph

from apps.backend.app.agent.nodes import QAGraphNodes
from apps.backend.app.agent.state import QAGraphState


def _route_after_classification(state: QAGraphState) -> str:
    route = str(state.get("route") or "document").strip().lower()
    return "search_response" if route == "search" else "resolve_scope"


def _route_after_answerability(state: QAGraphState) -> str:
    route = str(state.get("answerability_route") or "").strip().lower()
    return "synthesize_document_answer" if route == "metadata" else "retrieve_candidates"


def build_qa_graph(*, nodes: QAGraphNodes, checkpointer=None):
    graph_builder = StateGraph(QAGraphState)
    graph_builder.add_node("classify_intent", nodes.classify_intent)
    graph_builder.add_node("search_response", nodes.search_response)
    graph_builder.add_node("resolve_scope", nodes.resolve_scope)
    graph_builder.add_node("classify_question", nodes.classify_question)
    graph_builder.add_node("resolve_facts", nodes.resolve_facts)
    graph_builder.add_node("decide_answerability", nodes.decide_answerability)
    graph_builder.add_node("retrieve_candidates", nodes.retrieve_candidates)
    graph_builder.add_node("fuse_page_evidence", nodes.fuse_page_evidence)
    graph_builder.add_node("maybe_verify_visual", nodes.maybe_verify_visual)
    graph_builder.add_node("synthesize_document_answer", nodes.synthesize_document_answer)
    graph_builder.add_node("persist_turn", nodes.persist_turn)

    graph_builder.add_edge(START, "classify_intent")
    graph_builder.add_conditional_edges(
        "classify_intent",
        _route_after_classification,
        {
            "search_response": "search_response",
            "resolve_scope": "resolve_scope",
        },
    )
    graph_builder.add_edge("search_response", "persist_turn")
    graph_builder.add_edge("resolve_scope", "classify_question")
    graph_builder.add_edge("classify_question", "resolve_facts")
    graph_builder.add_edge("resolve_facts", "decide_answerability")
    graph_builder.add_conditional_edges(
        "decide_answerability",
        _route_after_answerability,
        {
            "retrieve_candidates": "retrieve_candidates",
            "synthesize_document_answer": "synthesize_document_answer",
        },
    )
    graph_builder.add_edge("retrieve_candidates", "fuse_page_evidence")
    graph_builder.add_edge("fuse_page_evidence", "maybe_verify_visual")
    graph_builder.add_edge("maybe_verify_visual", "synthesize_document_answer")
    graph_builder.add_edge("synthesize_document_answer", "persist_turn")
    graph_builder.add_edge("persist_turn", END)
    return graph_builder.compile(checkpointer=checkpointer)
