"""BrowserManager with real Chromium: launch, isolation, limits, expiry, crash, shutdown."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from uuid import uuid4

import pytest

from app.browser.errors import BrowserSessionLimitError, BrowserUnavailableError
from app.browser.manager import BrowserManager
from app.schemas.browser import BrowserSessionStatus

from ..conftest import browser_settings
from .conftest import RecordingTelemetry, fixture_url, make_guard


async def test_browser_starts_lazily_and_creates_real_context(manager: BrowserManager, telemetry: RecordingTelemetry) -> None:
    assert manager.is_started is False  # nothing launches until a session is needed
    session = await manager.get_or_create_session(uuid4())
    assert manager.is_started is True
    assert session.page.viewport_size == {"width": 1440, "height": 900}
    assert "browser.session_started" in telemetry.types() and "browser.session_ready" in telemetry.types()


async def test_sessions_get_isolated_contexts_and_cookies(manager: BrowserManager, fixture_origin: str) -> None:
    a = await manager.get_or_create_session(uuid4())
    b = await manager.get_or_create_session(uuid4())
    assert a.context is not b.context and a.page is not b.page
    await a.page.goto(fixture_url(fixture_origin, "index.html"))
    await b.page.goto(fixture_url(fixture_origin, "index.html"))
    await a.context.add_cookies([{"name": "tp", "value": "only-a", "url": fixture_origin}])
    await a.page.evaluate("localStorage.setItem('k', 'a')")
    assert [c["value"] for c in await a.context.cookies()] == ["only-a"]
    assert await b.context.cookies() == []
    assert await b.page.evaluate("localStorage.getItem('k')") is None


async def test_same_session_id_reuses_its_own_session(manager: BrowserManager) -> None:
    sid = uuid4()
    first = await manager.get_or_create_session(sid)
    second = await manager.get_or_create_session(sid)
    assert first is second and manager.active_session_count == 1


async def test_session_limit_is_enforced(fixture_origin: str) -> None:
    settings = browser_settings(fixture_origin, browser_max_sessions=1)
    mgr = BrowserManager(settings, guard=make_guard(fixture_origin), telemetry=RecordingTelemetry())  # type: ignore[arg-type]
    try:
        await mgr.get_or_create_session(uuid4())
        with pytest.raises(BrowserSessionLimitError):
            await mgr.get_or_create_session(uuid4())
    finally:
        await mgr.shutdown()


async def test_close_session_releases_resources(manager: BrowserManager, telemetry: RecordingTelemetry) -> None:
    sid = uuid4()
    session = await manager.get_or_create_session(sid)
    assert await manager.close_session(sid) is True
    assert session.status == BrowserSessionStatus.CLOSED
    assert await manager.get_session(sid) is None and manager.active_session_count == 0
    assert "browser.session_closed" in telemetry.types()
    assert await manager.close_session(sid) is False


async def test_idle_sessions_expire(manager: BrowserManager) -> None:
    sid = uuid4()
    session = await manager.get_or_create_session(sid)
    session.last_activity_at -= timedelta(hours=2)
    assert await manager.expire_idle() == 1
    assert await manager.get_session(sid) is None


async def test_browser_crash_invalidates_sessions_and_relaunches(manager: BrowserManager, telemetry: RecordingTelemetry) -> None:
    sid = uuid4()
    await manager.get_or_create_session(sid)
    assert manager._browser is not None
    await manager._browser.close()  # simulate Chromium going away
    assert manager.is_started is False
    assert await manager.get_session(sid) is None
    await asyncio.sleep(0.05)  # crash telemetry is published asynchronously
    assert any(e[1] == "browser.session_error" and e[2]["code"] == "BROWSER_CRASHED" for e in telemetry.events)
    fresh = await manager.get_or_create_session(sid)  # next execution relaunches
    assert manager.is_started and fresh.is_active


async def test_graceful_shutdown_closes_everything(fixture_origin: str) -> None:
    mgr = BrowserManager(browser_settings(fixture_origin), guard=make_guard(fixture_origin), telemetry=RecordingTelemetry())  # type: ignore[arg-type]
    session = await mgr.get_or_create_session(uuid4())
    await mgr.shutdown()
    assert mgr.is_started is False and session.status == BrowserSessionStatus.CLOSED
    with pytest.raises(BrowserUnavailableError):
        await mgr.start()  # a shutting-down manager never relaunches


async def test_missing_chromium_reports_unavailable_without_crashing(fixture_origin: str, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", str(tmp_path))  # an empty browser directory
    mgr = BrowserManager(browser_settings(fixture_origin), guard=make_guard(fixture_origin), telemetry=RecordingTelemetry())  # type: ignore[arg-type]
    try:
        with pytest.raises(BrowserUnavailableError) as info:
            await mgr.get_or_create_session(uuid4())
        assert "playwright install chromium" in info.value.message
        assert mgr.installation_available() is False
        assert "playwright install chromium" in (mgr.unavailable_reason or "")
    finally:
        await mgr.shutdown()
