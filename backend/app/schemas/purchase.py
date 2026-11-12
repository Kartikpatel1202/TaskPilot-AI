"""Exact-order purchase approval details (Phase 4). Mirrors `frontend/src/types/checkout.ts`.

Attached to a normal `ApprovalRequest` (`purchase` field) so the existing approval
service, endpoint and dialog are reused — there is no second approval system.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.checkout import PaymentMethod
from app.schemas.product import CommercePlatform


class PurchaseApprovalItem(BaseModel):
    name: str = Field(max_length=300)
    quantity: str = Field(max_length=60)
    line_total: Decimal | None = None


class PurchaseApprovalDetails(BaseModel):
    platform: CommercePlatform
    checkout_id: UUID
    cart_id: UUID | None = None
    summary_hash: str = Field(min_length=16, max_length=128)
    summary_version: int
    items: list[PurchaseApprovalItem]
    subtotal: Decimal | None = None
    delivery_fee: Decimal | None = None
    handling_fee: Decimal | None = None
    tax: Decimal | None = None
    discount: Decimal | None = None
    final_total: Decimal
    currency: str = "INR"
    masked_delivery_address: str | None = None
    delivery_slot: str | None = None
    payment_method: PaymentMethod
    places_real_order: bool = True
    warnings: list[str] = Field(default_factory=list)
