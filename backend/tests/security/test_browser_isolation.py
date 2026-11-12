"""Browser isolation: separate contexts per session, egress proxy wiring, worker hardening in deployment
config. Container/firewall enforcement itself is verified only where Docker runs (see the final report)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from app.browser.manager import BrowserManager
from app.config import Settings

from ..browser.conftest import make_guard
from ..conftest import browser_settings, make_settings, production_overrides

ROOT = Path(__file__).resolve().parents[3]


async def test_sessions_do_not_share_storage(fixture_origin: str) -> None:
    from ..browser.conftest import RecordingTelemetry, fixture_url

    mgr = BrowserManager(browser_settings(fixture_origin), guard=make_guard(fixture_origin), telemetry=RecordingTelemetry())  # type: ignore[arg-type]
    try:
        a = await mgr.get_or_create_session(uuid4())
        b = await mgr.get_or_create_session(uuid4())
        await a.page.goto(fixture_url(fixture_origin, "index.html"))
        await b.page.goto(fixture_url(fixture_origin, "index.html"))
        await a.page.evaluate("() => localStorage.setItem('secret', 'A-only')")
        assert await b.page.evaluate("() => localStorage.getItem('secret')") is None
        assert a.context is not b.context
    finally:
        await mgr.shutdown()


async def test_chromium_is_launched_through_the_egress_proxy(monkeypatch, fixture_origin: str) -> None:  # noqa: ANN001
    captured: dict[str, object] = {}

    class FakeChromium:
        async def launch(self, **kwargs: object) -> object:
            captured.update(kwargs)
            raise RuntimeError("stop after capturing launch options")

    class FakePW:
        chromium = FakeChromium()

        async def stop(self) -> None:
            return None

    from ..browser.conftest import RecordingTelemetry

    settings = browser_settings(fixture_origin, egress_proxy_url="http://egress:3128")
    mgr = BrowserManager(settings, guard=make_guard(fixture_origin), telemetry=RecordingTelemetry())  # type: ignore[arg-type]
    mgr._playwright = FakePW()  # type: ignore[attr-defined]
    with pytest.raises(Exception):
        await mgr.get_or_create_session(uuid4())
    assert captured.get("proxy") == {"server": "http://egress:3128", "bypass": "<-loopback>"}


def test_production_requires_controlled_egress() -> None:
    with pytest.raises(Exception, match="REQUIRE_EGRESS_PROXY"):
        make_settings(**production_overrides(require_egress_proxy=False, agent_allow_mock_in_production=True))
    with pytest.raises(Exception, match="EGRESS_PROXY_URL"):
        Settings(_env_file=None, require_egress_proxy=True)  # type: ignore[call-arg]


def test_deployment_hardens_the_browser_container() -> None:
    compose = (ROOT / "deployment" / "docker-compose.prod.yml").read_text(encoding="utf-8")
    assert "docker.sock" not in compose
    for needle in ("no-new-privileges", "cap_drop", "read_only", "mem_limit", "egress"):
        assert needle in compose, needle
    squid = (ROOT / "deployment" / "egress" / "squid.conf").read_text(encoding="utf-8")
    for blocked in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "169.254.0.0/16", "127.0.0.0/8", "fc00::/7", "fe80::/10"):
        assert blocked in squid, blocked
