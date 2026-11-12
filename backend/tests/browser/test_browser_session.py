"""BrowserSession helpers, encrypted storage-state persistence, popup control."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.browser.manager import BrowserManager
from app.browser.session import BrowserSession, safe_url
from app.browser.session_store import SessionStore

from ..conftest import browser_settings, make_settings
from .conftest import RecordingTelemetry, make_guard, open_fixture


def test_safe_url_strips_query_fragment_and_credentials() -> None:
    assert safe_url("https://u:p@blinkit.com/s?token=abc#x") == "https://blinkit.com/s"
    assert safe_url("javascript:alert(1)") == "javascript:"
    assert safe_url(None) is None


def test_encrypted_store_never_writes_plaintext(tmp_path) -> None:  # type: ignore[no-untyped-def]
    key = Fernet.generate_key().decode()
    store = SessionStore(tmp_path, key, ttl=timedelta(hours=1))
    sid = uuid4()
    state = {"cookies": [{"name": "session", "value": "SUPER-SECRET-COOKIE"}], "origins": []}
    store.save(sid, state)
    files = list(tmp_path.glob("*.state.enc"))
    assert len(files) == 1 and str(sid) not in files[0].name
    raw = files[0].read_bytes()
    assert b"SUPER-SECRET-COOKIE" not in raw and b"session" not in raw
    if os.name != "nt":
        assert oct(files[0].stat().st_mode & 0o777) == "0o600"
    assert store.load(sid) == state


def test_store_refuses_other_sessions_wrong_keys_and_expired_state(tmp_path) -> None:  # type: ignore[no-untyped-def]
    key = Fernet.generate_key().decode()
    store = SessionStore(tmp_path, key, ttl=timedelta(hours=1))
    sid = uuid4()
    store.save(sid, {"cookies": []})
    assert store.load(uuid4()) is None  # never another session's state
    other = SessionStore(tmp_path, Fernet.generate_key().decode(), ttl=timedelta(hours=1))
    assert other.load(sid) is None  # wrong key: unreadable, deleted
    store.save(sid, {"cookies": []})
    expired = SessionStore(tmp_path, key, ttl=timedelta(seconds=-1))
    assert expired.load(sid) is None
    store.save(sid, {"cookies": []})
    os.utime(next(tmp_path.glob("*.state.enc")), (0, 0))
    assert store.purge_expired() == 1


def test_persistence_requires_a_valid_key() -> None:
    with pytest.raises(ValidationError, match="BROWSER_STATE_ENCRYPTION_KEY"):
        make_settings(browser_persist_sessions=True)
    with pytest.raises(ValidationError, match="Fernet"):
        make_settings(browser_persist_sessions=True, browser_state_encryption_key="not-a-key")
    assert make_settings().browser_persist_sessions is False  # off by default


async def test_persistence_roundtrip_through_manager(fixture_origin: str, tmp_path) -> None:  # type: ignore[no-untyped-def]
    key = Fernet.generate_key().decode()
    settings = browser_settings(fixture_origin, browser_persist_sessions=True, browser_state_encryption_key=key)
    store = SessionStore(tmp_path, key, ttl=timedelta(hours=1))
    mgr = BrowserManager(settings, guard=make_guard(fixture_origin), telemetry=RecordingTelemetry(), store=store)  # type: ignore[arg-type]
    sid = uuid4()
    try:
        session = await mgr.get_or_create_session(sid)
        await session.context.add_cookies([{"name": "kept", "value": "yes", "url": fixture_origin}])
        await mgr.close_session(sid)
        restored = await mgr.get_or_create_session(sid)
        assert [c["value"] for c in await restored.context.cookies()] == ["yes"]
        other = await mgr.get_or_create_session(uuid4())
        assert await other.context.cookies() == []
    finally:
        await mgr.shutdown()
    assert not any(b"yes" in p.read_bytes() for p in tmp_path.glob("*.enc"))


async def test_popups_are_blocked(session: BrowserSession, fixture_origin: str, telemetry: RecordingTelemetry) -> None:
    await open_fixture(session, fixture_origin, "index.html")
    await session.page.evaluate("window.open('about:blank', '_blank')")
    await asyncio.sleep(0.3)
    assert len(session.context.pages) == 1
    assert "browser.popup_blocked" in telemetry.types()


async def test_refresh_page_info_tracks_url_and_title(session: BrowserSession, fixture_origin: str) -> None:
    await open_fixture(session, fixture_origin, "search.html")
    await session.refresh_page_info()
    assert session.current_title == "Search — TaskPilot Demo Shop"
    assert session.current_url and session.current_url.endswith("/search.html")
    json.dumps({"url": session.current_url})  # serialisable, never a Playwright object
