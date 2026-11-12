"""Integration adapter contract and shared types (Phase 5).

Adapters are trusted, site-specific code. They never launch browsers (they act through the
existing BrowserController), never run model-written code, and every click/fill passes the
IntegrationPolicy (on top of the unchanged Phase 3 BrowserActionPolicy where applicable).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any
from uuid import UUID

from app.schemas.integration import DomainType

if TYPE_CHECKING:
    from app.browser.controller import BrowserController
    from app.core.execution_events import ExecutionEvents
    from app.integrations.policies import IntegrationPolicy


class IntegrationError(Exception):
    """Safe, user-facing integration failure with a stable code."""

    def __init__(self, code: str, message: str, *, status: str = "FAILED") -> None:
        self.code = code
        self.message = message
        self.status = status  # FAILED | BLOCKED
        super().__init__(message)


class AccessStatus(str, Enum):
    READY = "READY"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    BLOCKED = "BLOCKED"  # CAPTCHA / bot check / access restriction


@dataclass(frozen=True)
class DomainBinding:
    """Where an integration lives. Real sites use their public URLs; fixtures are dev/test only."""

    key: str
    domain: DomainType
    name: str
    base_url: str
    url_prefix: str
    is_fixture: bool = False

    def url(self, path: str) -> str:
        return self.url_prefix.rstrip("/") + "/" + path.lstrip("/")

    def owns(self, url: str | None) -> bool:
        if not url:
            return False
        if self.is_fixture:
            return url.startswith(self.url_prefix.rstrip("/") + "/")
        from urllib.parse import urlsplit

        from app.browser.navigation_guard import domain_allowed

        host = (urlsplit(url).hostname or "").lower()
        base_host = (urlsplit(self.url_prefix).hostname or "").lower().removeprefix("www.")
        return domain_allowed(host, [base_host])


@dataclass
class IntegrationContext:
    session_id: UUID
    task_id: UUID | None
    controller: BrowserController
    policy: IntegrationPolicy
    telemetry: ExecutionEvents
    binding: DomainBinding
    timeout: float = 20.0
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    async def emit(self, event_type: Any, payload: Any) -> None:
        await self.telemetry.emit(self.session_id, event_type, payload, task_id=self.task_id)
