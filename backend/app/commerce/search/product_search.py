"""Search orchestration with bounded attempts (COMMERCE_MAX_SEARCH_ATTEMPTS).

An empty result is retried at most `max_attempts` times with a short pause; a CAPTCHA
or access block is never retried (the adapter raises and the run stops).
"""

from __future__ import annotations

import asyncio

from app.commerce.base import CommerceAdapter, CommerceContext
from app.schemas.product import ProductCandidate, ProductRequirement


async def search_with_retries(adapter: CommerceAdapter, req: ProductRequirement, ctx: CommerceContext) -> list[ProductCandidate]:
    candidates: list[ProductCandidate] = []
    for attempt in range(max(1, ctx.max_attempts)):
        if ctx.cancel_event.is_set():
            break
        candidates = await adapter.search_products(req, ctx)
        if candidates:
            break
        if attempt + 1 < ctx.max_attempts:
            await asyncio.sleep(0.5 * (attempt + 1))
    return candidates
