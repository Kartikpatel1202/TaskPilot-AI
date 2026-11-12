"""Raw, observed search-result rows -> ProductCandidate. Nothing is invented: a field that
was not read from the page stays None, and confidence reflects how much was observed."""

from __future__ import annotations

import re
from typing import Any
from uuid import uuid4

from app.commerce.money import parse_inr
from app.commerce.matching.variant_matcher import extract_specs
from app.core.logging import redact_text
from app.schemas.common import utc_now
from app.schemas.product import CommercePlatform, ProductAvailability, ProductCandidate

_REF_OK = re.compile(r"^k-\d{1,7}$")


def _clean(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = redact_text(" ".join(str(value).split()))[:limit]
    return text or None


def to_candidate(raw: dict[str, Any], platform: CommercePlatform, source_page: str) -> ProductCandidate | None:
    name = _clean(raw.get("name"))
    if not name:
        return None
    price_text = _clean(raw.get("price"), 40)
    availability = (
        ProductAvailability.UNAVAILABLE if raw.get("unavailable")
        else ProductAvailability.AVAILABLE if raw.get("can_add") or price_text
        else ProductAvailability.UNKNOWN
    )
    variant = {k: v for k, v in extract_specs(name, raw.get("specs_text")).items()}
    if platform == CommercePlatform.BLINKIT:
        variant.pop("COLOR", None)  # "White Bread" is a product type, not a colour option
    for key, value in (raw.get("specs") or {}).items():
        if _clean(key, 40) and _clean(value, 80):
            variant[_clean(key, 40) or key] = _clean(value, 80) or value
    observed = sum(1 for f in ("name", "price", "size") if raw.get(f)) + (1 if raw.get("can_add") or raw.get("unavailable") else 0)
    ref = raw.get("ref") if isinstance(raw.get("ref"), str) and _REF_OK.match(raw["ref"]) else None
    qty = raw.get("in_cart")
    return ProductCandidate(
        candidate_id=uuid4(),
        platform=platform,
        product_name=name,
        brand=_clean(raw.get("brand"), 60),
        variant=variant,
        pack_size=_clean(raw.get("size"), 60),
        displayed_price=price_text,
        normalized_price=parse_inr(price_text),
        list_price=parse_inr(_clean(raw.get("mrp"), 40)),
        availability=availability,
        seller=_clean(raw.get("seller"), 120),
        rating=_clean(raw.get("rating"), 40),
        review_count=_clean(raw.get("reviews"), 40),
        delivery_estimate=_clean(raw.get("delivery"), 120),
        product_url=raw.get("url") if isinstance(raw.get("url"), str) and raw["url"].startswith(("http://", "https://")) else None,
        image_url=raw.get("image") if isinstance(raw.get("image"), str) and raw["image"].startswith("https://") else None,
        in_cart_quantity=int(qty) if isinstance(qty, (int, float)) and qty >= 0 else None,
        observed_at=utc_now(),
        source_page=source_page,
        extraction_confidence=round(min(1.0, observed / 4), 2),
        dom_ref=ref,
    )


def to_candidates(rows: list[dict[str, Any]], platform: CommercePlatform, source_page: str, limit: int) -> list[ProductCandidate]:
    out: list[ProductCandidate] = []
    for raw in rows[: max(1, limit)]:
        cand = to_candidate(raw, platform, source_page)
        if cand is not None:
            out.append(cand)
    return out
