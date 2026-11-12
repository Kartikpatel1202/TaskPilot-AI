"""Shared adapter helpers: guarded navigation, blocker detection, policy-checked clicks,
address masking and checkout fingerprints. All page scripts here are fixed, trusted code.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from decimal import Decimal
from typing import Any, TypeVar
from uuid import UUID, uuid4

from app.browser.errors import BrowserError, SensitiveActionBlockedError
from app.commerce.base import CommerceContext, CommerceError, SessionStatus
from app.commerce.money import is_free, parse_inr
from app.commerce.policies.commerce_policy import ClickPurpose
from app.core.logging import get_logger, redact_text
from app.schemas.cart import CartItem
from app.schemas.checkout import PaymentMethod
from app.schemas.common import utc_now

logger = get_logger("commerce.adapter")
T = TypeVar("T")

BLOCKERS_JS = r"""
() => {
  const vis = (el) => { if (!el) return false; const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const text = (document.body ? document.body.innerText : '').slice(0, 20000);
  const captcha = /enter the characters you see below|verify you are a human|are you a robot|complete the security check|unusual traffic|checking (if the site connection is secure|your browser)/i.test(text)
    || /^just a moment\.{0,3}$|attention required/i.test((document.title || '').trim())
    || !!document.querySelector('form[action*="validateCaptcha"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], .g-recaptcha, #captchacharacters, #challenge-form, .cf-turnstile, iframe[src*="challenges.cloudflare.com"]');
  const pw = [...document.querySelectorAll('input[type=password]')].some(vis);
  const otp = [...document.querySelectorAll('input')].some((i) => vis(i) && ((i.getAttribute('autocomplete') || '') === 'one-time-code' || /\botp\b/i.test([i.name, i.id, i.placeholder].join(' '))));
  const phoneLogin = [...document.querySelectorAll('input[type=tel]')].some(vis) && /\blog ?in\b|mobile number/i.test(text);
  const emailSignIn = [...document.querySelectorAll('#ap_email, input[name=email]')].some(vis) && /\bsign[- ]?in\b/i.test(text);
  const dialogs = [...document.querySelectorAll('[role=dialog], dialog[open], [aria-modal="true"]')].filter(vis);
  const location = dialogs.some((d) => /select (your )?(delivery )?location|provide your delivery location|detect my location/i.test(d.innerText || ''))
    // Live Blinkit: a full-page location picker overlay that is not marked up as a dialog.
    || [...document.querySelectorAll('[class*="LocationDropDown"], [class*="LocationOverlay"], [class*="location-modal" i]')].some((el) => vis(el)
         && (/provide your delivery location|detect my location|select (your )?(delivery )?location/i.test(el.innerText || '') || /Overlay/.test(el.className || '')));
  return { captcha, login: pw || otp || phoneLogin || emailSignIn, location };
}
"""


def mask_address(raw: str | None) -> str | None:
    """'Home: Flat 12, Fixture Lane, Sector 1, Gurugram 122001' -> 'Home: •••, Gurugram 122•••'."""
    if not raw:
        return None
    text = re.sub(r"\s+", " ", raw).strip()
    label = ""
    m = re.match(r"^(home|work|office|other)\s*[:\-]\s*", text, re.IGNORECASE)
    if m:
        label, text = m.group(1).title() + ": ", text[m.end():]
    pin = re.search(r"\b(\d{3})\d{3}\b", text)
    parts = [p.strip() for p in re.sub(r"\b\d{6}\b", "", text).split(",") if p.strip()]
    named = [p for p in parts if not re.search(r"\d", p) and p.lower() != "india"]
    city = named[-1] if named else ""
    if len(named) >= 2 and city.isupper():  # "…, Bengaluru, KARNATAKA, 560001": show the city, not the state
        city = named[-2]
    city = re.sub(r"\b(india)\b", "", city, flags=re.IGNORECASE).strip(" ,")
    masked = "•••" + (f", {city}" if city else "") + (f" {pin.group(1)}•••" if pin else "")
    return (label + masked)[:120]


def address_fingerprint(raw: str | None) -> str | None:
    return hashlib.sha256(re.sub(r"\s+", " ", raw or "").strip().lower().encode()).hexdigest() if raw else None


def summary_fingerprint(payload: dict[str, Any]) -> str:
    def default(value: Any) -> str:
        return str(value)

    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=default).encode()).hexdigest()


def payment_method_from(label: str | None) -> PaymentMethod:
    t = (label or "").lower()
    if re.search(r"cash on delivery|pay on delivery|\bcod\b", t):
        return PaymentMethod.COD
    if "upi" in t:
        return PaymentMethod.UPI
    if re.search(r"card", t):
        return PaymentMethod.CARD
    if re.search(r"net ?banking", t):
        return PaymentMethod.NET_BANKING
    if "wallet" in t or "pay balance" in t:
        return PaymentMethod.WALLET
    return PaymentMethod.UNKNOWN


def fee(text: str | None) -> Decimal | None:
    if text is None:
        return None
    if is_free(text):
        return Decimal("0.00")
    return parse_inr(text)


async def wait_for(check: Callable[[], Awaitable[T | None]], timeout: float, interval: float = 0.25) -> T | None:
    """Poll `check` until it returns a truthy value or the timeout passes (bounded, no busy loop)."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        value = await check()
        if value:
            return value
        if loop.time() >= deadline:
            return None
        await asyncio.sleep(interval)


class AdapterBase:
    async def page(self, ctx: CommerceContext) -> Any:
        return await ctx.controller.page_for(ctx.session_id)

    async def goto(self, ctx: CommerceContext, url: str) -> None:
        """Guarded navigation through the Phase 3 controller (allow-list, DNS, redirect checks)."""
        try:
            await ctx.controller.navigate(ctx.session_id, url)
        except BrowserError as exc:
            raise CommerceError(exc.code, exc.message, status="BLOCKED" if exc.code == "NAVIGATION_BLOCKED" else "FAILED") from exc

    async def reload_page(self, ctx: CommerceContext) -> None:
        """Re-load the current page from the website (guarded GET) so re-checks never trust stale DOM."""
        page = await self.page(ctx)
        await self.goto(ctx, page.url)

    async def blockers(self, ctx: CommerceContext) -> SessionStatus:
        try:
            state = await ctx.controller.evaluate(ctx.session_id, BLOCKERS_JS)
        except Exception:  # navigating
            return SessionStatus.READY
        if state.get("captcha"):
            return SessionStatus.BLOCKED
        if state.get("location"):
            return SessionStatus.LOCATION_REQUIRED
        if state.get("login"):
            return SessionStatus.LOGIN_REQUIRED
        return SessionStatus.READY

    async def require_ready(self, ctx: CommerceContext, *, allow_login: bool = True) -> None:
        status = await self.blockers(ctx)
        manager = getattr(ctx.controller, "manager", None)
        headed = manager is not None and not manager.headless
        if status == SessionStatus.BLOCKED:
            # Security check: never solved by TaskPilot. Wait (bounded) — it may finish by itself, or the user completes it
            # in the visible window — then re-check.
            from app.browser.bot_check import wait_until_clear

            wait = (manager.human_check_wait_seconds if headed else min(10, manager.human_check_wait_seconds)) if manager else 0
            if wait:
                await wait_until_clear(await self.page(ctx), timeout_seconds=wait)
                status = await self.blockers(ctx)
        if status == SessionStatus.LOCATION_REQUIRED and headed and manager.human_check_wait_seconds:
            # The user picks the delivery location in the visible window (TaskPilot never invents an address).
            async def chosen() -> bool | None:
                return True if await self.blockers(ctx) != SessionStatus.LOCATION_REQUIRED else None

            await wait_for(chosen, float(manager.human_check_wait_seconds), interval=1.0)
            status = await self.blockers(ctx)
        if status == SessionStatus.BLOCKED:
            raise CommerceError(
                "CAPTCHA_REQUIRED",
                f"{ctx.binding.name} is showing a CAPTCHA / bot check. TaskPilot never bypasses it — please open the site yourself.",
                status="BLOCKED",
            )
        if status == SessionStatus.LOCATION_REQUIRED:
            raise CommerceError(
                "COMMERCE_LOCATION_REQUIRED",
                f"{ctx.binding.name} needs a delivery location. Please choose it yourself; TaskPilot never invents an address.",
                status="BLOCKED",
            )
        if status == SessionStatus.LOGIN_REQUIRED and not allow_login:
            raise CommerceError(
                "COMMERCE_SESSION_REQUIRED",
                f"Please sign in to {ctx.binding.name} yourself (TaskPilot never types passwords or OTPs), then run the plan again.",
                status="BLOCKED",
            )

    async def click(
        self, ctx: CommerceContext, locator: Any, purpose: ClickPurpose, *, label: str | None = None,
        authorization: Any = None, settle_ms: int = 1500,
    ) -> Any:
        text = label
        if text is None:
            text = ""
            for read in (lambda: locator.get_attribute("aria-label", timeout=5000), lambda: locator.inner_text(timeout=5000),
                         lambda: locator.text_content(timeout=5000), lambda: locator.get_attribute("value", timeout=5000)):
                try:
                    text = (await read() or "").strip()
                except Exception:  # noqa: BLE001 - try the next source; an unreadable control is refused below
                    continue
                if text:
                    break
            # Icon-font glyphs render as stray single letters (e.g. "r" before "My Cart"): drop one-character lines.
            text = " ".join(line for line in text.splitlines() if len(line.strip()) > 1) or text
        decision = ctx.policy.check_click(purpose, text or "", authorization=authorization)
        if not decision.allowed:
            raise CommerceError(decision.code or "PURCHASE_POLICY_BLOCKED", decision.message or "Blocked by policy.", status="BLOCKED")
        if authorization is not None:
            authorization.mark_clicked()  # before the click: a second attempt is impossible, even after a timeout
        try:
            return await ctx.controller.click_checked(ctx.session_id, locator, decision, settle_ms=settle_ms)
        except SensitiveActionBlockedError as exc:
            raise CommerceError("SENSITIVE_ACTION_BLOCKED", exc.message, status="BLOCKED") from exc

    async def type_search(self, ctx: CommerceContext, locator: Any, query: str, *, submit: bool) -> None:
        sensitive = False
        try:
            sensitive = (await locator.get_attribute("type") or "").lower() == "password"
        except Exception:
            pass
        decision = ctx.policy.check_type("Search", query, sensitive=sensitive)
        if not decision.allowed:
            raise CommerceError(decision.code or "SENSITIVE_ACTION_BLOCKED", decision.message or "Blocked.", status="BLOCKED")
        ok = await ctx.controller.fill_checked(ctx.session_id, locator, query, decision, submit=submit)
        if not ok:
            raise CommerceError("COMMERCE_SEARCH_FAILED", "The search text could not be entered.")

    @staticmethod
    def cart_item(raw: dict[str, Any], *, unit_price_is_line: bool) -> CartItem:
        """Raw observed cart row -> CartItem. Unknown values stay None."""
        from app.commerce.matching.similarity import parse_measure  # local import keeps module light
        from app.schemas.product import ProductAvailability, ProductUnit

        qty = float(raw.get("quantity") or 0)
        price = parse_inr(raw.get("price"))
        unit_price = None if unit_price_is_line else price
        line_total = price if unit_price_is_line else ((price * Decimal(str(qty))).quantize(Decimal("0.01")) if price is not None and qty else None)
        measure = parse_measure(raw.get("size"), raw.get("name"))
        return CartItem(
            item_id=uuid4(),
            product_name=redact_text(str(raw.get("name") or "Unknown item"))[:300],
            pack_size=raw.get("size") or (measure.text if measure else None),
            quantity=qty,
            unit=ProductUnit.PACK,
            unit_price=unit_price,
            line_total=line_total,
            availability=ProductAvailability.UNAVAILABLE if raw.get("unavailable") else ProductAvailability.AVAILABLE,
            product_url=raw.get("url"),
            observed_at=utc_now(),
            dom_ref=raw.get("ref"),
        )


def new_id() -> UUID:
    return uuid4()
