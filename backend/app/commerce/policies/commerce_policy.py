"""Commerce runtime policy: what an adapter may click, for which purpose.

It narrows — never widens — the Phase 3 BrowserActionPolicy:
- ordinary shopping clicks (search, add, +/−, open cart, choose a variant) go through the
  unchanged Phase 3 policy (payments/orders/checkout/sending stay hard-blocked);
- OPEN_CHECKOUT may click only a "proceed to checkout / proceed to buy" control (reviewable,
  not irreversible) — never a pay / place-order control;
- SELECT_COD may click only a cash/pay-on-delivery option;
- PLACE_COD_ORDER may click only a "place (your) order" control, and only with a valid
  single-use PurchaseAuthorization (see purchase_policy). Pay buttons are never clickable.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import TYPE_CHECKING

from app.policies.browser_action_policy import BrowserActionPolicy, PolicyDecision
from app.schemas.browser import BrowserPageState, DOMElementInfo

if TYPE_CHECKING:
    from app.commerce.policies.purchase_policy import PurchaseAuthorization


class ClickPurpose(str, Enum):
    OPEN_SEARCH = "OPEN_SEARCH"
    ADD_TO_CART = "ADD_TO_CART"
    INCREMENT = "INCREMENT"
    DECREMENT = "DECREMENT"
    OPEN_CART = "OPEN_CART"
    SELECT_VARIANT = "SELECT_VARIANT"
    OPEN_CHECKOUT = "OPEN_CHECKOUT"
    SELECT_COD = "SELECT_COD"
    PLACE_COD_ORDER = "PLACE_COD_ORDER"


COD_LABEL = re.compile(r"\b(cash on delivery|pay on delivery|cod)\b", re.IGNORECASE)
CHECKOUT_NAV = re.compile(r"^\s*(proceed( to (checkout|buy))?|checkout|go to checkout)\s*$", re.IGNORECASE)
PLACE_ORDER = re.compile(r"^\s*(place (your )?order|place order)\s*$", re.IGNORECASE)
# Anything that pays, authenticates a payment, or enters payment credentials. Never clicked.
PAYMENT = re.compile(
    r"\b(pay( now| securely| online| ₹| rs)?|payment|upi|card|net ?banking|wallet|emi|otp|pin|cvv|bank)\b",
    re.IGNORECASE,
)
_ADD = re.compile(r"^\s*(add( to cart)?|\+|add .*)\s*$", re.IGNORECASE)


def _blocked(code: str, message: str) -> PolicyDecision:
    return PolicyDecision(False, code, message)


class CommercePolicy:
    def __init__(self, base: BrowserActionPolicy | None = None) -> None:
        self._base = base or BrowserActionPolicy()

    def check_click(
        self,
        purpose: ClickPurpose,
        label: str,
        *,
        page: BrowserPageState | None = None,
        authorization: PurchaseAuthorization | None = None,
    ) -> PolicyDecision:
        text = re.sub(r"\s+", " ", label or "").strip()[:200]
        if not text:
            return _blocked("PURCHASE_POLICY_BLOCKED", "The control has no readable label; refusing to click it.")

        if purpose == ClickPurpose.OPEN_CHECKOUT:
            if CHECKOUT_NAV.match(text) and not PAYMENT.search(text) and not PLACE_ORDER.match(text):
                return PolicyDecision.allow()
            return _blocked("PURCHASE_POLICY_BLOCKED", f"“{text[:60]}” is not a checkout-review control.")

        if purpose == ClickPurpose.SELECT_COD:
            if COD_LABEL.search(text):
                return PolicyDecision.allow()
            return _blocked("PURCHASE_POLICY_BLOCKED", "Only a Cash/Pay on Delivery option may be selected automatically.")

        if purpose == ClickPurpose.PLACE_COD_ORDER:
            if not PLACE_ORDER.match(text) or (PAYMENT.search(text) and not COD_LABEL.search(text)):
                return _blocked("PURCHASE_POLICY_BLOCKED", f"“{text[:60]}” is not a cash-on-delivery order control.")
            if authorization is None or not authorization.ready_to_click():
                return _blocked("PURCHASE_APPROVAL_REQUIRED", "Placing an order needs a fresh, exact-order approval.")
            return PolicyDecision.allow()

        # Ordinary shopping clicks: the unchanged Phase 3 policy decides.
        element = DOMElementInfo(
            tag_name="button", role="button", accessible_name=text, text_content=text,
            is_visible=True, is_enabled=True, is_interactive=True,
        )
        decision = self._base.check_click(element, text, page)
        if not decision.allowed:
            return decision
        if PAYMENT.search(text) and not COD_LABEL.search(text):
            return _blocked("SENSITIVE_ACTION_BLOCKED", "Payment controls are never automated.")
        if purpose in (ClickPurpose.ADD_TO_CART, ClickPurpose.INCREMENT) and not (_ADD.match(text) or "add" in text.lower()):
            return _blocked("PURCHASE_POLICY_BLOCKED", f"“{text[:60]}” is not an add-to-cart control.")
        return PolicyDecision.allow()

    def check_type(self, field_label: str, text: str, *, sensitive: bool) -> PolicyDecision:
        """Only product search text is ever typed by commerce adapters."""
        element = DOMElementInfo(
            tag_name="input", role="searchbox", accessible_name=field_label, is_visible=True, is_enabled=True,
            is_interactive=True, is_editable=True, is_sensitive=sensitive,
        )
        return self._base.check_type(element, text)
