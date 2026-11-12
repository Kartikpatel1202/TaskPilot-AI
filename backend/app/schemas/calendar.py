"""Google Calendar schemas (Phase 5). Mirrors `frontend/src/types/calendar.ts`."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class CalendarEventRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = None
    start_at: datetime
    end_at: datetime
    timezone: str
    attendee_emails: list[EmailStr] = Field(default_factory=list, max_length=50)
    reminder_minutes: int | None = None
    recurrence_rule: str | None = None


class CalendarConflict(BaseModel):
    title: str
    start_label: str
    end_label: str
    kind: str  # EXACT | PARTIAL | NEARBY


class ConflictCheckStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    NO_CONFLICT_OBSERVED = "NO_CONFLICT_OBSERVED"
    CONFLICTS_FOUND = "CONFLICTS_FOUND"
    UNAVAILABLE = "UNAVAILABLE"  # calendar data could not be read: NOT assumed free


class CalendarEventStatus(str, Enum):
    PREPARED = "PREPARED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    CREATING = "CREATING"
    CREATED = "CREATED"
    ALREADY_EXISTS = "ALREADY_EXISTS"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


class CalendarEventReview(BaseModel):
    event: CalendarEventRequest
    date_label: str          # "Tuesday, November 10, 2026"
    time_label: str          # "3:00 PM – 3:30 PM"
    timezone_label: str      # "Asia/Kolkata (IST, UTC+05:30)"
    duration_minutes: int
    assumptions: list[str] = Field(default_factory=list)
    conflict_status: ConflictCheckStatus = ConflictCheckStatus.NOT_REQUESTED
    conflicts: list[CalendarConflict] = Field(default_factory=list)
    event_hash: str
    status: CalendarEventStatus = CalendarEventStatus.PREPARED
    approval_id: UUID | None = None
    message: str | None = None
    verified_reference: str | None = None  # visible event id/label on the calendar, when shown
    observed_at: datetime | None = None


class CalendarApprovalDetails(BaseModel):
    """Attached to ApprovalRequest.calendar — exactly the event being approved."""

    title: str
    date_label: str
    time_label: str
    timezone: str
    timezone_label: str
    start_at: datetime
    end_at: datetime
    location: str | None = None
    description: str | None = None
    attendee_emails: list[str] = Field(default_factory=list)
    reminder_minutes: int | None = None
    recurrence_rule: str | None = None
    conflict_status: ConflictCheckStatus
    conflicts: list[CalendarConflict] = Field(default_factory=list)
    sends_invitations: bool
    event_hash: str = Field(min_length=16, max_length=128)
