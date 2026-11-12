"""Integration runtime policy (Phase 5): what an adapter may click or type, for which purpose.

It narrows — never widens — the Phase 3 BrowserActionPolicy:
- Gmail: only Compose and "Save & close" are clickable. Any Send / Schedule send / Discard /
  Delete control is refused for every purpose (sending is never automated — even with approval);
- YouTube: only a Play control (no Subscribe, Join, Buy, Rent, Download, Sign in);
- Calendar: Save only with a valid single-use CalendarAuthorization bound to the exact event
  hash; the invitation dialog's "Send" only when the approved event lists attendees (and was
  shown as sending invitations), otherwise only "Don't send".
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from uuid import UUID

from app.core.logging import redact_text
from app.policies.browser_action_policy import BrowserActionPolicy, PolicyDecision
from app.schemas.browser import DOMElementInfo
from app.schemas.common import utc_now


class Purpose(str, Enum):
    YOUTUBE_PLAY = "YOUTUBE_PLAY"
    GMAIL_COMPOSE = "GMAIL_COMPOSE"
    GMAIL_SAVE_CLOSE = "GMAIL_SAVE_CLOSE"
    CALENDAR_SAVE = "CALENDAR_SAVE"
    CALENDAR_INVITES = "CALENDAR_INVITES"


class FieldKind(str, Enum):
    SEARCH = "SEARCH"
    RECIPIENTS = "RECIPIENTS"
    SUBJECT = "SUBJECT"
    BODY = "BODY"


SEND = re.compile(r"\b(send|schedule send|send now|bhej\w*|भेज\w*)\b", re.IGNORECASE)
DESTRUCTIVE = re.compile(r"\b(discard|delete|trash|remove|unsubscribe|report spam|archive|move to)\b", re.IGNORECASE)
_PLAY = re.compile(r"^\s*(play|play video|play \(k\)|resume)\s*$", re.IGNORECASE)
_YT_FORBIDDEN = re.compile(r"\b(subscribe|join|buy|rent|download|sign ?in|log ?in|premium|purchase|donate|thanks)\b", re.IGNORECASE)
_COMPOSE = re.compile(r"^\s*compose\s*$", re.IGNORECASE)
_SAVE_CLOSE = re.compile(r"^\s*(save (&|and) close|save & close)\s*$", re.IGNORECASE)
_SAVE = re.compile(r"^\s*save\s*$", re.IGNORECASE)
_DONT_SEND = re.compile(r"^\s*(don'?t send|do not send)\s*$", re.IGNORECASE)
_INVITE_SEND = re.compile(r"^\s*send\s*$", re.IGNORECASE)
EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def _blocked(code: str, message: str) -> PolicyDecision:
    return PolicyDecision(False, code, message)


@dataclass
class CalendarAuthorization:
    """Single-use permission to click Save for exactly one approved event."""

    approval_id: UUID
    task_id: UUID
    event_hash: str
    sends_invitations: bool
    expires_at: datetime
    consumed: bool = False
    clicked: bool = False
    invite_answered: bool = False
    created_at: datetime = field(default_factory=utc_now)

    def ready_to_click(self) -> bool:
        return self.consumed and not self.clicked and utc_now() < self.expires_at

    def mark_clicked(self) -> None:
        self.clicked = True


class IntegrationPolicy:
    def __init__(self, *, max_recipients: int = 20, max_body: int = 12_000, base: BrowserActionPolicy | None = None) -> None:
        self._base = base or BrowserActionPolicy()
        self.max_recipients = max_recipients
        self.max_body = max_body
        self._authorizations: dict[UUID, CalendarAuthorization] = {}
        self._used_approvals: set[UUID] = set()

    # ---------------------------------------------------------------- clicks

    def check_click(self, purpose: Purpose, label: str, *, authorization: CalendarAuthorization | None = None,
                    event_hash: str | None = None) -> PolicyDecision:
        text = re.sub(r"\s+", " ", label or "").strip()[:200]
        if not text:
            return _blocked("INTEGRATION_POLICY_BLOCKED", "The control has no readable label; refusing to click it.")
        if purpose in (Purpose.GMAIL_COMPOSE, Purpose.GMAIL_SAVE_CLOSE):
            if SEND.search(text):
                return _blocked("GMAIL_SEND_BLOCKED", "Sending email is never automated. TaskPilot only saves drafts.")
            if DESTRUCTIVE.search(text):
                return _blocked("INTEGRATION_POLICY_BLOCKED", f"“{text[:60]}” would discard or delete mail; refused.")
            ok = _COMPOSE.match(text) if purpose == Purpose.GMAIL_COMPOSE else _SAVE_CLOSE.match(text)
            return PolicyDecision.allow() if ok else _blocked("INTEGRATION_POLICY_BLOCKED", f"“{text[:60]}” is not an allowed Gmail control.")
        if purpose == Purpose.YOUTUBE_PLAY:
            if _PLAY.match(text) and not _YT_FORBIDDEN.search(text):
                return PolicyDecision.allow()
            return _blocked("INTEGRATION_POLICY_BLOCKED", f"“{text[:60]}” is not a play control.")
        if purpose == Purpose.CALENDAR_SAVE:
            if not _SAVE.match(text):
                return _blocked("INTEGRATION_POLICY_BLOCKED", f"“{text[:60]}” is not the event Save control.")
            if authorization is None or not authorization.ready_to_click():
                return _blocked("CALENDAR_APPROVAL_REQUIRED", "Creating an event needs a fresh approval of this exact event.")
            if event_hash is None or event_hash != authorization.event_hash:
                return _blocked("CALENDAR_APPROVAL_STALE", "The event changed after your approval; it was not created.")
            return PolicyDecision.allow()
        if purpose == Purpose.CALENDAR_INVITES:
            if _DONT_SEND.match(text):
                return PolicyDecision.allow()
            if _INVITE_SEND.match(text) and authorization is not None and authorization.sends_invitations and authorization.clicked:
                return PolicyDecision.allow()
            return _blocked("INTEGRATION_POLICY_BLOCKED", "Invitations are sent only when you approved an event with attendees.")
        return _blocked("INTEGRATION_POLICY_BLOCKED", "Unknown click purpose.")

    # ---------------------------------------------------------------- typing

    def check_fill(self, kind: FieldKind, text: str, *, sensitive: bool = False) -> PolicyDecision:
        if sensitive:
            return _blocked("SENSITIVE_ACTION_BLOCKED", "This looks like a password/OTP field. TaskPilot never types into it.")
        if kind == FieldKind.SEARCH:
            element = DOMElementInfo(tag_name="input", role="searchbox", accessible_name="Search", is_visible=True,
                                     is_enabled=True, is_interactive=True, is_editable=True)
            return self._base.check_type(element, text)
        if kind == FieldKind.RECIPIENTS:
            addresses = [a.strip() for a in text.split(",") if a.strip()]
            if not addresses or len(addresses) > self.max_recipients or not all(EMAIL.match(a) for a in addresses):
                return _blocked("GMAIL_RECIPIENT_INVALID", "Recipients must be valid email addresses you provided.")
            return PolicyDecision.allow()
        limit = 200 if kind == FieldKind.SUBJECT else self.max_body
        if not text.strip() or len(text) > limit:
            return _blocked("TEXT_TOO_LONG", f"Text must be 1–{limit} characters.")
        if redact_text(text) != text:
            return _blocked("SENSITIVE_ACTION_BLOCKED", "The text looks like it contains a credential or payment detail; it was not typed.")
        return PolicyDecision.allow()

    # ---------------------------------------------------------------- calendar authorizations

    def authorize_calendar(self, *, approval_id: UUID, task_id: UUID, approved: bool, approved_hash: str, live_hash: str,
                           sends_invitations: bool, window_seconds: int) -> CalendarAuthorization:
        """Turn an APPROVED, unused approval into a single-use authorization (or raise ValueError)."""
        if not approved:
            raise ValueError("CALENDAR_EVENT_REJECTED")
        if approval_id in self._used_approvals:
            raise ValueError("CALENDAR_APPROVAL_REUSED")
        if approved_hash != live_hash:
            raise ValueError("CALENDAR_APPROVAL_STALE")
        self._used_approvals.add(approval_id)
        auth = CalendarAuthorization(approval_id=approval_id, task_id=task_id, event_hash=approved_hash,
                                     sends_invitations=sends_invitations,
                                     expires_at=utc_now() + timedelta(seconds=max(30, window_seconds)), consumed=True)
        self._authorizations[approval_id] = auth
        return auth
