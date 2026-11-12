"""Runtime browser action policy — evaluated immediately before EVERY action.

Planning-time risk levels are advisory; this policy looks at what is actually on
the page (the resolved element's real name/text/type) and the planned intent.
A hard-blocked action is never executed, *even after a human approval*.

Manual-only in Phase 3: payments, placing/confirming orders, checkout, sending
messages/emails, publishing, deleting, transferring money, changing passwords or
security settings, submitting credentials/OTPs, and legally binding submissions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.logging import redact_text
from app.schemas.browser import BrowserPageState, DOMElementInfo

MAX_TYPED_CHARS = 500

HARD_BLOCK = re.compile(
    r"\b("
    r"place (your |the |my )?order|confirm (your |the |my )?(order|purchase|payment|booking)|"
    r"pay( now| securely| online)?|make (a )?payment|proceed to (pay|payment|checkout|buy)|"
    r"check ?out|buy now|submit (payment|order)|complete (purchase|order|payment|booking)|"
    r"transfer( money| funds)?|send money|send( (an |the )?(email|e-mail|message|mail|now|invite))?|"
    r"publish|post( now| it)?|tweet|delete( (account|permanently|all|everything))?|remove (my )?account|"
    r"change password|reset password|update password|security settings|two[- ]factor|"
    r"sign (the )?(contract|agreement)|accept (and )?(sign|terms)|subscribe (&|and) pay|confirm and pay"
    r")\b",
    re.IGNORECASE,
)
CREDENTIAL_SUBMIT = re.compile(r"\b(sign ?in|log ?in|verify|submit|continue|next)\b", re.IGNORECASE)
SENSITIVE_TEXT = re.compile(r"\b(password|passcode|otp|cvv|cvc|pin)\b", re.IGNORECASE)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    code: str | None = None
    message: str | None = None

    @staticmethod
    def allow() -> PolicyDecision:
        return PolicyDecision(True)


def _blocked(label: str) -> PolicyDecision:
    return PolicyDecision(
        False,
        "SENSITIVE_ACTION_BLOCKED",
        f"“{label[:80]}” is manual-only in Phase 3. Payments, orders, checkout, sending, publishing and "
        "deletions are never automated — even with approval. The browser is left open for you.",
    )


class BrowserActionPolicy:
    def check_planned(self, action_type: str, description: str, target: str | None = None) -> PolicyDecision:
        """Static pre-check of a planned action (used before asking for approval)."""
        if action_type == "click":
            blob = " ".join(filter(None, [description, target]))
            if HARD_BLOCK.search(blob):
                return _blocked(target or description)
        return PolicyDecision.allow()

    def check_click(self, element: DOMElementInfo, description: str, page: BrowserPageState | None) -> PolicyDecision:
        label = element.accessible_name or element.text_content or description
        blob = " ".join(filter(None, [element.accessible_name, element.text_content, element.aria_label, description]))
        if HARD_BLOCK.search(blob):
            return _blocked(label)
        if page is not None and (page.has_password_field or page.auth_required) and CREDENTIAL_SUBMIT.search(blob):
            return PolicyDecision(
                False, "SENSITIVE_ACTION_BLOCKED",
                "Submitting a sign-in or verification form is manual-only. Please sign in yourself.",
            )
        return PolicyDecision.allow()

    def check_type(self, element: DOMElementInfo, text: str) -> PolicyDecision:
        if element.is_sensitive or (element.input_type or "") == "password":
            return PolicyDecision(
                False, "SENSITIVE_ACTION_BLOCKED",
                "This field looks like a password, OTP, card or banking field. TaskPilot never types into it — "
                "please fill it in yourself.",
            )
        if len(text) > MAX_TYPED_CHARS:
            return PolicyDecision(False, "TEXT_TOO_LONG", f"Typed text is limited to {MAX_TYPED_CHARS} characters.")
        if redact_text(text) != text or SENSITIVE_TEXT.search(text):
            return PolicyDecision(
                False, "SENSITIVE_ACTION_BLOCKED", "The text looks like a credential or payment detail and was not typed."
            )
        return PolicyDecision.allow()
