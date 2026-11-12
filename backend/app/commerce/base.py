"""Commerce adapter contract and shared types.

Adapters are trusted, site-specific code. They never launch browsers (they act
through the existing BrowserController), never run model-written code, and every
click passes the CommercePolicy (on top of the unchanged Phase 3 policy).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from app.schemas.cart import CartItem, CartMutationResult, CartSnapshot
from app.schemas.checkout import CheckoutSummary, PaymentMethod
from app.schemas.product import CommercePlatform, ProductCandidate, ProductRequirement

if TYPE_CHECKING:
    from app.browser.controller import BrowserController
    from app.commerce.policies.commerce_policy import CommercePolicy
    from app.commerce.policies.purchase_policy import PurchaseAuthorization
    from app.core.execution_events import ExecutionEvents


class CommerceError(Exception):
    """Safe, user-facing commerce failure with a stable code."""

    def __init__(self, code: str, message: str, *, status: str = "FAILED") -> None:
        self.code = code
        self.message = message
        self.status = status  # FAILED | BLOCKED
        super().__init__(message)


class SessionStatus(str, Enum):
    READY = "READY"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    LOCATION_REQUIRED = "LOCATION_REQUIRED"
    BLOCKED = "BLOCKED"  # CAPTCHA / bot check / access restriction


@dataclass(frozen=True)
class SiteBinding:
    """Where a platform lives. Real sites use their public URLs; fixtures are dev/test only."""

    key: str
    platform: CommercePlatform
    name: str
    base_url: str          # page opened by open_store
    url_prefix: str        # every page of this site starts with this (used for detection)
    is_fixture: bool = False

    def url(self, path: str) -> str:
        return self.url_prefix.rstrip("/") + "/" + path.lstrip("/")


@dataclass
class CommerceContext:
    session_id: UUID
    task_id: UUID | None
    controller: BrowserController
    policy: CommercePolicy
    telemetry: ExecutionEvents
    binding: SiteBinding
    search_timeout: float = 20.0
    max_results: int = 30
    max_attempts: int = 3
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)

    async def emit(self, event_type: Any, payload: Any) -> None:
        await self.telemetry.emit(self.session_id, event_type, payload, task_id=self.task_id)


@dataclass
class ProductSelection:
    candidate: ProductCandidate
    packs_needed: int
    requirement: ProductRequirement | None = None


@dataclass
class OrderSubmission:
    confirmed: bool
    order_reference: str | None
    message: str


class CommerceAdapter(Protocol):
    platform: CommercePlatform

    def detect_page(self, url: str, binding: SiteBinding) -> bool: ...

    async def open_store(self, ctx: CommerceContext) -> SessionStatus: ...

    async def check_session(self, ctx: CommerceContext) -> SessionStatus: ...

    async def search_products(self, req: ProductRequirement, ctx: CommerceContext) -> list[ProductCandidate]: ...

    async def add_to_cart(self, selection: ProductSelection, packs: int, ctx: CommerceContext) -> CartMutationResult: ...

    async def inspect_cart(self, ctx: CommerceContext) -> CartSnapshot: ...

    async def update_quantity(self, item: CartItem, quantity: int, ctx: CommerceContext) -> CartMutationResult: ...

    async def open_checkout(self, ctx: CommerceContext) -> SessionStatus: ...

    async def inspect_checkout(self, ctx: CommerceContext, task_id: UUID) -> CheckoutSummary: ...

    async def select_payment_method(self, method: PaymentMethod, ctx: CommerceContext) -> bool: ...

    async def submit_cod_order(self, ctx: CommerceContext, authorization: PurchaseAuthorization) -> OrderSubmission: ...
