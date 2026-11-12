"""Runtime navigation and network guard (Phase 3).

Top-level navigations must be to an allow-listed domain (exact or proper
subdomain boundary), over http(s), resolving only to public IP addresses.
Sub-resources (CDN images, scripts) may come from any *public* host, so normal
sites keep working, but never from local/private networks or non-web schemes.

Application-level checks are not a complete SSRF/DNS-rebinding defence: the
browser re-resolves names itself after our check. Public deployments must also
restrict network egress at the infrastructure level.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin, urlsplit

from app.agent.policies.url_policy import UrlPolicyError, validate_url
from app.core.logging import get_logger

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Request, Route

logger = get_logger("browser.guard")

Resolver = Callable[[str], Awaitable[list[str]]]

# Sub-resources whose redirects are validated hop by hop (passive images/fonts/media/styles are
# checked on their first URL only; see docs/BROWSER_SECURITY.md for the residual risk).
ACTIVE_RESOURCE_TYPES = frozenset({"script", "xhr", "fetch", "document", "eventsource"})


@dataclass(frozen=True)
class GuardDecision:
    allowed: bool
    url: str
    domain: str | None = None
    code: str | None = None
    message: str | None = None


def domain_allowed(host: str, allowed: list[str]) -> bool:
    """Exact domain or a real subdomain of it. `blinkit.com.evil.example` never matches."""
    host = host.lower().rstrip(".")
    return any(host == d or host.endswith("." + d) for d in allowed)


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def system_resolver(host: str) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({info[4][0] for info in infos})


class NavigationGuard:
    def __init__(
        self,
        *,
        allowed_domains: list[str],
        trusted_origins: list[str] | None = None,
        resolver: Resolver = system_resolver,
        dns_timeout: float = 3.0,
        cache_ttl: float = 300.0,
        cache_size: int = 512,
    ) -> None:
        self.allowed_domains = [d.lower() for d in allowed_domains]
        self.trusted_origins = frozenset(o.lower().rstrip("/") for o in (trusted_origins or []))
        self._resolver = resolver
        self._dns_timeout = dns_timeout
        self._ttl = cache_ttl
        self._cache_size = cache_size
        self._dns_cache: OrderedDict[str, tuple[float, bool]] = OrderedDict()
        # True when a guard proxy enforces the address policy on every connection (incl. redirect hops): requests
        # are then made by Chromium itself instead of being re-fetched here.
        self.network_enforced = False

    # ---------------------------------------------------------------- checks

    def _origin(self, url: str) -> str:
        parts = urlsplit(url)
        return f"{parts.scheme.lower()}://{(parts.netloc or '').lower()}"

    def is_trusted_origin(self, url: str) -> bool:
        try:
            return self._origin(url) in self.trusted_origins
        except ValueError:
            return False

    def check_static(self, url: str) -> GuardDecision:
        """Scheme, credentials, local/private literals and the domain allow-list (no DNS)."""
        try:
            normalised = validate_url(url, trusted_origins=self.trusted_origins)
        except UrlPolicyError as exc:
            return GuardDecision(False, url, None, "NAVIGATION_BLOCKED", str(exc))
        host = (urlsplit(normalised).hostname or "").lower()
        if self.is_trusted_origin(normalised):
            return GuardDecision(True, normalised, host)
        if not domain_allowed(host, self.allowed_domains):
            return GuardDecision(
                False, normalised, host, "DOMAIN_NOT_ALLOWED", f"{host} is not in the browser's allowed domains."
            )
        return GuardDecision(True, normalised, host)

    async def host_is_public(self, host: str) -> bool:
        host = host.strip("[]").lower()
        try:
            ipaddress.ip_address(host)
            return is_public_ip(host)
        except ValueError:
            pass
        now = time.monotonic()
        cached = self._dns_cache.get(host)
        if cached and now - cached[0] < self._ttl:
            self._dns_cache.move_to_end(host)
            return cached[1]
        try:
            addresses = await asyncio.wait_for(self._resolver(host), timeout=self._dns_timeout)
            public = bool(addresses) and all(is_public_ip(a) for a in addresses)
        except (OSError, asyncio.TimeoutError, UnicodeError):
            public = False
        self._dns_cache[host] = (now, public)
        while len(self._dns_cache) > self._cache_size:
            self._dns_cache.popitem(last=False)
        return public

    async def check_navigation(self, url: str) -> GuardDecision:
        decision = self.check_static(url)
        if not decision.allowed or self.is_trusted_origin(decision.url):
            return decision
        if not await self.host_is_public(decision.domain or ""):
            return GuardDecision(
                False, decision.url, decision.domain, "NON_PUBLIC_ADDRESS",
                f"{decision.domain} does not resolve to a public address (or could not be resolved).",
            )
        return decision

    async def check_subresource(self, url: str) -> bool:
        scheme = url.split(":", 1)[0].lower()
        if scheme in ("data", "blob", "about"):
            return True
        if scheme not in ("http", "https"):
            return False
        if self.is_trusted_origin(url):
            return True
        try:
            validate_url(url)  # no allow-list for sub-resources, but local/private targets are refused
        except UrlPolicyError:
            return False
        return await self.host_is_public(urlsplit(url).hostname or "")

    # ---------------------------------------------------------------- Playwright integration

    async def install(
        self,
        context: BrowserContext,
        on_blocked: Callable[[str, GuardDecision], Awaitable[None]],
    ) -> None:
        """Intercept every request of this context and enforce the policy before it is sent."""

        async def handler(route: Route, request: Request) -> None:
            url = request.url
            try:
                is_main_nav = request.is_navigation_request() and request.frame.parent_frame is None
            except Exception:  # frame detached
                is_main_nav = request.is_navigation_request()
            if is_main_nav:
                decision = await self.check_navigation(url)
                if not decision.allowed:
                    await route.abort("blockedbyclient")
                    await on_blocked("navigation", decision)
                    return
                if self.network_enforced:
                    # The guard proxy checks every hop's real address; the final URL is re-checked against the
                    # allow-list after the navigation (BrowserController.navigate).
                    await route.continue_()
                    return
                # Chromium follows redirects without consulting the interceptor, so top-level
                # navigations are fetched here with redirects disabled and every Location is
                # validated BEFORE the browser is allowed to follow it.
                try:
                    response = await route.fetch(max_redirects=0)
                except Exception:  # network error: let the browser surface its own error page
                    await route.abort("failed")
                    return
                if 300 <= response.status < 400:
                    location = response.headers.get("location")
                    target = urljoin(url, location) if location else None
                    target_decision = await self.check_navigation(target) if target else None
                    if target_decision is None or not target_decision.allowed:
                        await route.abort("blockedbyclient")
                        await on_blocked(
                            "redirect",
                            target_decision
                            or GuardDecision(False, url, None, "NAVIGATION_BLOCKED", "Redirect without a destination."),
                        )
                        return
                    # Hand the browser a clean redirect to the validated absolute target;
                    # the follow-up request comes through this handler again.
                    await route.fulfill(status=response.status, headers={"location": target_decision.url})
                    return
                await route.fulfill(response=response)
                return
            elif not await self.check_subresource(url):
                await route.abort("blockedbyclient")
                if request.is_navigation_request():
                    await on_blocked("frame", GuardDecision(False, url, None, "NAVIGATION_BLOCKED", "Embedded frame blocked."))
                return
            if self.network_enforced:
                await route.continue_()
                return
            if request.resource_type in ACTIVE_RESOURCE_TYPES and url.startswith(("http://", "https://")):
                # Active content (scripts, XHR/fetch, sub-frames): Chromium would follow redirects without the
                # interceptor seeing the target, so fetch with redirects disabled and validate every Location.
                try:
                    response = await route.fetch(max_redirects=0)
                except Exception:
                    await route.abort("failed")
                    return
                if 300 <= response.status < 400:
                    location = response.headers.get("location")
                    target = urljoin(url, location) if location else None
                    if target is None or not await self.check_subresource(target):
                        await route.abort("blockedbyclient")
                        await on_blocked(
                            "redirect",
                            GuardDecision(False, target or url, None, "REDIRECT_BLOCKED", "A resource redirect to a disallowed address was blocked."),
                        )
                        return
                    await route.fulfill(status=response.status, headers={"location": target})
                    return
                await route.fulfill(response=response)
                return
            await route.continue_()

        await context.route("**/*", handler)


def describe_blocked(decision: GuardDecision) -> dict[str, Any]:
    return {"url": decision.url, "domain": decision.domain, "code": decision.code, "message": decision.message}
