"""CSRF protection for cookie-authenticated state-changing requests (double submit + token binding).

The CSRF cookie (readable by the page) must match the `X-CSRF-Token` header AND the digest bound
inside the HttpOnly access token, so an attacker who can plant a cookie still cannot forge a request.
Bearer-token requests (no cookies) are not subject to CSRF.
"""

from __future__ import annotations

import hmac

from app.auth.tokens import csrf_digest

CSRF_COOKIE = "tp_csrf"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def csrf_ok(method: str, cookie_value: str | None, header_value: str | None, bound_digest: str) -> bool:
    if method.upper() in SAFE_METHODS:
        return True
    if not cookie_value or not header_value:
        return False
    return hmac.compare_digest(cookie_value, header_value) and hmac.compare_digest(csrf_digest(header_value), bound_digest)
