"""Shared schema primitives."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    """Timezone-aware UTC timestamp. Use this everywhere instead of `datetime.utcnow()`."""
    return datetime.now(timezone.utc)


class APIError(BaseModel):
    """Consistent error body for every non-2xx REST response."""

    code: str
    message: str
    request_id: str | None = None
    details: list[dict[str, Any]] | None = Field(
        default=None,
        description="Optional, sanitized validation details (never stack traces).",
    )


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: datetime
