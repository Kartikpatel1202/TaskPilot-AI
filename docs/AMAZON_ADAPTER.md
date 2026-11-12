# Amazon India adapter

`backend/app/commerce/adapters/amazon_india.py` · Site: https://www.amazon.in · **Status: verified only against the local Amazon-like fixture. Not run on amazon.in.**

## Selectors (amazon.in conventions, mirrored by the fixture)
| Purpose | Selector |
| --- | --- |
| Search box / submit | `#twotabsearchtextbox` (+ Enter) |
| Results | `[data-component-type="s-search-result"][data-asin]` |
| Title / link | `h2 span`, `h2 a[href]` |
| Price / M.R.P. | `.a-price:not(.a-text-price) .a-offscreen`, `.a-price.a-text-price .a-offscreen` |
| Rating / reviews / delivery | `.a-icon-alt`, `.s-underline-text`, `[data-cy="delivery-recipe"]` |
| Product page | `#productTitle`, `#corePriceDisplay_desktop_feature_div .a-offscreen`, `#availability`, `#sellerProfileTriggerId`, `#productOverview_feature_div` rows |
| Add to cart | `#quantity` select, `#add-to-cart-button`, confirmation `#NATC_SMART_WAGON_CONF_MSG_SUCCESS` or `#nav-cart-count` |
| Cart | `#sc-active-cart [data-asin]` (`data-quantity`), `.sc-product-title`, `.sc-product-price`, `select[name=quantity]`, `#sc-subtotal-amount-activecart` |
| Checkout | `input[name=proceedToRetailCheckout]` ("Proceed to Buy"), `#deliver-to-address-text`, `#subtotals-marketplace-table`, payment radios, `input[name=placeYourOrder1]` ("Place your order") |
| Blockers | `form[action*=validateCaptcha]` / "Enter the characters you see below"; sign-in `#ap_email` / password |

## Behaviour
- **Listings:** brand and seller are **not** inferred from titles. They appear only where the page shows them (seller on the product page). Ratings, reviews, delivery and M.R.P. are taken only when shown.
- **Specs:** RAM, storage and colour are read from the title and the product-overview table. A contradiction (8 GB when 16 GB was asked) disqualifies the candidate; a spec that can't be confirmed needs the user's confirmation. The product page is **re-validated** before adding (title match plus specs). A mismatch gives `COMMERCE_VARIANT_MISMATCH` and nothing is added.
- **Budget:** any listing priced above the budget is excluded. Listing prices are never presented as the final checkout price.
- **Quantity:** chosen in `#quantity` before "Add to Cart". The cart count is checked afterwards, and a timeout is resolved by reading the count, not by clicking again.
- **Cart:** the cart page shows only the item subtotal, so delivery, fees and total stay unknown until checkout.
- **Checkout:** a sign-in wall stops the run (`COMMERCE_SESSION_REQUIRED`). Only "Cash on Delivery/Pay on Delivery" is ever selected automatically. "Pay …" and any other payment control is never clicked.

## Known limitations
- Live amazon.in has **not** been exercised. Expect sign-in, CAPTCHA, sponsored-result and A/B layout differences; each one stops the run safely.
- Variation pickers (twister) are read on the product page but are not clicked to *switch* variants. If the listing isn't the requested configuration, the run fails and asks the user rather than switching on its own.
