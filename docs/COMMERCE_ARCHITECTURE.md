# Commerce architecture (Phase 4)

Phase 4 adds shopping on **Blinkit** and **Amazon India** on top of the Phase 3 browser engine. The LLM (or the offline mock) only *understands* the request. Deterministic, site-specific code does everything else: searching, matching, cart changes, verification, checkout reading and the purchase gate.

```
command ─▶ IntentClassifier (LLM/mock): intent + products/brand/variant/qty/specs/budget/payment
        ─▶ CommercePlanner (trusted): ProductRequirement[] + fixed `commerce` steps
        ─▶ PlanValidator (risk floors, place_order self-gated) ─▶ PLANNED
Run Plan ─▶ ExecutionManager ─▶ PlanExecutor ─▶ CommerceHandler ─▶ CommerceManager
        ─▶ CommerceRegistry (domain-validated) ─▶ BlinkitAdapter | AmazonIndiaAdapter
        ─▶ BrowserController (Phase 3: guard, policy, screenshots) ─▶ Chromium
```

## Plan steps (`CommerceAction.operation`)
| Operation | What it does | Risk |
| --- | --- | --- |
| `open_store` | Open the site; detect CAPTCHA, login and location walls; read the existing cart | LOW |
| `search_products` | Search and rank real listings; **no cart change** | LOW |
| `search_and_add` | Search, match, add **only the missing quantity**, verify on the page | MEDIUM |
| `verify_cart` | Read the real cart; verify each item, quantity and variant; check prices | LOW |
| `checkout_review` | Open checkout; read items, fees, total, masked address and payment options (no purchase) | LOW |
| `place_order` | Exact-order approval, then a single COD submission, or a prepaid handoff | CRITICAL (self-gated) |

Item steps depend only on `open_store` and use `continue_on_failure`, so an unavailable item doesn't stop the others. `verify_cart` then reports the run as **PARTIAL**, and the run ends FAILED rather than complete. Checkout depends on a verified cart.

## Modules (`backend/app/commerce/`)
| Module | Role |
| --- | --- |
| `base.py` | Adapter protocol, `CommerceContext`, `SiteBinding`, `CommerceError` |
| `registry.py` | Platform → adapter, from **validated domains** (blinkit.com, amazon.in) or the exact dev-fixture prefix |
| `commerce_planner.py` | Entities → `ProductRequirement`s → steps (no model-written steps) |
| `commerce_manager.py` | Runs steps, holds per-task `ShoppingSummary`, product-choice pauses, purchase flow, REST operations |
| `adapters/blinkit.py`, `adapters/amazon_india.py` | Site-specific trusted page scripts and locators |
| `search/` | Bounded retries, result parsing (nothing invented), bounded scrolling |
| `matching/` | Deterministic matcher, units and pack sizes, variants and specs |
| `cart/` | Reconciliation (`quantity_manager`), verification, price checks |
| `checkout/` | Review, exact-order approval details, order verification |
| `policies/` | `CommercePolicy` (purpose-scoped clicks), `PurchasePolicy` (COD-only gate), `PriceChangePolicy` |
| `money.py` | INR parsing and formatting with `Decimal` |

## State and API
`ShoppingSummary` (per task) holds the requirements with their observed candidates and matches, any pending product choice, the last cart snapshot, the verification report, the checkout summary, the order state, price changes and warnings. It is served by `GET /tasks/{id}/commerce/summary`, and every `commerce.*` event tells the dashboard to re-fetch it. See [API_CONTRACT.md](API_CONTRACT.md) and [WEBSOCKET_PROTOCOL.md](WEBSOCKET_PROTOCOL.md).

## Verification levels (honest status)
| Level | Status |
| --- | --- |
| 1. Local fixtures (Blinkit-like, Amazon-like) with real Chromium | ✅ automated tests plus a live dashboard run |
| 2. Public-site smoke tests (blinkit.com, amazon.in) | ❌ **not performed**: opt-in only (`COMMERCE_ENABLE_PUBLIC_SMOKE_TESTS`) and needs the user's explicit authorisation |
| 3. Manual user-approved shopping run on the real sites | ❌ not performed |

The adapters target real-site markup, but **they have not run against the live sites**. Treat Blinkit and Amazon support as unverified until levels 2 and 3 are done.

## Phase 6 — purchase protection

* The COD "Place order" click requires consuming the exact-order approval in the database first; a second
  consumption fails (`PURCHASE_APPROVAL_REUSED`) — protects against duplicate queue delivery and retries.
* If the outcome of the order click is uncertain (timeout, crash), the step becomes UNKNOWN and TaskPilot asks
  the user to check the order history; it never clicks again.
* `commerce:search_and_add` is reconcilable: on a retry the cart is inspected first.
* Searches are rate limited per user (`COMMERCE_SEARCHES_PER_MINUTE`). Prepaid payment remains manual.
