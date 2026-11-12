"""Browser schemas (Phase 3). Mirrors `frontend/src/types/browser.ts`."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class BrowserSessionStatus(str, Enum):
    INITIALIZING = "INITIALIZING"
    READY = "READY"
    BUSY = "BUSY"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


class DOMElementInfo(BaseModel):
    """One visible element as seen by the trusted DOM inspector. Never contains input values."""

    element_id: str | None = None  # trusted inspector id (data-tp-id), never model-provided
    tag_name: str
    role: str | None = None
    accessible_name: str | None = None
    text_content: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    label: str | None = None
    input_type: str | None = None
    context_text: str | None = None  # nearby card/section text used for disambiguation
    is_visible: bool
    is_enabled: bool
    is_interactive: bool
    is_editable: bool = False
    is_sensitive: bool = False


class TargetDescription(BaseModel):
    description: str = Field(min_length=1, max_length=300)
    role_hint: str | None = Field(default=None, max_length=40)
    accessible_name: str | None = Field(default=None, max_length=200)
    text_hint: str | None = Field(default=None, max_length=200)


class BrowserPageState(BaseModel):
    url: str | None = None
    domain: str | None = None
    title: str | None = None
    headings: list[str] = Field(default_factory=list)
    interactive_count: int = 0
    has_password_field: bool = False
    auth_required: bool = False
    auth_reason: str | None = None
    dialog_open: bool = False


# ---------------------------------------------------------------------- REST


class BrowserStatusResponse(BaseModel):
    available: bool
    status: Literal["ready", "not_started", "unavailable"]
    engine: str
    active_sessions: int
    max_sessions: int
    headless: bool
    message: str | None = None


StreamStatus = Literal["CONNECTED", "DISCONNECTED"]


class BrowserSessionInfo(BaseModel):
    session_id: UUID
    status: BrowserSessionStatus
    current_url: str | None = None
    current_title: str | None = None
    active_task_id: UUID | None = None
    created_at: datetime
    last_activity_at: datetime
    stream_status: StreamStatus
    stream_subscribers: int = 0
    has_screenshot: bool = False
    auth_required: bool = False
    headless: bool = True


class BrowserSessionCloseRequest(BaseModel):
    session_id: UUID


class BrowserSessionCloseResponse(BaseModel):
    session_id: UUID
    closed: bool
    message: str


class FrameMetadata(BaseModel):
    frame_id: UUID
    session_id: UUID
    task_id: UUID | None
    sequence: int = Field(ge=1)
    captured_at: datetime
    mime_type: Literal["image/jpeg"] = "image/jpeg"
    width: int = Field(gt=0)
    height: int = Field(gt=0)


# ---------------------------------------------------------------------- telemetry payloads


class BrowserSessionPayload(BaseModel):
    status: BrowserSessionStatus
    engine: str
    headless: bool
    message: str | None = None


class BrowserNavigationPayload(BaseModel):
    url: str
    domain: str | None = None
    title: str | None = None
    step_id: UUID | None = None
    message: str


class NavigationBlockedPayload(BaseModel):
    url: str
    domain: str | None = None
    reason_code: str
    message: str
    step_id: UUID | None = None


class PageUpdatedPayload(BaseModel):
    url: str | None
    domain: str | None
    title: str | None


class FrameAvailablePayload(BaseModel):
    frame_id: UUID
    sequence: int
    width: int
    height: int
    bytes: int
    captured_at: datetime


class BrowserActionPayload(BaseModel):
    step_id: UUID
    action_type: str
    message: str
    strategy: str | None = None
    confidence: float | None = None
    error_code: str | None = None


class AuthenticationRequiredPayload(BaseModel):
    domain: str | None
    message: str
    headless: bool
    step_id: UUID | None = None


class PopupBlockedPayload(BaseModel):
    url: str | None
    message: str


class DownloadBlockedPayload(BaseModel):
    filename: str | None
    message: str


class BrowserSessionClosedPayload(BaseModel):
    reason: str


class BrowserSessionErrorPayload(BaseModel):
    code: str
    message: str


class BrowserStreamPayload(BaseModel):
    subscribers: int
