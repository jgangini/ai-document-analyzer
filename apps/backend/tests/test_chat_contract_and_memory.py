from __future__ import annotations

from apps.backend.app.contracts.chat import ChatRequest, ChatResponse
from apps.backend.app.core.config import Settings
from apps.backend.app.services.session_memory import SessionMemoryStore, normalize_session_id


def test_chat_contract_matches_required_shape() -> None:
    request = ChatRequest(message="hola", session_id="s1", reset_session=True)
    response = ChatResponse(answer="respuesta", sources=["fuente"])

    assert request.model_dump() == {
        "message": "hola",
        "session_id": "s1",
        "reset_session": True,
    }
    assert response.model_dump() == {
        "answer": "respuesta",
        "sources": ["fuente"],
    }


def test_session_memory_uses_sanitized_stable_session_key() -> None:
    assert normalize_session_id(" usuario 1 / pod ") == "usuario_1_pod"


def test_local_session_memory_reset_and_append_turn() -> None:
    settings = Settings(
        _env_file=None,
        SESSION_MEMORY_BACKEND="local",
        SESSION_MEMORY_TTL_SECONDS=60,
    )
    store = SessionMemoryStore(settings)

    store.reset_session("session-test")
    store.append_turn(
        session_id="session-test",
        user_message="pregunta",
        assistant_answer="respuesta",
    )

    assert store.get_history("session-test") == [
        {"role": "user", "content": "pregunta"},
        {"role": "assistant", "content": "respuesta"},
    ]

    store.reset_session("session-test")
    assert store.get_history("session-test") == []
