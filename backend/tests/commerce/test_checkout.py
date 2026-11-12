"""Checkout review rules, address masking, approval fingerprints and order verification."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.commerce.adapters.base_adapter import address_fingerprint, mask_address, payment_method_from, summary_fingerprint
from app.commerce.base import CommerceError, OrderSubmission
from app.commerce.checkout.checkout_inspector import compare_with_cart
from app.commerce.checkout.checkout_manager import CheckoutManager
from app.commerce.checkout.order_verifier import order_state
from app.schemas.cart import CartItem, CartSnapshot, CartVerificationReport, CartVerificationStatus
from app.schemas.checkout import CheckoutSummary, OrderStatus, PaymentMethod
from app.schemas.product import CommercePlatform, ProductAvailability, ProductUnit


def item(name: str, qty: float, size: str = "1 ltr") -> CartItem:
    return CartItem(item_id=uuid4(), product_name=name, pack_size=size, quantity=qty, unit=ProductUnit.PACK,
                    availability=ProductAvailability.AVAILABLE, observed_at=datetime.now(timezone.utc))


def cart(*items: CartItem) -> CartSnapshot:
    return CartSnapshot(cart_id=uuid4(), platform=CommercePlatform.BLINKIT, items=list(items), item_count=len(items),
                        observed_at=datetime.now(timezone.utc))


def report(status: CartVerificationStatus) -> CartVerificationReport:
    return CartVerificationReport(task_id=uuid4(), cart_id=uuid4(), status=status, requested_items=[], observed_items=[],
                                  verified_at=datetime.now(timezone.utc))


@pytest.mark.parametrize("status", [CartVerificationStatus.PARTIAL, CartVerificationStatus.MISMATCH, CartVerificationStatus.UNVERIFIED])
async def test_checkout_review_requires_a_verified_cart(status: CartVerificationStatus) -> None:
    with pytest.raises(CommerceError) as err:
        await CheckoutManager().review(None, None, uuid4(), report(status), cart(), None)  # type: ignore[arg-type]
    assert err.value.code == "COMMERCE_CART_UNVERIFIED"


def test_checkout_differences_from_the_verified_cart_are_reported() -> None:
    verified = cart(item("Amul Taaza Milk", 2), item("Farm Fresh Eggs", 1, "12 pieces"))
    summary = CheckoutSummary(checkout_id=uuid4(), task_id=uuid4(), platform=CommercePlatform.BLINKIT,
                              items=[item("Amul Taaza Milk", 3)], observed_at=datetime.now(timezone.utc), is_verified=True, summary_hash="x" * 64)
    problems = compare_with_cart(summary, verified)
    assert any("checkout shows 3" in p for p in problems) and any("Eggs" in p for p in problems)


@pytest.mark.parametrize(("raw", "masked"), [
    ("Home: Flat 12, Fixture Lane, Sector 1, Gurugram 122001", "Home: •••, Gurugram 122•••"),
    ("42, Fixture Residency, MG Road, Bengaluru, KARNATAKA, 560001, India", "•••, Bengaluru 560•••"),
    (None, None),
])
def test_addresses_are_masked(raw: str | None, masked: str | None) -> None:
    assert mask_address(raw) == masked


def test_fingerprints_change_with_address_total_or_payment() -> None:
    base = {"items": [("Milk", "1 L", 2, "112")], "total": "141", "address": address_fingerprint("Flat 12, Lane 1"), "payment": "COD"}
    h = summary_fingerprint(base)
    assert summary_fingerprint(dict(base)) == h
    assert summary_fingerprint({**base, "total": "145"}) != h
    assert summary_fingerprint({**base, "address": address_fingerprint("Flat 13, Lane 1")}) != h
    assert summary_fingerprint({**base, "payment": "UPI"}) != h


@pytest.mark.parametrize(("label", "method"), [
    ("Cash on Delivery/Pay on Delivery", PaymentMethod.COD), ("Other UPI Apps", PaymentMethod.UPI),
    ("Credit or debit card", PaymentMethod.CARD), ("Net Banking", PaymentMethod.NET_BANKING), ("Something else", PaymentMethod.UNKNOWN),
])
def test_payment_labels(label: str, method: PaymentMethod) -> None:
    assert payment_method_from(label) == method


def test_order_state_only_confirms_what_is_visible() -> None:
    task = uuid4()
    ok = order_state(task, OrderSubmission(True, "FXB-100001", "shown"), checkout_id=None, approval_id=None)
    assert ok.status == OrderStatus.CONFIRMED and ok.order_reference == "FXB-100001"
    unknown = order_state(task, OrderSubmission(False, None, "No confirmation visible."), checkout_id=None, approval_id=None)
    assert unknown.status == OrderStatus.UNKNOWN and unknown.order_reference is None
