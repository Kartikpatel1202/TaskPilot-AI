"""Real approval checkpoints during execution: approve, reject, expire, stop while waiting,
cross-task isolation, and the runtime policy still blocking after an approval.

Fixture site only (approval.html has a harmless "Save to wishlist" and a fake "Confirm and pay").
"""

from __future__ import annotations

from uuid import uuid4

from fastapi.testclient import TestClient

from app.schemas.action import RequestApprovalAction
from app.schemas.approval import RiskLevel

from ..conftest import wait_for_execution, wait_for_task_state
from .conftest import click, container, execute, install_plan, nav, page_eval, pending_approval, planned_task, results, step, stop, telemetry_types


def gate(reason: str = "Please confirm before I continue") -> object:
    return step(RequestApprovalAction(type="request_approval", reason=reason, risk_level=RiskLevel.HIGH), "Ask for approval")


def wishlist_plan(origin: str) -> list:
    g = gate()
    save = click("Save to wishlist button", "button", "Save to wishlist")
    save.depends_on.append(g.step_id)  # type: ignore[attr-defined]
    return [nav(origin, "approval.html"), g, save, stop()]


def saved_text(client: TestClient, sid: str) -> str:
    return page_eval(client, sid, "() => document.getElementById('saved').textContent")


def decide(client: TestClient, approval_id: object, decision: str) -> None:
    response = client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": decision})
    assert response.status_code == 200, response.text


def test_approved_checkpoint_resumes_and_completes(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, wishlist_plan(fixture_origin))
    execute(client, task_id, sid)
    approval = pending_approval(client, task_id)
    assert approval.is_demo is False
    assert wait_for_task_state(client, task_id, ("WAITING_APPROVAL",), timeout=10)
    assert saved_text(client, sid) == ""  # nothing clicked while waiting
    decide(client, approval.approval_id, "APPROVE")
    assert wait_for_execution(client, task_id, timeout=60)["state"] == "COMPLETED"
    assert saved_text(client, sid) == "Saved to wishlist"
    types = telemetry_types(client, sid)
    assert "task.execution_paused" in types and "task.execution_resumed" in types


def test_rejected_checkpoint_cancels_without_acting(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, wishlist_plan(fixture_origin))
    execute(client, task_id, sid)
    decide(client, pending_approval(client, task_id).approval_id, "REJECT")
    assert wait_for_execution(client, task_id, timeout=60)["state"] == "CANCELLED"
    rows = results(client, task_id)
    assert rows[1]["error_code"] == "APPROVAL_REJECTED" and rows[2]["status"] == "SKIPPED"
    assert saved_text(client, sid) == ""


def test_unanswered_checkpoint_expires_and_cancels(client: TestClient, fixture_origin: str) -> None:
    # browser_settings() uses the minimum approval TTL (10 s)
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, wishlist_plan(fixture_origin))
    execute(client, task_id, sid)
    approval = pending_approval(client, task_id)
    final = wait_for_execution(client, task_id, timeout=40)
    assert final["state"] == "CANCELLED"
    assert results(client, task_id)[1]["error_code"] == "APPROVAL_EXPIRED"
    assert container(client).approvals.get(approval.approval_id).status.value == "EXPIRED"
    assert saved_text(client, sid) == ""


def test_stop_while_waiting_withdraws_the_approval(client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, wishlist_plan(fixture_origin))
    execute(client, task_id, sid)
    approval = pending_approval(client, task_id)
    response = client.post(f"/api/v1/tasks/{task_id}/stop", json={"session_id": sid, "reason": "Not now"})
    assert response.status_code == 202
    assert wait_for_execution(client, task_id, timeout=30)["state"] == "CANCELLED"
    assert container(client).approvals.get(approval.approval_id).status.value != "PENDING"
    late = client.post(f"/api/v1/approvals/{approval.approval_id}/decision", json={"decision": "APPROVE"})
    assert late.status_code in (409, 410)  # a withdrawn approval can no longer resume anything
    assert saved_text(client, sid) == ""


def test_hard_blocked_click_stays_blocked_after_approval(client: TestClient, fixture_origin: str) -> None:
    """The plan text looks harmless ("Confirm"), the approval is granted — but the element actually
    resolved on the page is "Confirm and pay", so the runtime policy refuses to click it."""
    sid = str(uuid4())
    task_id = planned_task(client, sid)
    g = gate("Confirm the selection")
    confirm = click("Confirm selection button", "button", "Confirm")
    confirm.depends_on.append(g.step_id)  # type: ignore[attr-defined]
    install_plan(client, task_id, [nav(fixture_origin, "approval.html"), g, confirm, stop()])
    execute(client, task_id, sid)
    decide(client, pending_approval(client, task_id).approval_id, "APPROVE")
    final = wait_for_execution(client, task_id, timeout=60)
    rows = results(client, task_id)
    assert final["state"] == "CANCELLED"
    assert rows[1]["status"] == "SUCCEEDED"  # the approval itself was granted
    assert rows[2]["status"] == "BLOCKED" and rows[2]["error_code"] == "SENSITIVE_ACTION_BLOCKED"
    assert saved_text(client, sid) != "PAID"


def test_an_approval_only_resumes_its_own_task(client: TestClient, fixture_origin: str) -> None:
    sid_a, sid_b = str(uuid4()), str(uuid4())
    task_a, task_b = planned_task(client, sid_a), planned_task(client, sid_b)
    install_plan(client, task_a, wishlist_plan(fixture_origin))
    install_plan(client, task_b, wishlist_plan(fixture_origin))
    execute(client, task_a, sid_a)
    execute(client, task_b, sid_b)
    approval_a = pending_approval(client, task_a)
    pending_approval(client, task_b)
    decide(client, approval_a.approval_id, "APPROVE")
    assert wait_for_execution(client, task_a, timeout=60)["state"] == "COMPLETED"
    assert client.get(f"/api/v1/tasks/{task_b}").json()["state"] == "WAITING_APPROVAL"
    assert saved_text(client, sid_b) == ""
    client.post(f"/api/v1/tasks/{task_b}/stop", json={"session_id": sid_b, "reason": "cleanup"})
    wait_for_execution(client, task_b, timeout=30)
