"""Blinkit adapter against the LOCAL Blinkit-like fixture in real Chromium (not blinkit.com)."""

from __future__ import annotations

import pytest

from app.browser.manager import BrowserManager
from app.commerce.adapters.blinkit import BlinkitAdapter
from app.commerce.base import CommerceError, ProductSelection, SessionStatus
from app.commerce.registry import CommerceRegistry, fixture_binding
from app.schemas.product import CommercePlatform, ProductAvailability

from ..browser.conftest import RecordingTelemetry
from .conftest import make_ctx, page_eval, req

B = BlinkitAdapter()


async def test_site_detection_and_ready_session(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry)
    assert await B.open_store(ctx) == SessionStatus.READY
    page = await ctx.controller.page_for(ctx.session_id)
    assert B.detect_page(page.url, ctx.binding)
    registry = CommerceRegistry({}, ["BLINKIT", "AMAZON_IN"])
    registry.register_fixture(fixture_binding(CommercePlatform.BLINKIT, fixture_origin))
    assert registry.binding_for_url(page.url).platform == CommercePlatform.BLINKIT  # type: ignore[union-attr]
    assert registry.binding_for_url("https://www.blinkit.com/s/?q=milk").key == "blinkit"  # type: ignore[union-attr]
    assert registry.binding_for_url("https://blinkit.com.evil.example/") is None  # spoofed domain rejected
    assert registry.binding_for_website("blinkit.fixture.test").is_fixture  # type: ignore[union-attr]


async def test_location_requirement_is_detected_not_invented(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry, controls="reset=1&location=0")
    assert await B.open_store(ctx) == SessionStatus.LOCATION_REQUIRED
    with pytest.raises(CommerceError) as err:
        await B.search_products(req("milk", brand="Amul"), ctx)
    assert err.value.code == "COMMERCE_LOCATION_REQUIRED"


async def test_captcha_stops_without_retrying(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry, controls="reset=1&captcha=1")
    assert await B.open_store(ctx) == SessionStatus.BLOCKED
    with pytest.raises(CommerceError) as err:
        await B.search_products(req("milk"), ctx)
    assert err.value.code == "CAPTCHA_REQUIRED"


async def test_search_reads_delayed_dynamic_cards(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry)
    cands = await B.search_products(req("milk", brand="Amul", query="Amul milk"), ctx)
    names = {(c.product_name, c.pack_size) for c in cands}
    assert ("Amul Taaza Toned Fresh Milk", "1 ltr") in names and ("Amul Gold Full Cream Fresh Milk", "1 ltr") in names
    taaza = next(c for c in cands if c.pack_size == "1 ltr" and "Taaza" in c.product_name)
    assert taaza.displayed_price == "₹56" and str(taaza.list_price) == "58.00"  # struck MRP read separately
    assert taaza.in_cart_quantity == 0 and taaza.availability == ProductAvailability.AVAILABLE
    assert all(c.observed_at and c.source_page.endswith("search.html") for c in cands)


async def test_unavailable_products_and_empty_results(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry)
    found = await B.search_products(req("paneer", brand="Amul", query="Amul paneer"), ctx)
    paneer = next(c for c in found if "Paneer" in c.product_name)
    assert paneer.availability == ProductAvailability.UNAVAILABLE and paneer.in_cart_quantity is None
    assert await B.search_products(req("caviar", query="beluga caviar"), ctx) == []


async def test_add_exact_quantity_then_inspect_cart_and_bill(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry)
    milk = next(c for c in await B.search_products(req("milk", brand="Amul", query="Amul Taaza milk"), ctx)
                if c.pack_size == "1 ltr" and "Taaza" in c.product_name)
    result = await B.add_to_cart(ProductSelection(milk, 2), 2, ctx)
    assert result.success and result.before_quantity == 0 and result.after_quantity == 2
    cart = await B.inspect_cart(ctx)
    assert [(i.product_name, i.pack_size, i.quantity) for i in cart.items] == [("Amul Taaza Toned Fresh Milk", "1 ltr", 2.0)]
    assert str(cart.items[0].line_total) == "112.00" and str(cart.subtotal) == "112.00"
    assert str(cart.delivery_fee) == "25.00" and str(cart.handling_fee) == "4.00" and str(cart.total) == "141.00"
    assert cart.discount is None and cart.tax is None  # not shown -> unknown, never assumed zero


async def test_quantity_update_and_unrelated_items_untouched(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry)
    await page_eval(ctx, "() => localStorage.setItem('fxb:cart', JSON.stringify({'amul-taaza-1l': 1, 'apple-1kg': 1}))")
    cart = await B.inspect_cart(ctx)
    milk = next(i for i in cart.items if "Taaza" in i.product_name)
    result = await B.update_quantity(milk, 3, ctx)
    assert result.success and result.after_quantity == 3
    after = {i.product_name: i.quantity for i in result.snapshot.items}  # type: ignore[union-attr]
    assert after == {"Amul Taaza Toned Fresh Milk": 3.0, "Shimla Apple": 1.0}


async def test_checkout_review_reads_masked_address_and_payment_options(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    from uuid import uuid4

    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry)
    await page_eval(ctx, "() => localStorage.setItem('fxb:cart', JSON.stringify({'amul-taaza-1l': 2, 'eggs-12': 1}))")
    assert await B.open_checkout(ctx) == SessionStatus.READY
    summary = await B.inspect_checkout(ctx, uuid4())
    assert summary.is_verified and str(summary.final_total) == "212.00"
    assert summary.masked_delivery_address == "Home: •••, Gurugram 122•••"
    assert "Fixture Lane" not in (summary.masked_delivery_address or "")
    assert summary.delivery_slot == "Delivery in 12 minutes"
    assert {m.value for m in summary.available_payment_methods} >= {"COD", "UPI", "CARD"}
    assert summary.payment_method.value == "UNKNOWN"
    assert len(summary.summary_hash) == 64


async def test_checkout_login_wall_is_manual(cmanager: BrowserManager, fixture_origin: str, ctelemetry: RecordingTelemetry) -> None:
    from uuid import uuid4

    ctx = await make_ctx(cmanager, fixture_origin, CommercePlatform.BLINKIT, ctelemetry, controls="reset=1&login=0")
    await page_eval(ctx, "() => localStorage.setItem('fxb:cart', JSON.stringify({'eggs-12': 1}))")
    assert await B.open_checkout(ctx) == SessionStatus.LOGIN_REQUIRED
    with pytest.raises(CommerceError) as err:
        await B.inspect_checkout(ctx, uuid4())
    assert err.value.code == "COMMERCE_SESSION_REQUIRED"
