"""Exact-order purchase approval, built on the existing ApprovalService/Coordinator.

The approval carries the full observed order (items, quantities, totals, masked
address, payment method) and a fingerprint (`summary_hash`) of exactly that
summary. Any later change makes it stale (see purchase_policy).
"""

from __future__ import annotations

from app.commerce.money import format_inr
from app.schemas.checkout import CheckoutSummary
from app.schemas.purchase import PurchaseApprovalDetails, PurchaseApprovalItem


def approval_details(summary: CheckoutSummary) -> PurchaseApprovalDetails:
    if summary.final_total is None:
        raise ValueError("A purchase approval needs an observed final total.")
    return PurchaseApprovalDetails(
        platform=summary.platform,
        checkout_id=summary.checkout_id,
        cart_id=summary.cart_id,
        summary_hash=summary.summary_hash,
        summary_version=summary.version,
        items=[
            PurchaseApprovalItem(
                name=i.product_name[:300],
                quantity=(f"{i.quantity:g} × {i.pack_size}" if i.pack_size else f"{i.quantity:g}")[:60],
                line_total=i.line_total,
            )
            for i in summary.items
        ],
        subtotal=summary.subtotal,
        delivery_fee=summary.delivery_fee,
        handling_fee=summary.handling_fee,
        tax=summary.tax,
        discount=summary.discount,
        final_total=summary.final_total,
        currency=summary.currency,
        masked_delivery_address=summary.masked_delivery_address,
        delivery_slot=summary.delivery_slot,
        payment_method=summary.payment_method,
        warnings=list(summary.warnings),
    )


def approval_text(summary: CheckoutSummary, site_name: str) -> tuple[str, str, str]:
    """(action_summary, reason, estimated_impact) for the generic approval fields."""
    items = ", ".join(f"{i.product_name[:40]} ×{i.quantity:g}" for i in summary.items)[:300]
    action = f"Place this exact {summary.payment_method.value} order on {site_name}: {format_inr(summary.final_total)}"
    reason = "Confirm this exact order. It may place a real order on the website. Any change will require a new approval."
    impact = f"Items: {items}. Total {format_inr(summary.final_total)}. Payment: {summary.payment_method.value}."
    return action[:500], reason, impact[:1000]
