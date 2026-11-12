from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from fastapi.testclient import TestClient

from app.schemas.common import utc_now

from .conftest import of_type, receive_until


def _demo_approval(client: TestClient, session_id: str) -> dict[str, Any]:
    response = client.post("/api/v1/dev/demo/approval", json={"session_id": session_id})
    assert response.status_code == 201, response.text
    return response.json()


def _decide(client: TestClient, approval_id: str, decision: str = "APPROVE"):
    return client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": decision})


def test_demo_approval_can_be_generated(client: TestClient, session_id: str) -> None:
    approval = _demo_approval(client, session_id)
    assert approval["status"] == "PENDING"
    assert approval["is_demo"] is True
    assert approval["risk_level"] == "HIGH"
    assert approval["session_id"] == session_id
    task = client.get(f"/api/v1/tasks/{approval['task_id']}").json()
    assert task["state"] == "WAITING_APPROVAL"
    assert task["is_demo"] is True


def test_approval_required_event_is_published(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/ws/{session_id}") as ws:
        ws.receive_json()
        approval = _demo_approval(client, session_id)
        event, seen = receive_until(ws, of_type("approval.required"))
        assert event["data"]["approval_id"] == approval["approval_id"]
        assert event["data"]["is_demo"] is True
        states = [m["data"]["new_state"] for m in seen if m["type"] == "task.state_changed"]
        assert states == ["PLANNING", "EXECUTING", "WAITING_APPROVAL"]


def test_decision_accepted_once_and_duplicate_rejected(client: TestClient, session_id: str) -> None:
    approval = _demo_approval(client, session_id)
    first = _decide(client, approval["approval_id"], "APPROVE")
    assert first.status_code == 200
    body = first.json()
    assert body["decision"] == "APPROVE" and body["status"] == "APPROVED"
    assert set(body) == {"approval_id", "decision", "status", "resolved_at"}

    duplicate = _decide(client, approval["approval_id"], "REJECT")
    assert duplicate.status_code == 409
    assert duplicate.json()["code"] == "APPROVAL_ALREADY_RESOLVED"
    # decision is immutable
    assert client.get(f"/api/v1/approvals/{approval['approval_id']}").json()["status"] == "APPROVED"


def test_reject_decision(client: TestClient, session_id: str) -> None:
    approval = _demo_approval(client, session_id)
    body = _decide(client, approval["approval_id"], "REJECT").json()
    assert body["status"] == "REJECTED"
    task = client.get(f"/api/v1/tasks/{approval['task_id']}").json()
    assert task["state"] == "FAILED"


def test_expired_approval_is_rejected(client: TestClient, session_id: str) -> None:
    service = client.app.state.container.approvals  # type: ignore[attr-defined]
    approval = _demo_approval(client, session_id)
    service._clock = lambda: utc_now() + timedelta(hours=1)
    response = _decide(client, approval["approval_id"], "APPROVE")
    assert response.status_code == 410
    assert response.json()["code"] == "APPROVAL_EXPIRED"
    assert client.get(f"/api/v1/approvals/{approval['approval_id']}").json()["status"] == "EXPIRED"
    # still cannot be approved afterwards
    assert _decide(client, approval["approval_id"], "APPROVE").status_code == 409


def test_approval_resolution_event_is_published(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/ws/{session_id}") as ws:
        ws.receive_json()
        approval = _demo_approval(client, session_id)
        _decide(client, approval["approval_id"], "APPROVE")
        event, _ = receive_until(ws, of_type("approval.resolved"))
        assert event["data"]["approval_id"] == approval["approval_id"]
        assert event["data"]["decision"] == "APPROVE"
        assert event["data"]["status"] == "APPROVED"
        completed, _ = receive_until(ws, of_type("task.completed"))
        assert completed["data"]["is_demo"] is True


def test_invalid_approval_ids_rejected(client: TestClient) -> None:
    assert _decide(client, str(uuid.uuid4())).status_code == 404
    assert _decide(client, "not-a-uuid").status_code == 422


def test_invalid_decision_value_rejected(client: TestClient, session_id: str) -> None:
    approval = _demo_approval(client, session_id)
    assert _decide(client, approval["approval_id"], "MAYBE").status_code == 422


def test_demo_telemetry_stream_is_labelled(client: TestClient, session_id: str) -> None:
    with client.websocket_connect(f"/api/v1/ws/{session_id}") as ws:
        ws.receive_json()
        response = client.post("/api/v1/dev/demo/telemetry", json={"session_id": session_id})
        assert response.status_code == 202
        _, seen = receive_until(ws, of_type("task.completed"))
        receive_until(ws, of_type("browser.preview"))
        task_events = [m for m in seen if m["type"] != "connection.ready"]
        assert all(m["data"]["is_demo"] is True for m in task_events)
        preview = next(m for m in seen if m["type"] == "browser.preview")
        assert preview["data"]["mode"] == "PLACEHOLDER"
        assert preview["data"]["frame_data_url"] is None  # never a fabricated screenshot
        assert {"INFO", "DEBUG", "WARNING", "SUCCESS"} <= {
            m["data"]["level"] for m in seen if m["type"] == "log.created"
        }


def test_demo_endpoints_404_when_disabled(client_factory: Any, session_id: str) -> None:
    client = client_factory(enable_demo_endpoints=False)
    assert client.post("/api/v1/dev/demo/telemetry", json={"session_id": session_id}).status_code == 404
    assert client.post("/api/v1/dev/demo/approval", json={"session_id": session_id}).status_code == 404


def test_demo_endpoints_404_outside_development(client_factory: Any, session_id: str) -> None:
    # Phase 6: production refuses to start with unsafe development settings at all, so this runs in staging.
    client = client_factory(app_env="staging", enable_demo_endpoints=True, agent_allow_mock_in_production=True)
    assert client.post("/api/v1/dev/demo/approval", json={"session_id": session_id}).status_code == 404


def test_demo_endpoints_do_not_accept_arbitrary_events(client: TestClient, session_id: str) -> None:
    response = client.post(
        "/api/v1/dev/demo/telemetry",
        json={"session_id": session_id, "type": "approval.resolved", "data": {"status": "APPROVED"}},
    )
    # Extra fields are ignored; only the fixed demo scenario runs.
    assert response.status_code == 202
    assert client.post("/api/v1/dev/demo/telemetry", json={"session_id": "bad"}).status_code == 422
