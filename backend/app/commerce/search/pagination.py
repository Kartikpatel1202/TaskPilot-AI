"""Bounded result loading: scroll a few times for lazily rendered results, never endlessly."""

from __future__ import annotations

from typing import Any

MAX_SCROLLS = 3


async def load_more(page: Any, *, scrolls: int = MAX_SCROLLS, pause_ms: int = 400) -> None:
    for _ in range(max(0, min(scrolls, MAX_SCROLLS))):
        await page.mouse.wheel(0, 1200)
        await page.wait_for_timeout(pause_ms)
    await page.evaluate("() => window.scrollTo(0, 0)")
