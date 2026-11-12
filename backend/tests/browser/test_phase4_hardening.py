"""Phase 3 carry-forward fixes (Phase 4 prerequisites): page limits and active-resource redirects."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.browser.errors import BrowserPageLimitError
from app.browser.manager import BrowserManager

from .conftest import RecordingTelemetry, fixture_url


async def test_trusted_pages_are_limited_per_session(manager: BrowserManager) -> None:
    sid = uuid4()
    await manager.get_or_create_session(sid)
    limit = manager._settings.browser_max_pages_per_session  # noqa: SLF001 - default 3
    pages = [await manager.new_page(sid) for _ in range(limit - 1)]
    assert manager.page_count(sid) == limit
    with pytest.raises(BrowserPageLimitError):
        await manager.new_page(sid)
    assert manager.page_count(sid) == limit
    await pages[0].close()  # cleanup frees a slot
    await manager.new_page(sid)
    assert manager.page_count(sid) == limit


async def test_page_limits_are_isolated_between_sessions(manager: BrowserManager) -> None:
    a, b = uuid4(), uuid4()
    await manager.get_or_create_session(a)
    await manager.get_or_create_session(b)
    await manager.new_page(a)
    await manager.new_page(a)
    assert manager.page_count(a) == 3 and manager.page_count(b) == 1
    await manager.new_page(b)  # session b still has room


async def test_page_created_popups_are_still_closed(manager: BrowserManager, telemetry: RecordingTelemetry) -> None:
    sid = uuid4()
    session = await manager.get_or_create_session(sid)
    await session.page.set_content("<button onclick=\"window.open('about:blank')\">Open</button>")
    await session.page.click("button")
    for _ in range(40):
        if manager.page_count(sid) == 1 and "browser.popup_blocked" in telemetry.types():
            break
        await session.page.wait_for_timeout(50)
    assert manager.page_count(sid) == 1
    assert "browser.popup_blocked" in telemetry.types()


async def test_script_and_fetch_redirects_to_private_addresses_are_blocked(
    manager: BrowserManager, telemetry: RecordingTelemetry, fixture_origin: str
) -> None:
    session = await manager.get_or_create_session(uuid4())
    await session.page.goto(fixture_url(fixture_origin, "index.html"))
    result = await session.page.evaluate(
        """async (u) => { try { const r = await fetch(u); return 'status ' + r.status; } catch (e) { return 'blocked'; } }""",
        fixture_url(fixture_origin, "redirect/outside"),
    )
    assert result == "blocked"
    blocked = [e for e in telemetry.events if e[1] == "browser.navigation_blocked"]
    assert blocked and blocked[-1][2]["reason_code"] == "REDIRECT_BLOCKED"
    assert "10.0.0.1" in blocked[-1][2]["url"]


async def test_allowed_script_redirect_still_loads(manager: BrowserManager, fixture_origin: str) -> None:
    session = await manager.get_or_create_session(uuid4())
    await session.page.set_content("<p>no scripts yet</p>")
    assert await session.page.evaluate("typeof window.readCart") == "undefined"
    loaded = await session.page.evaluate(
        """(u) => new Promise((res) => { const s = document.createElement('script'); s.src = u;
              s.onload = () => res(typeof window.readCart === 'function'); s.onerror = () => res(false);
              document.head.appendChild(s); })""",
        fixture_url(fixture_origin, "redirect/script"),
    )
    assert loaded is True
