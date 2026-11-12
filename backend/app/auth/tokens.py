"""Access tokens (short-lived JWT, HS256) and opaque refresh tokens (only SHA-256 hashes are stored)."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import UUID

import jwt

ISSUER = "taskpilot-ai"
AUDIENCE = "taskpilot-api"


class TokenError(ValueError):
    pass


@dataclass(frozen=True)
class AccessClaims:
    user_id: UUID
    role: str
    version: int
    csrf_hash: str
    expires_at: datetime


def csrf_digest(csrf_token: str) -> str:
    return hashlib.sha256(csrf_token.encode()).hexdigest()[:32]


def issue_access(secret: str, *, user_id: UUID, role: str, version: int, csrf_token: str, ttl: timedelta) -> tuple[str, datetime]:
    now = datetime.now(timezone.utc)
    exp = now + ttl
    payload = {"sub": str(user_id), "role": role, "ver": version, "csrf": csrf_digest(csrf_token), "iat": int(now.timestamp()),
               "exp": int(exp.timestamp()), "iss": ISSUER, "aud": AUDIENCE, "typ": "access"}
    return jwt.encode(payload, secret, algorithm="HS256"), exp


def decode_access(secret: str, token: str) -> AccessClaims:
    try:
        data = jwt.decode(token, secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER,
                          options={"require": ["exp", "sub", "iat", "iss", "aud"]})
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("expired") from exc
    except jwt.PyJWTError as exc:
        raise TokenError("invalid") from exc
    if data.get("typ") != "access":
        raise TokenError("invalid")
    try:
        return AccessClaims(UUID(data["sub"]), str(data.get("role", "")), int(data.get("ver", -1)), str(data.get("csrf", "")),
                            datetime.fromtimestamp(data["exp"], tz=timezone.utc))
    except (ValueError, KeyError) as exc:
        raise TokenError("invalid") from exc


def new_refresh_token() -> tuple[str, str]:
    """(raw token for the HttpOnly cookie, SHA-256 hash for the database)."""
    raw = secrets.token_urlsafe(48)
    return raw, hash_refresh(raw)


def hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)
