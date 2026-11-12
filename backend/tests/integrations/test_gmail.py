"""Gmail DRAFT integration on the LOCAL Gmail-like fixture. The fixture has a FAKE Send button;
these tests prove TaskPilot never clicks it (its click counter must stay 0)."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient

from app.integrations.gmail.composer import body_for, subject_for
from app.integrations.policies import FieldKind, IntegrationPolicy, Purpose
from app.workflow.result_handoff import MissingOutputError, resolve

from ..conftest import post_command, wait_for_task_state
from .conftest import browser_eval, events_of, finished, planned, prime, results, run, workflow

SEND_CLICKS = "() => Number(localStorage.getItem('fx_gmail_sent_clicks') || '0')"
DRAFTS = "() => JSON.parse(localStorage.getItem('fx_gmail_drafts') || '[]')"


# ---------------------------------------------------------------------- unit: policy and content


@pytest.mark.parametrize("label", ["Send", "Send ‪(Ctrl-Enter)‬", "Schedule send", "send now", "Bhejo", "Discard draft", "Delete"])
def test_gmail_policy_never_allows_send_or_discard(label: str) -> None:
    policy = IntegrationPolicy()
    for purpose in (Purpose.GMAIL_COMPOSE, Purpose.GMAIL_SAVE_CLOSE):
        assert not policy.check_click(purpose, label).allowed


def test_gmail_policy_allows_only_compose_and_save_close() -> None:
    policy = IntegrationPolicy()
    assert policy.check_click(Purpose.GMAIL_COMPOSE, "Compose").allowed
    assert policy.check_click(Purpose.GMAIL_SAVE_CLOSE, "Save & close").allowed
    assert not policy.check_click(Purpose.GMAIL_COMPOSE, "Inbox").allowed


def test_recipient_and_body_checks() -> None:
    policy = IntegrationPolicy(max_recipients=2, max_body=50)
    assert policy.check_fill(FieldKind.RECIPIENTS, "a@example.com, b@example.com").allowed
    assert not policy.check_fill(FieldKind.RECIPIENTS, "a@example.com, b@example.com, c@example.com").allowed
    assert not policy.check_fill(FieldKind.RECIPIENTS, "not-an-email").allowed
    assert not policy.check_fill(FieldKind.BODY, "x" * 51).allowed
    assert not policy.check_fill(FieldKind.BODY, "my card 4111 1111 1111 1111").allowed


def test_templates_never_invent_names_or_facts() -> None:
    body = body_for("internship opportunities", ["youtube.video_reference"])
    assert "{{youtube.video_url}}" in body and "[Your name]" in body
    assert subject_for(None, ["file.reference"], None) == "File: {{file.name}}"
    with pytest.raises(MissingOutputError):
        resolve(body, {})


# ---------------------------------------------------------------------- E2E scenario 2


def test_scenario2_gmail_draft_saved_verified_and_never_sent(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "gmail", "index.html?reset=1")
    task_id, plan = planned(iclient, "Draft an email to hr@example.com about internship opportunities on fixture gmail", sid)
    step = plan["steps"][0]
    assert step["action"]["type"] == "gmail_create_draft" and step["action"]["send_requested"] is False
    assert step["requires_approval"] is False and step["risk_level"] == "MEDIUM"
    preview = iclient.get(f"/api/v1/tasks/{task_id}/gmail/draft", params={"session_id": sid}).json()
    assert preview["editable"] is True and preview["draft"]["status"] == "NOT_STARTED"
    edited = iclient.put(f"/api/v1/tasks/{task_id}/gmail/draft", json={
        "session_id": sid, "subject": "Internship opportunities", "body": "Hi,\n\nAre there internship openings this winter?\n\nThanks"})
    assert edited.status_code == 200, edited.text
    run(iclient, task_id, sid)
    task = finished(iclient, task_id)
    assert task["state"] == "COMPLETED", [(r["error_code"], r["message"]) for r in results(iclient, task_id)]
    draft = iclient.get(f"/api/v1/tasks/{task_id}/gmail/draft", params={"session_id": sid}).json()
    assert draft["draft"]["status"] == "DRAFT_SAVED" and draft["draft"]["verified"] is True and draft["draft"]["sent"] is False
    assert draft["draft"]["recipients_masked"] == ["h•••@example.com"]
    saved = browser_eval(iclient, sid, DRAFTS)
    assert saved[-1]["to"] == ["hr@example.com"] and saved[-1]["subject"] == "Internship opportunities"
    assert "internship openings" in saved[-1]["body"]
    assert browser_eval(iclient, sid, SEND_CLICKS) == 0
    kinds = [e["type"] for e in events_of(iclient, sid, "gmail.")]
    assert kinds[:1] == ["gmail.draft_started"] and "gmail.draft_verified" in kinds and "gmail.send_blocked" not in kinds
    # telemetry never carries the full body
    assert all("internship openings" not in str(e["data"]) for e in events_of(iclient, sid, ""))
    # the edit window closes once the plan has run
    late = iclient.put(f"/api/v1/tasks/{task_id}/gmail/draft", json={"session_id": sid, "subject": "x", "body": "y"})
    assert late.status_code == 409


def test_send_request_saves_a_draft_and_reports_send_blocked(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "gmail", "index.html?reset=1")
    task_id, plan = planned(iclient, "Send an email to boss@example.com about leave tomorrow on fixture gmail", sid)
    assert plan["steps"][0]["action"]["send_requested"] is True
    assert any("never automated" in a for a in plan["assumptions"])
    run(iclient, task_id, sid)
    assert finished(iclient, task_id)["state"] == "COMPLETED"
    blocked = [e for e in events_of(iclient, sid, "gmail.send_blocked")]
    assert blocked and "Final Send tum Gmail se manually kar sakte ho" in blocked[0]["data"]["message"]
    assert browser_eval(iclient, sid, SEND_CLICKS) == 0
    msg = next(r for r in results(iclient, task_id) if r["action_type"] == "gmail_create_draft")["message"]
    assert "NOT been sent" in msg


def test_missing_recipient_is_asked_not_invented(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    task_id = post_command(iclient, "Draft an email to HR about internship opportunities on fixture gmail", sid)["task_id"]
    task = wait_for_task_state(iclient, task_id, timeout=10)
    assert task["state"] == "NEEDS_CLARIFICATION"
    plan = iclient.get(f"/api/v1/tasks/{task_id}/plan").json()
    assert "email" in plan["clarification_question"].lower() and not plan["steps"]


def test_signed_out_gmail_is_handed_to_the_user(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "gmail", "index.html?reset=1")
    task_id, plan = planned(iclient, "Draft an email to hr@example.com about leave on fixture gmail", sid)
    # Point this run at the sign-in variant of the fixture (Gmail redirects signed-out users to sign-in).
    binding = iclient.app.state.container.integrations.registry.binding(plan["steps"][0]["action"]["site_key"])
    object.__setattr__(binding, "base_url", binding.base_url + "?login=1")
    try:
        run(iclient, task_id, sid)
        task = finished(iclient, task_id)
    finally:
        object.__setattr__(binding, "base_url", binding.base_url.replace("?login=1", ""))
    summary = iclient.get(f"/api/v1/tasks/{task_id}/execution").json()
    assert task["state"] == "CANCELLED" and summary["error_code"] == "GMAIL_LOGIN_REQUIRED"
    assert "never types passwords" in summary["message"]
    statuses = {s["domain"]: s["status"] for s in iclient.get("/api/v1/integrations/status", params={"session_id": sid}).json()}
    assert statuses["GMAIL"] == "AUTHENTICATION_REQUIRED"
    assert [e for e in events_of(iclient, sid, "integration.authentication_required")]


def test_failed_save_is_reported_honestly(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "gmail", "index.html?reset=1&nosave=1")
    task_id, _ = planned(iclient, "Draft an email to hr@example.com about leave on fixture gmail", sid)
    try:
        run(iclient, task_id, sid)
        task = finished(iclient, task_id)
    finally:
        prime(iclient, sid, fixture_origin, "gmail", "index.html?nosave=0")
    assert task["state"] == "FAILED"
    draft = iclient.get(f"/api/v1/tasks/{task_id}/gmail/draft", params={"session_id": sid}).json()["draft"]
    assert draft["status"] in ("DRAFT_SAVE_FAILED", "SAVE_STATUS_UNKNOWN") and draft["verified"] is False
    assert browser_eval(iclient, sid, SEND_CLICKS) == 0
    assert workflow(iclient, task_id, sid)["steps"][0]["status"] == "FAILED"
