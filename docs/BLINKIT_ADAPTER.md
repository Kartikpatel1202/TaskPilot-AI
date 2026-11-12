# Blinkit adapter

`backend/app/commerce/adapters/blinkit.py` · Site: https://blinkit.com · **Status: verified only against the local Blinkit-like fixture. Not run on blinkit.com.**

## Approach
Blinkit renders cards dynamically with generated class names, so the adapter uses page *structure* rather than classes:
- **Product card:** the smallest element containing exactly one `ADD` control (or a `− n +` stepper, or "Out of Stock") together with a ₹ price and a name line. Each card is tagged `data-tp-card="k-N"` by trusted script.
- **Fields read:** name (longest non-price/size line), size (`1 ltr`, `500 ml`, `12 pieces`…), selling price (first ₹ amount not struck through), MRP (struck-through amount), availability, in-cart quantity (stepper), and an https image if shown. Nothing else is inferred.
- **Search:** opens the search page (`/s/` on the real site) and types into the visible `input[placeholder*="Search"]`. It waits until the result set is stable across two reads, and recognises "No results".

## Flow
1. `open_store`: open the site and run the blocker check. A CAPTCHA/bot check gives `CAPTCHA_REQUIRED`, a location dialog gives `COMMERCE_LOCATION_REQUIRED` (an address is never invented), and a login wall at checkout gives `COMMERCE_SESSION_REQUIRED`.
2. `search_and_add`: match deterministically, then read the card's stepper (the live in-cart quantity) and add only the difference. Clicks are one at a time: `ADD` first, then `+`. After **each** click the adapter waits for the stepper to increase. If a click times out, it re-reads before doing anything else and never blindly clicks again.
3. `inspect_cart`: the real site opens the cart drawer through the "My Cart" button; the fixture uses `cart.html`. Rows come from steppers. Bill lines are read: Items total, Delivery charge (`FREE` = ₹0, as shown), Handling charge, Discount, Grand total / To pay. Anything not shown stays null.
4. `update_quantity`: `+`/`−` on the exact row, verified after each click. Other rows are never touched.
5. `open_checkout`: "Proceed" / "Proceed to checkout" only (the `OPEN_CHECKOUT` purpose).
6. `inspect_checkout`: the address is taken from the checkout's own address block and masked (`Home: •••, Gurugram 122•••`). Also read: delivery slot, item lines, bill, payment radios.
7. COD: selects only a "Cash on Delivery" option (`SELECT_COD`). The single "Place Order" click needs the purchase authorisation.

## Known limitations
- Live blinkit.com markup, the location flow, the phone/OTP login and the payment page have **not** been exercised. The real "Proceed"/"Place order" labels may differ, in which case the policy refuses to click them and the run stops safely.
- In headless mode the user cannot complete location or login steps. Use `BROWSER_HEADLESS=false` for a manual hand-over.
