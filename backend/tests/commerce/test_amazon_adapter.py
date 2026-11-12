"""Amazon India adapter against the LOCAL Amazon-like fixture in real Chromium (not amazon.in)."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.browser.manager import BrowserManager
from app.commerce.adapters.amazon_india import AmazonIndiaAdapter
from app.commerce.base import CommerceError, ProductSelection, SessionStatus
from app.commerce.matching.product_matcher import ProductMatcher
from app.schemas.product import CommercePlatform, MatchDecision, ProductAvailability

from ..browser.conftest import RecordingTelemetry
from .conftest import make_ctx, page_eval, req

A = AmazonIndiaAdapter()
LAPTOP = dict(qty=1, unit="UNKNOWN", specs={"RAM": "16GB", "STORAGE": "512GB"}, max_price=60000, query="laptop 16GB RAM 512GB SSD")


async def test_search_extracts_listings_without_inventing_fields(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry)
    assert await A.open_store(ctx) == SessionStatus.READY
    cands = await A.search_products(req("laptop", **LAPTOP), ctx)  # type: ignore[arg-type]
    assert len(cands) == 4
    asus = next(c for c in cands if c.product_name.startswith("ASUS"))
    assert str(asus.normalized_price) == "54990.00" and str(asus.list_price) == "70990.00"
    assert asus.rating == "4.1 out of 5 stars" and asus.review_count == "1,204"
    assert asus.delivery_estimate and asus.product_url and "product.html?asin=FXL0000001" in asus.product_url
    assert asus.variant.get("RAM") == "16GB" and asus.variant.get("STORAGE") == "512GB"
    assert asus.brand is None and asus.seller is None  # not shown on the listing -> not invented


async def test_budget_and_ram_storage_matching(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry)
    requirement = req("laptop", **LAPTOP)  # type: ignore[arg-type]
    cands = await A.search_products(requirement, ctx)
    result = ProductMatcher().match(requirement, cands)
    names = {c.candidate_id: c.product_name for c in cands}
    ok = sorted(names[m.candidate_id].split()[0] for m in result.ranked if not m.disqualified)
    assert ok == ["ASUS", "Acer"]  # HP has 8GB RAM; Lenovo is over budget
    assert result.decision == MatchDecision.AMBIGUOUS  # two equally good laptops -> the user chooses


async def test_ambiguous_phone_models_and_unavailable_listing(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry)
    requirement = req("phone", brand="Samsung", unit="UNKNOWN", query="Samsung phone")
    cands = await A.search_products(requirement, ctx)
    assert len(cands) == 3
    s23 = next(c for c in cands if "S23" in c.product_name)
    assert s23.availability == ProductAvailability.UNAVAILABLE and s23.normalized_price is None
    assert ProductMatcher().match(requirement, cands).decision == MatchDecision.AMBIGUOUS


async def test_add_to_cart_revalidates_product_page_and_quantity(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry)
    requirement = req("mouse", brand="Logitech", qty=2, unit="UNKNOWN", query="Logitech wireless mouse")
    cands = await A.search_products(requirement, ctx)
    m331 = next(c for c in cands if "M331" in c.product_name)
    result = await A.add_to_cart(ProductSelection(m331, 2, requirement), 2, ctx)
    assert result.success and result.before_quantity == 0 and result.after_quantity == 2
    cart = await A.inspect_cart(ctx)
    assert [(i.product_name[:25], i.quantity) for i in cart.items] == [("Logitech M331 Silent Plus", 2.0)]
    assert str(cart.items[0].unit_price) == "1395.00" and str(cart.items[0].line_total) == "2790.00"
    assert str(cart.subtotal) == "2790.00" and cart.total is None and cart.delivery_fee is None  # fees unknown until checkout


async def test_variant_mismatch_on_product_page_is_refused(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry)
    requirement = req("laptop", **LAPTOP)  # type: ignore[arg-type]
    hp = next(c for c in await A.search_products(requirement, ctx) if c.product_name.startswith("HP"))
    result = await A.add_to_cart(ProductSelection(hp, 1, requirement), 1, ctx)
    assert not result.success and result.error_code == "COMMERCE_VARIANT_MISMATCH"
    assert (await A.inspect_cart(ctx)).items == []


async def test_cart_quantity_update_and_seller_on_product_page(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry)
    await page_eval(ctx, "() => localStorage.setItem('fxa:cart', JSON.stringify({FXM0000001: 1, FXP0000001: 1}))")
    cart = await A.inspect_cart(ctx)
    mouse = next(i for i in cart.items if "M331" in i.product_name)
    result = await A.update_quantity(mouse, 3, ctx)
    assert result.success
    assert {i.product_name[:12]: i.quantity for i in result.snapshot.items} == {"Logitech M33": 3.0, "Samsung Gala": 1.0}  # type: ignore[union-attr]
    await A.goto(ctx, ctx.binding.url("product.html?asin=FXP0000001"))
    product = await A._product(ctx)
    assert product["seller"] == "Fixture Appario" and product["specs"]["RAM"] == "6 GB"


async def test_checkout_signin_wall_and_captcha(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry, controls="reset=1&login=0")
    await page_eval(ctx, "() => localStorage.setItem('fxa:cart', JSON.stringify({FXM0000001: 1}))")
    assert await A.open_checkout(ctx) == SessionStatus.LOGIN_REQUIRED
    with pytest.raises(CommerceError) as err:
        await A.inspect_checkout(ctx, uuid4())
    assert err.value.code == "COMMERCE_SESSION_REQUIRED"
    blocked = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry, controls="reset=1&captcha=1")
    assert await A.open_store(blocked) == SessionStatus.BLOCKED


async def test_checkout_summary_and_cod_selection(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.AMAZON_IN, ctelemetry)
    await page_eval(ctx, "() => localStorage.setItem('fxa:cart', JSON.stringify({FXM0000001: 2}))")
    assert await A.open_checkout(ctx) == SessionStatus.READY
    before = await A.inspect_checkout(ctx, uuid4())
    assert str(before.final_total) == "2790.00" and before.masked_delivery_address == "•••, Bengaluru 560•••"
    assert before.delivery_slot == "Arriving 10 Nov 2026"
    from app.schemas.checkout import PaymentMethod

    assert await A.select_payment_method(PaymentMethod.COD, ctx)
    after = await A.inspect_checkout(ctx, uuid4())
    assert after.payment_method == PaymentMethod.COD and after.summary_hash != before.summary_hash  # payment change => new fingerprint
    assert not await A.select_payment_method(PaymentMethod.UPI, ctx)  # prepaid is never selected automatically
