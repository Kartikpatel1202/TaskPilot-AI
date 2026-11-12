"""NavigationGuard: allow-list, URL rules, DNS checks, trusted test origins, redirects."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.browser.controller import BrowserController
from app.browser.errors import NavigationBlockedError
from app.browser.navigation_guard import NavigationGuard, domain_allowed

from .conftest import fixture_url


def guard(resolved: dict[str, list[str]] | None = None, origins: list[str] | None = None) -> NavigationGuard:
    async def resolver(host: str) -> list[str]:
        if resolved is None or host not in resolved:
            raise OSError("no such host")
        return resolved[host]

    return NavigationGuard(
        allowed_domains=["blinkit.com", "amazon.in", "youtube.com"], trusted_origins=origins or [], resolver=resolver
    )


PUBLIC = {"blinkit.com": ["104.18.1.1"], "www.blinkit.com": ["104.18.1.1"], "cdn.example.net": ["151.101.1.1"]}


async def test_https_and_http_on_allowed_domains_pass() -> None:
    g = guard(PUBLIC)
    assert (await g.check_navigation("https://blinkit.com/s?q=milk")).allowed
    assert (await g.check_navigation("http://www.blinkit.com/")).allowed


@pytest.mark.parametrize(
    "url",
    ["javascript:alert(1)", "file:///etc/passwd", "data:text/html,hi", "ftp://blinkit.com", "http://localhost:3000",
     "http://127.0.0.1/", "http://10.1.2.3/", "http://192.168.0.1/", "http://169.254.169.254/latest/meta-data",
     "https://user:pass@blinkit.com/", "http://[::1]/", "not a url", "https:///nohost"],
)
async def test_unsafe_urls_are_blocked(url: str) -> None:
    assert (await guard(PUBLIC).check_navigation(url)).allowed is False


async def test_unauthorized_and_spoofed_domains_are_blocked() -> None:
    g = guard({"blinkit.com.evil.example": ["8.8.8.8"], "evilblinkit.com": ["8.8.8.8"], "example.org": ["8.8.8.8"]})
    for url in ("https://blinkit.com.evil.example/", "https://evilblinkit.com/", "https://example.org/"):
        decision = await g.check_navigation(url)
        assert decision.allowed is False and decision.code == "DOMAIN_NOT_ALLOWED"
    assert domain_allowed("m.blinkit.com", ["blinkit.com"]) and not domain_allowed("xblinkit.com", ["blinkit.com"])


async def test_dns_resolving_to_private_address_is_blocked() -> None:
    g = guard({"blinkit.com": ["10.0.0.7"]})  # rebinding-style answer
    decision = await g.check_navigation("https://blinkit.com/")
    assert decision.allowed is False and decision.code == "NON_PUBLIC_ADDRESS"


async def test_dns_failure_is_handled_safely() -> None:
    decision = await guard({}).check_navigation("https://blinkit.com/")
    assert decision.allowed is False and decision.code == "NON_PUBLIC_ADDRESS"


async def test_dns_results_are_cached_and_bounded() -> None:
    calls: list[str] = []

    async def resolver(host: str) -> list[str]:
        calls.append(host)
        return ["104.18.1.1"]

    g = NavigationGuard(allowed_domains=["blinkit.com"], resolver=resolver, cache_size=2)
    for _ in range(3):
        await g.check_navigation("https://blinkit.com/")
    assert calls == ["blinkit.com"]
    for host in ("a.blinkit.com", "b.blinkit.com", "c.blinkit.com"):
        await g.check_navigation(f"https://{host}/")
    assert len(g._dns_cache) == 2


async def test_trusted_local_origin_is_exact_only() -> None:
    g = guard(PUBLIC, origins=["http://127.0.0.1:8765"])
    assert (await g.check_navigation("http://127.0.0.1:8765/api/v1/dev/fixtures/shop/index.html")).allowed
    assert not (await g.check_navigation("http://127.0.0.1:8766/")).allowed  # other port
    assert not (await g.check_navigation("http://localhost:8765/")).allowed  # other host spelling


async def test_subresources_allow_public_cdns_but_not_private_targets() -> None:
    g = guard(PUBLIC)
    assert await g.check_subresource("https://cdn.example.net/app.js")  # not allow-listed, but public
    assert await g.check_subresource("data:image/png;base64,AAAA")
    assert not await g.check_subresource("http://192.168.1.10/internal.js")
    assert not await g.check_subresource("file:///C:/secret.txt")


async def test_real_redirect_to_prohibited_destination_is_blocked(controller: BrowserController, fixture_origin: str) -> None:
    sid = uuid4()
    await controller.manager.get_or_create_session(sid)
    with pytest.raises(NavigationBlockedError):
        await controller.navigate(sid, fixture_url(fixture_origin, "redirect/outside"))
    session = await controller.manager.get_session(sid)
    assert session is not None and "10.0.0.1" not in session.page.url
    ok = await controller.navigate(sid, fixture_url(fixture_origin, "redirect/index"))  # redirect within the origin
    assert ok.url and ok.url.endswith("/index.html")


async def test_real_navigation_to_unlisted_domain_is_refused_before_loading(controller: BrowserController) -> None:
    sid = uuid4()
    await controller.manager.get_or_create_session(sid)
    with pytest.raises(NavigationBlockedError):
        await controller.navigate(sid, "https://example.org/")
