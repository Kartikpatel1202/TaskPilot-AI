# Agent safety

## Planning versus execution
- **Planning never executes.** The planner and orchestrator have no path to the browser and never transition a task to `EXECUTING`. Planning never launches Chromium.
- **Execution needs an explicit click.** Phase 3 runs a plan in Playwright/Chromium only via `POST /tasks/{id}/execute` with `confirm_execution: true`, sent by the **Run Plan** button. The plan is re-validated at that moment. `AGENT_BROWSER_EXECUTION_ENABLED=false` disables it (503).
- Model output is data. Selectors are never taken from model text, no model JS/CSS is evaluated, URLs are re-checked at runtime. There is still no shell, Python or arbitrary code execution.
- The UI marks steps *Planned* until they run, then shows only observed results (a click without a visible effect says so). It never shows a fake browser page or fake progress; the preview shows real screenshots or an honest empty state.

## Prompt-injection defences (layered)
1. **Input guard.** `policies/input_guard.py` checks a small, conservative pattern list before any LLM call and rejects obvious attempts:
   - ignoring or overriding instructions, or revealing the system prompt;
   - API keys, secrets, environment variables and server files;
   - shell or code execution;
   - other sessions' data;
   - hacking, phishing or bypassing OTPs.
2. **Data-only payload.** User text never becomes part of the instructions. It travels in a delimited JSON payload that the system prompt declares to be untrusted data.
3. **System rules.** The rules forbid changing the rules, revealing internals, running code, creating tools, typing credentials, inventing data and skipping approvals.
4. **Structured outputs.** Strict JSON schemas, a discriminated union of six actions, and Pydantic re-validation of every field.
5. **Deterministic checks.** Plan validation, URL policy, risk floors and approval-gate enforcement are applied regardless of what the model says. A model-claimed "LOW" risk is never trusted.
6. **Output sanitisation.**
   - Control and bidi characters are removed from model text and length limits are applied.
   - Replies that claim completion ("added to your cart", "order placed", "email sent", "cart mein add kar diya") are replaced with a safe template.
7. **Bounded inputs.** A 4,000-character command limit, 25-step plans, bounded memory and a bounded queue.

There is no `eval` or `exec` anywhere, and no dynamic imports based on model output.

## Risk classification
`policies/risk_classifier.py` computes a floor for each step from what is clicked or typed. It looks at the target description, accessible name and text hint, not at the model's prose. The final risk is `max(model, rule)`, so rules can raise risk but never lower it.

| Example | Risk |
| --- | --- |
| Open a site, search, read results | LOW |
| Add to cart, edit a draft, update a quantity | MEDIUM |
| Send, submit, publish, book, create an event, download | HIGH |
| Place an order, pay, checkout, transfer, delete | CRITICAL |

## Approval policy
Every HIGH or CRITICAL step must be preceded by a `request_approval` step of at least equal risk. The step must depend on that gate and be flagged `requires_approval`. Missing gates are inserted automatically, and the validator checks the result independently.

```
ACTION ─► REQUEST APPROVAL ─► wait for a human
                                 ├─ APPROVED ─► execution resumes; the runtime policy re-checks the next action
                                 ├─ REJECTED ─► run CANCELLED (APPROVAL_REJECTED)
                                 └─ no answer ─► run CANCELLED (APPROVAL_EXPIRED); Stop withdraws it
```

During execution a checkpoint first pre-checks the next action: if it is manual-only (pay, place order, checkout, send…) the run stops **without** asking. Otherwise a real approval request (`is_demo: false`) is raised and the task waits in `WAITING_APPROVAL`. An approval never unlocks a manual-only action — see [BROWSER_SECURITY.md](BROWSER_SECURITY.md).

## URL restrictions
`policies/url_policy.py` (planning stage) behaves as follows:
- It accepts only `http` and `https`, so `javascript:`, `file:`, `data:` and `ftp:` are rejected.
- It rejects URLs that:
  - embed credentials;
  - point to `localhost`, `*.localhost`, `.local`, `.internal`, `.lan` or single-label hosts;
  - point to loopback, private, link-local, reserved, multicast or unspecified IPs, including IPv4-mapped IPv6;
  - use integer, hex or octal IP shorthand;
  - are malformed or contain whitespace or backslashes.
- It normalises the scheme and host (lowercase, IDNA) and drops fragments.

Phase 3 must re-check every URL immediately before navigating. That check needs to cover DNS resolution to private addresses and redirects, because a public-looking hostname can resolve anywhere.

## Sensitive information
- Credentials are typed by the user, never the agent. Plans that type into password, OTP, PIN, card, CVV, UPI, bank or ID fields, or that set `sensitive: true`, are rejected.
- Free text is redacted before it is stored in memory, logged or sent to an LLM. This covers card numbers, OTPs, CVVs, passwords, bearer tokens and keys.
- API keys are `SecretStr` values. They never appear in logs or responses and are never sent to the frontend.
- Provider errors reach clients only as safe messages with a code. SDK details stay in server logs.
- Prompts, hidden reasoning and token usage are never included in API responses or telemetry.

## Phase 3 runtime safety (summary)
- Runtime `BrowserActionPolicy` before every click/type, judged on the element actually found on the page.
- Navigation allow-list + public-IP check + validated redirects; downloads cancelled; pop-ups closed.
- No typing into password/OTP/card/bank fields, no credential-like text, no sign-in submission; sign-in walls stop the run (`AUTHENTICATION_REQUIRED`).
- No screenshots while sensitive fields are visible; URLs without query strings in telemetry; extracted text redacted.
- Full details: [BROWSER_SECURITY.md](BROWSER_SECURITY.md).

## Phase 4 commerce safety (summary)
- The LLM only extracts requirements. Commerce steps, matching scores, cart changes and the purchase gate are deterministic, trusted code.
- Nothing is invented: unknown prices, fees, ratings, sellers and availability stay unknown. Ambiguous or uncertain products are chosen by the user.
- No duplicate additions (live-quantity reconciliation), no removal of unrelated items, and a verified cart is required before checkout.
- The **only** irreversible action is a COD order. It needs the user's explicit COD request, an exact-order approval bound to the observed summary hash, a reload and re-check, and a single-use authorisation, with exactly one click. Any change requires a fresh approval.
- Prepaid payments are always handed to the user. CAPTCHA, location, login and OTP are never automated.
- Details: [CHECKOUT_AND_PURCHASE_SAFETY.md](CHECKOUT_AND_PURCHASE_SAFETY.md).

## Phase 5 integration safety (summary)
- **No email is ever sent.** Gmail steps save and verify a draft; Send/Schedule send/Discard controls are refused for
  every purpose; send/attachment settings are locked off. Recipients must be addresses the user wrote.
- **No calendar event without approval of that exact event.** The approval is bound to a SHA-256 of every event field;
  the live form must match before Save; the authorization is single-use; creation is verified or reported UNKNOWN.
  Deletion/modification of events is not implemented and is locked off in settings.
- **No dangerous downloads.** Allow-listed domains and types only, hop-by-hop redirect checks, MIME + magic +
  macro checks, size/storage caps, isolated storage, never executed; YouTube video downloads are refused.
- **No sign-in automation.** Sign-in pages, password fields and "confirm you're not a bot" gates stop the step with
  `*_LOGIN_REQUIRED` / `CAPTCHA_REQUIRED`; the user acts personally.
- **Truthful results.** Only observed outcomes count: PLAYING needs advancing playback time, drafts must appear in
  Drafts, events must appear on the calendar; partial workflows are reported as partial.

## Phase 6 — safety invariants preserved and extended

* Approvals are one-time and DB-consumed; COD purchase approval is bound to the exact order snapshot and cannot
  be reused (`PURCHASE_APPROVAL_REUSED`). Restart or cancel → pending approvals become **WITHDRAWN**.
* Non-idempotent actions are never silently repeated: duplicate deliveries skip SUCCEEDED steps; uncertain
  mutating steps become UNKNOWN and stop the run.
* The self-correction replanner cannot raise risk, remove approvals, change action types or run code.
* Still never: Gmail send, automated prepaid payment, CAPTCHA/OTP/MFA solving, storing website passwords,
  executing LLM-generated code or arbitrary JavaScript.
