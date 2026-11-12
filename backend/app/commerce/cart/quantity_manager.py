"""Existing-cart reconciliation: add only what is missing, never duplicate.

Before adding, the observed cart quantity of the *same* product (same product line and
pack size) is compared with the packs needed; only the difference is added. Unrelated
items and other pack sizes are never touched.
"""

from __future__ import annotations

from app.commerce.matching.similarity import family_key, parse_measure
from app.schemas.cart import CartSnapshot
from app.schemas.product import ProductCandidate


def same_product(name_a: str, size_a: str | None, name_b: str, size_b: str | None) -> bool:
    if family_key(name_a) != family_key(name_b):
        return False
    ma, mb = parse_measure(size_a, name_a), parse_measure(size_b, name_b)
    if ma is None or mb is None:
        return (size_a or "").strip().lower() == (size_b or "").strip().lower()
    return ma.base == mb.base and ma.amount == mb.amount


def existing_packs(snapshot: CartSnapshot | None, candidate: ProductCandidate) -> int | None:
    """Packs of this exact product already in the observed cart (None when no cart was observed)."""
    if snapshot is None:
        return None
    return int(sum(i.quantity for i in snapshot.items if same_product(i.product_name, i.pack_size, candidate.product_name, candidate.pack_size)))


def packs_to_add(required: int, existing: int) -> int:
    return max(0, required - max(0, existing))


def resolve_existing(candidate: ProductCandidate, snapshot: CartSnapshot | None) -> int:
    """Prefer what the product card itself shows (live), else the last observed cart."""
    if candidate.in_cart_quantity is not None:
        return candidate.in_cart_quantity
    return existing_packs(snapshot, candidate) or 0
