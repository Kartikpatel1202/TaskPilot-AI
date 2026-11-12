"""DNS-pinned HTTP transport for the safe downloader.

The hostname is resolved ONCE here; every resolved address must be public (or the exact dev/test fixture
origin), and the TCP connection is made to that validated IP. TLS still verifies the original hostname
(SNI + certificate) because httpcore passes the URL host to start_tls. This closes the
check-then-resolve-again gap (DNS rebinding) for downloads made by TaskPilot itself.

When an egress proxy is configured the proxy enforces the destination policy instead (the connection
then goes to the proxy, which resolves and checks the destination once).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Iterable
from typing import Any

import httpcore
import httpx

from app.browser.navigation_guard import is_public_ip, system_resolver

Resolver = Callable[[str], Awaitable[list[str]]]


class PinningError(httpcore.ConnectError):
    pass


class PinnedNetworkBackend(httpcore.AsyncNetworkBackend):
    def __init__(self, *, resolver: Resolver = system_resolver, trusted_hosts: Iterable[str] = (),
                 inner: httpcore.AsyncNetworkBackend | None = None) -> None:
        self._resolver = resolver
        self._trusted = {h.lower() for h in trusted_hosts}
        self._inner = inner or httpcore.AnyIOBackend()
        self.connected_to: list[str] = []  # observability/tests: the IPs actually dialled

    async def connect_tcp(self, host: str, port: int, timeout: float | None = None, local_address: str | None = None,
                          socket_options: Iterable[Any] | None = None) -> httpcore.AsyncNetworkStream:
        host_l = host.strip("[]").lower()
        if f"{host_l}:{port}" in self._trusted or host_l in self._trusted:
            target = host_l  # exact development/test fixture origin (refused outside dev/test by settings)
        else:
            try:
                addresses = [host_l] if _is_ip(host_l) else await self._resolver(host_l)
            except Exception as exc:  # noqa: BLE001
                raise PinningError(f"Could not resolve {host_l}") from exc
            if not addresses or not all(is_public_ip(a) for a in addresses):
                raise PinningError(f"{host_l} resolves to a non-public address; refused.")
            target = addresses[0]
        self.connected_to.append(target)
        return await self._inner.connect_tcp(target, port, timeout=timeout, local_address=local_address, socket_options=socket_options)

    async def connect_unix_socket(self, path: str, timeout: float | None = None,
                                  socket_options: Iterable[Any] | None = None) -> httpcore.AsyncNetworkStream:
        raise PinningError("Unix sockets are never used for downloads.")

    async def sleep(self, seconds: float) -> None:
        await self._inner.sleep(seconds)


def _is_ip(value: str) -> bool:
    import ipaddress

    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def pinned_transport(backend: PinnedNetworkBackend) -> httpx.AsyncHTTPTransport:
    transport = httpx.AsyncHTTPTransport(retries=0)
    # httpx builds its httpcore pool internally; swap in one that dials through the pinning backend.
    transport._pool = httpcore.AsyncConnectionPool(ssl_context=httpx.create_ssl_context(), network_backend=backend,
                                                   max_connections=10, max_keepalive_connections=0)
    return transport
