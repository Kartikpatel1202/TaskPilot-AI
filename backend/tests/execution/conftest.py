"""Helpers for execution tests: the real app + real Chromium + the local fixture site.

Plans for specific scenarios are built from typed actions and passed through the
SAME risk/approval rules the planner uses (`apply_risk_and_approvals`), then
re-validated by the execution manager at Run Plan time — nothing bypasses validation.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

from app.agent.policies.approval_policy import apply_risk_and_approvals
from app.main import create_app
from app.schemas.action import ClickAction, ExtractAction, NavigateAction, StopAction, TypeAction
from app.schemas.approval import RiskLevel
from app.schemas.plan import PlannedAction

from ..conftest import FIXTURE_PREFIX, browser_settings, post_command, wait_for_task_state

DEMO_COMMAND = "Demo shop par 1 litre Amul milk cart mein add karo"


@pytest.fixture
def client(fixture_origin: str) -> Iterator[TestClient]:
    with TestClient(create_app(browser_settings(fixture_origin))) as c:
        yield c


def url(origin: str, name: str) -> str:
    return f"{origin}{FIXTURE_PREFIX}{name}"


def step(action: Any, description: str, depends: list[PlannedAction] | None = None) -> PlannedAction:
    return PlannedAction(
        step_id=uuid4(), order=1, action=action, description=description, expected_outcome=description,
        risk_level=RiskLevel.LOW, depends_on=[d.step_id for d in depends or []],
    )


def nav(origin: str, name: str) -> PlannedAction:
    return step(NavigateAction(type="navigate", url=url(origin, name), purpose="Open the page"), f"Open {name}")


def click(description: str, role: str | None = None, name: str | None = None, text: str | None = None) -> PlannedAction:
    action = ClickAction(type="click", target_description=description, role_hint=role, accessible_name=name, text_hint=text)
    return step(action, f"Click {description}")


def type_(description: str, text: str) -> PlannedAction:
    return step(TypeAction(type="type", target_description=description, text=text), f"Type into {description}")


def extract(description: str, fields: list[str]) -> PlannedAction:
    return step(ExtractAction(type="extract", target_description=description, fields=fields), f"Read {description}")


def stop() -> PlannedAction:
    return step(StopAction(type="stop", reason="Done"), "Stop")


def container(client: TestClient) -> Any:
    return client.app.state.container  # type: ignore[attr-defined]


def planned_task(client: TestClient, session_id: str, command: str = DEMO_COMMAND) -> str:
    task_id = post_command(client, command, session_id)["task_id"]
    task = wait_for_task_state(client, task_id, timeout=10)
    assert task["state"] == "PLANNED", task
    return task_id


def install_plan(client: TestClient, task_id: str, steps: list[PlannedAction]) -> list[PlannedAction]:
    """Replace the planned steps of a PLANNED task with a scenario plan (validated, approvals inserted)."""
    gated = apply_risk_and_approvals(steps)
    record = container(client).planning._store.get(UUID(task_id))
    plan = record.plan.model_copy(
        update={"steps": gated, "requires_human_approval": any(s.requires_approval for s in gated)}
    )
    report = container(client).execution._validator.validate(plan, task_id=UUID(task_id), session_id=plan.session_id)
    assert report.ok, report.errors
    record.set_plan(plan)
    return gated


def execute(client: TestClient, task_id: str, session_id: str) -> Any:
    return client.post(f"/api/v1/tasks/{task_id}/execute", json={"session_id": session_id, "confirm_execution": True})


def wait_until(predicate: Any, timeout: float = 30.0, interval: float = 0.05) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(interval)
    raise AssertionError("Condition not met in time")


def pending_approval(client: TestClient, task_id: str, timeout: float = 30.0) -> Any:
    approvals = container(client).approvals

    def find() -> Any:
        return next(
            (a for a in list(approvals._approvals.values()) if str(a.task_id) == task_id and a.status.value == "PENDING"),
            None,
        )

    return wait_until(find, timeout)


def results(client: TestClient, task_id: str) -> list[dict[str, Any]]:
    return client.get(f"/api/v1/tasks/{task_id}/execution").json()["results"]


def page_eval(client: TestClient, session_id: str, script: str) -> Any:
    async def run() -> Any:
        session = container(client).browser.peek_session(UUID(session_id))
        return await session.page.evaluate(script)

    return client.portal.call(run)  # type: ignore[union-attr]


def telemetry(client: TestClient, session_id: str) -> list[Any]:
    events, _ = container(client).ws_manager.replay(UUID(session_id), None)
    return events


def telemetry_types(client: TestClient, session_id: str) -> list[str]:
    return [e.type.value if hasattr(e.type, "value") else str(e.type) for e in telemetry(client, session_id)]
