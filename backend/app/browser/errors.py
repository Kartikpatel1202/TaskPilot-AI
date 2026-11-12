"""Browser domain errors. `message` is always safe to show users; no tracebacks or secrets."""

from __future__ import annotations


class BrowserError(Exception):
    code = "BROWSER_ERROR"
    default_message = "The browser could not complete the action."

    def __init__(self, message: str | None = None, *, code: str | None = None) -> None:
        self.message = message or self.default_message
        if code:
            self.code = code
        super().__init__(self.message)


class BrowserUnavailableError(BrowserError):
    code = "BROWSER_UNAVAILABLE"
    default_message = (
        "Chromium is not available. Install it with: python -m playwright install chromium"
    )


class BrowserSessionError(BrowserError):
    code = "BROWSER_SESSION_ERROR"
    default_message = "The browser session is not usable."


class BrowserSessionNotFoundError(BrowserError):
    code = "BROWSER_SESSION_NOT_FOUND"
    default_message = "No browser session exists for this TaskPilot session."


class BrowserSessionLimitError(BrowserError):
    code = "BROWSER_SESSION_LIMIT_REACHED"
    default_message = "The maximum number of browser sessions is already running. Close one and try again."


class BrowserPageLimitError(BrowserError):
    code = "BROWSER_PAGE_LIMIT_REACHED"
    default_message = "This browser session already has the maximum number of pages open."


class BrowserCrashedError(BrowserError):
    code = "BROWSER_CRASHED"
    default_message = "The browser crashed. Run the plan again to start a fresh session."


class NavigationBlockedError(BrowserError):
    code = "NAVIGATION_BLOCKED"
    default_message = "Navigation to this address is not allowed."


class SelectorResolutionError(BrowserError):
    code = "SELECTOR_NOT_FOUND"
    default_message = "The target element could not be found on the page."


class SelectorAmbiguousError(SelectorResolutionError):
    code = "SELECTOR_AMBIGUOUS"
    default_message = "Several elements match this target; refusing to pick one."


class SensitiveActionBlockedError(BrowserError):
    code = "SENSITIVE_ACTION_BLOCKED"
    default_message = "This action is manual-only and cannot be automated."


class BrowserActionTimeoutError(BrowserError):
    code = "ACTION_TIMEOUT"
    default_message = "The browser action timed out."


class ActionNotSupportedError(BrowserError):
    code = "ACTION_NOT_SUPPORTED"
    default_message = "This action type is not supported by the browser controller."


class SecurityCheckRequiredError(BrowserError):
    code = "CAPTCHA_REQUIRED"
    default_message = "The website is showing a security check (CAPTCHA / bot check). TaskPilot never bypasses it."


class AuthenticationRequiredError(BrowserError):
    code = "AUTHENTICATION_REQUIRED"
    default_message = "This page needs you to sign in manually before automation can continue."


class ScreenshotError(BrowserError):
    code = "SCREENSHOT_FAILED"
    default_message = "A browser screenshot could not be captured."
