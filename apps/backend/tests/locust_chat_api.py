from __future__ import annotations

from locust import HttpUser, between, task


class ChatApiUser(HttpUser):
    wait_time = between(0.5, 2.0)

    @task
    def chat(self) -> None:
        session_id = f"locust-{id(self)}"
        self.client.post(
            "/api/chat",
            json={
                "message": "Resume la informacion disponible y cita fuentes.",
                "session_id": session_id,
                "reset_session": False,
            },
            name="/api/chat",
        )
