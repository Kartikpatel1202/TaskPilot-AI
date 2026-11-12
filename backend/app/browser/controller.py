"""BrowserController — the single trusted abstraction over Playwright for actions.

Action handlers call this; nothing else touches Page/BrowserContext. It never
plans and never sees model text other than typed planning contracts.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.browser.dom_inspector import DOMInspector
from app.browser.errors import (
    SelectorResolutionError,
    BrowserActionTimeoutError,
    BrowserSessionNotFoundError,
    NavigationBlockedError,
    SensitiveActionBlockedError,
)
from app.browser.manager import BrowserManager
from app.browser.screenshot_manager import ScreenshotManager
from app.browser.selector_resolver import Intent, ResolvedTarget, SelectorResolver, significant, tokens
from app.browser.session import BrowserSession, safe_url
from app.core.logging import redact_text
from app.schemas.browser import BrowserPageState, TargetDescription

if TYPE_CHECKING:
    from playwright.async_api import Page

_MUTATION_START_JS = """
() => {
  window.__tpMut = 0;
  if (window.__tpObs) window.__tpObs.disconnect();
  window.__tpObs = new MutationObserver((m) => { window.__tpMut += m.length; });
  window.__tpObs.observe(document.documentElement, { subtree: true, childList: true, attributes: true, characterData: true });
}
"""
_MUTATION_READ_JS = "() => window.__tpMut || 0"


@dataclass
class NavigationOutcome:
    url: str | None
    domain: str | None
    title: str | None
    status: int | None


@dataclass
class InteractionOutcome:
    navigated: bool
    dom_changed: bool
    url: str | None

    @property
    def observed_change(self) -> bool:
        return self.navigated or self.dom_changed


class BrowserController:
    def __init__(
        self,
        *,
        manager: BrowserManager,
        inspector: DOMInspector,
        resolver: SelectorResolver,
        screenshots: ScreenshotManager,
        action_timeout_ms: int,
        navigation_timeout_ms: int,
    ) -> None:
        self.manager = manager
        self.inspector = inspector
        self.resolver = resolver
        self.screenshots = screenshots
        self._action_timeout = action_timeout_ms
        self._nav_timeout = navigation_timeout_ms

    async def _session(self, session_id: UUID) -> BrowserSession:
        session = await self.manager.get_session(session_id)
        if session is None:
            raise BrowserSessionNotFoundError()
        session.touch()
        return session

    # ---------------------------------------------------------------- navigation

    async def navigate(self, session_id: UUID, url: str) -> NavigationOutcome:
        session = await self._session(session_id)
        guard = self.manager.guard
        decision = await guard.check_navigation(url)
        if not decision.allowed:
            raise NavigationBlockedError(decision.message, code="NAVIGATION_BLOCKED")
        session.blocked_navigation = None
        page = session.page
        started = time.monotonic()
        try:
            response = await self._goto(page, decision.url)
        except Exception as exc:  # noqa: BLE001
            proxy = getattr(self.manager, "egress_guard", None)
            denial = proxy.denied_since(started) if proxy is not None else None
            if denial is not None:
                raise NavigationBlockedError(
                    f"A connection to {denial.host} was blocked ({denial.reason}); navigation stopped.") from exc
            if session.blocked_navigation:
                # Chrome commits its error page for the aborted request asynchronously; wait for that
                # commit so it cannot interrupt (and be confused with) the next navigation.
                try:
                    await page.wait_for_url(lambda u: u.startswith("chrome-error:"), timeout=3_000)
                    await page.wait_for_load_state("domcontentloaded", timeout=3_000)
                except Exception:
                    pass
                raise NavigationBlockedError("A redirect to a disallowed address was blocked.") from exc
            if "Timeout" in type(exc).__name__ or "timeout" in str(exc).lower():
                raise BrowserActionTimeoutError("The page took too long to load.") from exc
            raise NavigationBlockedError("The page could not be loaded.", code="NAVIGATION_FAILED") from exc
        # Redirects are revalidated on the final URL, independently of the request interceptor.
        final = page.url
        final_decision = guard.check_static(final)
        if not final_decision.allowed or session.blocked_navigation:
            await page.goto("about:blank")
            raise NavigationBlockedError(
                f"The site redirected to a disallowed address ({safe_url(final) or 'unknown'}); navigation stopped."
            )
        try:
            await page.wait_for_load_state("load", timeout=min(self._nav_timeout, 8_000))
        except Exception:  # long-polling sites never reach "load"; DOM is already ready
            pass
        await session.refresh_page_info()
        return NavigationOutcome(
            url=session.current_url, domain=final_decision.domain, title=session.current_title,
            status=response.status if response else None,
        )

    async def _goto(self, page: Page, url: str) -> Any:
        """page.goto, retried once only if a leftover (error-page) navigation interrupted it.

        Navigating to the same validated URL again is idempotent; nothing on the page was acted on.
        """
        for attempt in range(2):
            try:
                return await page.goto(url, wait_until="domcontentloaded", timeout=self._nav_timeout)
            except Exception as exc:  # noqa: BLE001
                if "interrupted by another navigation" not in str(exc) or attempt == 1:
                    raise
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=5_000)
                except Exception:
                    pass
                # The interrupting navigation may itself be the (validated) redirect target. Every
                # request still went through the guard and the caller revalidates the final URL.
                if not page.url.startswith(("about:", "chrome-error:")):
                    return None
        return None

    # ---------------------------------------------------------------- resolution

    async def resolve(self, session_id: UUID, target: TargetDescription, intent: Intent) -> ResolvedTarget:
        session = await self._session(session_id)
        return await self.resolver.resolve(session.page, target, intent)

    async def ensure_allowed_page(self, session_id: UUID) -> None:
        """Every action requires the current page to still be on an allowed site."""
        session = await self._session(session_id)
        url = session.page.url
        if url.startswith("about:"):
            return
        decision = self.manager.guard.check_static(url)
        if not decision.allowed:
            raise NavigationBlockedError(f"The browser is on a page outside the allowed sites ({safe_url(url)}).")

    # ---------------------------------------------------------------- interactions

    async def _observe(self, page: Page, before_url: str, settle_ms: int = 1500) -> InteractionOutcome:
        navigated = False
        changed = False
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settle_ms / 1000
        while loop.time() < deadline:
            if page.url != before_url:
                navigated = True
                break
            try:
                if await page.evaluate(_MUTATION_READ_JS) > 0:
                    changed = True
                    await page.wait_for_timeout(250)  # let follow-up rendering finish
                    break
            except Exception:  # execution context destroyed => a navigation happened
                navigated = True
                break
            await page.wait_for_timeout(100)
        if navigated:
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=self._nav_timeout)
            except Exception:
                pass
        return InteractionOutcome(navigated=navigated, dom_changed=changed, url=safe_url(page.url))

    async def click(self, session_id: UUID, resolved: ResolvedTarget) -> InteractionOutcome:
        session = await self._session(session_id)
        page = session.page
        before = page.url
        await page.evaluate(_MUTATION_START_JS)
        try:
            # Playwright performs actionability checks (attached, visible, stable, enabled, receives events).
            await resolved.locator.click(timeout=self._action_timeout)
        except Exception as exc:  # noqa: BLE001 - a timeout is NOT proof the click happened (or didn't)
            # Phase 6: the element was re-rendered away while Playwright waited for it to become actionable, so no
            # click was dispatched on it. Report it as a resolution failure so bounded self-correction can look for
            # the control's new form. A timeout on an element that is still there stays uncertain (never retried).
            gone = False
            with contextlib.suppress(Exception):
                gone = await resolved.locator.count() == 0
            if gone:
                raise SelectorResolutionError("The element disappeared from the page before it could be clicked.") from exc
            raise BrowserActionTimeoutError("The element could not be clicked in time.") from exc
        outcome = await self._observe(page, before)
        await session.refresh_page_info()
        return outcome

    async def type_text(
        self, session_id: UUID, resolved: ResolvedTarget, text: str, *, clear_first: bool, submit: bool
    ) -> tuple[bool, InteractionOutcome | None]:
        session = await self._session(session_id)
        page = session.page
        locator = resolved.locator
        try:
            if clear_first:
                await locator.fill(text, timeout=self._action_timeout)
                expected = text
            else:
                current = await locator.input_value(timeout=self._action_timeout)
                await locator.press_sequentially(text, delay=15, timeout=self._action_timeout)
                expected = current + text
            value_ok = (await locator.input_value(timeout=self._action_timeout)) == expected
        except Exception as exc:  # noqa: BLE001
            raise BrowserActionTimeoutError("The field could not be filled in time.") from exc
        outcome = None
        if submit and value_ok:
            before = page.url
            await page.evaluate(_MUTATION_START_JS)
            await locator.press("Enter", timeout=self._action_timeout)
            outcome = await self._observe(page, before, settle_ms=2500)
            await session.refresh_page_info()
        return value_ok, outcome

    # ---------------------------------------------------------------- trusted adapter primitives (Phase 4)
    # Commerce adapters act only through these. Each requires an *allowed* PolicyDecision produced by
    # the commerce/browser policy for this exact element, so no click bypasses the runtime policy.

    async def page_for(self, session_id: UUID) -> Page:
        return (await self._session(session_id)).page

    async def evaluate(self, session_id: UUID, script: str, arg: Any = None) -> Any:
        """Run one of the adapters' fixed, trusted page scripts (never model-provided code)."""
        page = (await self._session(session_id)).page
        return await page.evaluate(script, arg)

    async def click_checked(self, session_id: UUID, locator: Any, decision: Any, *, settle_ms: int = 1500) -> InteractionOutcome:
        if not getattr(decision, "allowed", False):
            raise SensitiveActionBlockedError(getattr(decision, "message", None) or "Blocked by policy.")
        session = await self._session(session_id)
        page = session.page
        before = page.url
        with contextlib.suppress(Exception):
            await page.evaluate(_MUTATION_START_JS)
        try:
            await locator.click(timeout=self._action_timeout)
        except Exception as exc:  # noqa: BLE001 - callers re-inspect state before any retry
            raise BrowserActionTimeoutError("The element could not be clicked in time.") from exc
        outcome = await self._observe(page, before, settle_ms=settle_ms)
        await session.refresh_page_info()
        return outcome

    async def fill_checked(
        self, session_id: UUID, locator: Any, text: str, decision: Any, *, submit: bool = False, rich: bool = False
    ) -> bool:
        """Fill an input (or, with `rich`, a contenteditable editor) and verify what the page now holds."""
        if not getattr(decision, "allowed", False):
            raise SensitiveActionBlockedError(getattr(decision, "message", None) or "Blocked by policy.")
        session = await self._session(session_id)
        try:
            await locator.fill(text, timeout=self._action_timeout)
            if rich:
                shown = await locator.inner_text(timeout=self._action_timeout)
                ok = _norm_text(shown) == _norm_text(text)
            else:
                ok = (await locator.input_value(timeout=self._action_timeout)) == text
            if submit and ok:
                before = session.page.url
                await locator.press("Enter", timeout=self._action_timeout)
                await self._observe(session.page, before, settle_ms=2500)
        except Exception as exc:  # noqa: BLE001
            raise BrowserActionTimeoutError("The field could not be filled in time.") from exc
        await session.refresh_page_info()
        return ok

    async def press_checked(self, session_id: UUID, locator: Any, key: str, decision: Any) -> None:
        """Press one key (Tab/Enter) on an element the caller's policy already allowed."""
        if not getattr(decision, "allowed", False):
            raise SensitiveActionBlockedError(getattr(decision, "message", None) or "Blocked by policy.")
        if key not in ("Tab", "Enter", "Escape"):
            raise SensitiveActionBlockedError("Only Tab, Enter and Escape may be pressed.")
        session = await self._session(session_id)
        try:
            await locator.press(key, timeout=self._action_timeout)
        except Exception as exc:  # noqa: BLE001
            raise BrowserActionTimeoutError("The key could not be pressed in time.") from exc
        await session.refresh_page_info()

    async def select_checked(self, session_id: UUID, locator: Any, value: str, decision: Any) -> None:
        if not getattr(decision, "allowed", False):
            raise SensitiveActionBlockedError(getattr(decision, "message", None) or "Blocked by policy.")
        session = await self._session(session_id)
        before = session.page.url
        with contextlib.suppress(Exception):
            await session.page.evaluate(_MUTATION_START_JS)
        try:
            await locator.select_option(value, timeout=self._action_timeout)
        except Exception as exc:  # noqa: BLE001
            raise BrowserActionTimeoutError("The option could not be selected in time.") from exc
        await self._observe(session.page, before)
        await session.refresh_page_info()

    # ---------------------------------------------------------------- reading

    async def extract(self, session_id: UUID, target: str, fields: list[str]) -> dict[str, Any]:
        session = await self._session(session_id)
        region = await self.inspector.extract_region(session.page, sorted(significant(target)))
        return map_fields(region, fields)

    async def get_page_state(self, session_id: UUID) -> BrowserPageState:
        session = await self._session(session_id)
        state = await self.inspector.inspect_page_summary(session.page)
        session.auth_required = state.auth_required
        return state

    async def capture_screenshot(self, session_id: UUID) -> bytes:
        session = await self._session(session_id)
        frame = await self.screenshots.capture(session)
        if frame is None:
            return session.latest_frame.jpeg if session.latest_frame else b""
        return frame.jpeg


# ---------------------------------------------------------------------- field mapping

_PRICE = re.compile(r"(₹|rs\.?|inr|\$|€|£)\s?\d[\d,]*(\.\d+)?", re.IGNORECASE)
_QTY = re.compile(
    r"\b(\d+(\.\d+)?\s?(ml|l|ltr|litre|liter|kg|g|gm|pcs|pieces?|pack|packs|dozen|units?))\b|\bqty\s*:?\s*\d+\b",
    re.IGNORECASE,
)
_RATING = re.compile(r"\b\d(\.\d)?\s*(★|stars?|out of 5)", re.IGNORECASE)
_AVAIL = re.compile(r"\b(in stock|out of stock|sold out|unavailable|available|only \d+ left)\b", re.IGNORECASE)


def _norm_text(value: str) -> str:
    """Whitespace-insensitive comparison for rich-text editors (they rewrap lines and add NBSPs)."""
    return re.sub(r"\s+", " ", (value or "").replace(" ", " ")).strip()


def _field_kind(field: str) -> str:
    f = " ".join(tokens(field))
    if any(w in f for w in ("price", "cost", "mrp", "amount", "total")):
        return "price"
    if any(w in f for w in ("quantity", "size", "pack", "weight", "volume", "qty")):
        return "quantity"
    if "rating" in f or "star" in f:
        return "rating"
    if any(w in f for w in ("availability", "stock", "available")):
        return "availability"
    if any(w in f for w in ("name", "title", "product", "item", "heading")):
        return "name"
    return "text"


def map_fields(region: dict[str, Any], fields: list[str]) -> dict[str, Any]:
    """Map requested fields to OBSERVED text only; anything not seen is reported as missing (null)."""
    items_out: list[dict[str, Any]] = []
    missing: set[str] = set()
    for item in region.get("items", []):
        lines: list[str] = item.get("lines", [])
        if not lines:
            continue
        joined = " | ".join(lines)
        row: dict[str, Any] = {}
        for field in fields:
            kind = _field_kind(field)
            value: str | None = None
            if kind == "price":
                m = _PRICE.search(joined)
                value = m.group(0) if m else None
            elif kind == "quantity":
                m = _QTY.search(joined)
                value = m.group(0) if m else None
            elif kind == "rating":
                m = _RATING.search(joined)
                value = m.group(0) if m else None
            elif kind == "availability":
                m = _AVAIL.search(joined)
                value = m.group(0) if m else None
            elif kind == "name":
                value = item.get("heading") or next((ln for ln in lines if not _PRICE.fullmatch(ln)), None)
            else:
                want = tokens(field)
                value = next((ln for ln in lines if want & tokens(ln)), None)
            if value is None:
                missing.add(field)
            row[field] = redact_text(value)[:160] if value else None
        items_out.append(row)
    return {
        "source": "observed_dom",
        "container": region.get("container"),
        "item_count": len(items_out),
        "total_matching_items": region.get("total", len(items_out)),
        "items": items_out,
        "missing_fields": sorted(missing),
    }
