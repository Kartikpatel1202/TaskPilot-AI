"""Existing-cart reconciliation: add only the missing quantity, never duplicates."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from app.commerce.cart.quantity_manager import existing_packs, packs_to_add, resolve_existing, same_product
from app.schemas.cart import CartItem, CartSnapshot
from app.schemas.product import CommercePlatform, ProductAvailability, ProductUnit

from .conftest import cand


def item(name: str, size: str, qty: float) -> CartItem:
    return CartItem(item_id=uuid4(), product_name=name, pack_size=size, quantity=qty, unit=ProductUnit.PACK,
                    availability=ProductAvailability.AVAILABLE, observed_at=datetime.now(timezone.utc))


def snap(*items: CartItem) -> CartSnapshot:
    return CartSnapshot(cart_id=uuid4(), platform=CommercePlatform.BLINKIT, items=list(items), item_count=len(items),
                        observed_at=datetime.now(timezone.utc))


def test_same_product_requires_same_line_and_size() -> None:
    assert same_product("Amul Taaza Toned Milk", "1 ltr", "Amul Taaza Toned Milk", "1 L")
    assert not same_product("Amul Taaza Toned Milk", "500 ml", "Amul Taaza Toned Milk", "1 L")
    assert not same_product("Amul Gold Milk", "1 L", "Amul Taaza Toned Milk", "1 L")


def test_only_the_missing_quantity_is_added() -> None:
    cart = snap(item("Amul Taaza Toned Milk", "1 ltr", 1), item("Britannia Bread", "400 g", 2))
    milk = cand("Amul Taaza Toned Milk", "1 L", "56")
    assert existing_packs(cart, milk) == 1
    assert packs_to_add(2, existing_packs(cart, milk) or 0) == 1  # "already one litre, add one more"
    assert packs_to_add(2, 3) == 0  # never removes, never duplicates
    assert packs_to_add(2, 0) == 2


def test_unrelated_and_other_size_items_are_ignored() -> None:
    cart = snap(item("Amul Taaza Toned Milk", "500 ml", 4), item("Shimla Apple", "1 kg", 1))
    assert existing_packs(cart, cand("Amul Taaza Toned Milk", "1 L", "56")) == 0


def test_live_card_quantity_wins_over_old_snapshot() -> None:
    c = cand("Amul Taaza Toned Milk", "1 L", "56")
    c.in_cart_quantity = 2
    assert resolve_existing(c, snap(item("Amul Taaza Toned Milk", "1 L", 1))) == 2
    assert existing_packs(None, c) is None
