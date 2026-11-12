"""CartManager: add only the difference, never duplicate; price changes are detected."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import uuid4

from app.commerce.base import ProductSelection
from app.commerce.cart.cart_manager import CartManager
from app.commerce.policies.price_change_policy import PriceChangePolicy
from app.schemas.cart import CartItem, CartMutationResult, CartSnapshot
from app.schemas.product import CommercePlatform, ProductAvailability, ProductUnit

from .conftest import cand

CM = CartManager(PriceChangePolicy(5))


class RecordingAdapter:
    def __init__(self) -> None:
        self.added: list[int] = []

    async def add_to_cart(self, selection: Any, packs: int, ctx: Any) -> CartMutationResult:
        self.added.append(packs)
        return CartMutationResult(success=True, before_quantity=None, after_quantity=packs, added_packs=packs, message="ok")


def snap(*items: tuple[str, str, float, str | None]) -> CartSnapshot:
    rows = [CartItem(item_id=uuid4(), product_name=n, pack_size=s, quantity=q, unit=ProductUnit.PACK,
                     line_total=Decimal(lt) if lt else None, availability=ProductAvailability.AVAILABLE,
                     observed_at=datetime.now(timezone.utc)) for n, s, q, lt in items]
    return CartSnapshot(cart_id=uuid4(), platform=CommercePlatform.BLINKIT, items=rows, item_count=len(rows), observed_at=datetime.now(timezone.utc))


async def test_adds_only_missing_packs() -> None:
    adapter = RecordingAdapter()
    milk = cand("Amul Taaza Toned Milk", "1 L", "56")
    result = await CM.ensure_quantity(adapter, ProductSelection(milk, 2), None, snap(("Amul Taaza Toned Milk", "1 ltr", 1, "56")))  # type: ignore[arg-type]
    assert adapter.added == [1] and result.before_quantity == 1


async def test_nothing_is_added_when_already_satisfied() -> None:
    adapter = RecordingAdapter()
    milk = cand("Amul Taaza Toned Milk", "1 L", "56")
    milk.in_cart_quantity = 2
    result = await CM.ensure_quantity(adapter, ProductSelection(milk, 2), None, None)  # type: ignore[arg-type]
    assert adapter.added == [] and result.success and result.added_packs == 0 and "nothing added" in result.message


def test_cart_price_changes_are_detected_from_observed_prices() -> None:
    milk = cand("Amul Taaza Toned Milk", "1 L", "56")
    changes = CM.price_changes({"m": milk}, snap(("Amul Taaza Toned Milk", "1 ltr", 2, "120")))
    assert len(changes) == 1 and changes[0].current == Decimal("60.00") and changes[0].significant
    assert CM.price_changes({"m": milk}, snap(("Amul Taaza Toned Milk", "1 ltr", 2, "112"))) == []
    assert CM.price_changes({"m": milk}, snap(("Amul Taaza Toned Milk", "1 ltr", 2, None))) == []  # unknown -> no claim
