"""Safe file downloader (Phase 5).

Every hop is validated before it is requested (scheme, credentials, private/local literals,
the FILE_DOWNLOAD_ALLOWED_DOMAINS allow-list — or, in dev/test only, the exact fixture origin —
and a public-DNS check). Redirects are followed manually (max 3), each re-validated. The body
is streamed to a `.part` file with a hard size cap and SHA-256, then validated (type, MIME,
magic, Office macros) before it is renamed into place. Rejected files are deleted.

Residual risk (documented in docs/FILE_DOWNLOAD_SECURITY.md): the HTTP client resolves DNS
again after our check (DNS rebinding); production deployments must also restrict egress.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from collections.abc import Awaitable, Callable
from urllib.parse import urljoin, urlsplit
from uuid import UUID, uuid4

import httpx

from app.browser.navigation_guard import NavigationGuard
from app.integrations.files.storage import FileStore
from app.integrations.files.validator import (
    FileValidationError,
    check_content_type,
    check_magic,
    check_name,
    check_office,
    filename_from,
)
from app.schemas.common import utc_now
from app.schemas.files import DownloadAttempt, DownloadedFile, DownloadStatus

Progress = Callable[[int, int | None], Awaitable[None]]
MAX_REDIRECTS = 3
SNIFF_BYTES = 8192


class FileDownloader:
    def __init__(self, *, store: FileStore, guard: NavigationGuard, allowed_extensions: list[str], max_bytes: int,
                 max_concurrent: int, timeout: float = 30.0, transport: httpx.AsyncBaseTransport | None = None,
                 proxy: str | None = None) -> None:
        self.store = store
        self.guard = guard
        self.allowed_extensions = allowed_extensions
        self.max_bytes = max_bytes
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._timeout = timeout
        self._transport = transport
        self._proxy = proxy or None

    async def validate_url(self, url: str) -> tuple[str, str]:
        """(normalised url, host) — or FileValidationError."""
        decision = await self.guard.check_navigation(url)
        if not decision.allowed:
            code = "FILE_DOMAIN_NOT_ALLOWED" if decision.code == "DOMAIN_NOT_ALLOWED" else "FILE_URL_BLOCKED"
            raise FileValidationError(code, decision.message or "This download address is not allowed.")
        return decision.url, decision.domain or ""

    async def download(self, url: str, *, session_id: UUID, task_id: UUID, on_progress: Progress | None = None,
                       suggested_name: str | None = None) -> DownloadAttempt:
        async with self._semaphore:
            try:
                return await self._download(url, session_id=session_id, task_id=task_id, on_progress=on_progress, suggested_name=suggested_name)
            except FileValidationError as exc:
                return DownloadAttempt(status=DownloadStatus.BLOCKED, message=exc.message, code=exc.code, source_domain=_host(url))
            except (httpx.HTTPError, OSError) as exc:
                code = "FILE_DOWNLOAD_TIMEOUT" if isinstance(exc, httpx.TimeoutException) else "FILE_DOWNLOAD_FAILED"
                return DownloadAttempt(status=DownloadStatus.FAILED, message="The download failed (network or storage error).",
                                       code=code, source_domain=_host(url))

    async def _download(self, url: str, *, session_id: UUID, task_id: UUID, on_progress: Progress | None,
                        suggested_name: str | None) -> DownloadAttempt:
        current, host = await self.validate_url(url)
        transport = self._transport
        if transport is None and self._proxy is None:
            from app.integrations.files.pinned_transport import PinnedNetworkBackend, pinned_transport

            trusted = [urlsplit(o).netloc for o in self.guard.trusted_origins]
            transport = pinned_transport(PinnedNetworkBackend(trusted_hosts=trusted))
        async with httpx.AsyncClient(follow_redirects=False, timeout=self._timeout, trust_env=False, transport=transport, proxy=self._proxy,
                                     headers={"User-Agent": "TaskPilot-SafeDownloader/1.0", "Accept-Encoding": "identity"}) as client:
            for _ in range(MAX_REDIRECTS + 1):
                async with client.stream("GET", current) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise FileValidationError("FILE_DOWNLOAD_FAILED", "The server sent a redirect without a target.")
                        current, host = await self.validate_url(urljoin(current, location))
                        continue
                    if response.status_code != 200:
                        return DownloadAttempt(status=DownloadStatus.FAILED, code="FILE_DOWNLOAD_FAILED", source_domain=host,
                                               message=f"The server answered HTTP {response.status_code}.")
                    return await self._receive(response, current, host, session_id, task_id, on_progress, suggested_name)
        raise FileValidationError("FILE_TOO_MANY_REDIRECTS", "Too many redirects; the download was stopped.")

    async def _receive(self, response: httpx.Response, url: str, host: str, session_id: UUID, task_id: UUID,
                       on_progress: Progress | None, suggested_name: str | None) -> DownloadAttempt:
        raw_name = filename_from(urlsplit(url).path, response.headers.get("content-disposition"))
        if suggested_name and "." not in raw_name:
            raw_name = suggested_name
        name, ext = check_name(raw_name, self.allowed_extensions)
        mime = check_content_type(response.headers.get("content-type"), ext)
        declared = response.headers.get("content-length")
        total = int(declared) if declared and declared.isdigit() else None
        if total is not None and total > self.max_bytes:
            raise FileValidationError("FILE_TOO_LARGE", f"The file is larger than the {self.max_bytes // (1024 * 1024)} MB limit.")
        if self.store.used_bytes() + (total or 0) > self.store.max_storage_bytes:
            raise FileValidationError("FILE_STORAGE_FULL", "Download storage is full; delete old files first.")
        file_id = uuid4()
        part = self.store.path_for(session_id, file_id, ext, partial=True)
        digest = hashlib.sha256()
        received = 0
        head = b""
        kept: list[bytes] = []
        last_report = 0
        try:
            with open(part, "wb") as out:
                async for chunk in response.aiter_bytes():
                    received += len(chunk)
                    if received > self.max_bytes:
                        raise FileValidationError("FILE_TOO_LARGE", f"The file exceeded the {self.max_bytes // (1024 * 1024)} MB limit; it was deleted.")
                    if len(head) < SNIFF_BYTES:
                        head = (head + chunk)[:SNIFF_BYTES]
                        if len(head) >= SNIFF_BYTES:
                            check_magic(head, ext)  # stop early: never keep streaming an executable
                    if ext in ("docx", "xlsx", "pptx"):
                        kept.append(chunk)
                    digest.update(chunk)
                    out.write(chunk)
                    if on_progress is not None and received - last_report >= 256 * 1024:
                        last_report = received
                        await on_progress(received, total)
            if received == 0:
                raise FileValidationError("FILE_EMPTY", "The server sent an empty file.")
            check_magic(head, ext)
            check_office(b"".join(kept), ext)
            if self.store.used_bytes() + received > self.store.max_storage_bytes:
                raise FileValidationError("FILE_STORAGE_FULL", "Download storage is full; delete old files first.")
            final = self.store.path_for(session_id, file_id, ext)
            part.replace(final)
        except BaseException:
            with contextlib.suppress(OSError):
                part.unlink()
            raise
        meta = DownloadedFile(
            file_id=file_id, session_id=session_id, task_id=task_id, original_name=name, stored_name=f"{file_id}.{ext}",
            extension=ext, mime_type=mime, size_bytes=received, sha256=digest.hexdigest(), source_domain=host,
            status=DownloadStatus.COMPLETED, created_at=utc_now(), expires_at=self.store.expires_at(),
            validation=["extension allowed", "content type consistent", "file signature verified", "size within limit",
                        "stored outside the web root; never executed"],
        )
        self.store.add(meta, final)
        if on_progress is not None:
            await on_progress(received, total)
        return DownloadAttempt(status=DownloadStatus.COMPLETED, message=f"Downloaded {name} ({_size(received)}), SHA-256 verified.",
                               file=meta, source_domain=host)


def _host(url: str) -> str | None:
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def _size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


size_label = _size
