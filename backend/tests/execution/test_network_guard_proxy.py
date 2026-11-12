"""BROWSER_NETWORK_GUARD=proxy: Chromium makes its own requests (so bot-protected sites work), and a guard proxy
checks every connection and redirect hop against the address it really connects to."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.browser.egress_guard_proxy import LocalEgressGuardProxy
from app.main import create_app

from ..conftest import browser_settings, wait_for_execution
from .conftest import container, execute, install_plan, nav, planned_task, results


def _proxy(answers: dict[str, list[str]], trusted: list[str] | None = None) -> LocalEgressGuardProxy:
    async def resolver(host: str) -> list[str]:
        return answers.get(host, [])

    return LocalEgressGuardProxy(resolver=resolver, trusted_origins=trusted)


@pytest.mark.parametrize("host,port", [
    ("127.0.0.1", 443), ("10.0.0.1", 80), ("169.254.169.254", 80), ("192.168.1.5", 443), ("::1", 443), ("100.64.0.1", 443),
    ("0.0.0.0", 80), ("::ffff:127.0.0.1", 443), ("224.0.0.1", 80),
])
def test_non_public_literals_are_refused(host: str, port: int) -> None:
    with pytest.raises(PermissionError):
        asyncio.run(_proxy({}).resolve_allowed(host, port))


def test_hostnames_must_resolve_only_to_public_addresses_and_are_pinned() -> None:
    p = _proxy({"shop.example": ["93.184.216.34"], "rebind.example": ["93.184.216.34", "127.0.0.1"], "internal.example": ["10.1.2.3"]})
    assert asyncio.run(p.resolve_allowed("shop.example", 443)) == "93.184.216.34"  # the connection goes to this exact IP
    for host in ("rebind.example", "internal.example", "unknown.example"):
        with pytest.raises(PermissionError):
            asyncio.run(p.resolve_allowed(host, 443))


def test_only_web_ports_except_exact_trusted_fixture_origins() -> None:
    p = _proxy({"shop.example": ["93.184.216.34"]}, trusted=["http://127.0.0.1:8123"])
    with pytest.raises(PermissionError):
        asyncio.run(p.resolve_allowed("shop.example", 22))
    assert asyncio.run(p.resolve_allowed("127.0.0.1", 8123)) == "127.0.0.1"
    with pytest.raises(PermissionError):
        asyncio.run(p.resolve_allowed("127.0.0.1", 8124))  # a different local port is not trusted


@pytest.fixture
def proxy_client(fixture_origin: str) -> Iterator[TestClient]:
    with TestClient(create_app(browser_settings(fixture_origin, browser_network_guard="proxy"))) as c:
        yield c


def test_pages_load_through_the_guard_proxy(proxy_client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(proxy_client, sid)
    install_plan(proxy_client, task_id, [nav(fixture_origin, "index.html"), nav(fixture_origin, "redirect/index")])
    execute(proxy_client, task_id, sid)
    assert wait_for_execution(proxy_client, task_id, timeout=60)["state"] == "COMPLETED", results(proxy_client, task_id)
    browser = container(proxy_client).browser
    assert browser.guard.network_enforced and browser.egress_guard is not None  # Chromium really used the proxy


def test_redirect_to_a_private_address_is_blocked_at_the_network(proxy_client: TestClient, fixture_origin: str) -> None:
    sid = str(uuid4())
    task_id = planned_task(proxy_client, sid)
    install_plan(proxy_client, task_id, [nav(fixture_origin, "redirect/outside")])  # 302 -> http://10.0.0.1/admin
    execute(proxy_client, task_id, sid)
    wait_for_execution(proxy_client, task_id, timeout=60)
    step = results(proxy_client, task_id)[0]
    assert step["status"] in ("FAILED", "BLOCKED") and step["error_code"] in ("NAVIGATION_BLOCKED", "NAVIGATION_FAILED"), step
    denials = container(proxy_client).browser.egress_guard.denials
    assert any(d.host == "10.0.0.1" for d in denials)  # the hop never reached 10.0.0.1
