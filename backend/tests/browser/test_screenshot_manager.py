"""ScreenshotManager on real Chromium: real JPEG, size limits, privacy pause, latest frame only."""

from __future__ import annotations

import pytest

from app.browser.errors import ScreenshotError
from app.browser.screenshot_manager import ScreenshotManager
from app.browser.session import BrowserSession

from .conftest import open_fixture


def shots(**overrides: object) -> ScreenshotManager:
    base = {"quality": 55, "max_bytes": 300_000, "fps": 1.0, "width": 1440, "height": 900}
    base.update(overrides)
    return ScreenshotManager(**base)  # type: ignore[arg-type]


async def test_captures_a_real_jpeg_of_the_viewport(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    frame = await shots().capture(session)
    assert frame is not None
    assert frame.jpeg[:3] == b"\xff\xd8\xff" and frame.jpeg[-2:] == b"\xff\xd9"
    assert (frame.width, frame.height) == (1440, 900) and frame.sequence == 1
    assert session.latest_frame is frame


async def test_only_the_latest_frame_is_kept(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    manager = shots()
    first = await manager.capture(session)
    await open_fixture(session, fixture_origin, "cart.html")
    second = await manager.capture(session)
    assert first is not None and second is not None
    assert second.sequence == first.sequence + 1 and session.latest_frame is second
    assert not hasattr(session, "frames")  # no frame history is stored anywhere on the session


async def test_oversized_frames_are_refused(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    with pytest.raises(ScreenshotError):
        await shots(max_bytes=500).capture(session)
    assert session.latest_frame is None


async def test_privacy_pause_while_password_or_otp_is_visible(session: BrowserSession, fixture_origin: str) -> None:
    manager = shots()
    await open_fixture(session, fixture_origin, "index.html")
    safe = await manager.capture(session)
    await open_fixture(session, fixture_origin, "login.html")
    assert await manager.capture(session) is None
    assert session.privacy_pause is True and session.latest_frame is safe  # the login page was never captured
    await open_fixture(session, fixture_origin, "index.html")
    assert await manager.capture(session) is not None and session.privacy_pause is False


async def test_frame_rate_is_bounded(session: BrowserSession, fixture_origin: str) -> None:
    manager = shots(fps=1.0)
    await open_fixture(session, fixture_origin, "index.html")
    assert manager.due(session.session_id)
    await manager.capture(session)
    assert not manager.due(session.session_id)
    manager.forget(session.session_id)
    assert manager.due(session.session_id)
