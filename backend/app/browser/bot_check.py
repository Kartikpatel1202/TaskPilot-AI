"""Detect website security checks (Cloudflare "Just a moment…", CAPTCHA, "verify you are human").

TaskPilot never solves, skips or spoofs these checks. What it does:
  * reports them honestly instead of treating the challenge page as the real site;
  * waits a bounded time, because many checks finish by themselves in a normal browser, and — when the
    browser window is visible on the user's machine — the user can complete the check themselves;
  * stops with CAPTCHA_REQUIRED if the check is still there afterwards.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

BOT_CHECK_JS = r"""
() => {
  const title = (document.title || '').trim();
  const text = (document.body ? document.body.innerText : '').slice(0, 8000);
  const titled = /^just a moment\.{0,3}$|attention required|access denied|are you a robot|security check|verify you are human/i.test(title);
  const texty = /verify you are a human|checking (if the site connection is secure|your browser)|enable javascript and cookies to continue|are you a robot|complete the security check|unusual traffic|press (and|&) hold/i.test(text);
  const widget = !!document.querySelector('#challenge-form, #challenge-running, #cf-challenge-running, .cf-turnstile, [name="cf-turnstile-response"], iframe[src*="challenges.cloudflare.com"], iframe[src*="recaptcha"], iframe[src*="hcaptcha"], .g-recaptcha, #captchacharacters, form[action*="validateCaptcha"], #px-captcha');
  return { blocked: titled || texty || widget, title: title.slice(0, 120) };
}
"""


async def is_bot_check(page: Any) -> bool:
    try:
        state = await page.evaluate(BOT_CHECK_JS)
    except Exception:  # noqa: BLE001 - navigating / closed: not a verdict
        return False
    return bool(state.get("blocked"))


async def wait_until_clear(page: Any, *, timeout_seconds: float, poll_seconds: float = 1.0) -> bool:
    """True once the page is no longer a security check (finished automatically or by the user)."""
    deadline = time.monotonic() + max(0.0, timeout_seconds)
    while True:
        if not await is_bot_check(page):
            return True
        if time.monotonic() >= deadline:
            return False
        await asyncio.sleep(poll_seconds)
