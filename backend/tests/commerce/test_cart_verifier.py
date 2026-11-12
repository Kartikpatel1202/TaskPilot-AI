"""Cart verification: VERIFIED / PARTIAL / MISMATCH from requested vs. observed items."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

from app.commerce.cart.cart_verifier import CartVerifier
from app.commerce.matching.product_matcher import ProductMatcher
from app.schemas.cart import CartItem, CartSnapshot, CartVerificationStatus
from app.schemas.commerce import RequirementProgress, RequirementStatus
from app.schemas.product import CommercePlatform, ProductAvailability, ProductUnit

from .conftest import req

V = CartVerifier(ProductMatcher())


def item(name: str, size: str, qty: float, line: str | None = None) -> CartItem:
    return CartItem(item_id=uuid4(), product_name=name, pack_size=size, quantity=qty, unit=ProductUnit.PACK,
                    line_total=Decimal(line) if line else None, availability=ProductAvailability.AVAILABLE,
                    observed_at=datetime.now(timezone.utc))


def snap(*items: CartItem, subtotal: str | None = None, total: str | None = None) -> CartSnapshot:
    return CartSnapshot(cart_id=uuid4(), platform=CommercePlatform.BLINKIT, items=list(items), item_count=len(items),
                        subtotal=Decimal(subtotal) if subtotal else None, total=Decimal(total) if total else None,
                        observed_at=datetime.now(timezone.utc))


MILK = req("milk", brand="Amul", qty=2, unit="LITER", variant="taaza")
EGGS = req("eggs", qty=12, unit="PIECE")


def progress(*reqs, status=RequirementStatus.ADDED):  # type: ignore[no-untyped-def]
    return [RequirementProgress(requirement=r, status=status) for r in reqs]


def test_verified_when_everything_matches_exactly() -> None:
    cart = snap(item("Amul Taaza Toned Milk", "1 ltr", 2, "112"), item("Farm Fresh Eggs", "12 pieces", 1, "96"),
                subtotal="208", total="237")
    report = V.verify(uuid4(), progress(MILK, EGGS), cart)
    assert report.status == CartVerificationStatus.VERIFIED
    assert report.computed_subtotal == Decimal("208.00") and not report.missing_items


def test_partial_when_an_item_is_missing() -> None:
    report = V.verify(uuid4(), progress(MILK, EGGS), snap(item("Amul Taaza Toned Milk", "1 ltr", 2, "112")))
    assert report.status == CartVerificationStatus.PARTIAL
    assert report.missing_items == [EGGS.label()]


def test_quantity_mismatch_is_never_verified() -> None:
    report = V.verify(uuid4(), progress(MILK), snap(item("Amul Taaza Toned Milk", "1 ltr", 1, "56")))
    assert report.status == CartVerificationStatus.MISMATCH
    assert "quantity mismatch" in report.mismatched_items[0]


def test_wrong_variant_is_a_mismatch_not_a_match() -> None:
    report = V.verify(uuid4(), progress(MILK), snap(item("Amul Gold Full Cream Milk", "1 ltr", 2, "136")))
    assert report.status == CartVerificationStatus.MISMATCH
    assert report.checks[0].status == "VARIANT_MISMATCH"


def test_multiple_pack_sizes_add_up() -> None:
    cart = snap(item("Amul Taaza Toned Milk", "1 ltr", 1), item("Amul Taaza Toned Milk", "500 ml", 2))
    assert V.verify(uuid4(), progress(MILK), cart).status == CartVerificationStatus.VERIFIED


def test_unrelated_items_are_reported_and_left_alone() -> None:
    cart = snap(item("Amul Taaza Toned Milk", "1 ltr", 2, "112"), item("Shimla Apple", "1 kg", 1, "180"))
    report = V.verify(uuid4(), progress(MILK), cart)
    assert report.status == CartVerificationStatus.VERIFIED
    assert any("left unchanged" in w and "Shimla Apple" in w for w in report.warnings)


def test_subtotal_disagreement_and_unknown_total_are_warned() -> None:
    cart = snap(item("Amul Taaza Toned Milk", "1 ltr", 2, "112"), subtotal="120")
    report = V.verify(uuid4(), progress(MILK), cart)
    assert any("subtotal" in w for w in report.warnings)
    assert any("final total was not shown" in w for w in report.warnings)


def test_empty_requirements_are_unverified() -> None:
    assert V.verify(uuid4(), [], snap()).status == CartVerificationStatus.UNVERIFIED
