"""Planning-stage URL guardrail.

Phase 3 must re-check immediately before navigation (DNS resolution to a private
address, redirects), because a hostname that looks public can resolve anywhere.
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit, urlunsplit

MAX_URL_LENGTH = 2048
_BLOCKED_HOST_SUFFIXES = (".localhost", ".local", ".internal", ".lan", ".home.arpa", ".intranet", ".corp")


class UrlPolicyError(ValueError):
    pass


def _check_ip(host: str) -> None:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return
    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or (isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None)
    ):
        raise UrlPolicyError(f"Private, loopback or reserved address is not allowed: {host}")


def validate_url(url: str, *, trusted_origins: frozenset[str] = frozenset()) -> str:
    """Return a normalised http(s) URL or raise `UrlPolicyError`.

    `trusted_origins` holds exact test/dev-only origins (e.g. a local fixture
    server). Settings validation guarantees it is empty outside development/test.
    """
    if not isinstance(url, str) or not url.strip():
        raise UrlPolicyError("URL is empty.")
    raw = url.strip()
    if len(raw) > MAX_URL_LENGTH:
        raise UrlPolicyError("URL is too long.")
    if any(ch in raw for ch in ("\n", "\r", "\t", " ", "\\")):
        raise UrlPolicyError("URL contains whitespace or backslashes.")
    try:
        parts = urlsplit(raw)
    except ValueError as exc:
        raise UrlPolicyError("Malformed URL.") from exc

    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise UrlPolicyError(f"Unsupported URL scheme: {scheme or 'none'}")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise UrlPolicyError("URLs with embedded credentials are not allowed.")
    try:
        port = parts.port
    except ValueError as exc:
        raise UrlPolicyError("Invalid port.") from exc

    host = (parts.hostname or "").rstrip(".")
    if not host:
        raise UrlPolicyError("URL has no hostname.")
    try:
        host = host.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise UrlPolicyError("Invalid hostname.") from exc

    netloc = host if port is None else f"{host}:{port}"
    if f"{scheme}://{netloc}" in trusted_origins:
        return urlunsplit((scheme, netloc, parts.path or "", parts.query, ""))

    if host == "localhost" or host.endswith(_BLOCKED_HOST_SUFFIXES):
        raise UrlPolicyError("Local hostnames are not allowed.")
    _check_ip(host.strip("[]"))
    # Integer / hex / octal shorthand IPs ("2130706433", "0x7f.1") are rejected outright.
    if host.replace(".", "").isdigit() and not _is_dotted_quad(host):
        raise UrlPolicyError("Numeric hostnames are not allowed.")
    if host.startswith("0x") or ".0x" in host:
        raise UrlPolicyError("Numeric hostnames are not allowed.")
    if "." not in host and ":" not in host:
        raise UrlPolicyError("Single-label hostnames are not allowed.")

    return urlunsplit((scheme, netloc, parts.path or "", parts.query, ""))


def _is_dotted_quad(host: str) -> bool:
    pieces = host.split(".")
    return len(pieces) == 4 and all(p.isdigit() and 0 <= int(p) <= 255 for p in pieces)
