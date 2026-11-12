"""Commerce workflow schemas (Phase 4). Mirrors `frontend/src/types/commerce.ts`.

`CommerceAction` is a plan step built only by the deterministic commerce planner
(never parsed from LLM output). Execution maps it to trusted adapter code.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.cart import CartSnapshot, CartVerificationReport, CartVerificationStatus
from app.schemas.checkout import CheckoutSummary, OrderState
from app.schemas.product import (
    CommercePlatform,
    MatchDecision,
    ProductCandidate,
    ProductMatch,
    ProductRequirement,
)

CommerceOperation = Literal[
    "open_store",       # open the site, check access/login/location, read the existing cart
    "search_products",  # search + rank only (no cart change)
    "search_and_add",   # search, match, add the missing quantity, verify
    "verify_cart",      # read the cart and verify it against every requirement
    "checkout_review",  # open checkout and read the exact summary (no purchase)
    "place_order",      # exact-order approval -> COD submission once, or prepaid handoff
]
PaymentPreference = Literal["COD", "PREPAID", "ANY"]


class CommerceAction(BaseModel):
    type: Literal["commerce"]
    operation: CommerceOperation
    platform: CommercePlatform
    site_key: str = Field(min_length=1, max_length=40)
    requirement: ProductRequirement | None = None
    payment_preference: PaymentPreference | None = None
    # A failed item does not stop independent later items (the cart check still reports it).
    continue_on_failure: bool = False


class RequirementStatus(str, Enum):
    PENDING = "PENDING"
    SEARCHING = "SEARCHING"
    AWAITING_SELECTION = "AWAITING_SELECTION"
    SELECTED = "SELECTED"
    ADDED = "ADDED"
    ALREADY_IN_CART = "ALREADY_IN_CART"
    FOUND = "FOUND"  # search-only requirement with suitable options
    NOT_FOUND = "NOT_FOUND"
    UNAVAILABLE = "UNAVAILABLE"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"


class RequirementProgress(BaseModel):
    requirement: ProductRequirement
    status: RequirementStatus = RequirementStatus.PENDING
    decision: MatchDecision | None = None
    message: str | None = None
    candidates: list[ProductCandidate] = Field(default_factory=list)
    matches: list[ProductMatch] = Field(default_factory=list)
    selected_candidate_id: UUID | None = None
    packs_added: int = 0


class PendingSelection(BaseModel):
    selection_id: UUID
    task_id: UUID
    requirement_id: UUID
    question: str
    candidate_ids: list[UUID]
    expires_at: datetime


class WorkflowStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    WAITING_USER = "WAITING_USER"
    CART_READY = "CART_READY"
    PARTIAL = "PARTIAL"
    SEARCH_COMPLETE = "SEARCH_COMPLETE"
    CHECKOUT_READY = "CHECKOUT_READY"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    PAYMENT_HANDOFF = "PAYMENT_HANDOFF"
    ORDER_CONFIRMED = "ORDER_CONFIRMED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class ShoppingSummary(BaseModel):
    task_id: UUID
    session_id: UUID
    platform: CommercePlatform
    site_name: str
    is_fixture: bool
    status: WorkflowStatus
    message: str | None = None
    requirements: list[RequirementProgress]
    pending_selection: PendingSelection | None = None
    cart: CartSnapshot | None = None
    verification: CartVerificationReport | None = None
    checkout: CheckoutSummary | None = None
    order: OrderState | None = None
    price_changes: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    updated_at: datetime


# ---------------------------------------------------------------------- REST bodies


class ProductSelectionRequest(BaseModel):
    session_id: UUID
    selection_id: UUID
    candidate_id: UUID | None = None  # null = skip this product


class QuantityUpdateRequest(BaseModel):
    session_id: UUID
    quantity: int = Field(ge=0, le=50)


class SessionOwnedRequest(BaseModel):
    session_id: UUID


# ---------------------------------------------------------------------- telemetry payloads


class CommerceSessionPayload(BaseModel):
    platform: CommercePlatform
    site_name: str
    is_fixture: bool
    status: str  # READY | LOGIN_REQUIRED | LOCATION_REQUIRED | BLOCKED
    message: str


class CommerceSearchPayload(BaseModel):
    platform: CommercePlatform
    requirement_id: UUID
    query: str
    message: str


class ProductsFoundPayload(BaseModel):
    platform: CommercePlatform
    requirement_id: UUID
    query: str
    candidate_count: int
    exact_match_count: int


class ProductDecisionPayload(BaseModel):
    platform: CommercePlatform
    requirement_id: UUID
    product_name: str | None = None
    decision: MatchDecision
    message: str
    selection_id: UUID | None = None
    candidate_count: int = 0


class CartChangePayload(BaseModel):
    platform: CommercePlatform
    requirement_id: UUID | None = None
    product_name: str | None = None
    before_quantity: float | None = None
    after_quantity: float | None = None
    message: str


class CartVerificationPayload(BaseModel):
    status: CartVerificationStatus
    requested_item_count: int
    matched_item_count: int
    missing_items: list[str] = Field(default_factory=list)
    mismatched_items: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PriceChangedPayload(BaseModel):
    platform: CommercePlatform
    product_name: str | None = None
    previous: Decimal | None = None
    current: Decimal | None = None
    difference: Decimal | None = None
    message: str
    approval_invalidated: bool = False


class CheckoutReadyPayload(BaseModel):
    platform: CommercePlatform
    checkout_id: UUID
    final_total: Decimal | None = None
    currency: str = "INR"
    payment_method: str
    is_verified: bool
    item_count: int


class PurchaseStatusPayload(BaseModel):
    platform: CommercePlatform
    status: str
    message: str
    approval_id: UUID | None = None
    checkout_id: UUID | None = None
    final_total: Decimal | None = None
    order_reference: str | None = None


class CommerceFailedPayload(BaseModel):
    platform: CommercePlatform | None = None
    code: str
    message: str
