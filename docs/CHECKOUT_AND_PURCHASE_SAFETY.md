# Checkout and purchase safety

## Checkout review (never purchases)
`checkout_review` requires a **VERIFIED** cart. It clicks only a "Proceed / Proceed to checkout / Proceed to Buy" control (the `OPEN_CHECKOUT` purpose) and reads:
- items and quantities;
- subtotal, delivery, handling, tax, discount and final total, each only if shown;
- the delivery slot and the payment options;
- the **masked** delivery address.

Differences from the verified cart, or a missing total or address, make the review unverified. A sign-in wall stops the run (`COMMERCE_SESSION_REQUIRED`); TaskPilot never types passwords or OTPs.

## The only irreversible action: a cash-on-delivery order
`place_order` runs only when the user asked to order **and** said cash on delivery (`payment_preference: COD`).

1. Select "Cash on Delivery" (`SELECT_COD`: only a COD-labelled option can be clicked). If COD is unavailable or disabled, hand over to the user.
2. Re-read the checkout and create a **real approval with purchase details** through the existing ApprovalService. The `ApprovalRequest.purchase` field carries the items, totals, masked address, payment method, `checkout_id` and `summary_hash`. The dashboard shows it in **PurchaseApprovalDialog** ("KAMLESH BHAI — FINAL PURCHASE REVIEW", "Reject Purchase" / "Confirm This Exact Order"). Enter never approves.
3. On approval, **reload** the checkout page and re-read it. `PurchasePolicy.authorize` issues a single-use authorisation only if all of these hold:
   - COD orders are enabled and prepaid automation is off;
   - the approval is real (not a demo), belongs to this task, is APPROVED, was decided within the TTL and has never been used;
   - this task has never submitted an order;
   - the live summary hash equals the approved hash (items, quantities, line totals, fees, total, address fingerprint and payment method all unchanged);
   - the summary is verified, the total is known and the payment method is COD.
4. A changed checkout (price, address, payment, items) invalidates the approval: `commerce.price_changed` is sent with `approval_invalidated: true` and a **fresh** approval is requested. This happens at most twice, then the run stops.
5. The authorisation is consumed (recorded) **before** the click, and the click marks it used. The "Place (your) order" control is clicked **once**, and only with that authorisation (`PLACE_COD_ORDER`).
6. The order is `CONFIRMED` only when the website visibly shows a confirmation; the order reference is recorded only if shown. Otherwise the state is `UNKNOWN` and the user is asked to check the site. TaskPilot never submits again.

Rejecting places no order and keeps the cart (`PURCHASE_REJECTED` → task CANCELLED). Expiry or Stop also places no order, and the pending approval is withdrawn.

## Prepaid payments (UPI, card, net banking, wallet): always the user
A payment handoff: the checkout is prepared and the verified total shown, then "Please complete the payment manually on the merchant website." TaskPilot never selects a prepaid method, never types card numbers, UPI PINs or OTPs, and never clicks a pay control. `COMMERCE_AUTOMATED_PREPAID_PAYMENT=true` is refused by settings validation.

## Click policy summary (`CommercePolicy`)
| Purpose | Allowed labels |
| --- | --- |
| shopping clicks (add, +/−, open cart, quantity) | anything the unchanged Phase 3 policy allows, minus any payment wording |
| `OPEN_CHECKOUT` | "proceed", "proceed to checkout/buy", "checkout" only |
| `SELECT_COD` | "cash on delivery" / "pay on delivery" / "COD" only |
| `PLACE_COD_ORDER` | "place (your) order" only, with a ready, unused purchase authorisation |
| anything with "pay", "payment", "UPI", "card", "net banking", "wallet", "OTP", "PIN", "CVV" or "bank" | **never**, for any purpose |

Generic plan approvals (Phase 3 `request_approval`) can never authorise a purchase. `place_order` is self-gated by the exact-order approval instead.

## Testing
COD submission has been exercised **only on the local fixture**. Its "orders" are fake confirmations (`FXB-…`, `403-0000000-…`), and the tests assert a submission counter of exactly 1. No real order or payment was made during development or testing.
