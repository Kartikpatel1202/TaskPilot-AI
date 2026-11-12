"""Cart mutations with reconciliation, idempotency and price checks."""

from __future__ import annotations

from app.commerce.base import CommerceAdapter, CommerceContext, ProductSelection
from app.commerce.cart.quantity_manager import packs_to_add, resolve_existing
from app.commerce.policies.price_change_policy import PriceChange, PriceChangePolicy
from app.schemas.cart import CartMutationResult, CartSnapshot
from app.schemas.product import ProductCandidate


class CartManager:
    def __init__(self, price_policy: PriceChangePolicy) -> None:
        self._prices = price_policy

    async def ensure_quantity(
        self, adapter: CommerceAdapter, selection: ProductSelection, ctx: CommerceContext, known_cart: CartSnapshot | None,
    ) -> CartMutationResult:
        """Bring the cart to exactly `packs_needed` of this product — adding only the difference."""
        existing = resolve_existing(selection.candidate, known_cart)
        delta = packs_to_add(selection.packs_needed, existing)
        if delta == 0:
            return CartMutationResult(
                success=True, before_quantity=existing, after_quantity=existing, added_packs=0,
                message=f"{selection.candidate.product_name} already in the cart ({existing}); nothing added.",
            )
        result = await adapter.add_to_cart(selection, delta, ctx)
        if result.before_quantity is None:
            result.before_quantity = existing
        return result

    def price_changes(self, candidates: dict[str, ProductCandidate], cart: CartSnapshot) -> list[PriceChange]:
        """Compare listing prices with the unit prices observed in the cart."""
        changes: list[PriceChange] = []
        from app.commerce.cart.quantity_manager import same_product

        for cand in candidates.values():
            for item in cart.items:
                if not same_product(item.product_name, item.pack_size, cand.product_name, cand.pack_size):
                    continue
                unit = item.unit_price
                if unit is None and item.line_total is not None and item.quantity:
                    from decimal import Decimal

                    unit = (item.line_total / Decimal(str(item.quantity))).quantize(Decimal("0.01"))
                change = self._prices.compare(cand.product_name, cand.normalized_price, unit)
                if change:
                    changes.append(change)
        return changes
