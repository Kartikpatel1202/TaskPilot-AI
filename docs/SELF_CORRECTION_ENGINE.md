# Self-Correction Engine (Phase 6)

When a browser step fails because the page changed, TaskPilot tries a **small, bounded, verifiable** fix
instead of failing immediately. It never trades safety for success.

## Components

| Module | Role |
|---|---|
| `browser/mutation_monitor.py` | Ring buffer (`DOM_MUTATION_BUFFER_SIZE`) of DOM changes observed via a MutationObserver installed by trusted code |
| `browser/selector_memory.py` | Per-site memory of selectors that worked (`SELECTOR_CACHE_TTL_MINUTES`); invalidated on failure |
| `agent/self_correction/failure_classifier.py` | Maps an error + evidence to a `FailureType` (SELECTOR_NOT_FOUND, SELECTOR_AMBIGUOUS, DOM_CHANGED, AUTHENTICATION_REQUIRED, RATE_LIMITED, PRICE_CHANGED, …) |
| `agent/self_correction/evidence_builder.py` | Redacted evidence: URL host/path, visible candidate labels, recent mutations — no field values |
| `agent/self_correction/recovery_policy.py` | Which failure types are recoverable, and how |
| `browser/recovery_engine.py` | Runs the bounded loop |
| `agent/self_correction/replanner.py` | Optional LLM suggestion of a replacement target |

## Loop

1. A click/type raises `SelectorResolutionError` (**never** on ambiguity — ambiguous matches always stop).
2. Classifier decides the failure type. Non-recoverable types (AUTHENTICATION_REQUIRED, APPROVAL_REQUIRED,
   PRICE_CHANGED, WEBSITE_BLOCKED, RATE_LIMITED…) stop and ask the user.
3. **Deterministic relabel match:** synonym/normalised matching over visible candidates. Accepted only if
   exactly one candidate scores ≥ 0.67 with a margin ≥ 0.2 over the next, **and** `replacement_allowed` holds
   (the new label is not riskier, e.g. "Add" may not become "Buy now"/"Place order"/"Delete").
4. Otherwise, the **replanner** may ask the LLM for a replacement. Its output is schema-validated, and:
   * it may only name a candidate that actually exists on the page;
   * it can never raise risk, remove an approval, or change the action type;
   * it never yields code or JavaScript — only a target label;
   * non-idempotent steps are not re-attempted if the first attempt may have taken effect (journal state);
   * skipped entirely for the offline mock provider.
5. Bounds: `SELF_CORRECTION_MAX_ATTEMPTS` (2), `SELF_CORRECTION_MAX_REPLANS` (2),
   `SELF_CORRECTION_MAX_TIME_SECONDS` (60). Every attempt emits telemetry and
   `taskpilot_selector_recovery_total` / `_success_total`.

## Tests

`tests/resilience/test_self_correction.py` — scenario 3: a fixture page (`relabel.html`) renames a button after
load; the step recovers via deterministic match; a riskier relabel is refused; an ambiguous page stops.
