"""Reads the live cart through the platform adapter (never a cached or invented cart)."""

from __future__ import annotations

from app.commerce.base import CommerceAdapter, CommerceContext
from app.schemas.cart import CartSnapshot


async def inspect(adapter: CommerceAdapter, ctx: CommerceContext) -> CartSnapshot:
    return await adapter.inspect_cart(ctx)
