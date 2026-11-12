# Safe file downloads

Downloads never go through the browser's download manager (contexts keep `accept_downloads=False`).
`integrations/files/downloader.py` fetches validated URLs with `httpx` and stores files privately.
**Downloaded files are never opened, rendered or executed by TaskPilot.**

## Where a download may come from

- Every hop (initial URL and each redirect, max 3, followed manually) is checked by a dedicated
  `NavigationGuard`: http(s) only, no credentials in URLs, no local/private address literals, the host
  must be in `FILE_DOWNLOAD_ALLOWED_DOMAINS` (exact or subdomain) **and** resolve only to public IPs.
- Default `FILE_DOWNLOAD_ALLOWED_DOMAINS=` (empty) → no real-site downloads until an operator lists domains.
- Development/test only: the exact fixture origin (`BROWSER_TEST_ALLOWED_ORIGINS`, with
  `INTEGRATION_ENABLE_FIXTURES=true`).
- When the URL is a page, the link is located in the session browser (guarded navigation) among links of an
  allowed type; if several match, the user chooses.
- YouTube video downloads are refused at planning time.

## What may be stored

1. **Name:** sanitised (no path parts); final extension must be in `FILE_DOWNLOAD_ALLOWED_EXTENSIONS`
   (default `pdf,txt,csv,png,jpg,jpeg,webp,docx,xlsx,pptx`). Executables, scripts, active content
   (`.exe .msi .bat .ps1 .js .sh .jar .apk .dll .html .svg .docm …`) and **any** dangerous inner extension
   (`invoice.exe.pdf`) are refused; archives (`.zip .rar .7z .tar .gz …`) are refused
   (`FILE_DOWNLOAD_ALLOW_ARCHIVES/EXECUTABLES=true` are rejected by settings validation).
2. **Content-Type** must match the extension (generic `application/octet-stream` falls back to the magic check;
   `text/html` for a `.pdf` — typically a login page — is refused).
3. **Size:** `Content-Length` pre-check and a hard streaming cap (`FILE_DOWNLOAD_MAX_SIZE_MB`, default 25);
   total storage cap `FILE_DOWNLOAD_MAX_STORAGE_MB`.
4. **Magic:** executable signatures (`MZ`, ELF, Mach-O, `#!`) are refused for every type, early in the stream;
   PDF/PNG/JPEG/WebP signatures must match; text/CSV must be UTF-8 without NUL bytes; Office files must be
   real OOXML containers without macros or embedded programs.
5. Rejected or interrupted downloads are deleted (`.part` files never remain).

## Storage

`<FILE_DOWNLOAD_STORAGE>/<sha256(session)[:24]>/<file_id>.<ext>` with owner-only permissions (0600; no execute
bit), outside the web root and git (`runtime/` is ignored). An in-memory registry keeps metadata
(name, type, size, SHA-256, source domain, expiry). Files expire after `FILE_DOWNLOAD_TTL_HOURS` and are
deleted on the next access. Paths never appear in APIs, telemetry or logs.

## APIs (owner session only)

- `GET /files?session_id=` — list; `GET /files/{id}?session_id=` — metadata;
- `GET /files/{id}/download?session_id=` — attachment with `X-Content-Type-Options: nosniff`,
  `Content-Security-Policy: sandbox`, `Cache-Control: no-store`;
- `DELETE /files/{id}` with `{session_id, confirm: true}` — permanent delete (400 without `confirm`).

Another session gets 403; unknown files 404.

## Residual risks

- **DNS rebinding:** `httpx` resolves the host again after the guard's check. Production deployments must
  also restrict egress (firewall/proxy) — the same caveat as the browser guard.
- Files are validated, not virus-scanned. Users should still treat downloads from the internet with care.

## Events

`file.download_started`, `file.download_progress` (every 256 KB), `file.validation_completed`,
`file.download_completed`, `file.download_blocked`, `file.download_failed`.
