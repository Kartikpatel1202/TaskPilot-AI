"""Deterministic commerce planning.

The LLM (or the offline mock) classifies the request and extracts product entities;
this trusted code turns them into typed `ProductRequirement`s and a fixed sequence of
`commerce` steps for the validated site. No step here comes from model text.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.agent.policies.approval_policy import apply_risk_and_approvals
from app.commerce.base import SiteBinding
from app.core.persona import Language
from app.schemas.approval import RiskLevel
from app.schemas.commerce import CommerceAction, PaymentPreference
from app.schemas.common import utc_now
from app.schemas.intent import IntentClassification, IntentType, ProductEntity
from app.schemas.plan import ClarificationExchange, PlannedAction, PlanStatus, TaskPlan
from app.schemas.product import ProductRequirement, ProductUnit

COMMERCE_INTENTS = frozenset({
    IntentType.ECOMMERCE_SEARCH, IntentType.ECOMMERCE_SHOPPING, IntentType.ECOMMERCE_CART_REVIEW,
    IntentType.ECOMMERCE_CHECKOUT_REVIEW, IntentType.ECOMMERCE_PURCHASE,
})

_UNITS = {
    "litre": ProductUnit.LITER, "liter": ProductUnit.LITER, "l": ProductUnit.LITER, "ltr": ProductUnit.LITER,
    "ml": ProductUnit.MILLILITER, "kg": ProductUnit.KILOGRAM, "kilo": ProductUnit.KILOGRAM, "g": ProductUnit.GRAM,
    "gm": ProductUnit.GRAM, "gram": ProductUnit.GRAM, "packet": ProductUnit.PACK, "pack": ProductUnit.PACK,
    "bottle": ProductUnit.PACK, "piece": ProductUnit.PIECE, "pcs": ProductUnit.PIECE, "dozen": ProductUnit.DOZEN,
}


def _say(lang: str, en: str, hinglish: str, hi: str) -> str:
    return {"hinglish": hinglish, "hi": hi}.get(lang, en)


def requirement_from(entity: ProductEntity) -> tuple[ProductRequirement, list[str]]:
    """Typed requirement from an extracted entity. Missing details are noted, never invented."""
    notes: list[str] = []
    unit = _UNITS.get((entity.unit or "").lower().rstrip("s"), ProductUnit.UNKNOWN)
    quantity = float(entity.quantity) if entity.quantity else 1.0
    if entity.quantity is None:
        unit = ProductUnit.PACK if entity.category is None else ProductUnit.UNKNOWN
        notes.append(f"No quantity given for {entity.name} — 1 {'pack' if unit == ProductUnit.PACK else 'unit'} will be added; change it before running if needed.")
    if unit == ProductUnit.DOZEN:
        quantity, unit = quantity * 12, ProductUnit.PIECE
    specs: dict[str, str] = {}
    for spec in entity.specs:
        m = re.match(r"(\d+)\s*(GB|TB)\s*(RAM|SSD|HDD|STORAGE|ROM)", spec.upper())
        if m:
            specs["RAM" if m.group(3) == "RAM" else "STORAGE"] = f"{m.group(1)}{m.group(2)}"
    # Search by brand/variant/name: the pack size is matched deterministically, so every size stays visible.
    query_parts = [entity.brand or "", entity.variant or "", entity.name]
    if specs:
        query_parts.extend(f"{v} {k if k == 'RAM' else 'SSD'}" for k, v in specs.items())
    query = " ".join(p for p in query_parts if p).strip()
    req = ProductRequirement(
        product_id=uuid4(),
        query=query[:200] or entity.name,
        product_name=entity.name,
        brand=entity.brand,
        quantity=quantity,
        unit=unit,
        preferred_variant={"line": entity.variant} if entity.variant else {},
        must_match_brand=bool(entity.brand),
        allow_substitute=False,
        category=entity.category,
        max_price=Decimal(str(int(entity.max_price))) if entity.max_price else None,
        required_specs=specs,
        notes=notes,
    )
    return req, notes


class CommercePlanner:
    def __init__(self, max_products: int) -> None:
        self._max_products = max_products

    def build(
        self, *, task_id: UUID, session_id: UUID, classification: IntentClassification, binding: SiteBinding,
        provider: str, model: str, history: list[ClarificationExchange],
    ) -> TaskPlan:
        lang: Language = classification.language
        entities = classification.entities
        intent = classification.intent
        actions = {a.lower() for a in entities.requested_actions}
        wants_order = intent == IntentType.ECOMMERCE_PURCHASE or "place_order" in actions or "payment" in actions
        payment: PaymentPreference | None = None
        pref = (entities.payment_preference or "").upper()
        if pref == "COD":
            payment = "COD"
        elif pref in ("PREPAID", "UPI", "CARD", "NET_BANKING", "WALLET"):
            payment = "PREPAID"

        requirements: list[ProductRequirement] = []
        assumptions: list[str] = []
        for entity in entities.products[: self._max_products]:
            req, notes = requirement_from(entity)
            requirements.append(req)
            assumptions.extend(notes)
        if len(entities.products) > self._max_products:
            assumptions.append(f"Only the first {self._max_products} products are planned.")

        steps: list[PlannedAction] = []

        def add(op: str, description: str, outcome: str, *, req: ProductRequirement | None = None, deps: list[PlannedAction] | None = None,
                cont: bool = False) -> PlannedAction:
            action = CommerceAction(type="commerce", operation=op, platform=binding.platform, site_key=binding.key,  # type: ignore[arg-type]
                                    requirement=req, payment_preference=payment if op == "place_order" else None, continue_on_failure=cont)
            step = PlannedAction(step_id=uuid4(), order=len(steps) + 1, action=action, description=description[:300],
                                 expected_outcome=outcome[:300], risk_level=RiskLevel.LOW, depends_on=[d.step_id for d in deps or []])
            steps.append(step)
            return step

        open_step = add("open_store", f"Open {binding.name}; check sign-in, location and the existing cart.",
                        f"{binding.name} is ready (or you are asked to act yourself).")
        search_only = intent == IntentType.ECOMMERCE_SEARCH
        review_only = intent in (IntentType.ECOMMERCE_CART_REVIEW, IntentType.ECOMMERCE_CHECKOUT_REVIEW) and not wants_order
        if search_only:
            for req in requirements or []:
                add("search_products", f"Search {binding.name} for {req.label()} and compare real listings.",
                    "Matching listings are shown; nothing is added to the cart.", req=req, deps=[open_step], cont=True)
        elif not review_only:
            for req in requirements:
                add("search_and_add", f"Find {req.label()}, match brand/variant/size, add only the missing quantity.",
                    f"{req.label()} is in the cart (verified on the page).", req=req, deps=[open_step], cont=True)
        verify = None
        if not search_only:
            verify = add("verify_cart", "Read the real cart and verify every item, quantity and price.",
                         "Cart verified — or exact differences reported.", deps=[open_step])
        checkout = None
        if verify is not None and (wants_order or intent == IntentType.ECOMMERCE_CHECKOUT_REVIEW):
            checkout = add("checkout_review", "Open checkout and read the exact items, fees, total, address and payment options.",
                           "Checkout summary is ready. Nothing is purchased.", deps=[verify])
        if checkout is not None and wants_order:
            how = "cash on delivery" if payment == "COD" else "your chosen payment method"
            add("place_order", f"Final exact-order approval, then {'place the COD order once' if payment == 'COD' else 'hand payment over to you'}.",
                f"Order placed only after your explicit approval ({how}); prepaid payments are always completed by you.", deps=[checkout])
        steps = apply_risk_and_approvals(steps)

        labels = ", ".join(r.label() for r in requirements) or "your cart"
        site = binding.name
        if search_only:
            msg = _say(lang, f"Sure! I'll search {site} for {labels}, compare the real listings and show you the matches. Nothing gets bought.",
                       f"Haan bhai! {site} pe {labels} dhundh ke real listings compare karunga aur matching options dikhaunga. Kuch khareeda nahi jayega.",
                       f"ज़रूर! {site} पर {labels} खोजकर असली लिस्टिंग की तुलना करूँगा और मिलते विकल्प दिखाऊँगा। कुछ खरीदा नहीं जाएगा।")
            summary = f"Search {site} for {labels}."
        elif wants_order:
            msg = _say(lang, f"Got it! I'll prepare {labels} on {site}, verify the cart and checkout, and ask for your final approval of the exact order. "
                             "Prepaid payments stay with you.",
                       f"Haan bhai! {site} par {labels} cart mein verify karke checkout review karunga, phir exact order ki final approval tumse lunga. "
                       "Prepaid payment tum khud karoge.",
                       f"ठीक है! {site} पर {labels} कार्ट में जोड़कर जाँचूँगा, चेकआउट दिखाऊँगा और सटीक ऑर्डर की अंतिम मंज़ूरी लूँगा। प्रीपेड भुगतान आप स्वयं करेंगे।")
            summary = f"Prepare {labels} on {site} and request final approval to order."
        elif review_only:
            msg = _say(lang, f"Sure! I'll open {site} and read your actual cart{' and checkout' if checkout else ''}. Nothing gets bought.",
                       f"Haan bhai! {site} kholke tumhara asli cart{' aur checkout' if checkout else ''} padh ke dikhaunga. Kuch khareeda nahi jayega.",
                       f"ज़रूर! {site} खोलकर आपका असली कार्ट{' और चेकआउट' if checkout else ''} पढ़कर दिखाऊँगा। कुछ खरीदा नहीं जाएगा।")
            summary = f"Review the cart on {site}."
        else:
            msg = _say(lang, f"Haan! I'll search {site} for {labels}, match the exact products and verify the cart before adding anything more. "
                             "No order will be placed.",
                       f"Haan bhai! {site} par {labels} search karke matching options verify karunga. Cart mein add karne se pehle product details check kar lenge. "
                       "Order place nahi hoga.",
                       f"हाँ! {site} पर {labels} खोजकर सही उत्पाद मिलाऊँगा और कार्ट जाँचूँगा। कोई ऑर्डर नहीं होगा।")
            summary = f"Prepare a {site} cart with {labels}."
        if binding.is_fixture:
            assumptions.append("This is a LOCAL TEST FIXTURE site — not the real website; no real products or orders.")
        return TaskPlan(
            plan_id=uuid4(), task_id=task_id, session_id=session_id, status=PlanStatus.READY, intent=intent,
            summary=summary[:300], user_facing_message=msg, language=lang, target_website=classification.target_website,
            confidence=classification.confidence, assumptions=assumptions[:10], clarification_history=list(history),
            steps=steps, requires_human_approval=any(s.requires_approval for s in steps), provider=provider, model=model,
            is_mock=provider == "mock", created_at=utc_now(),
        )


def requirement_summary(plan: TaskPlan) -> list[dict[str, Any]]:
    return [s.action.requirement.model_dump(mode="json") for s in plan.steps
            if getattr(s.action, "type", None) == "commerce" and s.action.requirement is not None]  # type: ignore[union-attr]
