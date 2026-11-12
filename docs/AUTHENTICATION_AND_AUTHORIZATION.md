# Authentication and Authorization (Phase 6)

These are **TaskPilot accounts** only. TaskPilot never stores or types the user's passwords for Blinkit,
Amazon, Google or any other website; those sign-ins happen in the browser by the user.

## When authentication is enforced

`auth_enforced = AUTH_REQUIRED or APP_ENV in {staging, production}`. Production additionally refuses to start
unless `AUTH_REQUIRED=true` and `ALLOW_DEV_AUTH_BYPASS=false`. In development with auth off, the API behaves as
in Phase 5 (single implicit user) so local work and the older test suites are unchanged.

## Local accounts

* **Passwords:** Argon2id (`argon2-cffi`), minimum `PASSWORD_MIN_LENGTH` (12). Unknown emails are verified
  against a dummy hash so response timing does not reveal which accounts exist.
* **First user** to register becomes OWNER; later users are MEMBER. `REGISTRATION_ENABLED=false` closes signup;
  `BOOTSTRAP_OWNER_EMAIL/PASSWORD` creates the first OWNER on an empty database.
* **Login throttling:** `AUTH_LOGIN_ATTEMPTS_PER_MINUTE` per email and per client IP (Redis; local fallback
  when Redis is down, reported as degraded).
* **Disable:** a disabled user's access tokens are rejected on the next request; refresh fails.

## Tokens and cookies

| Cookie | Content | Flags |
|---|---|---|
| `tp_access` | JWT HS256, `sub`, `role`, `ver` (token_version), `csrf` digest, 15 min | HttpOnly, Secure (prod), SameSite=Lax, path `/` |
| `tp_refresh` | opaque random token (DB stores SHA-256 only), 7 days | HttpOnly, Secure, path `/api/v1/auth` |
| `tp_csrf` | random CSRF token | readable by JS (double-submit) |

* **Refresh rotation:** each `/auth/refresh` consumes the token and issues a new one in the same family.
  Presenting an already-used token (theft/replay) **revokes the whole family**.
* **Logout** revokes the presented refresh token; **logout-all** bumps `token_version`, invalidating every access
  token and revoking all refresh tokens.
* `Authorization: Bearer` is accepted for API clients (CSRF is not required for bearer requests since
  browsers do not attach it automatically).

## CSRF

Double-submit: mutating requests authenticated by cookie must send `X-CSRF-Token` equal to the `tp_csrf`
cookie **and** matching the digest bound inside the access JWT, so a token planted by a sibling subdomain
cannot be paired with a victim's session.

## Endpoints

`POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `POST /auth/logout`, `POST /auth/logout-all`,
`GET /auth/me`, `GET /auth/config` (public: tells the UI whether to show sign-in). All under `/api/v1`.

## Roles

| Role | Can |
|---|---|
| OWNER | Everything a MEMBER can; audit for all users (`/audit?all_users=true`, export, verify); `/health/details` |
| MEMBER | Create/plan/execute own tasks, decide own approvals, own files, own audit trail |
| READ_ONLY | Read own tasks/history; **every mutating request is rejected** (403 `READ_ONLY_ACCOUNT`) |

## Ownership (enforced centrally)

The auth middleware (`app/auth/authorization.py`) resolves the user and then checks ownership of every
resource named by the request **before the route runs**: `session_id` (query, body or path — first use claims
it), `task_id`, `approval_id`, `file_id`. A session owned by someone else returns 403 `SESSION_ACCESS_DENIED`; another user's
task/approval/file returns 403 `RESOURCE_ACCESS_DENIED`; unknown IDs fall through to the endpoint's own 404.
Client-supplied IDs are never treated as proof of access.
WebSockets authenticate from the cookie during the handshake, check `Origin`, session ownership and the
per-user connection cap (`MAX_WEBSOCKET_CONNECTIONS_PER_USER`).

## OIDC

`AUTH_MODE=oidc` exists as configuration (issuer/client id are validated) but **the OIDC login flow is not
implemented**. Do not select it in production.

## Tests

`tests/security/test_authentication.py`, `test_authorization.py`, `test_csrf.py`, `test_session_isolation.py`,
`test_websocket_security.py`, `test_rate_limits.py`.
