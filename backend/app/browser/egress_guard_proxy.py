"""Local egress guard proxy for the automation browser (development; production uses the egress proxy service).

Why it exists: intercepting requests in Playwright and re-fetching them from Python (`route.fetch`) lets the
guard see every redirect, but sites behind bot protection (e.g. Blinkit via Cloudflare) reject those non-browser
requests, so the site never works. With this proxy Chromium performs its own requests, and every connection —
including each redirect hop, iframe, script, XHR and WebSocket — is checked here, at the network level:

  * the host is resolved once and EVERY resolved address must be public (no loopback, private, link-local,
    cloud metadata, CGNAT, multicast or reserved ranges); the connection then goes to that validated address, so
    a DNS-rebinding answer can never be used afterwards;
  * only ports 80 and 443 are allowed, except the exact development fixture origins configured as trusted;
  * plain HTTP requests are forwarded with `Connection: close`, so one client connection can never be reused to
    reach a different host.

Only the origins the guard already trusts (local dev/test fixtures) may use loopback. The page-level allow-list
(which sites the agent may open) is still enforced by NavigationGuard and on every final URL.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.core.logging import get_logger

logger = get_logger("browser.egress_guard")

Resolver = Callable[[str], Awaitable[list[str]]]
MAX_HEAD = 32 * 1024
ALLOWED_PORTS = frozenset({80, 443})


@dataclass(frozen=True)
class EgressDenial:
    at: float
    host: str
    reason: str


def _public(addr: str) -> bool:
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class LocalEgressGuardProxy:
    def __init__(self, *, resolver: Resolver, trusted_origins: list[str] | None = None, connect_timeout: float = 15.0,
                 dns_timeout: float = 5.0) -> None:
        self._resolver = resolver
        self._connect_timeout = connect_timeout
        self._dns_timeout = dns_timeout
        self._trusted: set[tuple[str, int]] = set()
        for origin in trusted_origins or []:
            parts = urlsplit(origin)
            if parts.hostname:
                self._trusted.add((parts.hostname.lower(), parts.port or (443 if parts.scheme == "https" else 80)))
        self._server: asyncio.base_events.Server | None = None
        self._conns: set[asyncio.Task[None]] = set()
        self.denials: deque[EgressDenial] = deque(maxlen=200)
        self.url: str | None = None

    # ---------------------------------------------------------------- lifecycle

    async def start(self) -> str:
        if self._server is None:
            self._server = await asyncio.start_server(self._accept, host="127.0.0.1", port=0)
            port = self._server.sockets[0].getsockname()[1]
            self.url = f"http://127.0.0.1:{port}"
            logger.info("egress_guard.started", extra={"port": port})
        assert self.url is not None
        return self.url

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            with contextlib.suppress(Exception):
                await self._server.wait_closed()
            self._server = None
        for task in list(self._conns):
            task.cancel()
        self._conns.clear()

    def denied_since(self, since: float) -> EgressDenial | None:
        return next((d for d in reversed(self.denials) if d.at >= since), None)

    # ---------------------------------------------------------------- policy

    async def resolve_allowed(self, host: str, port: int) -> str:
        """The single address to connect to, or raise PermissionError with a reason."""
        host = host.strip("[]").lower().rstrip(".")
        if (host, port) in self._trusted:
            infos = await asyncio.wait_for(self._resolver(host), timeout=self._dns_timeout) if not _is_ip(host) else [host]
            if not infos:
                raise PermissionError("could not resolve")
            return infos[0]
        if port not in ALLOWED_PORTS:
            raise PermissionError(f"port {port} is not allowed")
        if _is_ip(host):
            if not _public(host):
                raise PermissionError("non-public address")
            return host
        try:
            addresses = await asyncio.wait_for(self._resolver(host), timeout=self._dns_timeout)
        except (OSError, asyncio.TimeoutError, UnicodeError) as exc:
            raise PermissionError("could not resolve") from exc
        if not addresses:
            raise PermissionError("could not resolve")
        if not all(_public(a) for a in addresses):
            raise PermissionError("resolves to a non-public address")
        return addresses[0]

    # ---------------------------------------------------------------- connections

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        if task is not None:
            self._conns.add(task)
        try:
            await self._handle(reader, writer)
        except (asyncio.CancelledError, ConnectionError, asyncio.IncompleteReadError):
            pass
        except Exception:  # noqa: BLE001 - a broken client connection must never affect others
            logger.debug("egress_guard.connection_error", exc_info=True)
        finally:
            with contextlib.suppress(Exception):
                writer.close()
            if task is not None:
                self._conns.discard(task)

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        head = await reader.readuntil(b"\r\n\r\n")
        if len(head) > MAX_HEAD:
            return
        lines = head.decode("latin-1").split("\r\n")
        try:
            method, target, version = lines[0].split(" ", 2)
        except ValueError:
            return
        if method.upper() == "CONNECT":
            host, _, port_s = target.rpartition(":")
            port = int(port_s) if port_s.isdigit() else 443
            ip = await self._check(host, port, writer)
            if ip is None:
                return
            upstream_r, upstream_w = await self._connect(ip, port, writer)
            if upstream_w is None:
                return
            writer.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await writer.drain()
            await self._pipe(reader, writer, upstream_r, upstream_w)
            return
        parts = urlsplit(target)
        if parts.scheme != "http" or not parts.hostname:
            await self._deny(writer, parts.hostname or "?", "unsupported proxy request")
            return
        port = parts.port or 80
        ip = await self._check(parts.hostname, port, writer)
        if ip is None:
            return
        upstream_r, upstream_w = await self._connect(ip, port, writer)
        if upstream_w is None:
            return
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        headers = [h for h in lines[1:] if h and not h.lower().startswith(("proxy-connection:", "proxy-authorization:", "connection:", "keep-alive:"))]
        request = f"{method} {path} {version}\r\n" + "\r\n".join(headers) + "\r\nConnection: close\r\n\r\n"
        upstream_w.write(request.encode("latin-1"))
        await upstream_w.drain()
        await self._pipe(reader, writer, upstream_r, upstream_w)

    async def _check(self, host: str, port: int, writer: asyncio.StreamWriter) -> str | None:
        try:
            return await self.resolve_allowed(host, port)
        except PermissionError as exc:
            await self._deny(writer, host, str(exc))
            return None

    async def _deny(self, writer: asyncio.StreamWriter, host: str, reason: str) -> None:
        self.denials.append(EgressDenial(time.monotonic(), host.lower()[:120], reason))
        logger.warning("egress_guard.denied", extra={"host": host.lower()[:120], "reason": reason})
        body = f"Blocked by the TaskPilot egress guard: {reason}.".encode()
        writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nConnection: close\r\nContent-Length: "
                     + str(len(body)).encode() + b"\r\n\r\n" + body)
        with contextlib.suppress(Exception):
            await writer.drain()

    async def _connect(self, ip: str, port: int, writer: asyncio.StreamWriter
                       ) -> tuple[asyncio.StreamReader | None, asyncio.StreamWriter | None]:
        try:
            return await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=self._connect_timeout)
        except (OSError, asyncio.TimeoutError):
            with contextlib.suppress(Exception):
                writer.write(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\nContent-Length: 0\r\n\r\n")
                await writer.drain()
            return None, None

    async def _pipe(self, cr: asyncio.StreamReader, cw: asyncio.StreamWriter, ur: asyncio.StreamReader,
                    uw: asyncio.StreamWriter) -> None:
        async def copy(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
            try:
                while chunk := await src.read(65536):
                    dst.write(chunk)
                    await dst.drain()
            except (ConnectionError, asyncio.CancelledError):
                pass
            finally:
                with contextlib.suppress(Exception):
                    dst.close()

        try:
            await asyncio.gather(copy(cr, uw), copy(ur, cw))
        finally:
            with contextlib.suppress(Exception):
                uw.close()


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False
