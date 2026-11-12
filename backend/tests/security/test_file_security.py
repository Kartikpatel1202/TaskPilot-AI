"""File security (Scenario 9): interrupted downloads are never published, retries validate checksums,
quotas apply per user, malware scanning is reported honestly, and only the owner can fetch a file."""

from __future__ import annotations

import hashlib
import uuid
from pathlib import Path

import httpx

from app.browser.navigation_guard import NavigationGuard
from app.integrations.files.downloader import FileDownloader
from app.integrations.files.scanner import ClamAVScanner, NullScanner, ScanResult
from app.integrations.files.storage import FileStore

PDF = b"%PDF-1.4\n" + b"0" * 300_000 + b"\n%%EOF\n"


def _guard() -> NavigationGuard:
    async def resolver(host: str) -> list[str]:
        return ["93.184.216.34"]

    return NavigationGuard(allowed_domains=["example.com"], resolver=resolver)


class _Interrupting(httpx.AsyncByteStream):
    async def __aiter__(self):  # noqa: ANN204
        yield PDF[:100_000]
        raise httpx.ReadError("connection reset mid-download")


async def test_scenario9_interrupted_download_is_not_published_and_retry_is_verified(tmp_path: Path) -> None:
    store = FileStore(tmp_path / "dl", ttl_hours=1, max_storage_bytes=10_000_000)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, headers={"content-type": "application/pdf", "content-length": str(len(PDF))}, stream=_Interrupting())
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})

    d = FileDownloader(store=store, guard=_guard(), allowed_extensions=["pdf"], max_bytes=5_000_000, max_concurrent=1,
                       transport=httpx.MockTransport(handler))
    sid = uuid.uuid4()
    first = await d.download("https://files.example.com/report.pdf", session_id=sid, task_id=uuid.uuid4())
    assert first.status.value == "FAILED" and store.list(sid) == []
    assert not list((tmp_path / "dl").rglob("*.part")) and not list((tmp_path / "dl").rglob("*.pdf"))
    second = await d.download("https://files.example.com/report.pdf", session_id=sid, task_id=uuid.uuid4())
    assert second.status.value == "COMPLETED" and second.file is not None
    assert second.file.sha256 == hashlib.sha256(PDF).hexdigest()
    other = uuid.uuid4()
    import pytest

    from app.integrations.files.storage import FileRequestError

    with pytest.raises(FileRequestError) as exc:
        store.get(second.file.file_id, other)
    assert exc.value.status_code == 403


async def test_disk_full_mid_write_leaves_nothing_behind(tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
    store = FileStore(tmp_path / "dl", ttl_hours=1, max_storage_bytes=10_000_000)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=PDF, headers={"content-type": "application/pdf"})

    d = FileDownloader(store=store, guard=_guard(), allowed_extensions=["pdf"], max_bytes=5_000_000, max_concurrent=1,
                       transport=httpx.MockTransport(handler))
    import builtins

    real_open = builtins.open

    class _Full:
        def __init__(self, f):  # noqa: ANN001
            self.f = f

        def __enter__(self):  # noqa: ANN204
            return self

        def __exit__(self, *a):  # noqa: ANN002, ANN204
            self.f.close()

        def write(self, chunk: bytes) -> int:
            raise OSError(28, "No space left on device")

    def fake_open(path, mode="r", *a, **k):  # noqa: ANN001, ANN002, ANN003, ANN202
        f = real_open(path, mode, *a, **k)
        return _Full(f) if str(path).endswith(".part") else f

    monkeypatch.setattr(builtins, "open", fake_open)
    attempt = await d.download("https://files.example.com/report.pdf", session_id=uuid.uuid4(), task_id=uuid.uuid4())
    monkeypatch.setattr(builtins, "open", real_open)
    assert attempt.status.value == "FAILED" and not list((tmp_path / "dl").rglob("*.*"))


async def test_scanner_never_claims_clean_when_unavailable(tmp_path: Path) -> None:
    f = tmp_path / "x.pdf"
    f.write_bytes(PDF)
    assert await NullScanner().scan(f) == ScanResult.UNAVAILABLE
    assert await ClamAVScanner("127.0.0.1", 1, timeout=1).scan(f) == ScanResult.UNAVAILABLE  # nothing listening


def test_per_user_quota_blocks_further_downloads(fixture_origin: str, tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from app.main import create_app

    from ..integrations.conftest import PREFIX, integration_settings
    from ..integrations.conftest import finished, planned, run
    from .conftest import SECRET, Users

    settings = integration_settings(fixture_origin, tmp_path / "dl", auth_required=True, app_secret_key=SECRET, file_max_count_per_user=1,
                                    allow_dev_auth_bypass=False)
    with TestClient(create_app(settings)) as client:
        users = Users(client)
        a = users.new("quota@example.com")
        url = f"{fixture_origin}{PREFIX}/files/sample.txt"
        codes = []
        for _ in range(2):
            r = users.post(a, "/api/v1/tasks", {"command": f"Download the notes from {url}", "session_id": a.session_id, "input_mode": "TEXT"})
            task_id = r.json()["task_id"]
            import time

            deadline = time.monotonic() + 10
            while users.get(a, f"/api/v1/tasks/{task_id}").json()["state"] != "PLANNED" and time.monotonic() < deadline:
                time.sleep(0.05)
            users.post(a, f"/api/v1/tasks/{task_id}/execute", {"session_id": a.session_id, "confirm_execution": True})
            deadline = time.monotonic() + 60
            while users.get(a, f"/api/v1/tasks/{task_id}").json()["state"] not in ("COMPLETED", "FAILED", "CANCELLED") and time.monotonic() < deadline:
                time.sleep(0.1)
            codes.append(users.get(a, f"/api/v1/tasks/{task_id}/execution").json()["results"][0].get("error_code"))
        assert codes == [None, "FILE_QUOTA_EXCEEDED"]
        _ = (planned, run, finished)
