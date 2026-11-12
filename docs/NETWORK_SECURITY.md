# Network Security and SSRF (Phase 6)

## Layers

1. **Application checks (verified by tests).** `NavigationGuard` and the download guard resolve hostnames and
   reject loopback, RFC 1918 private, link-local (incl. `169.254.169.254` metadata), CGNAT, multicast, reserved,
   IPv6 ULA/link-local, IPv4-mapped IPv6, and encoded forms (decimal `2130706433`, octal `0177.0.0.1`, hex
   `0x7f.1`, short `127.1`). Redirects are re-validated hop by hop.
2. **DNS pinning for downloads (verified by tests).** `integrations/files/pinned_transport.py` resolves once,
   validates every resolved address, and connects to the validated IP (with SNI/Host set to the original name).
   A second, rebinding DNS answer is never used.
3. **Network egress proxy (configured, NOT verified end-to-end).** In `docker-compose.prod.yml` the api has no
   direct internet route; `deployment/egress/squid.conf` denies private/loopback/link-local/metadata destinations
   **after resolution**, permits only ports 80/443, and strips forwarding headers. Chromium is launched with
   `proxy={"server": EGRESS_PROXY_URL, "bypass": "<-loopback>"}`; httpx downloads use the same proxy.

## What is and is not verified

| Claim | Status |
|---|---|
| Guard rejects loopback/private/link-local/metadata/encoded IPs | VERIFIED (tests/security/test_ssrf.py) |
| DNS rebinding between check and connect is defeated for downloads | VERIFIED (test_dns_rebinding.py) |
| Redirect to an internal address is refused | VERIFIED (test_redirect_security.py) |
| Chromium is launched with the egress proxy | VERIFIED (launch options captured in test_browser_isolation.py) |
| Production refuses to start without an egress proxy | VERIFIED |
| Squid actually blocks internal destinations in a running stack | **NOT VERIFIED** — Docker daemon unavailable |
| No other process in the container bypasses the proxy | **NOT VERIFIED** (relies on `internal: true` network) |

**SSRF is therefore mitigated at the application layer, and network-level enforcement is designed but not
yet demonstrated.** Do not describe SSRF as fully prevented until the compose stack has been launched and the
checks in [PRODUCTION_DEPLOYMENT.md](PRODUCTION_DEPLOYMENT.md#post-deploy-verification) pass.

## Chromium-specific notes

* NavigationGuard intercepts every request of a browser context (`context.route("**/*")`), including
  subresources, and re-validates each redirect hop of active content. However, the guard resolves DNS itself and
  Chromium resolves again when it connects, so a rebinding DNS server could answer differently in between. Only
  the egress proxy (which checks the address it actually connects to) closes that window — this is why the proxy
  is mandatory in production.
* WebRTC/UDP from pages is not specifically restricted by TaskPilot; in the production network layout UDP has no
  route out of the `egress` network, but this was not tested.

## HTTP hardening

API responses carry `X-Content-Type-Options`, `X-Frame-Options: DENY`, `Referrer-Policy`, a restrictive
`Content-Security-Policy: default-src 'none'` and `Cache-Control: no-store` on API responses. nginx adds HSTS and
the frontend CSP (`deployment/nginx/security.conf`). Request bodies are capped (`MAX_REQUEST_BODY_BYTES`, nginx
`client_max_body_size 1m`). CORS is an explicit origin list with credentials.
