"""Blinkit adapter (https://blinkit.com).

Blinkit renders product cards dynamically with generated class names, so this adapter
uses semantic structure instead of brittle classes: a product card is the smallest
element that contains one ADD control (or a −/n/+ stepper, or "Out of Stock") and a ₹
price. Search uses the visible search input on the search page.

VERIFICATION STATUS: exercised end-to-end against the local Blinkit-like fixture only.
It has NOT been run against the live blinkit.com (markup may differ; login, location
and bot checks stop the run safely).
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from app.commerce.adapters.base_adapter import (
    AdapterBase,
    address_fingerprint,
    fee,
    mask_address,
    payment_method_from,
    summary_fingerprint,
    wait_for,
)
from app.commerce.base import (
    CommerceContext,
    CommerceError,
    OrderSubmission,
    ProductSelection,
    SessionStatus,
    SiteBinding,
)
from app.commerce.matching.similarity import family_key
from app.commerce.money import parse_inr
from app.commerce.policies.commerce_policy import ClickPurpose
from app.commerce.search.result_parser import to_candidates
from app.schemas.cart import CartItem, CartMutationResult, CartSnapshot
from app.schemas.checkout import CheckoutSummary, PaymentMethod
from app.schemas.common import utc_now
from app.schemas.product import CommercePlatform, ProductCandidate, ProductRequirement

# Trusted extraction script: tags each card with data-tp-card="k-N" and returns observed text only.
CARDS_JS = r"""
(max) => {
  const vis = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const PRICE = /₹\s?[\d,]+(\.\d+)?/;
  const SIZE = /^(\d+(\.\d+)?\s?(x\s?\d+(\.\d+)?\s?)?(ml|l|ltr|litre|kg|g|gm|pcs?|pieces?|units?|pack|dozen)\b.*|pack of \d+.*|\d+\s?x\s?\d+.*)$/i;
  const isStepper = (el) => el.children.length <= 4 && /^[−\-–]\d{1,3}\+$/.test((el.innerText || '').replace(/\s+/g, ''));
  const hasName = (t) => t.split('\n').map((l) => l.trim()).some((l) => l.length >= 6 && !PRICE.test(l) && !SIZE.test(l) && !/^(add|out of stock|\d+ mins?)$/i.test(l));
  const controls = [...document.querySelectorAll('div,button,span,a')].filter((el) => vis(el) && (
      /^add$/i.test((el.innerText || '').trim()) && el.children.length <= 1 ||
      /^out of stock$/i.test((el.innerText || '').trim()) || isStepper(el)));
  const cards = [];
  for (const c of controls) {
    let node = c.parentElement;
    while (node && node !== document.body) {
      const t = node.innerText || '';
      if (PRICE.test(t) && hasName(t)) break;
      node = node.parentElement;
    }
    if (!node || node === document.body) continue;
    const addCount = [...node.querySelectorAll('div,button,span,a')].filter((e) => /^add$/i.test((e.innerText || '').trim()) && e.children.length <= 1).length;
    if (addCount > 1) continue;  // container of several cards, not one card
    if (!cards.includes(node) && !cards.some((k) => k.contains(node) || node.contains(k))) cards.push(node);
  }
  let counter = window.__tpCardCounter || 0;
  const out = [];
  for (const card of cards.slice(0, max)) {
    if (!card.dataset.tpCard) { counter += 1; card.dataset.tpCard = 'k-' + counter; }
    const lines = (card.innerText || '').split('\n').map((l) => l.replace(/\s+/g, ' ').trim()).filter(Boolean);
    const struck = [...card.querySelectorAll('*')].filter((e) => e.children.length === 0 && /line-through/.test(getComputedStyle(e).textDecorationLine) && PRICE.test(e.innerText || '')).map((e) => e.innerText.trim());
    const remaining = ((card.innerText || '').match(/₹\s?[\d,]+(\.\d+)?/g) || []).map((p) => p.trim());
    struck.forEach((s) => { const i = remaining.indexOf(s); if (i >= 0) remaining.splice(i, 1); });
    const price = remaining[0] || null;
    const size = lines.find((l) => SIZE.test(l)) || null;
    const name = lines.filter((l) => !PRICE.test(l) && l !== size && !/^(add|out of stock|\d+ mins?|[−+\-]|\d+)$/i.test(l) && !/off$/i.test(l))
                      .sort((a, b) => b.length - a.length)[0] || null;
    const stepper = [...card.querySelectorAll('div,span')].find(isStepper);
    const qtyEl = stepper ? { innerText: (stepper.innerText || '').replace(/[^0-9]/g, '') } : null;
    const unavailable = /out of stock|sold out|currently unavailable/i.test(card.innerText || '');
    const canAdd = !unavailable && (/\bADD\b/.test(card.innerText || '') || !!qtyEl);
    const img = card.querySelector('img');
    const link = card.closest('a[href]') || card.querySelector('a[href]');
    out.push({ ref: card.dataset.tpCard, name, size, price, mrp: struck[0] || null, unavailable, can_add: canAdd,
               in_cart: qtyEl ? Number((qtyEl.innerText || '').trim()) : (canAdd ? 0 : null),
               image: img && img.src && img.src.startsWith('https://') ? img.src : null,
               url: link ? link.href : null });
  }
  window.__tpCardCounter = counter;
  return out;
}
"""

CART_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const PRICE = /₹\s?[\d,]+(\.\d+)?/;
  const SIZE = /^(\d+(\.\d+)?\s?(ml|l|ltr|litre|kg|g|gm|pcs?|pieces?|units?|pack|dozen)\b.*|pack of \d+.*)$/i;
  const isStepper = (el) => el.children.length <= 4 && /^[−\-–]\d{1,3}\+$/.test((el.innerText || '').replace(/\s+/g, ''));
  const steppers = [...document.querySelectorAll('div,span')].filter((el) => vis(el) && isStepper(el));
  const rows = [];
  let counter = window.__tpRowCounter || 0;
  for (const q of steppers) {
    let node = q.parentElement;
    while (node && node !== document.body && !PRICE.test(node.innerText || '')) node = node.parentElement;
    if (!node || node === document.body || rows.some((r) => r.node === node)) continue;
    if (!node.dataset.tpRow) { counter += 1; node.dataset.tpRow = 'r-' + counter; }
    const lines = (node.innerText || '').split('\n').map((l) => l.replace(/\s+/g, ' ').trim()).filter(Boolean);
    const size = lines.find((l) => SIZE.test(l)) || null;
    const price = lines.find((l) => /^₹\s?[\d,]+(\.\d+)?$/.test(l)) || null;
    const name = lines.filter((l) => !PRICE.test(l) && l !== size && !/^([−+\-]|\d+)$/.test(l)).sort((a, b) => b.length - a.length)[0] || null;
    rows.push({ node, ref: node.dataset.tpRow, name, size, price, quantity: Number((q.innerText || '').replace(/[^0-9]/g, '') || 0), unavailable: /out of stock|unavailable/i.test(node.innerText || '') });
  }
  window.__tpRowCounter = counter;
  const text = document.body.innerText || '';
  const LABELS = { items: /^(items? total|sub ?total|mrp total)/i, delivery: /^delivery (charge|fee)/i, handling: /^handling (charge|fee)/i,
                   discount: /^(discount|savings|product discount)/i, total: /^(grand total|to pay|total payable|order total)/i };
  const bill = {};
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
  lines.forEach((line, i) => {
    for (const [key, re] of Object.entries(LABELS)) {
      if (bill[key] === undefined && re.test(line)) {
        const inline = line.replace(re, '').trim().match(/(-?\s?₹\s?[\d,]+(\.\d+)?|free)/i);
        const next = (lines[i + 1] || '').match(/^(-?\s?₹\s?[\d,]+(\.\d+)?|free)$/i);
        bill[key] = inline ? inline[0] : next ? next[0] : null;
      }
    }
  });
  const empty = /don't have any items in your cart|your cart is empty/i.test(text);
  return { rows: rows.map(({ node, ...r }) => r), bill, empty };
}
"""

CHECKOUT_JS = r"""
() => {
  const vis = (el) => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const text = document.body.innerText || '';
  // Prefer the checkout's own address block over a header location chip.
  const addrEl = document.querySelector('section[aria-label*="address" i] [data-address], main [data-address]')
    || [...document.querySelectorAll('main section, main div')].find((s) => /^delivering to|^delivery address/i.test((s.innerText || '').trim()))
    || document.querySelector('[data-address]');
  const address = addrEl ? (addrEl.matches('[data-address]') ? addrEl.innerText : (addrEl.innerText || '').split('\n').slice(1, 2).join(' ')) : null;
  const slot = (text.match(/delivery in \d+ ?(minutes|mins?)|arriving [^\n]+|delivery (by|on) [^\n]+/i) || [null])[0];
  const items = [...document.querySelectorAll('[data-checkout-item], li')].filter((li) => vis(li) && /₹/.test(li.innerText || '') && /×|x\s*\d/i.test(li.innerText || ''))
    .map((li) => ({ name: (li.querySelector('.title') || li).innerText.split('×')[0].replace(/₹.*$/, '').trim(),
                    size: (li.querySelector('.size') || {}).innerText || null,
                    quantity: Number(((li.innerText || '').match(/×\s*(\d+)/) || [0, 0])[1]),
                    price: ((li.innerText || '').match(/₹\s?[\d,]+(\.\d+)?/g) || []).slice(-1)[0] || null }));
  const radios = [...document.querySelectorAll('input[type=radio]')].filter(vis).map((r) => ({ label: (r.closest('label') || r.parentElement).innerText.trim(), checked: r.checked }));
  const LABELS = { items: /^(items? total|sub ?total)/i, delivery: /^delivery (charge|fee)/i, handling: /^handling (charge|fee)/i,
                   discount: /^(discount|savings)/i, total: /^(grand total|to pay|total payable|order total)/i };
  const bill = {};
  const lines = text.split('\n').map((l) => l.trim()).filter(Boolean);
  lines.forEach((line, i) => { for (const [k, re] of Object.entries(LABELS)) if (bill[k] === undefined && re.test(line)) {
    const inline = line.replace(re, '').trim().match(/(-?\s?₹\s?[\d,]+(\.\d+)?|free)/i); const next = (lines[i + 1] || '').match(/^(-?\s?₹\s?[\d,]+(\.\d+)?|free)$/i);
    bill[k] = inline ? inline[0] : next ? next[0] : null; } });
  const codUnavailable = /cash on delivery is not available|pay on delivery is unavailable/i.test(text);
  return { address, slot, items, radios, bill, codUnavailable };
}
"""

CONFIRMATION_JS = r"""
() => {
  const text = document.body.innerText || '';
  const confirmed = !!document.querySelector('[data-order-confirmation]') || /order (has been )?placed|order is confirmed|thank you for your order/i.test(text);
  const idEl = document.querySelector('[data-order-id]');
  const m = text.match(/order\s*(?:id|#|no\.?|number)?\s*[:#]?\s*([A-Z0-9][A-Z0-9-]{4,30})/i);
  return { confirmed, reference: idEl ? idEl.innerText.trim() : (confirmed && m ? m[1] : null) };
}
"""


class BlinkitAdapter(AdapterBase):
    platform = CommercePlatform.BLINKIT

    def detect_page(self, url: str, binding: SiteBinding) -> bool:
        return url.startswith(binding.url_prefix)

    def _path(self, binding: SiteBinding, page: str, query: str | None = None) -> str:
        from urllib.parse import quote

        if binding.is_fixture:
            name = {"search": "search.html", "cart": "cart.html", "checkout": "checkout.html"}[page]
            return binding.url(name)
        return binding.url({"search": "s/", "cart": "", "checkout": ""}[page]) + (f"?q={quote(query)}" if query and page == "search" else "")

    # ---------------------------------------------------------------- session

    async def open_store(self, ctx: CommerceContext) -> SessionStatus:
        await self.goto(ctx, ctx.binding.base_url)
        if not ctx.binding.is_fixture:
            # Live blinkit.com renders its header (cart, location) and any location picker a few seconds after load.
            page = await self.page(ctx)
            try:
                await page.locator('[class*="CartButton"], [class*="LocationDropDown"], input[placeholder*="Search" i]').first.wait_for(
                    state="visible", timeout=10_000)
                await page.wait_for_timeout(1500)
            except Exception:  # noqa: BLE001 - blockers() below still reports what the page shows
                pass
        return await self.blockers(ctx)

    async def check_session(self, ctx: CommerceContext) -> SessionStatus:
        return await self.blockers(ctx)

    # ---------------------------------------------------------------- search

    async def _cards(self, ctx: CommerceContext) -> list[dict[str, Any]]:
        try:
            return await ctx.controller.evaluate(ctx.session_id, CARDS_JS, ctx.max_results)
        except Exception:
            return []

    async def search_products(self, req: ProductRequirement, ctx: CommerceContext) -> list[ProductCandidate]:
        await self.goto(ctx, self._path(ctx.binding, "search"))
        await self.require_ready(ctx)
        page = await self.page(ctx)
        box = page.locator('input[placeholder*="Search" i], input[type="search"]').first
        try:
            await box.wait_for(state="visible", timeout=8000)
        except Exception as exc:
            raise CommerceError("COMMERCE_SEARCH_FAILED", "The Blinkit search box was not found.") from exc
        await self.type_search(ctx, box, req.query, submit=False)

        async def settled() -> list[dict[str, Any]] | None:
            await self.require_ready(ctx)
            text = await page.evaluate("() => document.body.innerText || ''")
            if re.search(r"no results for|no products found", text, re.IGNORECASE):
                return [{"empty": True}]
            first = await self._cards(ctx)
            if not first:
                return None
            await page.wait_for_timeout(350)
            second = await self._cards(ctx)
            return second if len(second) == len(first) else None

        rows = await wait_for(settled, ctx.search_timeout, interval=0.3) or []
        rows = [r for r in rows if not r.get("empty")]
        return to_candidates(rows, self.platform, page.url, ctx.max_results)

    # ---------------------------------------------------------------- cart mutation

    async def _find_card(self, ctx: CommerceContext, cand: ProductCandidate) -> dict[str, Any] | None:
        want = (family_key(cand.product_name), (cand.pack_size or "").lower())
        for row in await self._cards(ctx):
            if (family_key(row.get("name") or ""), (row.get("size") or "").lower()) == want:
                return row
        return None

    async def add_to_cart(self, selection: ProductSelection, packs: int, ctx: CommerceContext) -> CartMutationResult:
        cand = selection.candidate
        page = await self.page(ctx)
        card = await self._find_card(ctx, cand)
        if card is None:  # results page changed (e.g. after a cart read): search again
            await self.goto(ctx, self._path(ctx.binding, "search"))
            box = page.locator('input[placeholder*="Search" i], input[type="search"]').first
            await self.type_search(ctx, box, cand.product_name, submit=False)
            card = await wait_for(lambda: self._find_card(ctx, cand), ctx.search_timeout, interval=0.3)
        if card is None:
            return CartMutationResult(success=False, message=f"{cand.product_name} is no longer shown on the page.", error_code="COMMERCE_PRODUCT_NOT_FOUND")
        if card.get("unavailable"):
            return CartMutationResult(success=False, message=f"{cand.product_name} is out of stock.", error_code="COMMERCE_PRODUCT_NOT_FOUND")

        start = int(card.get("in_cart") or 0)
        target = start + packs
        current = start
        for _ in range(packs):
            before = current
            row = await self._find_card(ctx, cand)
            if row is None:
                break
            loc = page.locator(f'[data-tp-card="{row["ref"]}"]')
            if before == 0:
                control = loc.get_by_text(re.compile(r"^\s*ADD\s*$", re.IGNORECASE)).first
                purpose = ClickPurpose.ADD_TO_CART
            else:
                control = loc.locator('button[aria-label^="Add" i], button:has-text("+")').first
                purpose = ClickPurpose.INCREMENT
            try:
                await self.click(ctx, control, purpose, label="Add" if purpose == ClickPurpose.ADD_TO_CART else "Add one more", settle_ms=600)
            except CommerceError as exc:
                if exc.code != "ACTION_TIMEOUT":
                    raise
                # Uncertain click: never retry blindly — re-read the stepper first.

            async def advanced() -> int | None:
                r = await self._find_card(ctx, cand)
                value = int((r or {}).get("in_cart") or 0)
                return value if value > before else None

            observed = await wait_for(advanced, 6.0, interval=0.25)
            if observed is None:
                return CartMutationResult(
                    success=False, before_quantity=start, after_quantity=before, added_packs=before - start,
                    message=f"Clicking add for {cand.product_name} did not change the cart.", error_code="COMMERCE_QUANTITY_MISMATCH",
                )
            current = observed
            if current >= target:
                break
        ok = current == target
        return CartMutationResult(
            success=ok, before_quantity=start, after_quantity=current, added_packs=current - start,
            message=(f"{cand.product_name}: cart quantity {start} → {current}." if ok
                     else f"{cand.product_name}: expected {target} in cart, saw {current}."),
            error_code=None if ok else "COMMERCE_QUANTITY_MISMATCH",
        )

    # ---------------------------------------------------------------- cart reading

    async def inspect_cart(self, ctx: CommerceContext) -> CartSnapshot:
        page = await self.page(ctx)
        if ctx.binding.is_fixture:
            await self.goto(ctx, self._path(ctx.binding, "cart"))
        else:
            await self.require_ready(ctx)  # e.g. the location picker can appear late; never click through an overlay
            # Live blinkit.com renders the header cart control as a styled <div> ("My Cart" / "N items ₹…"), not a button.
            control = page.get_by_role("button", name=re.compile(r"my cart|\d+ items?", re.IGNORECASE)).or_(
                page.locator('[class*="CartButton"]').filter(has_text=re.compile(r"my cart|\d+ items?", re.IGNORECASE))).first
            await self.click(ctx, control, ClickPurpose.OPEN_CART)
        await self.require_ready(ctx)

        async def read() -> dict[str, Any] | None:
            data = await ctx.controller.evaluate(ctx.session_id, CART_JS)
            return data if (data.get("rows") or data.get("empty")) else None

        data = await wait_for(read, 8.0, interval=0.3)
        if data is None:
            raise CommerceError("COMMERCE_CART_UNVERIFIED", "The Blinkit cart could not be read.")
        bill = data.get("bill") or {}
        items = [self.cart_item(r, unit_price_is_line=True) for r in data.get("rows", [])]
        discount = parse_inr(bill.get("discount"))
        return CartSnapshot(
            cart_id=uuid4(), platform=self.platform, items=items, item_count=len(items),
            subtotal=fee(bill.get("items")), delivery_fee=fee(bill.get("delivery")), handling_fee=fee(bill.get("handling")),
            discount=-abs(discount) if discount is not None else None, total=fee(bill.get("total")),
            observed_at=utc_now(), source_page=page.url,
        )

    async def update_quantity(self, item: CartItem, quantity: int, ctx: CommerceContext) -> CartMutationResult:
        page = await self.page(ctx)
        snapshot = await self.inspect_cart(ctx)
        row = next((i for i in snapshot.items if family_key(i.product_name) == family_key(item.product_name)
                    and (i.pack_size or "") == (item.pack_size or "")), None)
        if row is None or row.dom_ref is None:
            return CartMutationResult(success=False, message=f"{item.product_name} is not in the cart.", error_code="COMMERCE_PRODUCT_NOT_FOUND")
        start = int(row.quantity)
        current = start
        while current != quantity:
            snapshot = await self.inspect_cart(ctx) if current != start else snapshot
            row = next((i for i in snapshot.items if family_key(i.product_name) == family_key(item.product_name)
                        and (i.pack_size or "") == (item.pack_size or "")), None)
            if row is None:
                current = 0
                break
            loc = page.locator(f'[data-tp-row="{row.dom_ref}"]')
            if quantity > current:
                await self.click(ctx, loc.locator('button[aria-label^="Add" i], button:has-text("+")').first, ClickPurpose.INCREMENT, label="Add one more", settle_ms=600)
            else:
                await self.click(ctx, loc.locator('button[aria-label^="Remove" i], button:has-text("−")').first, ClickPurpose.DECREMENT, label="Remove one", settle_ms=600)
            before = current

            async def moved() -> float | None:
                data = await ctx.controller.evaluate(ctx.session_id, CART_JS)
                match = next((r for r in data.get("rows", []) if family_key(r.get("name") or "") == family_key(item.product_name)
                              and (r.get("size") or "") == (item.pack_size or "")), None)
                value = float(match["quantity"]) if match else 0.0
                return value + 1000 if value != before else None  # +1000 keeps 0 truthy

            seen = await wait_for(moved, 6.0)
            if seen is None:
                return CartMutationResult(success=False, before_quantity=start, after_quantity=before,
                                          message="The cart quantity did not change.", error_code="COMMERCE_QUANTITY_MISMATCH")
            current = int(seen - 1000)
        final = await self.inspect_cart(ctx)
        return CartMutationResult(success=True, before_quantity=start, after_quantity=current,
                                  message=f"{item.product_name}: quantity {start} → {current}.", snapshot=final)

    # ---------------------------------------------------------------- checkout

    async def open_checkout(self, ctx: CommerceContext) -> SessionStatus:
        page = await self.page(ctx)
        await self.inspect_cart(ctx)
        button = page.get_by_role("button", name=re.compile(r"^\s*(proceed( to checkout)?|checkout)\s*$", re.IGNORECASE)).first
        await self.click(ctx, button, ClickPurpose.OPEN_CHECKOUT)
        await page.wait_for_load_state("domcontentloaded")
        return await self.blockers(ctx)

    async def inspect_checkout(self, ctx: CommerceContext, task_id: UUID) -> CheckoutSummary:
        await self.require_ready(ctx, allow_login=False)
        data = await ctx.controller.evaluate(ctx.session_id, CHECKOUT_JS)
        return build_checkout_summary(self.platform, task_id, data, unit_price_is_line=True, adapter=self)

    async def select_payment_method(self, method: PaymentMethod, ctx: CommerceContext) -> bool:
        if method != PaymentMethod.COD:
            return False  # prepaid methods are always chosen and paid by the user
        page = await self.page(ctx)
        option = page.locator("label").filter(has_text=re.compile(r"cash on delivery|pay on delivery", re.IGNORECASE)).first
        if await option.count() == 0:
            return False
        await self.click(ctx, option, ClickPurpose.SELECT_COD, label=(await option.inner_text()))
        data = await ctx.controller.evaluate(ctx.session_id, CHECKOUT_JS)
        return any(r["checked"] and payment_method_from(r["label"]) == PaymentMethod.COD for r in data.get("radios", []))

    async def submit_cod_order(self, ctx: CommerceContext, authorization: Any) -> OrderSubmission:
        page = await self.page(ctx)
        button = page.get_by_role("button", name=re.compile(r"^\s*place (your )?order\s*$", re.IGNORECASE)).first
        return await submit_once(self, ctx, button, authorization, page)


async def submit_once(adapter: AdapterBase, ctx: CommerceContext, button: Any, authorization: Any, page: Any) -> OrderSubmission:
    """Single, authorized submission. The authorization is consumed by the caller's purchase
    policy *before* this runs; a timeout is never followed by a second click."""
    if await button.count() == 0:
        raise CommerceError("PURCHASE_POLICY_BLOCKED", "The cash-on-delivery order button was not found.", status="BLOCKED")
    label = (await button.get_attribute("value")) or (await button.inner_text())
    try:
        await adapter.click(ctx, button, ClickPurpose.PLACE_COD_ORDER, label=label, authorization=authorization, settle_ms=2500)
    except CommerceError as exc:
        if exc.code != "ACTION_TIMEOUT":
            raise
    result = await wait_for(lambda: _confirmation(ctx), 10.0, interval=0.4)
    if result:
        return OrderSubmission(True, result.get("reference"), "The website shows an order confirmation.")
    return OrderSubmission(False, None, "No order confirmation was visible. Please check the website yourself; TaskPilot will not submit again.")


async def _confirmation(ctx: CommerceContext) -> dict[str, Any] | None:
    try:
        data = await ctx.controller.evaluate(ctx.session_id, CONFIRMATION_JS)
    except Exception:
        return None
    return data if data.get("confirmed") else None


def build_checkout_summary(
    platform: CommercePlatform, task_id: UUID, data: dict[str, Any], *, unit_price_is_line: bool, adapter: AdapterBase,
) -> CheckoutSummary:
    bill = data.get("bill") or {}
    items = [adapter.cart_item(r, unit_price_is_line=unit_price_is_line) for r in data.get("items", [])]
    radios = data.get("radios") or []
    methods = [payment_method_from(r.get("label")) for r in radios]
    selected = next((payment_method_from(r.get("label")) for r in radios if r.get("checked")), PaymentMethod.UNKNOWN)
    total = fee(bill.get("total"))
    discount = parse_inr(bill.get("discount"))
    raw_address = data.get("address")
    warnings: list[str] = []
    if data.get("codUnavailable"):
        warnings.append("Cash on Delivery is not available for this order.")
    if total is None:
        warnings.append("The final total could not be read.")
    if not raw_address:
        warnings.append("The delivery address could not be read.")
    verified = bool(items) and total is not None and bool(raw_address)
    payload = {
        "platform": platform.value,
        "items": [(i.product_name, i.pack_size, i.quantity, str(i.line_total)) for i in items],
        "subtotal": str(fee(bill.get("items"))), "delivery": str(fee(bill.get("delivery"))),
        "handling": str(fee(bill.get("handling"))), "discount": str(discount), "total": str(total),
        "address": address_fingerprint(raw_address), "payment": selected.value,
    }
    return CheckoutSummary(
        checkout_id=uuid4(), task_id=task_id, platform=platform, items=items,
        subtotal=fee(bill.get("items")), delivery_fee=fee(bill.get("delivery")), handling_fee=fee(bill.get("handling")),
        tax=None, discount=-abs(discount) if discount is not None else None, final_total=total,
        masked_delivery_address=mask_address(raw_address), delivery_slot=(data.get("slot") or None),
        payment_method=selected, available_payment_methods=sorted(set(methods), key=lambda m: m.value),
        observed_at=utc_now(), is_verified=verified, summary_hash=summary_fingerprint(payload), warnings=warnings,
    )


__all__ = ["BlinkitAdapter", "build_checkout_summary", "submit_once", "Decimal"]
