"""Safe file downloader: allow-list, content validation, size cap, isolated storage and the
/files APIs (LOCAL fixture files only; nothing is ever opened or executed)."""

from __future__ import annotations

import hashlib
import os
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.browser.navigation_guard import NavigationGuard
from app.integrations.files.downloader import FileDownloader
from app.integrations.files.storage import FileStore
from app.integrations.files.validator import FileValidationError, check_content_type, check_magic, check_name

from .conftest import PREFIX, container, events_of, finished, planned, results, run

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "integrations" / "files"
ALLOWED = ["pdf", "txt", "csv", "png", "jpg", "jpeg", "webp", "docx", "xlsx", "pptx"]


# ---------------------------------------------------------------------- unit: validation


@pytest.mark.parametrize("name,code", [
    ("setup.exe", "FILE_TYPE_BLOCKED"), ("invoice.pdf.exe", "FILE_TYPE_BLOCKED"), ("invoice.exe.pdf", "FILE_TYPE_BLOCKED"),
    ("bundle.zip", "FILE_TYPE_BLOCKED"), ("script.ps1", "FILE_TYPE_BLOCKED"), ("page.html", "FILE_TYPE_BLOCKED"),
    ("macro.docm", "FILE_TYPE_BLOCKED"), ("payload.bin", "FILE_TYPE_BLOCKED"), ("noext", "FILE_TYPE_NOT_ALLOWED"),
    ("photo.gif", "FILE_TYPE_NOT_ALLOWED"),
])
def test_dangerous_or_unlisted_names_are_refused(name: str, code: str) -> None:
    with pytest.raises(FileValidationError) as exc:
        check_name(name, ALLOWED)
    assert exc.value.code == code


def test_names_are_sanitised_and_paths_cannot_escape() -> None:
    assert check_name("../../etc/report.pdf", ALLOWED) == ("report.pdf", "pdf")
    assert check_name("Q3 report (final).PDF", ALLOWED)[1] == "pdf"


def test_content_type_and_magic_must_agree() -> None:
    assert check_content_type("application/pdf; charset=binary", "pdf") == "application/pdf"
    assert check_content_type("application/octet-stream", "png") == "image/png"
    with pytest.raises(FileValidationError):
        check_content_type("text/html", "pdf")  # e.g. a login page served instead of the file
    check_magic(b"%PDF-1.4\n", "pdf")
    for head, ext in ((b"MZ\x90\x00", "pdf"), (b"\x7fELF", "txt"), (b"#!/bin/sh", "txt"), (b"<html>", "pdf"), (b"a\x00b", "csv")):
        with pytest.raises(FileValidationError):
            check_magic(head, ext)


# ---------------------------------------------------------------------- downloader against the fixture server


@pytest.fixture
def downloader(fixture_origin: str, tmp_path: Path) -> FileDownloader:
    store = FileStore(tmp_path / "dl", ttl_hours=1, max_storage_bytes=100 * 1024 * 1024)
    guard = NavigationGuard(allowed_domains=[], trusted_origins=[fixture_origin])
    return FileDownloader(store=store, guard=guard, allowed_extensions=ALLOWED, max_bytes=25 * 1024 * 1024, max_concurrent=2)


def _url(origin: str, name: str) -> str:
    return f"{origin}{PREFIX}/files/{name}"


async def test_pdf_download_is_validated_hashed_and_isolated(downloader: FileDownloader, fixture_origin: str) -> None:
    sid, tid = uuid.uuid4(), uuid.uuid4()
    progress: list[int] = []

    async def on_progress(received: int, total: int | None) -> None:
        progress.append(received)

    attempt = await downloader.download(_url(fixture_origin, "report.pdf"), session_id=sid, task_id=tid, on_progress=on_progress)
    assert attempt.status.value == "COMPLETED", attempt.message
    meta = attempt.file
    assert meta is not None and meta.original_name == "report.pdf" and meta.mime_type == "application/pdf"
    assert meta.sha256 == hashlib.sha256((FIXTURES / "report.pdf").read_bytes()).hexdigest()
    assert meta.stored_name == f"{meta.file_id}.pdf" and progress
    stored = downloader.store.get(meta.file_id, sid)
    assert stored.path.parent.name != str(sid) and downloader.store.root in stored.path.parents
    assert not list(stored.path.parent.glob("*.part"))
    if os.name != "nt":
        assert not os.access(stored.path, os.X_OK)


@pytest.mark.parametrize("name,code", [
    ("fake_executable.bin", "FILE_TYPE_BLOCKED"),
    ("disguised.pdf", "FILE_EXECUTABLE_CONTENT"),
    ("invalid_extension.txt", "FILE_EXECUTABLE_CONTENT"),
    ("oversized_file.pdf", "FILE_TOO_LARGE"),
])
async def test_dangerous_files_are_blocked_and_removed(downloader: FileDownloader, fixture_origin: str, name: str, code: str) -> None:
    sid = uuid.uuid4()
    attempt = await downloader.download(_url(fixture_origin, name), session_id=sid, task_id=uuid.uuid4())
    assert attempt.status.value == "BLOCKED" and attempt.code == code, attempt.message
    assert downloader.store.list(sid) == []
    assert not [p for p in downloader.store.root.rglob("*") if p.is_file()]


async def test_text_csv_and_image_downloads(downloader: FileDownloader, fixture_origin: str) -> None:
    sid = uuid.uuid4()
    for name, ext in (("data.csv", "csv"), ("sample.txt", "txt"), ("image.png", "png")):
        attempt = await downloader.download(_url(fixture_origin, name), session_id=sid, task_id=uuid.uuid4())
        assert attempt.status.value == "COMPLETED" and attempt.file and attempt.file.extension == ext, attempt.message
    assert len(downloader.store.list(sid)) == 3


async def test_redirects_are_revalidated_each_hop(downloader: FileDownloader, fixture_origin: str) -> None:
    ok = await downloader.download(_url(fixture_origin, "redirect/inside"), session_id=uuid.uuid4(), task_id=uuid.uuid4())
    assert ok.status.value == "COMPLETED"
    bad = await downloader.download(_url(fixture_origin, "redirect/outside"), session_id=uuid.uuid4(), task_id=uuid.uuid4())
    assert bad.status.value == "BLOCKED" and bad.code == "FILE_URL_BLOCKED"


async def test_unlisted_and_private_hosts_are_refused(downloader: FileDownloader) -> None:
    for url, code in (("https://example.com/report.pdf", "FILE_DOMAIN_NOT_ALLOWED"), ("http://10.0.0.1/report.pdf", "FILE_URL_BLOCKED"),
                      ("http://localhost:8000/report.pdf", "FILE_URL_BLOCKED"), ("file:///etc/passwd", "FILE_URL_BLOCKED")):
        attempt = await downloader.download(url, session_id=uuid.uuid4(), task_id=uuid.uuid4())
        assert attempt.status.value == "BLOCKED" and attempt.code == code, (url, attempt.code)


async def test_storage_quota_and_ttl(fixture_origin: str, tmp_path: Path) -> None:
    store = FileStore(tmp_path / "q", ttl_hours=1, max_storage_bytes=(FIXTURES / "report.pdf").stat().st_size + 100)
    d = FileDownloader(store=store, guard=NavigationGuard(allowed_domains=[], trusted_origins=[fixture_origin]), allowed_extensions=ALLOWED,
                       max_bytes=10_000, max_concurrent=1)
    sid = uuid.uuid4()
    first = await d.download(_url(fixture_origin, "report.pdf"), session_id=sid, task_id=uuid.uuid4())
    assert first.status.value == "COMPLETED"
    second = await d.download(_url(fixture_origin, "report.pdf"), session_id=sid, task_id=uuid.uuid4())
    assert second.status.value == "BLOCKED" and second.code == "FILE_STORAGE_FULL"
    assert first.file is not None
    from datetime import timedelta

    from app.schemas.common import utc_now

    store.get(first.file.file_id, sid).meta.expires_at = utc_now() - timedelta(seconds=1)
    assert store.purge_expired() == 1 and store.list(sid) == []


# ---------------------------------------------------------------------- E2E scenario 4 + /files APIs


def test_scenario4_pdf_download_and_files_api(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    task_id, plan = planned(iclient, f"Download the quarterly report from {_url(fixture_origin, 'report.pdf')}", sid)
    step = plan["steps"][0]
    assert step["action"]["type"] == "file_download" and step["risk_level"] == "MEDIUM" and step["requires_approval"] is False
    run(iclient, task_id, sid)
    assert finished(iclient, task_id)["state"] == "COMPLETED", [(r["error_code"], r["message"]) for r in results(iclient, task_id)]
    files = iclient.get("/api/v1/files", params={"session_id": sid}).json()
    assert len(files) == 1 and files[0]["original_name"] == "report.pdf"
    assert "path" not in str(files[0]).lower() or "\\" not in str(files[0])
    file_id = files[0]["file_id"]
    assert iclient.get(f"/api/v1/files/{file_id}", params={"session_id": sid}).json()["sha256"] == files[0]["sha256"]
    body = iclient.get(f"/api/v1/files/{file_id}/download", params={"session_id": sid})
    assert body.status_code == 200 and body.content.startswith(b"%PDF-")
    assert body.headers["x-content-type-options"] == "nosniff" and "attachment" in body.headers["content-disposition"]
    other = str(uuid.uuid4())
    assert iclient.get(f"/api/v1/files/{file_id}", params={"session_id": other}).status_code == 403
    assert iclient.get(f"/api/v1/files/{file_id}/download", params={"session_id": other}).status_code == 403
    assert iclient.get("/api/v1/files", params={"session_id": other}).json() == []
    assert iclient.request("DELETE", f"/api/v1/files/{file_id}", json={"session_id": other, "confirm": True}).status_code == 403
    assert iclient.request("DELETE", f"/api/v1/files/{file_id}", json={"session_id": sid, "confirm": False}).status_code == 400
    gone = iclient.request("DELETE", f"/api/v1/files/{file_id}", json={"session_id": sid, "confirm": True})
    assert gone.status_code == 200 and gone.json()["deleted"] is True
    assert iclient.get(f"/api/v1/files/{file_id}", params={"session_id": sid}).status_code == 404
    kinds = [e["type"] for e in events_of(iclient, sid, "file.")]
    assert {"file.download_started", "file.validation_completed", "file.download_completed"} <= set(kinds)
    assert all(str(container(iclient).integrations.files.root) not in str(e["data"]) for e in events_of(iclient, sid, ""))


def test_executable_download_request_is_blocked_end_to_end(iclient: TestClient, fixture_origin: str) -> None:
    sid = str(uuid.uuid4())
    task_id, _ = planned(iclient, f"Download the installer from {_url(fixture_origin, 'fake_executable.bin')}", sid)
    run(iclient, task_id, sid)
    assert finished(iclient, task_id)["state"] == "FAILED"
    step = results(iclient, task_id)[0]
    assert step["status"] == "BLOCKED" and step["error_code"] == "FILE_TYPE_BLOCKED"
    assert [e for e in events_of(iclient, sid, "file.download_blocked")]
    assert iclient.get("/api/v1/files", params={"session_id": sid}).json() == []


def test_link_is_found_on_a_page_or_chosen_by_the_user(iclient: TestClient) -> None:
    sid = str(uuid.uuid4())
    task_id, plan = planned(iclient, "download the order data csv from fixture files", sid)
    assert plan["steps"][0]["action"]["expected_extension"] == "csv"
    run(iclient, task_id, sid)
    assert finished(iclient, task_id)["state"] == "COMPLETED", [(r["error_code"], r["message"]) for r in results(iclient, task_id)]
    assert [f["original_name"] for f in iclient.get("/api/v1/files", params={"session_id": sid}).json()] == ["data.csv"]
