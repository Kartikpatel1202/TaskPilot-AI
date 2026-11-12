# Security Threat Model (STRIDE, Phase 6)

## Assets

TaskPilot accounts and sessions · the user's logged-in website sessions inside Chromium (shopping, Gmail, Calendar)
· purchase/draft/event approvals · downloaded files · LLM API keys and `APP_SECRET_KEY` · the audit trail ·
the host network (internal services, cloud metadata).

## Trust boundaries

1. Browser (dashboard) ↔ nginx/API — untrusted client.
2. API ↔ LLM provider — model output is untrusted data.
3. Chromium ↔ websites — page content is untrusted (prompt injection, malicious redirects, downloads).
4. API ↔ PostgreSQL/Redis — trusted network, authenticated.
5. API/Chromium ↔ internet — through the egress proxy.

## STRIDE

| Threat | Example | Mitigations | Residual risk |
|---|---|---|---|
| **S**poofing | Stolen session cookie; credential stuffing | HttpOnly/Secure/SameSite cookies, 15-min access JWT, refresh rotation with family revocation on replay, Argon2id, login throttling, logout-all | No MFA for TaskPilot accounts; OIDC not implemented |
| **S**poofing | Cross-site WebSocket hijacking | Origin allow-list + cookie auth + session ownership on handshake | — |
| **T**ampering | CSRF on Run Plan / approve | Double-submit token bound into the JWT; SameSite=Lax | Bearer clients rely on token secrecy |
| **T**ampering | Approval reused or swapped after review | Snapshot hash of exactly what was shown, one-time DB consumption (`used_at`, version), exact-order COD check | — |
| **T**ampering | LLM replanner escalates action | Replanner output validated; only on-page labels; cannot raise risk or drop approvals; never code | Novel label semantics could mislead the risk check (bounded by approvals) |
| **T**ampering | Audit rows edited | SHA-256 hash chain + verify endpoint | A DB superuser can rewrite the whole chain → export to WORM storage |
| **R**epudiation | "I never approved that order" | Audit events for approval decide/consume and purchase submission with user id + correlation id | Audit retention is manual |
| **I**nformation disclosure | Another user's tasks/files via guessed IDs | Central ownership checks on session/task/approval/file IDs; WS ownership | Single-tenant ops (OWNER) see all audit events |
| **I**nformation disclosure | Secrets in logs/LLM prompts | Redaction for logs, memory and LLM payloads; no field values in evidence; secrets via env only | Redaction is pattern-based |
| **I**nformation disclosure | SSRF to metadata/internal services | App-level IP/DNS/redirect checks, DNS-pinned downloads, egress proxy with deny-lists, `internal` networks | **Network enforcement not yet verified in a running stack** |
| **D**enial of service | Flooding planning/LLM; huge bodies | Per-user Redis rate limits, bounded queues (503 when full), body limits, nginx limits, circuit breakers, LLM daily token budget | Single api replica; Chromium is memory-heavy (load test shows the limits) |
| **E**levation of privilege | Prompt injection in a web page makes the agent buy/send | Actions only from validated plans; sensitive steps require explicit approval; Gmail send blocked; prepaid payments never automated; CAPTCHA/OTP never solved | Users can still approve a bad action they misread |
| **E**levation of privilege | Chromium exploit escapes to the API | Non-root container, cap_drop ALL, no-new-privileges, read-only root, no Docker socket, egress-only network | **Chromium shares the api container** (separate worker not implemented) |
| **E**levation of privilege | READ_ONLY user mutates | Middleware rejects all mutations for READ_ONLY | — |

## Out of scope / accepted

* Compromise of the user's own device or browser.
* Malicious OWNER.
* Website-side fraud (e.g. a seller changing an item after delivery).

## Security tests

`backend/tests/security/` — 16 files covering authentication, authorization, CSRF, session isolation, WebSocket
security, rate limits, SSRF, DNS rebinding, redirects, execution recovery, idempotency, approval integrity, file
security, prompt injection, sensitive-data redaction and browser isolation.
