"""Google Calendar integration: deterministic time parsing, exact-event approval and verified
creation on the LOCAL Calendar-like fixture (never calendar.google.com)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.integrations.calendar.datetime_parser import parse_event_time
from app.integrations.calendar.event_review import approval_details, build_review, event_hash
from app.integrations.policies import IntegrationPolicy, Purpose
from app.schemas.calendar import CalendarEventRequest

from ..conftest import post_command, wait_for_task_state
from .conftest import (
    browser_eval,
    events_of,
    finished,
    pending_calendar_approval,
    planned,
    prime,
    results,
    run,
    workflow,
)

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 9, 10, 0, tzinfo=IST)
CAL = "() => window.__fxCal ? window.__fxCal() : null"


def parse(text: str, **kw: object):  # noqa: ANN201
    return parse_event_time(text, now=kw.pop("now", NOW), default_tz=kw.pop("tz", "Asia/Kolkata"), **kw)  # type: ignore[arg-type]


# ---------------------------------------------------------------------- unit: parsing


def test_parses_relative_dates_times_and_durations() -> None:
    r = parse("meeting tomorrow at 3pm for 30 minutes")
    assert r.ok and r.start == datetime(2026, 11, 10, 15, 0, tzinfo=IST) and r.duration_minutes == 30
    r = parse("kal shaam 5 baje 1 ghanta")
    assert r.ok and r.start.hour == 17 and r.duration_minutes == 60 and any("kal" in a for a in r.assumptions)
    r = parse("10 Nov 3-4pm")
    assert r.ok and (r.start.hour, r.end.hour) == (15, 16)
    r = parse("2026-11-12 from 3:30pm to 5pm")
    assert r.ok and r.duration_minutes == 90


@pytest.mark.parametrize("text,missing", [
    ("kal 3 baje 1 hour", "am_pm"),           # AM or PM?
    ("meeting on 10/11 at 3pm for 1 hour", "date_format"),  # 10 Nov or 11 Oct?
    ("meeting tomorrow at 3pm", "duration"),  # never guessed (default duration is 0 = ask)
    ("today at 9am for 30 min", "past_time"),
    ("meeting at 3pm for 30 min", "date"),
])
def test_ambiguity_is_clarified_never_guessed(text: str, missing: str) -> None:
    r = parse(text)
    assert not r.ok and r.missing[0] == missing and r.question


def test_default_duration_is_an_explicit_assumption() -> None:
    r = parse("meeting tomorrow at 3pm", default_duration=45)
    assert r.ok and r.duration_minutes == 45 and any("default of 45 minutes" in a for a in r.assumptions)


def test_timezones_and_dst() -> None:
    r = parse("tomorrow 10am for 1 hour PST")
    assert r.ok and r.timezone == "America/Los_Angeles" and r.start.utcoffset() == timedelta(hours=-8)
    # 2027-03-14 02:30 does not exist in New York (clocks jump 02:00 -> 03:00)
    r = parse("March 14 2027 2:30am for 1 hour America/New_York")
    assert not r.ok and r.missing == ["nonexistent_time"]
    # 2027-11-07 01:30 happens twice in New York: the first occurrence is used and stated
    r = parse("November 7 2027 1:30am for 1 hour America/New_York")
    assert r.ok and r.start.utcoffset() == timedelta(hours=-4) and any("occurs twice" in a for a in r.assumptions)
    # a 1-hour event across the jump ends at the correct wall time
    r = parse("March 14 2027 1:30am for 1 hour America/New_York")
    assert r.ok and r.end.hour == 3 and r.end.minute == 30


def _event(**over: object) -> CalendarEventRequest:
    base = dict(title="Meeting with Rahul", start_at=datetime(2026, 11, 10, 15, tzinfo=IST), end_at=datetime(2026, 11, 10, 15, 30, tzinfo=IST),
                timezone="Asia/Kolkata")
    base.update(over)
    return CalendarEventRequest(**base)  # type: ignore[arg-type]


def test_event_hash_changes_with_every_field() -> None:
    h = event_hash(_event())
    assert h == event_hash(_event())
    for change in ({"title": "Meeting with Rahul!"}, {"end_at": datetime(2026, 11, 10, 16, tzinfo=IST)}, {"timezone": "UTC"},
                   {"attendee_emails": ["a@example.com"]}, {"description": "x"}, {"location": "Room 1"}, {"reminder_minutes": 10}):
        assert event_hash(_event(**change)) != h
    review = build_review(_event(attendee_emails=["a@example.com"]))
    assert review.date_label == "Tuesday, November 10, 2026" and review.time_label == "3:00 PM – 3:30 PM"
    assert review.timezone_label == "Asia/Kolkata (IST, UTC+05:30)"
    assert approval_details(review).sends_invitations is True


def test_calendar_save_needs_a_fresh_exact_authorization() -> None:
    policy = IntegrationPolicy()
    assert not policy.check_click(Purpose.CALENDAR_SAVE, "Save").allowed
    approval_id, task_id = uuid.uuid4(), uuid.uuid4()
    with pytest.raises(ValueError, match="STALE"):
        policy.authorize_calendar(approval_id=approval_id, task_id=task_id, approved=True, approved_hash="a" * 64, live_hash="b" * 64,
                                  sends_invitations=False, window_seconds=60)
    with pytest.raises(ValueError, match="REJECTED"):
        policy.authorize_calendar(approval_id=approval_id, task_id=task_id, approved=False, approved_hash="a" * 64, live_hash="a" * 64,
                                  sends_invitations=False, window_seconds=60)
    auth = policy.authorize_calendar(approval_id=approval_id, task_id=task_id, approved=True, approved_hash="a" * 64, live_hash="a" * 64,
                                     sends_invitations=False, window_seconds=60)
    assert not policy.check_click(Purpose.CALENDAR_SAVE, "Save", authorization=auth, event_hash="b" * 64).allowed
    assert not policy.check_click(Purpose.CALENDAR_SAVE, "Delete", authorization=auth, event_hash="a" * 64).allowed
    assert policy.check_click(Purpose.CALENDAR_SAVE, "Save", authorization=auth, event_hash="a" * 64).allowed
    auth.mark_clicked()
    assert not policy.check_click(Purpose.CALENDAR_SAVE, "Save", authorization=auth, event_hash="a" * 64).allowed  # single use
    assert not policy.check_click(Purpose.CALENDAR_INVITES, "Send", authorization=auth).allowed  # no attendees approved
    assert policy.check_click(Purpose.CALENDAR_INVITES, "Don't send", authorization=auth).allowed
    with pytest.raises(ValueError, match="REUSED"):
        policy.authorize_calendar(approval_id=approval_id, task_id=task_id, approved=True, approved_hash="a" * 64, live_hash="a" * 64,
                                  sends_invitations=False, window_seconds=60)


# ---------------------------------------------------------------------- planning via the API


def test_missing_duration_is_asked_then_planned(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    task_id = post_command(iclient, "Schedule a meeting with Rahul tomorrow at 3pm on fixture calendar", sid)["task_id"]
    assert wait_for_task_state(iclient, task_id, timeout=10)["state"] == "NEEDS_CLARIFICATION"
    plan = iclient.get(f"/api/v1/tasks/{task_id}/plan").json()
    assert plan["missing_information"] == ["duration"] and "long" in plan["clarification_question"].lower()
    r = iclient.post(f"/api/v1/tasks/{task_id}/clarification", json={"session_id": sid, "message": "30 minutes"})
    assert r.status_code == 202, r.text
    assert wait_for_task_state(iclient, task_id, timeout=10)["state"] == "PLANNED"
    step = iclient.get(f"/api/v1/tasks/{task_id}/plan").json()["steps"][0]
    assert step["action"]["type"] == "calendar_create_event" and step["requires_approval"] is True and step["risk_level"] == "HIGH"
    start = datetime.fromisoformat(step["action"]["start_at"])
    end = datetime.fromisoformat(step["action"]["end_at"])
    assert (end - start) == timedelta(minutes=30) and start.astimezone(IST).hour == 15


# ---------------------------------------------------------------------- E2E scenario 3: reject, then approve


def _tomorrow_3pm_utc() -> str:
    t = (datetime.now(IST) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decide(client: TestClient, approval_id: object, decision: str) -> None:
    r = client.post(f"/api/v1/approvals/{approval_id}/decision", json={"decision": decision})
    assert r.status_code == 200, r.text


def test_scenario3_calendar_reject_then_approve(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "calendar", "index.html?reset=1")
    command = "Schedule a meeting with Rahul tomorrow at 3pm for 30 minutes on fixture calendar"
    # --- 1) reject: nothing is created
    task_id, _ = planned(iclient, command, sid)
    run(iclient, task_id, sid)
    approval = pending_calendar_approval(iclient, task_id)
    details = approval.calendar
    assert details.title == "Meeting with Rahul" and details.time_label == "3:00 PM – 3:30 PM" and details.sends_invitations is False
    assert details.conflict_status.value == "NO_CONFLICT_OBSERVED"
    review = iclient.get(f"/api/v1/tasks/{task_id}/calendar/review", params={"session_id": sid}).json()
    assert review["status"] == "APPROVAL_PENDING" and review["event_hash"] == details.event_hash
    _decide(iclient, approval.approval_id, "REJECT")
    task = finished(iclient, task_id)
    assert task["state"] == "CANCELLED"
    assert iclient.get(f"/api/v1/tasks/{task_id}/calendar/status", params={"session_id": sid}).json()["status"] == "REJECTED"
    state = browser_eval(iclient, sid, CAL)
    assert state is None or (state["events"] == [] and state["saves"] == 0)
    # --- 2) approve: exactly one event is created and verified on the calendar
    task_id, _ = planned(iclient, command, sid)
    run(iclient, task_id, sid)
    approval = pending_calendar_approval(iclient, task_id)
    _decide(iclient, approval.approval_id, "APPROVE")
    task = finished(iclient, task_id)
    assert task["state"] == "COMPLETED", [(r["error_code"], r["message"]) for r in results(iclient, task_id)]
    status = iclient.get(f"/api/v1/tasks/{task_id}/calendar/status", params={"session_id": sid}).json()
    assert status["status"] == "CREATED" and status["verified_reference"]
    state = browser_eval(iclient, sid, CAL)
    assert state["saves"] == 1 and [e["title"] for e in state["events"]] == ["Meeting with Rahul"] and state["invites"] == 0
    kinds = [e["type"] for e in events_of(iclient, sid, "calendar.")]
    for k in ("calendar.event_prepared", "calendar.approval_required", "calendar.approval_resolved", "calendar.event_creation_started",
              "calendar.event_created"):
        assert k in kinds
    # --- 3) the same request again: an identical event exists -> no duplicate, no approval
    task_id, _ = planned(iclient, command, sid)
    run(iclient, task_id, sid)
    assert finished(iclient, task_id)["state"] == "COMPLETED"
    assert iclient.get(f"/api/v1/tasks/{task_id}/calendar/status", params={"session_id": sid}).json()["status"] == "ALREADY_EXISTS"
    assert browser_eval(iclient, sid, CAL)["saves"] == 1


def test_conflicts_are_shown_in_the_approval(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "calendar", f"index.html?reset=1&conflict={_tomorrow_3pm_utc()}/60/Design%20review")
    task_id, _ = planned(iclient, "Schedule a meeting with Rahul tomorrow at 3pm for 30 minutes on fixture calendar", sid)
    run(iclient, task_id, sid)
    approval = pending_calendar_approval(iclient, task_id)
    assert approval.calendar.conflict_status.value == "CONFLICTS_FOUND"
    assert approval.calendar.conflicts[0].title == "Design review" and approval.calendar.conflicts[0].kind == "PARTIAL"
    assert "overlapping" in (approval.estimated_impact or "")
    assert [e for e in events_of(iclient, sid, "calendar.conflict_detected")]
    _decide(iclient, approval.approval_id, "REJECT")
    assert finished(iclient, task_id)["state"] == "CANCELLED"


def test_invitations_are_sent_only_for_an_approved_attendee_list(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "calendar", "index.html?reset=1")
    task_id, plan = planned(iclient, "Schedule a meeting with rahul@example.com tomorrow at 4pm for 30 minutes on fixture calendar", sid)
    assert plan["steps"][0]["action"]["attendee_emails"] == ["rahul@example.com"]
    assert any("invitations" in a for a in plan["assumptions"])
    run(iclient, task_id, sid)
    approval = pending_calendar_approval(iclient, task_id)
    assert approval.calendar.sends_invitations is True and approval.calendar.attendee_emails == ["rahul@example.com"]
    _decide(iclient, approval.approval_id, "APPROVE")
    assert finished(iclient, task_id)["state"] == "COMPLETED"
    assert browser_eval(iclient, sid, CAL)["invites"] == 1


def test_unverifiable_creation_is_reported_as_unknown(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    prime(iclient, sid, fixture_origin, "calendar", "index.html?reset=1&silentsave=1")
    task_id, _ = planned(iclient, "Schedule a meeting with Rahul tomorrow at 5pm for 30 minutes on fixture calendar", sid)
    try:
        run(iclient, task_id, sid)
        _decide(iclient, pending_calendar_approval(iclient, task_id).approval_id, "APPROVE")
        task = finished(iclient, task_id)
    finally:
        prime(iclient, sid, fixture_origin, "calendar", "index.html?silentsave=0")
    assert task["state"] == "FAILED"
    status = iclient.get(f"/api/v1/tasks/{task_id}/calendar/status", params={"session_id": sid}).json()
    assert status["status"] == "UNKNOWN" and "check Google Calendar" in status["message"]
    assert browser_eval(iclient, sid, CAL)["saves"] == 1  # never retried
    assert workflow(iclient, task_id, sid)["steps"][0]["error_code"] == "CALENDAR_EVENT_STATUS_UNKNOWN"
