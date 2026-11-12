"""Deterministic risk classification.

The model's `risk_level` is advisory. Trusted rules compute a floor for every
action and the final level is `max(model, rules)` — rules can raise risk, never
lower it.
"""

from __future__ import annotations

import re

from app.schemas.action import (
    ClickAction,
    ExtractAction,
    NavigateAction,
    RequestApprovalAction,
    StopAction,
    TypeAction,
)
from app.schemas.approval import RiskLevel
from app.schemas.commerce import CommerceAction
from app.schemas.integration import INTEGRATION_ACTION_TYPES

_ORDER = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2, RiskLevel.CRITICAL: 3}

_CRITICAL = re.compile(
    r"\b(place (the |your )?order|confirm (the )?order|pay(ment)?|pay now|buy now|purchase|checkout|"
    r"proceed to (pay|checkout)|transfer|send money|delete|remove (my |the )?account|empty (the )?trash|"
    r"permanently)\b",
    re.IGNORECASE,
)
_HIGH = re.compile(
    r"\b(send|submit|publish|post|tweet|share publicly|save event|create event|schedule|book|reserve|"
    r"confirm|download|sign up|register|subscribe|accept (terms|invite))\b",
    re.IGNORECASE,
)
_MEDIUM = re.compile(
    r"\b(add to cart|add|increase quantity|update quantity|remove from cart|save draft|edit|update|"
    r"apply coupon)\b",
    re.IGNORECASE,
)
# Fields the agent must never fill — the user enters these personally.
CREDENTIAL_FIELD = re.compile(
    r"\b(password|passcode|otp|one[- ]time|pin|cvv|cvc|card number|credit card|debit card|upi pin|"
    r"security code|bank account|ifsc|aadhaar|pan number)\b",
    re.IGNORECASE,
)


def max_risk(*levels: RiskLevel) -> RiskLevel:
    return max(levels, key=lambda level: _ORDER[level])


def risk_at_least(level: RiskLevel, floor: RiskLevel) -> bool:
    return _ORDER[level] >= _ORDER[floor]


def _text_risk(*texts: str | None) -> RiskLevel:
    blob = " ".join(t for t in texts if t)
    if _CRITICAL.search(blob):
        return RiskLevel.CRITICAL
    if _HIGH.search(blob):
        return RiskLevel.HIGH
    if _MEDIUM.search(blob):
        return RiskLevel.MEDIUM
    return RiskLevel.LOW


def rule_risk(action: object, description: str = "") -> RiskLevel:
    """Minimum risk implied by the action itself, independent of the model's opinion."""
    if isinstance(action, (NavigateAction, ExtractAction, StopAction)):
        return RiskLevel.LOW
    if isinstance(action, RequestApprovalAction):
        return action.risk_level
    if isinstance(action, TypeAction):
        if action.sensitive or CREDENTIAL_FIELD.search(action.target_description):
            return RiskLevel.HIGH
        return RiskLevel.LOW
    if isinstance(action, ClickAction):
        # Judge what is clicked, not the model's prose about it.
        return _text_risk(action.target_description, action.accessible_name, action.text_hint)
    if isinstance(action, CommerceAction):
        return {"place_order": RiskLevel.CRITICAL, "search_and_add": RiskLevel.MEDIUM}.get(action.operation, RiskLevel.LOW)
    if getattr(action, "type", None) in INTEGRATION_ACTION_TYPES:
        # Phase 5: reading/playing is LOW; a saved (never sent) draft and a validated download are MEDIUM;
        # creating a calendar event is HIGH and self-gated by the exact-event approval.
        return {"youtube_search": RiskLevel.LOW, "youtube_play": RiskLevel.LOW, "gmail_create_draft": RiskLevel.MEDIUM,
                "file_download": RiskLevel.MEDIUM, "calendar_create_event": RiskLevel.HIGH}[action.type]  # type: ignore[attr-defined]
    return RiskLevel.HIGH  # unknown action types are treated conservatively


def classify_risk(action: object, model_risk: RiskLevel, description: str = "") -> RiskLevel:
    return max_risk(model_risk, rule_risk(action, description))
