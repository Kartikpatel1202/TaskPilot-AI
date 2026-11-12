"""Cart schemas (Phase 4). Mirrors `frontend/src/types/cart.ts`.

Unknown values stay null — fees, taxes and discounts are never assumed to be zero.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.product import CommercePlatform, ProductAvailability, ProductRequirement, ProductUnit


class CartVerificationStatus(str, Enum):
    VERIFIED = "VERIFIED"
    PARTIAL = "PARTIAL"
    MISMATCH = "MISMATCH"
    UNVERIFIED = "UNVERIFIED"


class CartItem(BaseModel):
    item_id: UUID
    product_name: str
    brand: str | None = None
    variant: dict[str, str] = Field(default_factory=dict)
    pack_size: str | None = None
    quantity: float  # number of packs/units shown in the cart
    unit: ProductUnit
    unit_price: Decimal | None = None
    line_total: Decimal | None = None
    availability: ProductAvailability
    product_url: str | None = None
    observed_at: datetime
    dom_ref: str | None = Field(default=None, pattern=r"^r-\d{1,7}$")


class CartSnapshot(BaseModel):
    cart_id: UUID
    platform: CommercePlatform
    items: list[CartItem]
    item_count: int
    subtotal: Decimal | None = None
    delivery_fee: Decimal | None = None
    handling_fee: Decimal | None = None
    discount: Decimal | None = None
    tax: Decimal | None = None
    total: Decimal | None = None
    currency: str = "INR"
    observed_at: datetime
    verification_status: CartVerificationStatus = CartVerificationStatus.UNVERIFIED
    source_page: str | None = None


class CartItemCheck(BaseModel):
    requirement_id: UUID
    label: str
    status: str  # OK | MISSING | QUANTITY_MISMATCH | VARIANT_MISMATCH | UNAVAILABLE | SKIPPED
    observed_item_id: UUID | None = None
    requested: str
    observed: str | None = None
    message: str


class CartVerificationReport(BaseModel):
    task_id: UUID
    cart_id: UUID
    status: CartVerificationStatus
    requested_items: list[ProductRequirement]
    observed_items: list[CartItem]
    checks: list[CartItemCheck] = Field(default_factory=list)
    missing_items: list[str] = Field(default_factory=list)
    mismatched_items: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    computed_subtotal: Decimal | None = None
    verified_at: datetime


class CartMutationResult(BaseModel):
    success: bool
    requirement_id: UUID | None = None
    before_quantity: float | None = None
    after_quantity: float | None = None
    added_packs: int = 0
    message: str
    error_code: str | None = None
    snapshot: CartSnapshot | None = None
