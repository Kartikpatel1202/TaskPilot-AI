"""Execution + browser REST APIs: validation, ownership, duplicates, stop, status, session,
screenshot and close. Planning never starts a browser; only Run Plan does."""

from __future__ import annotations

import time
from uuid import uuid4

from fastapi.testclient import TestClient

from app.main import create_app

from ..conftest import browser_settings, post_command, wait_for_execution, wait_for_task_state
from .conftest import click, execute, install_plan, nav, pending_approval, planned_task, stop


def test_execute_requires_explicit_confirmation(client: TestClient) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    assert client.post(f"/api/v1/tasks/{task_id}/execute", json={"session_id": sid}).status_code == 422
    assert client.post(
        f"/api/v1/tasks/{task_id}/execute", json={"session_id": sid, "confirm_execution": False}
    ).status_code == 422
    assert client.get(f"/api/v1/tasks/{task_id}").json()["state"] == "PLANNED"


def test_execute_rejects_other_sessions_and_unknown_tasks(client: TestClient) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    other = execute(client, task_id, str(uuid4()))
    assert other.status_code == 403 and other.json()["code"] == "TASK_SESSION_MISMATCH"
    assert execute(client, str(uuid4()), sid).status_code == 404


def test_only_ready_browser_plans_can_run(client: TestClient) -> None:
    sid = str(uuid4())
    task_id = post_command(client, "hello", sid)["task_id"]
    task = wait_for_task_state(client, task_id, timeout=10)
    response = execute(client, task_id, sid)
    plan = client.get(f"/api/v1/tasks/{task_id}/plan").json()
    assert task["state"] != "PLANNED" or plan["intent"] == "GENERAL_CHAT" and plan["steps"] == []
    assert response.status_code in (404, 409)
    assert response.json()["code"] in ("PLAN_NOT_READY", "PLAN_NOT_FOUND")


def test_duplicate_run_is_refused(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [nav(fixture_origin, "approval.html"), click("Save to wishlist button", "button", "Save to wishlist"), stop()])
    assert execute(client, task_id, sid).status_code == 202
    again = execute(client, task_id, sid)
    assert again.status_code == 409 and again.json()["code"] in ("EXECUTION_ALREADY_STARTED", "PLAN_NOT_READY")
    assert wait_for_execution(client, task_id, timeout=60)["state"] == "COMPLETED"
    after = execute(client, task_id, sid)
    assert after.status_code == 409


def test_one_running_plan_per_browser_session(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    first, second = planned_task(client, sid), planned_task(client, sid)
    from app.schemas.action import RequestApprovalAction
    from app.schemas.approval import RiskLevel

    from .conftest import step

    gate = step(RequestApprovalAction(type="request_approval", reason="hold", risk_level=RiskLevel.HIGH), "Hold")
    install_plan(client, first, [nav(fixture_origin, "index.html"), gate, stop()])
    execute(client, first, sid)
    pending_approval(client, first)
    busy = execute(client, second, sid)
    assert busy.status_code == 409 and busy.json()["code"] == "BROWSER_SESSION_BUSY"
    client.post(f"/api/v1/tasks/{first}/stop", json={"session_id": sid})
    assert wait_for_execution(client, first, timeout=30)["state"] == "CANCELLED"


def test_stop_validation(client: TestClient) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    not_active = client.post(f"/api/v1/tasks/{task_id}/stop", json={"session_id": sid})
    assert not_active.status_code == 409 and not_active.json()["code"] == "EXECUTION_NOT_ACTIVE"
    wrong = client.post(f"/api/v1/tasks/{task_id}/stop", json={"session_id": str(uuid4())})
    assert wrong.status_code == 403


def test_execution_disabled_returns_503(fixture_origin: str) -> None:
    with TestClient(create_app(browser_settings(fixture_origin, agent_browser_execution_enabled=False))) as c:
        sid = str(uuid4())
        task_id = post_command(c, "Demo shop par 1 litre Amul milk cart mein add karo", sid)["task_id"]
        assert wait_for_task_state(c, task_id, timeout=10)["state"] == "PLANNED"
        response = c.post(f"/api/v1/tasks/{task_id}/execute", json={"session_id": sid, "confirm_execution": True})
        assert response.status_code == 503 and response.json()["code"] == "BROWSER_UNAVAILABLE"
        assert c.get("/api/v1/agent/status").json()["browser_execution_enabled"] is False


def test_planning_never_auto_executes(client: TestClient) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    time.sleep(0.5)
    assert client.get(f"/api/v1/tasks/{task_id}").json()["state"] == "PLANNED"
    status = client.get("/api/v1/browser/status").json()
    assert status["status"] == "not_started" and status["active_sessions"] == 0
    assert client.get(f"/api/v1/browser/sessions/{sid}").status_code == 404


def test_browser_session_screenshot_and_close(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [nav(fixture_origin, "index.html"), stop()])
    execute(client, task_id, sid)
    assert wait_for_execution(client, task_id, timeout=60)["state"] == "COMPLETED"
    summary = client.get(f"/api/v1/tasks/{task_id}/execution", params={"session_id": sid})
    assert summary.status_code == 200 and summary.json()["status"] == "COMPLETED"
    assert client.get(f"/api/v1/tasks/{task_id}/execution", params={"session_id": str(uuid4())}).status_code == 403

    status = client.get("/api/v1/browser/status").json()
    assert status["status"] == "ready" and status["active_sessions"] == 1 and status["engine"] == "chromium"
    assert "path" not in str(status).lower()
    info = client.get(f"/api/v1/browser/sessions/{sid}").json()
    assert info["current_url"].endswith("/index.html") and info["has_screenshot"] is True
    assert "?" not in info["current_url"]

    shot = client.get(f"/api/v1/browser/sessions/{sid}/screenshot")
    assert shot.status_code == 200 and shot.headers["content-type"] == "image/jpeg"
    assert shot.content[:3] == b"\xff\xd8\xff" and len(shot.content) > 1000  # a real JPEG from Chromium
    assert client.get(f"/api/v1/browser/sessions/{uuid4()}/screenshot").status_code == 404

    mismatch = client.post(f"/api/v1/browser/sessions/{sid}/close", json={"session_id": str(uuid4())})
    assert mismatch.status_code in (400, 403, 422)
    closed = client.post(f"/api/v1/browser/sessions/{sid}/close", json={"session_id": sid})
    assert closed.status_code == 200 and closed.json()["closed"] is True
    assert client.get(f"/api/v1/browser/sessions/{sid}").status_code == 404
