"""Shared integration adapter helpers: guarded navigation, access/blocker detection and
policy-checked clicks/fills. All page scripts here are fixed, trusted code (never model text)."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar
from urllib.parse import urlsplit

from app.browser.errors import BrowserError, SensitiveActionBlockedError
from app.commerce.adapters.base_adapter import BLOCKERS_JS
from app.integrations.base import AccessStatus, IntegrationContext, IntegrationError
from app.integrations.policies import FieldKind, Purpose

T = TypeVar("T")
SIGN_IN_HOSTS = ("accounts.google.com",)


async def wait_for(check: Callable[[], Awaitable[T | None]], timeout: float, interval: float = 0.25) -> T | None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        try:
            value = await check()
        except Exception:  # noqa: BLE001 - the page may be mid-navigation; poll again
            value = None
        if value:
            return value
        if loop.time() >= deadline:
            return None
        await asyncio.sleep(interval)


class IntegrationAdapterBase:
    async def page(self, ctx: IntegrationContext) -> Any:
        return await ctx.controller.page_for(ctx.session_id)

    async def goto(self, ctx: IntegrationContext, url: str) -> None:
        """Guarded navigation through the Phase 3 controller (allow-list, DNS, redirect checks)."""
        try:
            await ctx.controller.navigate(ctx.session_id, url)
        except BrowserError as exc:
            raise IntegrationError(exc.code, exc.message, status="BLOCKED" if exc.code == "NAVIGATION_BLOCKED" else "FAILED") from exc

    async def access(self, ctx: IntegrationContext) -> AccessStatus:
        page = await self.page(ctx)
        host = (urlsplit(page.url).hostname or "").lower()
        if host in SIGN_IN_HOSTS or page.url.endswith("/signin.html"):
            return AccessStatus.LOGIN_REQUIRED
        try:
            state = await ctx.controller.evaluate(ctx.session_id, BLOCKERS_JS)
        except Exception:  # noqa: BLE001
            return AccessStatus.READY
        if state.get("captcha"):
            return AccessStatus.BLOCKED
        if state.get("login"):
            return AccessStatus.LOGIN_REQUIRED
        return AccessStatus.READY

    async def require_access(self, ctx: IntegrationContext, *, login_code: str) -> None:
        status = await self.access(ctx)
        name = ctx.binding.name
        if status == AccessStatus.BLOCKED:
            raise IntegrationError("CAPTCHA_REQUIRED",
                                   f"{name} is showing a CAPTCHA / bot check. TaskPilot never bypasses it — please open it yourself.",
                                   status="BLOCKED")
        if status == AccessStatus.LOGIN_REQUIRED:
            raise IntegrationError(login_code,
                                   f"Please sign in to {name} yourself in the browser (TaskPilot never types passwords, OTPs or "
                                   "2-step codes), then run the plan again.", status="BLOCKED")

    async def label_of(self, locator: Any) -> str:
        for getter in ("aria-label", "data-tooltip", "value"):
            try:
                value = await locator.get_attribute(getter)
            except Exception:  # noqa: BLE001
                value = None
            if value:
                return value
        try:
            return (await locator.inner_text()) or ""
        except Exception:  # noqa: BLE001
            return ""

    async def click(self, ctx: IntegrationContext, locator: Any, purpose: Purpose, *, label: str | None = None,
                    authorization: Any = None, event_hash: str | None = None, settle_ms: int = 1200) -> Any:
        text = label if label is not None else await self.label_of(locator)
        decision = ctx.policy.check_click(purpose, text, authorization=authorization, event_hash=event_hash)
        if not decision.allowed:
            raise IntegrationError(decision.code or "INTEGRATION_POLICY_BLOCKED", decision.message or "Blocked by policy.", status="BLOCKED")
        if authorization is not None and purpose == Purpose.CALENDAR_SAVE:
            authorization.mark_clicked()  # before the click: a second Save is impossible, even after a timeout
        try:
            return await ctx.controller.click_checked(ctx.session_id, locator, decision, settle_ms=settle_ms)
        except SensitiveActionBlockedError as exc:
            raise IntegrationError("SENSITIVE_ACTION_BLOCKED", exc.message, status="BLOCKED") from exc
        except BrowserError as exc:
            raise IntegrationError(exc.code, exc.message) from exc

    async def fill(self, ctx: IntegrationContext, locator: Any, text: str, kind: FieldKind, *, submit: bool = False,
                   rich: bool = False) -> bool:
        sensitive = False
        try:
            sensitive = (await locator.get_attribute("type") or "").lower() == "password"
        except Exception:  # noqa: BLE001
            pass
        decision = ctx.policy.check_fill(kind, text, sensitive=sensitive)
        if not decision.allowed:
            raise IntegrationError(decision.code or "SENSITIVE_ACTION_BLOCKED", decision.message or "Blocked.", status="BLOCKED")
        try:
            return await ctx.controller.fill_checked(ctx.session_id, locator, text, decision, submit=submit, rich=rich)
        except BrowserError as exc:
            raise IntegrationError(exc.code, exc.message) from exc

    async def press(self, ctx: IntegrationContext, locator: Any, key: str, kind: FieldKind, text: str) -> None:
        decision = ctx.policy.check_fill(kind, text)
        try:
            await ctx.controller.press_checked(ctx.session_id, locator, key, decision)
        except BrowserError as exc:
            raise IntegrationError(exc.code, exc.message) from exc
