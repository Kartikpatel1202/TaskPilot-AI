"""Amazon India adapter (https://www.amazon.in).

Uses amazon.in's long-standing, documented-in-the-wild markup: search box
`#twotabsearchtextbox`, results `[data-component-type="s-search-result"][data-asin]`,
prices `.a-price .a-offscreen`, product page `#productTitle` / `#add-to-cart-button`,
cart `#sc-active-cart [data-asin]` with `select[name=quantity]`, checkout
"Proceed to Buy" and the cash-on-delivery "Place your order" control.

VERIFICATION STATUS: exercised end-to-end against the local Amazon-like fixture only.
It has NOT been run against the live amazon.in (sign-in, CAPTCHA and bot checks stop
the run safely; markup can change without notice).
"""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID, uuid4

from app.commerce.adapters.base_adapter import AdapterBase, fee, wait_for
from app.commerce.adapters.blinkit import build_checkout_summary, submit_once
from app.commerce.base import (
    CommerceContext,
    CommerceError,
    OrderSubmission,
    ProductSelection,
    SessionStatus,
    SiteBinding,
)
from app.commerce.matching.similarity import coverage, tokens
from app.commerce.matching.variant_matcher import check_variant
from app.commerce.policies.commerce_policy import ClickPurpose
from app.commerce.search.result_parser import to_candidates
from app.schemas.cart import CartItem, CartMutationResult, CartSnapshot
from app.schemas.checkout import CheckoutSummary, PaymentMethod
from app.schemas.common import utc_now
from app.schemas.product import CommercePlatform, ProductCandidate, ProductRequirement

RESULTS_JS = r"""
(max) => {
  const rows = [...document.querySelectorAll('[data-component-type="s-search-result"][data-asin]')].filter((r) => r.dataset.asin);
  let counter = window.__tpCardCounter || 0;
  return rows.slice(0, max).map((r) => {
    if (!r.dataset.tpCard) { counter += 1; r.dataset.tpCard = 'k-' + counter; }
    window.__tpCardCounter = counter;
    const q = (s) => r.querySelector(s);
    const title = q('h2 span') || q('h2');
    const link = q('h2 a[href]') || q('a.a-link-normal[href]');
    const price = r.querySelector('.a-price:not(.a-text-price) .a-offscreen');
    const mrp = r.querySelector('.a-price.a-text-price .a-offscreen');
    const unavailable = /currently unavailable|out of stock/i.test(r.innerText || '');
    return { ref: r.dataset.tpCard, asin: r.dataset.asin, name: title ? title.innerText.trim() : null,
             price: price ? price.textContent.trim() : null, mrp: mrp ? mrp.textContent.trim() : null,
             rating: (q('.a-icon-alt') || {}).textContent || null, reviews: (q('.s-underline-text') || {}).textContent || null,
             delivery: (q('[data-cy="delivery-recipe"]') || {}).innerText || null, unavailable, can_add: !unavailable && !!price,
             url: link ? link.href : null, sponsored: /\bsponsored\b/i.test(r.innerText || '') };
  });
}
"""

PRODUCT_JS = r"""
() => {
  const t = (s) => { const e = document.querySelector(s); return e ? e.innerText.trim() : null; };
  const specs = {};
  document.querySelectorAll('#productOverview_feature_div tr, #productDetails_techSpec_section_1 tr').forEach((tr) => {
    const cells = tr.querySelectorAll('td,th'); if (cells.length >= 2) specs[cells[0].innerText.trim()] = cells[cells.length - 1].innerText.trim();
  });
  const price = document.querySelector('#corePriceDisplay_desktop_feature_div .a-price .a-offscreen, #corePrice_feature_div .a-price .a-offscreen, #priceblock_ourprice');
  return { title: t('#productTitle'), price: price ? price.textContent.trim() : null, availability: t('#availability'),
           seller: t('#sellerProfileTriggerId') || t('#merchant-info'), delivery: t('#mir-layout-DELIVERY_BLOCK'), specs,
           added: !!document.querySelector('#NATC_SMART_WAGON_CONF_MSG_SUCCESS, #sw-atc-confirmation, #huc-v2-order-row-confirm-text'),
           cartCount: Number((document.querySelector('#nav-cart-count') || {}).textContent || 0) };
}
"""

CART_JS = r"""
() => {
  const rows = [...document.querySelectorAll('#sc-active-cart [data-asin], div[data-name="Active Items"] [data-asin]')].filter((r) => r.dataset.asin);
  let counter = window.__tpRowCounter || 0;
  const items = rows.map((r) => {
    if (!r.dataset.tpRow) { counter += 1; r.dataset.tpRow = 'r-' + counter; }
    const title = r.querySelector('.sc-product-title .a-truncate-full, .sc-product-title');
    const sel = r.querySelector('select[name=quantity]');
    const qty = r.dataset.quantity || (sel ? sel.value : null) || ((r.querySelector('[data-a-selector="value"]') || {}).textContent || '').trim();
    const link = r.querySelector('a.sc-product-link[href]');
    return { ref: r.dataset.tpRow, asin: r.dataset.asin, name: title ? title.textContent.trim() : null,
             price: ((r.querySelector('.sc-product-price') || {}).textContent || '').trim() || null,
             quantity: Number(qty || 0), unavailable: /currently unavailable/i.test(r.innerText || ''), url: link ? link.href : null };
  });
  window.__tpRowCounter = counter;
  const sub = document.querySelector('#sc-subtotal-amount-activecart');
  return { rows: items, bill: { items: sub ? sub.innerText.trim() : null }, empty: /your amazon cart is empty/i.test(document.body.innerText || '') };
}
"""

CHECKOUT_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const t = (s) => { const e = document.querySelector(s); return e ? e.innerText.trim() : null; };
  const items = [...document.querySelectorAll('#items .item, .a-row.item')].map((r) => ({
    name: ((r.querySelector('.a-text-bold') || r).innerText || '').trim(),
    quantity: Number(((r.innerText || '').match(/quantity:\s*(\d+)/i) || [0, 0])[1]),
    price: ((r.innerText || '').match(/₹\s?[\d,]+(\.\d+)?/g) || []).slice(-1)[0] || null }));
  const bill = {};
  document.querySelectorAll('#subtotals-marketplace-table tr').forEach((tr) => {
    const label = (tr.cells[0] || {}).innerText || ''; const value = (tr.cells[tr.cells.length - 1] || {}).innerText || '';
    if (/^items/i.test(label)) bill.items = value; else if (/^delivery/i.test(label)) bill.delivery = value;
    else if (/promotion|discount/i.test(label)) bill.discount = value; else if (/order total/i.test(label)) bill.total = value;
    else if (/tax|gst/i.test(label)) bill.tax = value; });
  const radios = [...document.querySelectorAll('input[type=radio][name="ppw-instrumentRowSelection"], #payment-method-section input[type=radio]')]
    .filter(vis).map((r) => ({ label: (r.closest('label') || r.parentElement).innerText.trim(), checked: r.checked }));
  return { address: t('#deliver-to-address-text'), slot: t('#delivery-promise'), items, bill, radios,
           codUnavailable: /pay on delivery is unavailable|cash on delivery is not available/i.test(document.body.innerText || '') };
}
"""


class AmazonIndiaAdapter(AdapterBase):
    platform = CommercePlatform.AMAZON_IN

    def detect_page(self, url: str, binding: SiteBinding) -> bool:
        return url.startswith(binding.url_prefix)

    def _path(self, binding: SiteBinding, page: str) -> str:
        if binding.is_fixture:
            return binding.url({"cart": "cart.html", "home": "index.html"}[page])
        return binding.url({"cart": "gp/cart/view.html", "home": ""}[page])

    async def open_store(self, ctx: CommerceContext) -> SessionStatus:
        await self.goto(ctx, ctx.binding.base_url)
        return await self.blockers(ctx)

    async def check_session(self, ctx: CommerceContext) -> SessionStatus:
        return await self.blockers(ctx)

    # ---------------------------------------------------------------- search

    async def search_products(self, req: ProductRequirement, ctx: CommerceContext) -> list[ProductCandidate]:
        page = await self.page(ctx)
        if not self.detect_page(page.url, ctx.binding):
            await self.goto(ctx, ctx.binding.base_url)
        await self.require_ready(ctx)
        box = page.locator("#twotabsearchtextbox, input[name='field-keywords']").first
        try:
            await box.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise CommerceError("COMMERCE_SEARCH_FAILED", "The Amazon search box was not found.") from exc
        await self.type_search(ctx, box, req.query, submit=True)

        async def results() -> list[dict[str, Any]] | None:
            await self.require_ready(ctx)
            text = await page.evaluate("() => document.body.innerText || ''")
            if re.search(r"no results (found|for)", text, re.IGNORECASE):
                return [{"empty": True}]
            rows = await ctx.controller.evaluate(ctx.session_id, RESULTS_JS, ctx.max_results)
            return rows or None

        rows = await wait_for(results, ctx.search_timeout, interval=0.3) or []
        rows = [r for r in rows if not r.get("empty")]
        return to_candidates(rows, self.platform, page.url, ctx.max_results)

    # ---------------------------------------------------------------- product page + add to cart

    async def _product(self, ctx: CommerceContext) -> dict[str, Any]:
        return await ctx.controller.evaluate(ctx.session_id, PRODUCT_JS)

    async def add_to_cart(self, selection: ProductSelection, packs: int, ctx: CommerceContext) -> CartMutationResult:
        cand = selection.candidate
        if not cand.product_url:
            return CartMutationResult(success=False, message="The listing has no product link.", error_code="COMMERCE_PRODUCT_NOT_FOUND")
        await self.goto(ctx, cand.product_url)  # guarded: must stay on amazon.in (or the dev fixture)
        await self.require_ready(ctx)
        page = await self.page(ctx)
        data = await wait_for(lambda: self._title_ready(ctx), 10.0)
        if not data:
            return CartMutationResult(success=False, message="The product page did not load.", error_code="COMMERCE_PRODUCT_NOT_FOUND")
        # Re-validate the product page against the chosen listing and the requested configuration.
        if coverage(tokens(cand.product_name), tokens(data["title"])) < 0.8:
            return CartMutationResult(success=False, message="The product page does not match the chosen listing.", error_code="COMMERCE_VARIANT_MISMATCH")
        req = selection_requirement(selection)
        if req is not None:
            check = check_variant(req.required_specs, req.preferred_variant, data["title"] or "", data.get("specs") or {})
            if check.contradicted:
                return CartMutationResult(success=False, message="Product page shows a different configuration: " + "; ".join(check.contradicted),
                                          error_code="COMMERCE_VARIANT_MISMATCH")
        if re.search(r"unavailable|out of stock", data.get("availability") or "", re.IGNORECASE):
            return CartMutationResult(success=False, message=f"{cand.product_name} is currently unavailable.", error_code="COMMERCE_PRODUCT_NOT_FOUND")
        before = int(data.get("cartCount") or 0)
        qty = page.locator("#quantity, select[name='quantity']").first
        if packs > 1:
            if await qty.count() == 0:
                return CartMutationResult(success=False, message="This listing has no quantity selector.", error_code="COMMERCE_QUANTITY_MISMATCH")
            decision = ctx.policy.check_click(ClickPurpose.SELECT_VARIANT, "Quantity")
            await ctx.controller.select_checked(ctx.session_id, qty, str(packs), decision)
        button = page.locator("#add-to-cart-button").first
        try:
            await self.click(ctx, button, ClickPurpose.ADD_TO_CART, label="Add to Cart", settle_ms=800)
        except CommerceError as exc:
            if exc.code != "ACTION_TIMEOUT":
                raise  # uncertain clicks are resolved below by reading the cart count, never re-clicked blindly

        async def added() -> dict[str, Any] | None:
            d = await self._product(ctx)
            return d if d.get("added") or int(d.get("cartCount") or 0) >= before + packs else None

        after = await wait_for(added, 8.0)
        if after is None:
            return CartMutationResult(success=False, before_quantity=before, after_quantity=before,
                                      message="Amazon did not confirm the add to cart.", error_code="COMMERCE_QUANTITY_MISMATCH")
        count = int(after.get("cartCount") or 0)
        return CartMutationResult(success=True, before_quantity=before, after_quantity=count, added_packs=count - before,
                                  message=f"Added {packs} × {cand.product_name[:60]} (cart count {before} → {count}).")

    async def _title_ready(self, ctx: CommerceContext) -> dict[str, Any] | None:
        try:
            d = await self._product(ctx)
        except Exception:
            return None
        return d if d.get("title") else None

    # ---------------------------------------------------------------- cart

    async def inspect_cart(self, ctx: CommerceContext) -> CartSnapshot:
        await self.goto(ctx, self._path(ctx.binding, "cart"))
        await self.require_ready(ctx)
        page = await self.page(ctx)

        async def read() -> dict[str, Any] | None:
            d = await ctx.controller.evaluate(ctx.session_id, CART_JS)
            return d if d.get("rows") or d.get("empty") else None

        data = await wait_for(read, 8.0, interval=0.3)
        if data is None:
            raise CommerceError("COMMERCE_CART_UNVERIFIED", "The Amazon cart could not be read.")
        items = [self.cart_item(r, unit_price_is_line=False) for r in data.get("rows", [])]
        # Amazon's cart shows the item subtotal only; delivery/fees/total appear at checkout (left unknown here).
        return CartSnapshot(cart_id=uuid4(), platform=self.platform, items=items, item_count=len(items),
                            subtotal=fee((data.get("bill") or {}).get("items")), observed_at=utc_now(), source_page=page.url)

    async def update_quantity(self, item: CartItem, quantity: int, ctx: CommerceContext) -> CartMutationResult:
        snapshot = await self.inspect_cart(ctx)
        page = await self.page(ctx)
        row = next((i for i in snapshot.items if tokens(i.product_name) == tokens(item.product_name)), None)
        if row is None or row.dom_ref is None:
            return CartMutationResult(success=False, message=f"{item.product_name[:60]} is not in the cart.", error_code="COMMERCE_PRODUCT_NOT_FOUND")
        start = int(row.quantity)
        select = page.locator(f'[data-tp-row="{row.dom_ref}"] select[name=quantity]').first
        purpose = ClickPurpose.DECREMENT if quantity < start else ClickPurpose.SELECT_VARIANT
        decision = ctx.policy.check_click(purpose, "Quantity")
        await ctx.controller.select_checked(ctx.session_id, select, str(quantity), decision)

        async def settled() -> CartSnapshot | None:
            d = await ctx.controller.evaluate(ctx.session_id, CART_JS)
            match = next((r for r in d.get("rows", []) if tokens(r.get("name") or "") == tokens(item.product_name)), None)
            seen = int(match["quantity"]) if match else 0
            return await self.inspect_cart(ctx) if seen == quantity else None

        final = await wait_for(settled, 8.0)
        if final is None:
            return CartMutationResult(success=False, before_quantity=start, message="The cart quantity did not update.", error_code="COMMERCE_QUANTITY_MISMATCH")
        return CartMutationResult(success=True, before_quantity=start, after_quantity=quantity,
                                  message=f"{item.product_name[:60]}: quantity {start} → {quantity}.", snapshot=final)

    # ---------------------------------------------------------------- checkout

    async def open_checkout(self, ctx: CommerceContext) -> SessionStatus:
        await self.inspect_cart(ctx)
        page = await self.page(ctx)
        button = page.locator("input[name='proceedToRetailCheckout'], #sc-buy-box-ptc-button input").first
        if await button.count() == 0:
            raise CommerceError("COMMERCE_CHECKOUT_UNVERIFIED", "The 'Proceed to Buy' control was not found.")
        await self.click(ctx, button, ClickPurpose.OPEN_CHECKOUT, label=(await button.get_attribute("value")) or "Proceed to Buy")
        await page.wait_for_load_state("domcontentloaded")
        return await self.blockers(ctx)

    async def inspect_checkout(self, ctx: CommerceContext, task_id: UUID) -> CheckoutSummary:
        await self.require_ready(ctx, allow_login=False)
        data = await ctx.controller.evaluate(ctx.session_id, CHECKOUT_JS)
        return build_checkout_summary(self.platform, task_id, data, unit_price_is_line=True, adapter=self)

    async def select_payment_method(self, method: PaymentMethod, ctx: CommerceContext) -> bool:
        if method != PaymentMethod.COD:
            return False
        page = await self.page(ctx)
        option = page.locator("label").filter(has_text=re.compile(r"cash on delivery|pay on delivery", re.IGNORECASE)).first
        if await option.count() == 0:
            return False
        await self.click(ctx, option, ClickPurpose.SELECT_COD, label=await option.inner_text())
        data = await ctx.controller.evaluate(ctx.session_id, CHECKOUT_JS)
        return any(r["checked"] and re.search(r"cash on delivery|pay on delivery", r["label"], re.IGNORECASE) for r in data.get("radios", []))

    async def submit_cod_order(self, ctx: CommerceContext, authorization: Any) -> OrderSubmission:
        page = await self.page(ctx)
        button = page.locator("input[name='placeYourOrder1'], #placeOrder, #submitOrderButtonId input").first
        return await submit_once(self, ctx, button, authorization, page)


def selection_requirement(selection: ProductSelection) -> ProductRequirement | None:
    return selection.requirement
