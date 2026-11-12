# Playwright controller (Phase 3)

`BrowserController` (`backend/app/browser/controller.py`) is the only code that acts on a page. Handlers call it; nothing evaluates model-provided code, CSS or selectors.

## Navigation
1. `NavigationGuard.check_navigation(url)`: scheme, credentials, allow-list (or exact dev/test origin) and DNS resolving to public addresses only.
2. `page.goto(url, wait_until="domcontentloaded")`; a best-effort `load` wait follows.
3. The final URL is re-validated. If a redirect was refused, the controller waits for Chrome's error page to commit (so it can't interrupt the next navigation) and raises `NavigationBlockedError`.
4. A login page (password or OTP field, or a `/login`-style path) stops the run with `AUTHENTICATION_REQUIRED`. TaskPilot never types credentials.

## Element resolution (`SelectorResolver`)
The plan only *describes* targets (`target_description`, `role_hint`, `accessible_name`, `text_hint`). Resolution order:
1. **Exact strategies**: role + accessible name, label, placeholder, visible text. A single exact match must still fit the description's context.
2. **Semantic scoring** over a fresh `DOMInspector` snapshot:
   `score = 0.5 × name match + 0.2 × role compatibility + 0.3 × context match`.
   The best candidate must reach `BROWSER_SELECTOR_MIN_CONFIDENCE` (0.82) and beat the runner-up by ≥ 0.05, otherwise `SELECTOR_AMBIGUOUS` (nothing is clicked).
3. **Bounded healing**: up to `BROWSER_SELECTOR_MAX_ATTEMPTS` re-inspections with a short growing wait, for late-rendering pages.

The only CSS ever built is `[data-tp-id="tp-N"]`, matching `^tp-\d{1,7}$` (ids set by the trusted inspector). A cache keyed by site path + description stores `(role, name)` only and is always revalidated.

Acceptance checks: exactly one match, visible, enabled (`ELEMENT_DISABLED` otherwise), editable for typing.

## Actions
| Action | Behaviour | Verification | Retries |
| --- | --- | --- | --- |
| navigate | guarded `goto` | final URL allowed | 1 retry on timeout |
| click | resolve → **policy** → `locator.click()` | URL change or DOM mutations (MutationObserver) | **never** (a timeout is not proof either way) |
| type | resolve (editable) → **policy** → `fill` | `input_value` equals the expected text | none |
| extract | region extraction mapped to the requested fields | items found; missing fields reported as `null` | bounded settle re-reads (≤ 5 × 0.6 s) |
| request_approval | pre-checks the next action; a hard-blocked action is refused **without** asking | — | — |
| stop | ends the plan | — | — |

Search fields submit with Enter unless the next step clicks a search or submit button.

## Extraction output
```json
{ "source": "observed_dom", "container": "Search results for milk", "item_count": 3,
  "items": [{ "name": "Amul Taaza Toned Milk", "pack size": "1 L", "price": "₹54" }],
  "missing_fields": [] }
```
All text is redacted (card numbers, CVVs, OTP/PIN codes, passwords, tokens) before it leaves the browser layer. Elements containing a password field are skipped.

## Errors
`BrowserError` subclasses carry stable codes: `BROWSER_UNAVAILABLE`, `BROWSER_SESSION_NOT_FOUND`, `BROWSER_SESSION_LIMIT_REACHED`, `BROWSER_CRASHED`, `NAVIGATION_BLOCKED`, `NAVIGATION_FAILED`, `SELECTOR_NOT_FOUND`, `SELECTOR_AMBIGUOUS`, `ELEMENT_DISABLED`, `SENSITIVE_ACTION_BLOCKED`, `ACTION_TIMEOUT`, `ACTION_NOT_SUPPORTED`, `AUTHENTICATION_REQUIRED`, `SCREENSHOT_FAILED`, `EXTRACTION_EMPTY`. Messages are safe for the UI and never contain stack traces or secrets.
