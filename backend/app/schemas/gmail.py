"""Gmail draft schemas (Phase 5). Mirrors `frontend/src/types/gmail.ts`. Drafts only — never sent."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, EmailStr, Field


class EmailDraftRequest(BaseModel):
    recipient_emails: list[EmailStr] = Field(min_length=1, max_length=20)
    cc_emails: list[EmailStr] = Field(default_factory=list)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=12_000)
    tone: str | None = None
    purpose: str | None = None


class DraftStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    DRAFT_COMPOSED = "DRAFT_COMPOSED"
    DRAFT_SAVE_PENDING = "DRAFT_SAVE_PENDING"
    DRAFT_SAVED = "DRAFT_SAVED"
    DRAFT_SAVE_FAILED = "DRAFT_SAVE_FAILED"
    SAVE_STATUS_UNKNOWN = "SAVE_STATUS_UNKNOWN"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"


class EmailDraftSummary(BaseModel):
    """Safe draft metadata (no inbox content). The body is returned only to the owning session."""

    status: DraftStatus
    recipients_masked: list[str]
    recipient_count: int
    cc_count: int
    subject: str
    body_preview: str | None = None
    saved_at: datetime | None = None
    verified: bool = False
    sent: bool = False  # always False: TaskPilot never sends email
    message: str
    send_blocked: bool = False


class EmailDraftUpdateRequest(BaseModel):
    session_id: str
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=12_000)
