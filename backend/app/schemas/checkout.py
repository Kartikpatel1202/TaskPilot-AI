"""Checkout and order schemas (Phase 4). Mirrors `frontend/src/types/checkout.ts`."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field

from app.schemas.cart import CartItem
from app.schemas.product import CommercePlatform


class PaymentMethod(str, Enum):
    COD = "COD"
    UPI = "UPI"
    CARD = "CARD"
    NET_BANKING = "NET_BANKING"
    WALLET = "WALLET"
    UNKNOWN = "UNKNOWN"


class CheckoutSummary(BaseModel):
    checkout_id: UUID
    task_id: UUID
    platform: CommercePlatform
    items: list[CartItem]
    subtotal: Decimal | None = None
    delivery_fee: Decimal | None = None
    handling_fee: Decimal | None = None
    tax: Decimal | None = None
    discount: Decimal | None = None
    final_total: Decimal | None = None
    currency: str = "INR"
    masked_delivery_address: str | None = None
    delivery_slot: str | None = None
    payment_method: PaymentMethod = PaymentMethod.UNKNOWN
    available_payment_methods: list[PaymentMethod] = Field(default_factory=list)
    cart_id: UUID | None = None
    observed_at: datetime
    is_verified: bool
    # Stable fingerprint of everything an approval binds to (items, totals, address, payment).
    summary_hash: str
    version: int = 1
    warnings: list[str] = Field(default_factory=list)


class OrderStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    APPROVAL_PENDING = "APPROVAL_PENDING"
    REJECTED = "REJECTED"
    PAYMENT_HANDOFF = "PAYMENT_HANDOFF"
    SUBMISSION_PENDING = "SUBMISSION_PENDING"
    CONFIRMED = "CONFIRMED"
    UNKNOWN = "UNKNOWN"
    FAILED = "FAILED"


class OrderState(BaseModel):
    task_id: UUID
    status: OrderStatus
    message: str
    order_reference: str | None = None  # only when visibly shown by the website
    checkout_id: UUID | None = None
    approval_id: UUID | None = None
    observed_at: datetime | None = None
