"""Registered browser action handlers. Only these action types can run (Phase 3 six + commerce + Phase 5 integrations)."""

from __future__ import annotations

from .approval import ApprovalHandler
from app.schemas.integration import INTEGRATION_ACTION_TYPES

from .base import BrowserActionHandler
from .click import ClickHandler
from .commerce import CommerceHandler
from .extract import ExtractHandler
from .integration import IntegrationHandler
from .navigate import NavigateHandler
from .stop import StopHandler
from .type import TypeHandler


def default_handlers() -> dict[str, BrowserActionHandler]:
    handlers: list[BrowserActionHandler] = [
        NavigateHandler(), ClickHandler(), TypeHandler(), ExtractHandler(), ApprovalHandler(), StopHandler(), CommerceHandler(),
        *(IntegrationHandler(t) for t in INTEGRATION_ACTION_TYPES),
    ]
    return {h.action_type: h for h in handlers}


__all__ = ["BrowserActionHandler", "default_handlers"]
