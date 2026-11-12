"""Deterministic product matching.

Scores observed candidates against a requirement — the LLM never sets a score.

    overall = 0.25·brand + 0.35·name + 0.25·quantity + 0.15·variant

Hard constraints disqualify a candidate (score capped at 0.4): a mandatory brand
that differs, a contradicted variant/spec, a size that cannot make the requested
quantity exactly, a price above the budget, or the product being unavailable.

Decision:
- no viable candidate ≥ ACCEPTABLE            -> NOT_FOUND (or UNAVAILABLE)
- two different products within the margin     -> AMBIGUOUS (ask the user)
- exact match ≥ EXACT                          -> SELECTED
- otherwise                                    -> NEEDS_CONFIRMATION (ask the user)
Same product in different pack sizes is not ambiguous: the fewest packs win.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.commerce.matching.similarity import (
    coverage,
    family_key,
    packs_for,
    parse_measure,
    requirement_measure,
    tokens,
)
from app.commerce.matching.variant_matcher import check_variant
from app.schemas.product import (
    MatchDecision,
    MatchResult,
    ProductAvailability,
    ProductCandidate,
    ProductMatch,
    ProductRequirement,
    ProductUnit,
)

W_BRAND, W_NAME, W_QTY, W_VARIANT = 0.25, 0.35, 0.25, 0.15
DISQUALIFIED_CAP = 0.4


@dataclass(frozen=True)
class MatchThresholds:
    exact: float = 0.92
    acceptable: float = 0.80
    margin: float = 0.05
    max_packs: int = 6


class ProductMatcher:
    def __init__(self, thresholds: MatchThresholds | None = None) -> None:
        self.t = thresholds or MatchThresholds()

    # ---------------------------------------------------------------- scoring

    def score(self, req: ProductRequirement, cand: ProductCandidate) -> ProductMatch:
        reasons: list[str] = []
        disqualified = False
        cand_words = tokens(cand.product_name) | tokens(cand.brand) | tokens(" ".join(cand.variant.values()))

        # brand
        if req.brand:
            brand_words = tokens(req.brand)
            brand_score = 1.0 if brand_words and brand_words <= cand_words else 0.0
            if brand_score == 0.0:
                reasons.append(f"brand is not {req.brand}")
                if req.must_match_brand:
                    disqualified = True
        else:
            brand_score = 1.0

        # name (product words + requested model), brand words excluded
        wanted = tokens(req.product_name) | tokens(req.model) | tokens(req.category)
        wanted -= tokens(req.brand)
        name_score = round(coverage(wanted, cand_words), 3)
        if name_score < 1.0:
            reasons.append("name differs")

        # quantity
        packs: int | None = None
        requested = requirement_measure(req)
        offered = parse_measure(cand.pack_size, cand.product_name)
        if requested is None:
            packs = max(1, int(req.quantity)) if req.unit in (ProductUnit.PACK, ProductUnit.UNKNOWN) else None
            quantity_score = 0.9 if packs else 0.5
        elif offered is None:
            quantity_score = 0.5
            reasons.append("pack size not shown")
        else:
            packs = packs_for(requested, offered, self.t.max_packs)
            if packs is None:
                quantity_score = 0.0
                disqualified = True
                reasons.append(f"{offered.describe()} cannot make exactly {requested.describe()}")
            else:
                # Fewer packs is better; the total is identical either way.
                quantity_score = 1.0 if packs == 1 else max(0.9 - 0.01 * (packs - 2), 0.85)
                if packs > 1:
                    reasons.append(f"{packs} × {offered.describe()} = {requested.describe()}")

        # variant / specs
        variant = check_variant(req.required_specs, req.preferred_variant, cand.product_name, cand.variant)
        if variant.contradicted:
            disqualified = True
            reasons.extend(variant.contradicted)
        if variant.unverified:
            reasons.append("could not verify " + ", ".join(variant.unverified))

        # budget and availability
        if req.max_price is not None:
            if cand.normalized_price is None:
                reasons.append("price not shown")
            elif cand.normalized_price > req.max_price:
                disqualified = True
                reasons.append(f"price ₹{cand.normalized_price} is above the ₹{req.max_price} budget")
        if cand.availability == ProductAvailability.UNAVAILABLE:
            disqualified = True
            reasons.append("currently unavailable")

        overall = W_BRAND * brand_score + W_NAME * name_score + W_QTY * quantity_score + W_VARIANT * variant.score
        if disqualified:
            overall = min(overall, DISQUALIFIED_CAP)
        overall = round(overall, 3)
        exact = (
            not disqualified
            and brand_score == 1.0
            and name_score == 1.0
            and quantity_score >= 0.85
            and variant.score == 1.0
            and (req.max_price is None or cand.normalized_price is not None)
        )
        explanation = "Exact match" if exact and not reasons else "; ".join(reasons) or "Partial match"
        if exact and reasons:
            explanation = "Exact match — " + "; ".join(reasons)
        return ProductMatch(
            requirement_id=req.product_id,
            candidate_id=cand.candidate_id,
            brand_score=brand_score,
            name_score=name_score,
            quantity_score=round(quantity_score, 3),
            variant_score=variant.score,
            overall_score=overall,
            exact_match=exact,
            explanation=explanation[:300],
            needs_user_confirmation=not exact,
            packs_needed=packs,
            disqualified=disqualified,
        )

    # ---------------------------------------------------------------- decision

    def match(self, req: ProductRequirement, candidates: list[ProductCandidate]) -> MatchResult:
        by_id = {c.candidate_id: c for c in candidates}
        ranked = sorted((self.score(req, c) for c in candidates), key=lambda m: (-m.overall_score, m.packs_needed or 99))
        viable = [m for m in ranked if not m.disqualified]

        if not viable or viable[0].overall_score < self.t.acceptable:
            unavailable = [
                m for m in ranked
                if by_id[m.candidate_id].availability == ProductAvailability.UNAVAILABLE
                and m.brand_score == 1.0 and m.name_score == 1.0
            ]
            if unavailable and not viable:
                return MatchResult(requirement_id=req.product_id, decision=MatchDecision.UNAVAILABLE, ranked=ranked,
                                   message=f"{req.label()} is shown but currently unavailable.")
            return MatchResult(requirement_id=req.product_id, decision=MatchDecision.NOT_FOUND, ranked=ranked,
                               message=f"No suitable match found for {req.label()}.")

        best = viable[0]
        rivals = [
            m for m in viable[1:]
            if m.overall_score >= self.t.acceptable
            and best.overall_score - m.overall_score < self.t.margin
            and not self._same_product_other_pack(by_id[best.candidate_id], by_id[m.candidate_id], best, m)
        ]
        if rivals:
            return MatchResult(
                requirement_id=req.product_id, decision=MatchDecision.AMBIGUOUS, ranked=ranked,
                message=f"{len(rivals) + 1} products match {req.label()} equally well — please choose one.",
            )
        if best.exact_match and best.overall_score >= self.t.exact:
            return MatchResult(requirement_id=req.product_id, decision=MatchDecision.SELECTED, selected=best,
                               ranked=ranked, message=f"Selected {by_id[best.candidate_id].product_name}.")
        return MatchResult(
            requirement_id=req.product_id, decision=MatchDecision.NEEDS_CONFIRMATION, selected=best, ranked=ranked,
            message=f"Closest match for {req.label()} needs your confirmation: {best.explanation}.",
        )

    @staticmethod
    def _same_product_other_pack(a: ProductCandidate, b: ProductCandidate, ma: ProductMatch, mb: ProductMatch) -> bool:
        """Same product line in a different pack size (the better-ranked one has fewer packs)."""
        same_family = family_key(a.product_name) == family_key(b.product_name) and (a.brand or "") == (b.brand or "")
        different_pack = (a.pack_size or "") != (b.pack_size or "") or ma.packs_needed != mb.packs_needed
        return same_family and different_pack
