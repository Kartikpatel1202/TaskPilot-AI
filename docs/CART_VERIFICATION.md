# Cart reconciliation and verification

## Reconciliation (no duplicates)
`cart/quantity_manager.py`. Before adding, the adapter reads the **live** quantity of the *same* product (same product line and pack size): on Blinkit from the card's stepper, otherwise from the cart read by `open_store`. Only `required − existing` packs are added.

Example: the cart already has 1 × 1 L Taaza and the user wants 2 L, so exactly one more pack is added and the cart then shows 2.

Unrelated items and other pack sizes are never changed, removed or cleared. They are listed as "left unchanged".

**Uncertain clicks:** a click timeout is followed by a re-read; the click is retried only if the page proves it did not happen. Each Blinkit increment is verified individually.

## Verification
`cart/cart_verifier.py` compares every requirement with the observed cart, checking brand/name, variant and the total amount. Pack sizes are summed, so 1 × 1 L + 2 × 500 ml counts as 2 L.

| Status | Meaning |
| --- | --- |
| `VERIFIED` | every requested item present with the right variant and exact quantity |
| `PARTIAL` | some items OK, others missing, unavailable or skipped |
| `MISMATCH` | a wrong variant or wrong quantity (or nothing matched) |
| `UNVERIFIED` | nothing to verify or the cart could not be read |

The report lists each check (`OK`, `MISSING`, `QUANTITY_MISMATCH`, `VARIANT_MISMATCH`, `UNAVAILABLE`, `SKIPPED`), the missing and mismatched items, and warnings: unrelated items, unavailable rows, an item total that disagrees with the shown subtotal, and a final total not shown. Nothing is silently corrected, and checkout review **requires** `VERIFIED`.

## Prices
`PriceChangePolicy`: every difference between a listing price and the cart unit price (or between the cart subtotal and the checkout subtotal) is disclosed. Above `COMMERCE_MAX_PRICE_CHANGE_PERCENT` it is flagged as significant. All money is `Decimal` and serialised as strings. Fees, discounts and taxes that were not shown stay **null** and are displayed as "Not available", never ₹0. "FREE" shown by the site is recorded as ₹0.00 because it was observed.
