# Browser security (Phase 3)

## Execution only on an explicit click
`POST /tasks/{id}/execute` requires `"confirm_execution": true` (422 otherwise) and is sent only by the **Run Plan** button. The manager re-validates ownership (`TASK_SESSION_MISMATCH` 403), state (`PLANNED`), the plan (`READY`, has steps, not chat) and **re-runs the plan validator** before queueing. Planning code has no path to the browser.

## Navigation guard (`browser/navigation_guard.py`)
Every request in a context passes through `context.route("**/*")`:
- **Top-level navigations** must be `http(s)`, carry no credentials, target an allow-listed domain (`BROWSER_ALLOWED_DOMAINS`, exact or real subdomain: `blinkit.com.evil.example` never matches) and resolve **only to public IP addresses** (cached DNS check with timeout; private, loopback, link-local, CGNAT, multicast and reserved ranges refused).
- **Redirects.** Chromium follows redirects without consulting the interceptor, so main-frame navigations are fetched with `max_redirects=0`. Each `Location` is validated before the browser sees it; an allowed redirect is replayed as a clean 30x to the validated absolute URL, and a disallowed one is aborted (`browser.navigation_blocked`, reason `redirect`). The controller also re-checks the final URL.
- **Sub-resources** (images, scripts, CDNs) may come from any public host, never from private networks or non-web schemes. Embedded frames follow the same sub-resource rule (public hosts only; private targets are aborted and reported).
- **Dev/test origins.** `BROWSER_TEST_ALLOWED_ORIGINS` lists exact local origins (for example the fixture shop at `http://127.0.0.1:8000`). Settings validation rejects it outside `APP_ENV=development|test`, together with `BROWSER_DEV_FIXTURES_ENABLED`.

**Limitations:**
- The browser re-resolves DNS itself after our check, so DNS rebinding is not fully prevented at application level (`route.fetch` also resolves on its own).
- Since Phase 4, **active** sub-resources (scripts, XHR/fetch, event streams and embedded frames) are fetched with redirects disabled, and every `Location` is validated hop by hop (`REDIRECT_BLOCKED`). **Passive** resources (images, fonts, media, stylesheets) are checked on their first URL only; a redirect of those to a private address is still followed by Chromium. Their responses are not readable by page scripts, but the request itself reaches the target.
- Public deployments must also restrict **network egress** at the infrastructure level (firewall or egress proxy denying private ranges and cloud metadata endpoints).

## Runtime action policy (`policies/browser_action_policy.py`)
It is checked immediately before each click or type, against the element actually resolved on the page, not the plan's wording. It cannot be overridden by an approval.
- **Manual-only (hard block):** place/confirm order, pay or "pay now", checkout and "proceed to pay", buy now, payment/order submission, transfer or send money, send email/message, publish, post, delete account or permanently, change/reset password, security or 2FA settings, signing contracts, "confirm and pay". Result: `BLOCKED SENSITIVE_ACTION_BLOCKED`, and the run ends `CANCELLED`.
- **Approval pre-check:** a `request_approval` step looks at the next action first. If that action is hard-blocked, no approval is even requested.
- **Credentials:** no typing into password, OTP, card, CVV, UPI, bank or Aadhaar/PAN-like fields (detected by type, autocomplete, name, label); no typing of credential-like text; no clicking sign-in/verify/continue while a password field is shown. Typed text is capped at 500 characters.
- **Sign-in walls** stop the run with `AUTHENTICATION_REQUIRED`. CAPTCHA, OTP and MFA are never automated or bypassed.

## Downloads and pop-ups
Contexts use `accept_downloads=False`, and every download event is cancelled and reported by sanitised file name only (never the URL). Path helpers refuse traversal and dangerous extensions for future phases. Pop-ups and new windows are closed.

## Privacy
- **Never collected:** input values, cookies, storage, raw HTML. The DOM inspector reports structure, names and redacted text; the ARIA snapshot has field values stripped.
- **Redaction:** telemetry and logs carry URLs without query strings, fragments or credentials. Extracted text is redacted (card numbers, CVVs, OTP/PIN codes, passwords, bearer tokens, API keys).
- **Privacy pause:** no screenshot is captured while a password, OTP or card field is visible. The preview keeps the previous frame and says so.
- Only the latest frame per session is kept in memory. Frames are never written to disk.

## Model-output trust boundary
The LLM produces typed plans only. Selectors are never taken from model text (CSS in a description is just text to match), no model JS is evaluated, and URLs are re-validated at runtime.

## Phase 4 additions
- `BROWSER_MAX_PAGES_PER_SESSION` is enforced: only trusted code (`BrowserManager.new_page`) may open extra pages, up to the limit (`BROWSER_PAGE_LIMIT_REACHED`). Page-created pop-ups are still closed.
- Commerce clicks pass the purpose-scoped `CommercePolicy` *on top of* the unchanged Phase 3 policy. The only purchase path is a COD order with a single-use authorisation. See [CHECKOUT_AND_PURCHASE_SAFETY.md](CHECKOUT_AND_PURCHASE_SAFETY.md).
- Delivery addresses are masked before they reach telemetry, approvals or the UI. Approvals bind to a SHA-256 fingerprint of the full address, which is never stored.

## Phase 6 — browser hardening

* Chromium is launched with the egress proxy (`EGRESS_PROXY_URL`, loopback bypass only); production refuses
  to start without it. Network-level enforcement is not yet verified in a running stack — see
  [NETWORK_SECURITY.md](NETWORK_SECURITY.md).
* Production forbids `BROWSER_PERSIST_SESSIONS`; sessions are CLOSED on restart.
* Container: non-root, `cap_drop: ALL`, `no-new-privileges`, read-only root, tmpfs, memory/pid limits, no Docker
  socket. Chromium still shares the api container (separate browser worker not implemented).
* Browser actions are rate limited per user (`BROWSER_ACTIONS_PER_MINUTE`).

## Network guard modes (`BROWSER_NETWORK_GUARD`)

* `route` (default): every top-level page, script and XHR is re-fetched by the server with redirects disabled so each
  hop is validated. Sites behind bot protection (Blinkit/Cloudflare) reject these non-browser requests (403 on scripts,
  "Just a moment…" pages), so they cannot work in this mode.
* `proxy` (development `.env`): Chromium makes its own requests through a guard proxy — `EGRESS_PROXY_URL` when set,
  otherwise a built-in local proxy (`app/browser/egress_guard_proxy.py`). The proxy resolves each host once, refuses
  the connection unless every address is public, connects to that validated address (DNS-rebinding resistant), allows
  only ports 80/443 (plus the exact trusted dev fixture origins) and sees every redirect hop, iframe, script, XHR and
  WebSocket. Loopback is routed through the proxy too (`<-loopback>`). The allow-list of sites the agent may open is
  still checked on the first URL and again on the final URL after redirects.

## Website security checks

Cloudflare "Just a moment…" pages and CAPTCHAs are detected (`app/browser/bot_check.py`) and never solved or bypassed.
TaskPilot waits up to `BROWSER_HUMAN_CHECK_WAIT_SECONDS` (90) with a visible browser — the check may finish by itself or
you complete it in the window — and otherwise stops with `CAPTCHA_REQUIRED`. Blinkit's delivery-location picker is
handled the same way: you choose the location in the window; TaskPilot never enters an address.
