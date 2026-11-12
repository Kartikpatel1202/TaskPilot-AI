"""Kamlesh Bhai's user-facing replies: sanitised model text with safe fallbacks."""

from __future__ import annotations

import re

from app.core.logging import redact_text
from app.core.persona import Language, persona_message
from app.schemas.plan import PlanStatus

MAX_MESSAGE_CHARS = 800
_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u200b-\u200f\u202a-\u202e]")
# Planned != done. A reply that claims completion is replaced with a template.
_COMPLETION_CLAIM = re.compile(
    r"\b(added (it |them |these |those )?to (your |the )?cart|have added|has been added|order (has been |is )?placed|"
    r"placed (the |your )?order|payment (is |has been )?(done|completed|successful)|paid|email (has been |was )?sent|"
    r"sent the email|event (has been |is )?created|downloaded|cart mein (add|daal) (kar )?diya|order kar diya|"
    r"bhej diya|payment kar diya)\b",
    re.IGNORECASE,
)

_STATUS_TEMPLATE = {
    PlanStatus.READY: "plan_ready",
    PlanStatus.NEEDS_CLARIFICATION: "clarification",
    PlanStatus.REJECTED: "rejected",
    PlanStatus.FAILED: "failed",
}


def sanitize_message(text: str | None, status: PlanStatus, language: Language) -> str:
    fallback = persona_message(_STATUS_TEMPLATE[status], language)
    if not text:
        return fallback
    cleaned = redact_text(_CONTROL.sub("", text)).strip()
    if not cleaned or _COMPLETION_CLAIM.search(cleaned):
        return fallback
    if len(cleaned) > MAX_MESSAGE_CHARS:
        cleaned = cleaned[: MAX_MESSAGE_CHARS - 1].rstrip() + "…"
    return cleaned


def sanitize_short(text: str, limit: int = 300) -> str:
    cleaned = redact_text(_CONTROL.sub("", text)).strip()
    return cleaned if len(cleaned) <= limit else cleaned[: limit - 1] + "…"
