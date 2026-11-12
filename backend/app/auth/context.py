"""Request-scoped identity (set by the auth middleware / WebSocket handshake)."""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class AuthUser:
    id: UUID
    email: str
    role: str


current_user: ContextVar[AuthUser | None] = ContextVar("taskpilot_current_user", default=None)
correlation_id: ContextVar[str | None] = ContextVar("taskpilot_correlation_id", default=None)


def current_user_id() -> UUID | None:
    user = current_user.get()
    return user.id if user else None
