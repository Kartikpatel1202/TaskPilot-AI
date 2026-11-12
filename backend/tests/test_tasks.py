from __future__ import annotations

import sys
import uuid
from datetime import datetime
from typing import Any

from fastapi.testclient import TestClient

from app.core.persona import detect_language


def _post(client: TestClient, command: str, session_id: str | None = None, mode: str = "TEXT"):
    return client.post(
        "/api/v1/tasks",
        json={"command": command, "session_id": session_id or str(uuid.uuid4()), "input_mode": mode},
    )


def test_valid_command_returns_202(client: TestClient, session_id: str) -> None:
    response = _post(client, "Open Blinkit and prepare my grocery cart", session_id)
    assert response.status_code == 202
    body = response.json()
    assert body["accepted"] is True
    assert body["session_id"] == session_id
    assert body["state"] == "IDLE"
    assert body["message"] == "Task accepted. Kamlesh Bhai is preparing an action plan."
    uuid.UUID(body["task_id"])
    assert datetime.fromisoformat(body["created_at"].replace("Z", "+00:00")).tzinfo is not None


def test_voice_input_mode_is_accepted(client: TestClient) -> None:
    assert _post(client, "Search for Python tutorials", mode="VOICE").status_code == 202


def test_empty_command_rejected(client: TestClient) -> None:
    response = _post(client, "")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_whitespace_only_command_rejected(client: TestClient) -> None:
    response = _post(client, "   \n\t  ")
    assert response.status_code == 422
    assert response.json()["code"] == "VALIDATION_ERROR"


def test_command_is_trimmed(client: TestClient) -> None:
    body = _post(client, "   hello there   ").json()
    task = client.get(f"/api/v1/tasks/{body['task_id']}").json()
    assert task["command"] == "hello there"


def test_command_beyond_max_length_rejected(client: TestClient) -> None:
    assert _post(client, "a" * 4000).status_code == 202
    assert _post(client, "a" * 4001).status_code == 422


def test_invalid_session_id_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks", json={"command": "hi", "session_id": "not-a-uuid", "input_mode": "TEXT"}
    )
    assert response.status_code == 422


def test_invalid_input_mode_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/v1/tasks", json={"command": "hi", "session_id": str(uuid.uuid4()), "input_mode": "TELEPATHY"}
    )
    assert response.status_code == 422


def test_task_ids_are_unique(client: TestClient, session_id: str) -> None:
    ids = {_post(client, f"command {i}", session_id).json()["task_id"] for i in range(25)}
    assert len(ids) == 25


def test_task_starts_idle_and_stays_idle_when_planning_disabled(client_factory: Any, session_id: str) -> None:
    client = client_factory(agent_planning_enabled=False)
    body = _post(client, "Find a laptop under 60000 on Amazon", session_id).json()
    assert body["state"] == "IDLE"
    assert body["message"] == "Task accepted. Agent planning will be available in a later phase."
    task = client.get(f"/api/v1/tasks/{body['task_id']}").json()
    assert task["state"] == "IDLE"  # no planner runs when planning is disabled


def test_new_task_is_accepted_in_idle_state(client: TestClient, session_id: str) -> None:
    assert _post(client, "Find a laptop under 60000 on Amazon", session_id).json()["state"] == "IDLE"


def test_planning_never_launches_a_browser(client: TestClient) -> None:
    from .conftest import wait_for_task_state

    container = client.app.state.container  # type: ignore[attr-defined]
    task_id = _post(client, "Open YouTube and search for Python tutorials").json()["task_id"]
    assert wait_for_task_state(client, task_id)["state"] == "PLANNED"
    assert container.provider.name == "mock"
    # Only an explicit Run Plan (POST /tasks/{id}/execute) may start Chromium.
    assert container.browser.is_started is False
    assert container.browser.active_session_count == 0
    for module in ("selenium", "langchain", "langgraph"):
        assert module not in sys.modules


def test_get_unknown_task_returns_404(client: TestClient) -> None:
    response = client.get(f"/api/v1/tasks/{uuid.uuid4()}")
    assert response.status_code == 404
    assert response.json()["code"] == "TASK_NOT_FOUND"


def test_list_tasks_is_scoped_to_session(client: TestClient) -> None:
    a, b = str(uuid.uuid4()), str(uuid.uuid4())
    _post(client, "for a", a)
    _post(client, "for b", b)
    tasks = client.get("/api/v1/tasks", params={"session_id": a}).json()["tasks"]
    assert [t["command"] for t in tasks] == ["for a"]


def test_language_detection_for_persona() -> None:
    assert detect_language("Open YouTube and search for Python tutorials") == "en"
    assert detect_language("Blinkit kholo aur 2 litre doodh add karo") == "hinglish"
    assert detect_language("मुझे दूध और ब्रेड चाहिए") == "hi"
    assert detect_language("Please do it") == "en"
