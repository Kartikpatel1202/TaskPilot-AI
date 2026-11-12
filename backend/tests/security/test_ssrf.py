"""Scenario 5 (application layer): prohibited destinations are refused by the URL policy and the
navigation guard before any request is made. Uses a fake DNS resolver — no public internet needed."""

from __future__ import annotations

import pytest

from app.agent.policies.url_policy import UrlPolicyError, validate_url
from app.browser.navigation_guard import NavigationGuard, is_public_ip

BLOCKED_LITERALS = [
    "http://127.0.0.1/", "http://localhost/admin", "http://10.1.2.3/", "http://172.16.0.5/", "http://172.31.255.255/",
    "http://192.168.1.1/", "http://[::1]/", "http://[fc00::1]/", "http://[fd12:3456::1]/", "http://[fe80::1]/",
    "http://169.254.169.254/latest/meta-data/", "http://2130706433/", "http://0x7f.1/", "http://017700000001/", "http://0/",
    "http://[::ffff:127.0.0.1]/", "http://user:pass@example.com/", "file:///etc/passwd", "javascript:alert(1)", "gopher://x/",
    "http://metadata.google.internal/", "http://224.0.0.1/",
]


@pytest.mark.parametrize("url", BLOCKED_LITERALS)
async def test_private_local_metadata_and_encoded_destinations_are_blocked(url: str) -> None:
    async def resolver(host: str) -> list[str]:
        return ["93.184.216.34"]

    guard = NavigationGuard(allowed_domains=["example.com", "google.internal"], resolver=resolver)
    decision = await guard.check_navigation(url)
    assert not decision.allowed, url


async def test_public_hostname_resolving_to_private_address_is_blocked() -> None:
    async def evil(host: str) -> list[str]:
        return ["10.0.0.7"]

    guard = NavigationGuard(allowed_domains=["example.com"], resolver=evil)
    decision = await guard.check_navigation("https://shop.example.com/")
    assert not decision.allowed and decision.code == "NON_PUBLIC_ADDRESS"


async def test_mixed_public_and_private_records_are_blocked() -> None:
    async def mixed(host: str) -> list[str]:
        return ["93.184.216.34", "127.0.0.1"]

    guard = NavigationGuard(allowed_domains=["example.com"], resolver=mixed)
    assert not (await guard.check_navigation("https://example.com/")).allowed


async def test_unsafe_subresources_are_refused_but_public_cdns_are_allowed() -> None:
    async def resolver(host: str) -> list[str]:
        return ["10.0.0.1"] if host == "internal.example.com" else ["151.101.1.1"]

    guard = NavigationGuard(allowed_domains=["example.com"], resolver=resolver)
    assert await guard.check_subresource("https://cdn.jsdelivr.net/x.js")
    assert not await guard.check_subresource("https://internal.example.com/x.js")
    assert not await guard.check_subresource("http://192.168.0.10/pixel.gif")
    assert not await guard.check_subresource("file:///etc/hosts")


def test_ip_classification() -> None:
    for ip in ("127.0.0.1", "10.0.0.1", "192.168.1.1", "169.254.169.254", "::1", "fc00::1", "fe80::1", "0.0.0.0", "100.64.0.1"):
        assert not is_public_ip(ip), ip
    assert is_public_ip("93.184.216.34") and is_public_ip("2606:4700::1111")
    with pytest.raises(UrlPolicyError):
        validate_url("http://127.1/")
