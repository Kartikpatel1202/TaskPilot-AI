"""Multi-domain integration schemas (Phase 5). Mirrors `frontend/src/types/integration.ts`.

Integration plan actions are built only by the deterministic integration planner and
validated against the trusted CapabilityRegistry before anything runs.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from pydantic import BaseModel, EmailStr, Field, field_validator, model_validator

from app.schemas.approval import RiskLevel


class DomainType(str, Enum):
    YOUTUBE = "YOUTUBE"
    GMAIL = "GMAIL"
    GOOGLE_CALENDAR = "GOOGLE_CALENDAR"
    FILES = "FILES"
    BLINKIT = "BLINKIT"
    AMAZON_IN = "AMAZON_IN"


class IntegrationCapability(str, Enum):
    YOUTUBE_SEARCH = "YOUTUBE_SEARCH"
    YOUTUBE_PLAY = "YOUTUBE_PLAY"
    GMAIL_CREATE_DRAFT = "GMAIL_CREATE_DRAFT"
    GMAIL_READ_DRAFT = "GMAIL_READ_DRAFT"
    CALENDAR_LIST_EVENTS = "CALENDAR_LIST_EVENTS"
    CALENDAR_CREATE_EVENT = "CALENDAR_CREATE_EVENT"
    FILE_DOWNLOAD = "FILE_DOWNLOAD"
    FILE_INSPECT = "FILE_INSPECT"
    COMMERCE_SEARCH = "COMMERCE_SEARCH"
    COMMERCE_CART = "COMMERCE_CART"


class CapabilityDefinition(BaseModel):
    capability: IntegrationCapability
    domain: DomainType
    description: str
    input_schema: dict[str, object]
    requires_browser: bool
    requires_approval: bool
    risk_level: RiskLevel
    enabled: bool
    action_type: str | None = None  # plan action type that executes this capability


class DomainStatus(str, Enum):
    NOT_CONFIGURED = "NOT_CONFIGURED"
    AVAILABLE = "AVAILABLE"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    CONNECTED = "CONNECTED"
    BLOCKED = "BLOCKED"
    ERROR = "ERROR"


class DomainStatusEntry(BaseModel):
    domain: DomainType
    label: str
    status: DomainStatus
    message: str
    capabilities: list[IntegrationCapability]
    observed_at: datetime | None = None


# ---------------------------------------------------------------------- plan actions

VIDEO_REFERENCE = re.compile(r"^(selected_from_search|https://(www\.)?youtube\.com/watch\?v=[\w-]{6,20})$")
OutputType = Literal["youtube.video_reference", "file.reference"]
_RRULE = re.compile(r"^FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)(;(INTERVAL=\d{1,2}|COUNT=\d{1,3}|BYDAY=(MO|TU|WE|TH|FR|SA|SU)(,(MO|TU|WE|TH|FR|SA|SU))*))*$")


class YouTubeSearchAction(BaseModel):
    type: Literal["youtube_search"]
    query: str = Field(min_length=1, max_length=500)
    max_results: int = Field(default=10, ge=1, le=20)
    preferred_channel: str | None = Field(default=None, max_length=100)
    # Pick one video (auto when clearly best, otherwise the user chooses) for playback or a later step.
    select: bool = False
    site_key: str = Field(default="youtube", max_length=40)
    # Multi-domain workflows: an independent later step still runs if this one fails (partial success).
    continue_on_failure: bool = False


class YouTubePlayAction(BaseModel):
    type: Literal["youtube_play"]
    video_reference: str = Field(max_length=200)
    site_key: str = Field(default="youtube", max_length=40)
    # Multi-domain workflows: an independent later step still runs if this one fails (partial success).
    continue_on_failure: bool = False

    @field_validator("video_reference")
    @classmethod
    def _ref(cls, value: str) -> str:
        if not VIDEO_REFERENCE.match(value):
            raise ValueError("video_reference must be 'selected_from_search' or a youtube.com watch URL")
        return value


class GmailCreateDraftAction(BaseModel):
    type: Literal["gmail_create_draft"]
    recipient_emails: list[EmailStr] = Field(min_length=1, max_length=20)
    cc_emails: list[EmailStr] = Field(default_factory=list, max_length=20)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=12_000)
    tone: str | None = Field(default=None, max_length=40)
    purpose: str | None = Field(default=None, max_length=200)
    # Typed outputs of earlier steps this draft may use ({{youtube.video_url}}, {{file.name}} placeholders).
    insert_outputs: list[OutputType] = Field(default_factory=list, max_length=4)
    # The user asked to SEND: only a draft is ever saved, and the send request is reported as blocked.
    send_requested: bool = False
    site_key: str = Field(default="gmail", max_length=40)
    # Multi-domain workflows: an independent later step still runs if this one fails (partial success).
    continue_on_failure: bool = False

    @model_validator(mode="after")
    def _unique(self) -> "GmailCreateDraftAction":
        everyone = [e.lower() for e in [*self.recipient_emails, *self.cc_emails]]
        if len(everyone) != len(set(everyone)):
            raise ValueError("Duplicate recipient addresses.")
        return self


class CalendarCreateEventAction(BaseModel):
    type: Literal["calendar_create_event"]
    title: str = Field(min_length=1, max_length=200)
    start_at: datetime
    end_at: datetime
    timezone: str = Field(min_length=1, max_length=64)
    description: str | None = Field(default=None, max_length=5000)
    location: str | None = Field(default=None, max_length=300)
    attendee_emails: list[EmailStr] = Field(default_factory=list, max_length=50)
    reminder_minutes: int | None = Field(default=None, ge=0, le=40_320)
    recurrence_rule: str | None = Field(default=None, max_length=120)
    check_conflicts: bool = True
    assumptions: list[str] = Field(default_factory=list, max_length=5)
    site_key: str = Field(default="gcalendar", max_length=40)
    # Multi-domain workflows: an independent later step still runs if this one fails (partial success).
    continue_on_failure: bool = False

    @model_validator(mode="after")
    def _check(self) -> "CalendarCreateEventAction":
        try:
            ZoneInfo(self.timezone)
        except Exception as exc:  # noqa: BLE001
            raise ValueError("timezone must be a valid IANA timezone") from exc
        if self.start_at.tzinfo is None or self.end_at.tzinfo is None:
            raise ValueError("start_at and end_at must include a UTC offset")
        if self.end_at <= self.start_at:
            raise ValueError("end_at must be after start_at")
        if self.recurrence_rule and not _RRULE.match(self.recurrence_rule):
            raise ValueError("unsupported recurrence rule")
        if len({e.lower() for e in self.attendee_emails}) != len(self.attendee_emails):
            raise ValueError("Duplicate attendee addresses.")
        return self


class FileDownloadAction(BaseModel):
    type: Literal["file_download"]
    source_url: str = Field(min_length=8, max_length=2048)
    file_description: str = Field(min_length=1, max_length=200)
    expected_extension: str | None = Field(default=None, max_length=10)
    suggested_filename: str | None = Field(default=None, max_length=120)
    site_key: str = Field(default="files", max_length=40)
    # Multi-domain workflows: an independent later step still runs if this one fails (partial success).
    continue_on_failure: bool = False

    @field_validator("source_url")
    @classmethod
    def _http(cls, value: str) -> str:
        if not value.startswith(("http://", "https://")):
            raise ValueError("source_url must be http(s)")
        return value


INTEGRATION_ACTION_TYPES = ("youtube_search", "youtube_play", "gmail_create_draft", "calendar_create_event", "file_download")


# ---------------------------------------------------------------------- user choices (e.g. which video/link)


class ChoiceOption(BaseModel):
    option_id: str = Field(max_length=40)
    label: str = Field(max_length=300)
    detail: str | None = Field(default=None, max_length=300)


class PendingChoice(BaseModel):
    choice_id: UUID
    task_id: UUID
    step_id: UUID
    domain: DomainType
    question: str
    options: list[ChoiceOption]
    expires_at: datetime


class ChoiceAnswerRequest(BaseModel):
    session_id: UUID
    choice_id: UUID
    option_id: str | None = Field(default=None, max_length=40)  # null = skip


# ---------------------------------------------------------------------- telemetry payload


class IntegrationEventPayload(BaseModel):
    """One bounded payload for every integration/youtube/gmail/calendar/file/workflow event.

    Never contains email bodies, full addresses, private event details, cookies or file paths.
    """

    domain: DomainType | None = None
    message: str = Field(max_length=500)
    status: str | None = Field(default=None, max_length=40)
    step_id: UUID | None = None
    capability: IntegrationCapability | None = None
    code: str | None = Field(default=None, max_length=80)
    result_count: int | None = None
    choice_id: UUID | None = None
    approval_id: UUID | None = None
    file_id: UUID | None = None
    bytes_received: int | None = None
    completed_steps: int | None = None
    total_steps: int | None = None
