"""Reads the live checkout summary (never estimated) and compares it with the verified cart."""

from __future__ import annotations

from uuid import UUID

from app.commerce.base import CommerceAdapter, CommerceContext
from app.commerce.cart.quantity_manager import same_product
from app.schemas.cart import CartSnapshot
from app.schemas.checkout import CheckoutSummary


async def read_summary(adapter: CommerceAdapter, ctx: CommerceContext, task_id: UUID) -> CheckoutSummary:
    return await adapter.inspect_checkout(ctx, task_id)


def compare_with_cart(summary: CheckoutSummary, cart: CartSnapshot) -> list[str]:
    """Differences between the verified cart and the checkout page (each one must be disclosed)."""
    problems: list[str] = []
    for item in cart.items:
        match = next((s for s in summary.items if same_product(s.product_name, s.pack_size or item.pack_size, item.product_name, item.pack_size)
                      or s.product_name.strip().lower().startswith(item.product_name.strip().lower()[:30])), None)
        if match is None:
            problems.append(f"{item.product_name[:50]} is in the cart but not on the checkout page.")
        elif match.quantity != item.quantity:
            problems.append(f"{item.product_name[:50]}: cart quantity {item.quantity:g}, checkout shows {match.quantity:g}.")
    if len(summary.items) > len(cart.items):
        problems.append("The checkout page lists items that were not in the verified cart.")
    return problems
