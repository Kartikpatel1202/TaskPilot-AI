"""Exact-event review and hashing (Phase 5).

The approval is bound to `event_hash` — a SHA-256 over every field that would be written to
the calendar. Any change (title, time, timezone, attendees, description, location, reminder,
recurrence) produces a different hash, so an earlier approval can never authorise it.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone

from app.integrations.calendar.datetime_parser import date_label, time_label, timezone_label
from app.schemas.calendar import (
    CalendarApprovalDetails,
    CalendarEventRequest,
    CalendarEventReview,
    ConflictCheckStatus,
)
from app.schemas.integration import CalendarCreateEventAction


def event_from_action(action: CalendarCreateEventAction) -> CalendarEventRequest:
    return CalendarEventRequest(
        title=action.title, description=action.description, location=action.location, start_at=action.start_at,
        end_at=action.end_at, timezone=action.timezone, attendee_emails=list(action.attendee_emails),
        reminder_minutes=action.reminder_minutes, recurrence_rule=action.recurrence_rule,
    )


def event_hash(event: CalendarEventRequest) -> str:
    canonical = {
        "title": event.title.strip(),
        "start": event.start_at.astimezone(timezone.utc).isoformat(),
        "end": event.end_at.astimezone(timezone.utc).isoformat(),
        "timezone": event.timezone,
        "description": (event.description or "").strip(),
        "location": (event.location or "").strip(),
        "attendees": sorted(str(e).lower() for e in event.attendee_emails),
        "reminder": event.reminder_minutes,
        "recurrence": event.recurrence_rule or "",
    }
    return hashlib.sha256(json.dumps(canonical, sort_keys=True).encode()).hexdigest()


def build_review(event: CalendarEventRequest, assumptions: list[str] | None = None) -> CalendarEventReview:
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(event.timezone)
    start, end = event.start_at.astimezone(tz), event.end_at.astimezone(tz)
    return CalendarEventReview(
        event=event, date_label=date_label(start), time_label=time_label(start, end),
        timezone_label=timezone_label(start, event.timezone),
        duration_minutes=int((end - start).total_seconds() // 60), assumptions=list(assumptions or []),
        event_hash=event_hash(event),
    )


def approval_details(review: CalendarEventReview) -> CalendarApprovalDetails:
    e = review.event
    return CalendarApprovalDetails(
        title=e.title, date_label=review.date_label, time_label=review.time_label, timezone=e.timezone,
        timezone_label=review.timezone_label, start_at=e.start_at, end_at=e.end_at, location=e.location,
        description=e.description, attendee_emails=[str(a) for a in e.attendee_emails], reminder_minutes=e.reminder_minutes,
        recurrence_rule=e.recurrence_rule, conflict_status=review.conflict_status, conflicts=list(review.conflicts),
        sends_invitations=bool(e.attendee_emails), event_hash=review.event_hash,
    )


def approval_text(review: CalendarEventReview, site: str) -> tuple[str, str, str]:
    e = review.event
    action = f"Create calendar event “{e.title[:80]}” on {review.date_label}, {review.time_label}"
    reason = (f"TaskPilot will create exactly this event on {site} and nothing else. "
              "Any change to the event cancels this approval.")
    conflict = {
        ConflictCheckStatus.CONFLICTS_FOUND: f"{len(review.conflicts)} overlapping event(s) were seen on that day.",
        ConflictCheckStatus.NO_CONFLICT_OBSERVED: "No overlapping events were seen on that day.",
        ConflictCheckStatus.UNAVAILABLE: "Your calendar could not be read, so conflicts are UNKNOWN (not assumed free).",
    }.get(review.conflict_status, "Conflicts were not checked.")
    invites = (f" Invitation emails will be sent to {len(e.attendee_emails)} attendee(s) by Google Calendar."
               if e.attendee_emails else " No attendees — no invitations are sent.")
    return action[:500], reason, (conflict + invites)[:1000]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
