"""Every redirect hop of a download is re-validated (scheme, allow-list, private targets, hop limit)."""

from __future__ import annotations

import uuid
from pathlib import Path

import httpx

from app.browser.navigation_guard import NavigationGuard
from app.integrations.files.downloader import FileDownloader
from app.integrations.files.storage import FileStore

PDF = b"%PDF-1.4\n%fixture\n%%EOF\n"


def _downloader(tmp_path: Path, handler) -> FileDownloader:  # noqa: ANN001
    async def resolver(host: str) -> list[str]:
        return {"files.example.com": ["93.184.216.34"], "cdn.example.com": ["93.184.216.35"]}.get(host, ["10.0.0.9"])

    guard = NavigationGuard(allowed_domains=["example.com"], resolver=resolver)
    store = FileStore(tmp_path / "dl", ttl_hours=1, max_storage_bytes=10_000_000)
    return FileDownloader(store=store, guard=guard, allowed_extensions=["pdf"], max_bytes=1_000_000, max_concurrent=1,
                          transport=httpx.MockTransport(handler))


async def _get(d: FileDownloader, url: str):  # noqa: ANN202
    return await d.download(url, session_id=uuid.uuid4(), task_id=uuid.uuid4())


async def test_redirect_to_private_metadata_or_other_domain_is_blocked(tmp_path: Path) -> None:
    targets = {"/a.pdf": "http://169.254.169.254/latest/meta-data", "/b.pdf": "https://evil.example.org/x.pdf",
               "/c.pdf": "file:///etc/passwd", "/d.pdf": "https://internal.example.com/x.pdf"}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": targets[request.url.path]})

    d = _downloader(tmp_path, handler)
    for path in targets:
        attempt = await _get(d, f"https://files.example.com{path}")
        assert attempt.status.value == "BLOCKED", path
    assert not list((tmp_path / "dl").rglob("*.*"))


async def test_allowed_redirect_chain_works_but_is_bounded(tmp_path: Path) -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "files.example.com":
            return httpx.Response(302, headers={"location": "https://cdn.example.com/report.pdf"})
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})

    assert (await _get(_downloader(tmp_path / "1", ok_handler), "https://files.example.com/report.pdf")).status.value == "COMPLETED"

    def loop(request: httpx.Request) -> httpx.Response:
        n = int(request.url.params.get("n", "0"))
        return httpx.Response(302, headers={"location": f"https://files.example.com/r.pdf?n={n + 1}"})

    attempt = await _get(_downloader(tmp_path / "2", loop), "https://files.example.com/r.pdf")
    assert attempt.status.value == "BLOCKED" and attempt.code == "FILE_TOO_MANY_REDIRECTS"
