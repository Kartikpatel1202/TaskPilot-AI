"""Classify a failed step from TRUSTED signals only (error codes, exception types, inspected page state).
The LLM never decides what kind of failure happened."""

from __future__ import annotations

from enum import Enum
from typing import Any


class FailureType(str, Enum):
    SELECTOR_NOT_FOUND = "SELECTOR_NOT_FOUND"
    SELECTOR_AMBIGUOUS = "SELECTOR_AMBIGUOUS"
    ELEMENT_HIDDEN = "ELEMENT_HIDDEN"
    ELEMENT_DISABLED = "ELEMENT_DISABLED"
    DOM_CHANGED = "DOM_CHANGED"
    NAVIGATION_TIMEOUT = "NAVIGATION_TIMEOUT"
    SESSION_EXPIRED = "SESSION_EXPIRED"
    AUTHENTICATION_REQUIRED = "AUTHENTICATION_REQUIRED"
    RATE_LIMITED = "RATE_LIMITED"
    WEBSITE_BLOCKED = "WEBSITE_BLOCKED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    PRICE_CHANGED = "PRICE_CHANGED"
    PRODUCT_UNAVAILABLE = "PRODUCT_UNAVAILABLE"
    FILE_VALIDATION_FAILED = "FILE_VALIDATION_FAILED"
    UNKNOWN = "UNKNOWN"


_BY_CODE = {
    "SELECTOR_NOT_FOUND": FailureType.SELECTOR_NOT_FOUND,
    "SELECTOR_AMBIGUOUS": FailureType.SELECTOR_AMBIGUOUS,
    "ELEMENT_DISABLED": FailureType.ELEMENT_DISABLED,
    "ELEMENT_HIDDEN": FailureType.ELEMENT_HIDDEN,
    "NAVIGATION_TIMEOUT": FailureType.NAVIGATION_TIMEOUT,
    "ACTION_TIMEOUT": FailureType.NAVIGATION_TIMEOUT,
    "BROWSER_SESSION_NOT_FOUND": FailureType.SESSION_EXPIRED,
    "AUTHENTICATION_REQUIRED": FailureType.AUTHENTICATION_REQUIRED,
    "CAPTCHA_REQUIRED": FailureType.WEBSITE_BLOCKED,
    "NAVIGATION_BLOCKED": FailureType.WEBSITE_BLOCKED,
    "RATE_LIMITED": FailureType.RATE_LIMITED,
    "PURCHASE_APPROVAL_REQUIRED": FailureType.APPROVAL_REQUIRED,
    "CALENDAR_APPROVAL_REQUIRED": FailureType.APPROVAL_REQUIRED,
    "PURCHASE_APPROVAL_STALE": FailureType.PRICE_CHANGED,
    "COMMERCE_PRODUCT_UNAVAILABLE": FailureType.PRODUCT_UNAVAILABLE,
    "COMMERCE_PRODUCT_NOT_FOUND": FailureType.PRODUCT_UNAVAILABLE,
}
# Only these may be retried by re-inspecting the page (nothing was clicked or typed yet).
RECOVERABLE = frozenset({FailureType.SELECTOR_NOT_FOUND, FailureType.DOM_CHANGED, FailureType.ELEMENT_HIDDEN})


def classify(code: str | None, message: str = "", *, page: Any | None = None, http_status: int | None = None) -> FailureType:
    if page is not None and getattr(page, "auth_required", False):
        return FailureType.AUTHENTICATION_REQUIRED
    if http_status == 429:
        return FailureType.RATE_LIMITED
    if http_status in (401, 403) and code in (None, "NAVIGATION_FAILED"):
        return FailureType.WEBSITE_BLOCKED
    if code and code.startswith("FILE_"):
        return FailureType.FILE_VALIDATION_FAILED
    if code in _BY_CODE:
        failure = _BY_CODE[code]
        if failure == FailureType.SELECTOR_NOT_FOUND:
            text = message.lower()
            if "not visible" in text:
                return FailureType.ELEMENT_HIDDEN
            if "detached" in text:
                return FailureType.DOM_CHANGED
        return failure
    return FailureType.UNKNOWN
