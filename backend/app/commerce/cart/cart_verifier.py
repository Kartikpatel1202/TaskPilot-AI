"""Independent cart verification: requested items vs. the cart actually observed.

VERIFIED only when every requested item is present with the right brand/variant and
exactly the requested quantity. Missing items give PARTIAL (when others are fine);
any wrong variant or quantity gives MISMATCH. Nothing is silently corrected.
"""

from __future__ import annotations

from decimal import Decimal
from uuid import UUID

from app.commerce.matching.product_matcher import ProductMatcher
from app.commerce.matching.similarity import parse_measure, requirement_measure
from app.schemas.cart import CartItem, CartItemCheck, CartSnapshot, CartVerificationReport, CartVerificationStatus
from app.schemas.commerce import RequirementProgress, RequirementStatus
from app.schemas.common import utc_now
from app.schemas.product import ProductAvailability, ProductCandidate, ProductUnit


def _as_candidate(item: CartItem, platform: str) -> ProductCandidate:
    return ProductCandidate(
        candidate_id=item.item_id, platform=platform, product_name=item.product_name, brand=item.brand,  # type: ignore[arg-type]
        variant=item.variant, pack_size=item.pack_size, availability=item.availability, observed_at=item.observed_at,
        source_page="cart", extraction_confidence=1.0,
    )


class CartVerifier:
    def __init__(self, matcher: ProductMatcher) -> None:
        self._matcher = matcher

    def verify(self, task_id: UUID, progress: list[RequirementProgress], snapshot: CartSnapshot) -> CartVerificationReport:
        checks: list[CartItemCheck] = []
        used: set[UUID] = set()
        for entry in progress:
            req = entry.requirement
            label = req.label()
            # Every requirement is checked against the cart, even ones that failed (an earlier run may have added them).
            scored = []
            for item in snapshot.items:
                m = self._matcher.score(req, _as_candidate(item, snapshot.platform.value))
                scored.append((m, item))
            # Items of the right product (brand + name), regardless of size.
            relevant = [(m, i) for m, i in scored if m.brand_score == 1.0 and m.name_score >= 0.99]
            correct = [(m, i) for m, i in relevant if not _variant_wrong(m)]
            if not relevant:
                status = "UNAVAILABLE" if entry.status == RequirementStatus.UNAVAILABLE else "SKIPPED" if entry.status == RequirementStatus.SKIPPED else "MISSING"
                checks.append(CartItemCheck(requirement_id=req.product_id, label=label, status=status, requested=label,
                                            message=f"{label} is not in the cart." + (" It was unavailable." if status == "UNAVAILABLE" else "")))
                continue
            if not correct:
                m, item = relevant[0]
                used.add(item.item_id)
                checks.append(CartItemCheck(requirement_id=req.product_id, label=label, status="VARIANT_MISMATCH", requested=label,
                                            observed=f"{item.product_name} {item.pack_size or ''}".strip(), observed_item_id=item.item_id,
                                            message=f"Cart has {item.product_name} — {m.explanation}."))
                continue
            for _, item in correct:
                used.add(item.item_id)
            observed_amount, observed_text = _total(correct, req.unit)
            requested_amount = _requested(req)
            ok = observed_amount is not None and requested_amount is not None and observed_amount == requested_amount
            first = correct[0][1]
            checks.append(CartItemCheck(
                requirement_id=req.product_id, label=label, status="OK" if ok else "QUANTITY_MISMATCH",
                requested=label, observed=observed_text, observed_item_id=first.item_id,
                message=f"{label}: in cart {observed_text}." if ok else f"{label}: requested {_fmt(requested_amount, req.unit)}, cart has {observed_text}.",
            ))

        missing = [c.label for c in checks if c.status in ("MISSING", "UNAVAILABLE", "SKIPPED")]
        mismatched = [f"{c.label} ({c.status.replace('_', ' ').lower()})" for c in checks if c.status in ("VARIANT_MISMATCH", "QUANTITY_MISMATCH")]
        ok_count = sum(1 for c in checks if c.status == "OK")
        if not checks:
            status = CartVerificationStatus.UNVERIFIED
        elif mismatched:
            status = CartVerificationStatus.MISMATCH
        elif missing:
            status = CartVerificationStatus.PARTIAL if ok_count else CartVerificationStatus.MISMATCH
        else:
            status = CartVerificationStatus.VERIFIED

        warnings: list[str] = []
        others = [i for i in snapshot.items if i.item_id not in used]
        if others:
            warnings.append(f"{len(others)} other item(s) already in the cart were left unchanged: " + ", ".join(i.product_name[:40] for i in others[:5]))
        unavailable = [i.product_name for i in snapshot.items if i.availability == ProductAvailability.UNAVAILABLE]
        if unavailable:
            warnings.append("Unavailable in cart: " + ", ".join(unavailable[:5]))
        computed = None
        if snapshot.items and all(i.line_total is not None for i in snapshot.items):
            computed = sum((i.line_total for i in snapshot.items if i.line_total is not None), Decimal("0.00"))
            if snapshot.subtotal is not None and computed != snapshot.subtotal:
                warnings.append(f"Item prices add up to ₹{computed} but the cart shows a subtotal of ₹{snapshot.subtotal}.")
        if snapshot.total is None:
            warnings.append("The cart's final total was not shown; fees and taxes are unknown until checkout.")
        return CartVerificationReport(
            task_id=task_id, cart_id=snapshot.cart_id, status=status, requested_items=[p.requirement for p in progress],
            observed_items=snapshot.items, checks=checks, missing_items=missing, mismatched_items=mismatched,
            warnings=warnings, computed_subtotal=computed, verified_at=utc_now(),
        )


def _variant_wrong(m: object) -> bool:
    return getattr(m, "variant_score", 1.0) == 0.0


def _requested(req: object) -> Decimal | None:
    measure = requirement_measure(req)  # type: ignore[arg-type]
    if measure is not None:
        return measure.amount
    return Decimal(str(getattr(req, "quantity", 0)))


def _total(items: list[tuple[object, CartItem]], unit: ProductUnit) -> tuple[Decimal | None, str]:
    measured = unit not in (ProductUnit.PACK, ProductUnit.UNKNOWN)
    total = Decimal(0)
    parts: list[str] = []
    for _, item in items:
        qty = Decimal(str(item.quantity))
        if measured:
            m = parse_measure(item.pack_size, item.product_name)
            if m is None:
                return None, f"{item.quantity:g} × {item.pack_size or 'unknown size'}"
            total += qty * m.amount
        else:
            total += qty
        parts.append(f"{item.quantity:g} × {item.pack_size or item.product_name[:30]}")
    return total, " + ".join(parts)


def _fmt(amount: Decimal | None, unit: ProductUnit) -> str:
    if amount is None:
        return "unknown"
    if unit in (ProductUnit.LITER, ProductUnit.MILLILITER):
        return f"{format((amount / 1000).normalize(), 'f')} L" if amount >= 1000 else f"{format(amount.normalize(), 'f')} ml"
    if unit in (ProductUnit.KILOGRAM, ProductUnit.GRAM):
        return f"{format((amount / 1000).normalize(), 'f')} kg" if amount >= 1000 else f"{format(amount.normalize(), 'f')} g"
    if unit in (ProductUnit.PIECE, ProductUnit.DOZEN):
        return f"{format(amount.normalize(), 'f')} pcs"
    return f"{format(amount.normalize(), 'f')} pack(s)"
