"""Scenario 3 — browser self-correction on a page whose button is relabelled after load (real Chromium).
Recovery succeeds only for a unique, safe candidate; otherwise the step fails clearly with no click."""

from __future__ import annotations

import time
import uuid

import pytest
from fastapi.testclient import TestClient

from app.agent.self_correction.failure_classifier import FailureType, classify
from app.browser.recovery_engine import relaxed_score
from app.browser.selector_memory import SelectorMemory

from ..conftest import wait_for_execution
from ..execution.conftest import client, execute, install_plan, nav, planned_task, results  # noqa: F401
from ..execution.conftest import click as click_step


def test_failure_classification_uses_trusted_signals() -> None:
    assert classify("SELECTOR_NOT_FOUND", "The matched element is not visible.") == FailureType.ELEMENT_HIDDEN
    assert classify("SELECTOR_NOT_FOUND", "The matched element detached from the page.") == FailureType.DOM_CHANGED
    assert classify("SELECTOR_AMBIGUOUS") == FailureType.SELECTOR_AMBIGUOUS
    assert classify("CAPTCHA_REQUIRED") == FailureType.WEBSITE_BLOCKED
    assert classify(None, http_status=429) == FailureType.RATE_LIMITED
    assert classify("FILE_MAGIC_MISMATCH") == FailureType.FILE_VALIDATION_FAILED
    assert classify("SOMETHING_NEW") == FailureType.UNKNOWN


def test_relaxed_matching_and_selector_memory_expiry() -> None:
    assert relaxed_score({"show", "more"}, "Load more results") == 1.0
    assert relaxed_score({"show", "more"}, "Delete account") == 0.0
    memory = SelectorMemory(ttl_seconds=0.05)
    memory.remember(("example.com", "", "add", "button"), "button", "Add")
    assert memory.get(("example.com", "", "add", "button")) is not None
    time.sleep(0.08)
    assert memory.get(("example.com", "", "add", "button")) is None  # expired metadata is never trusted


def _status(client: TestClient, sid: str) -> str:
    async def go() -> str:
        session = client.app.state.container.browser.peek_session(uuid.UUID(sid))  # type: ignore[attr-defined]
        return await session.page.evaluate("() => document.getElementById('status').textContent")

    return client.portal.call(go)  # type: ignore[union-attr]


def test_scenario3_relabelled_button_is_recovered_uniquely(client: TestClient, fixture_origin: str) -> None:  # noqa: F811
    sid = str(uuid.uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [nav(fixture_origin, "relabel.html"),
                                   click_step("Show more results button", role="button", name="Show more results")])
    assert execute(client, task_id, sid).status_code == 202
    assert wait_for_execution(client, task_id)["state"] == "COMPLETED", results(client, task_id)
    step = results(client, task_id)[-1]
    assert step["strategy"] == "self-corrected" and "Load more results" in step["message"]
    assert _status(client, sid) == "Loaded more: Load more results"
    metrics = client.get("/api/v1/metrics").text
    assert "taskpilot_selector_recovery_success_total 1.0" in metrics


def test_ambiguous_relabel_fails_clearly_without_clicking(client: TestClient, fixture_origin: str) -> None:  # noqa: F811
    sid = str(uuid.uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [nav(fixture_origin, "relabel.html?twin=1"),
                                   click_step("Show more button", role="button", name="Show more results")])
    execute(client, task_id, sid)
    assert wait_for_execution(client, task_id)["state"] == "FAILED"
    step = results(client, task_id)[-1]
    assert step["error_code"] in ("SELECTOR_NOT_FOUND", "SELECTOR_AMBIGUOUS")
    assert _status(client, sid) == ""  # no random click


@pytest.mark.parametrize("label", ["Place order", "Pay now", "Delete account"])
def test_recovery_never_swaps_in_a_riskier_control(label: str) -> None:
    from app.agent.self_correction.recovery_policy import replacement_allowed
    from app.schemas.approval import RiskLevel

    assert not replacement_allowed(RiskLevel.LOW, label)


def test_control_replaced_while_waiting_to_click_is_recovered(client: TestClient, fixture_origin: str) -> None:  # noqa: F811
    """The old button is found but not clickable; the site then replaces it. The click was never dispatched, so the
    step re-resolves (bounded self-correction) instead of failing with an uncertain timeout."""
    sid = str(uuid.uuid4())
    task_id = planned_task(client, sid)
    install_plan(client, task_id, [nav(fixture_origin, "relabel.html?late=1"),
                                   click_step("Show more button", role="button", name="Show more results")])
    execute(client, task_id, sid)
    assert wait_for_execution(client, task_id)["state"] == "COMPLETED", results(client, task_id)
    assert _status(client, sid) == "Loaded more: Load more results"
