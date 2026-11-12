"""Download guard: every download is cancelled; path helpers refuse traversal and dangerous types."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.browser.download_guard import DownloadBlockedError, safe_download_path, sanitize_filename
from app.browser.session import BrowserSession

from .conftest import RecordingTelemetry


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("../../etc/passwd", "passwd"), ("C:\\Windows\\evil.txt", "evil.txt"), ("a<b>|c.pdf", "a_b__c.pdf"), ("", "download"), ("...", "download")],
)
def test_sanitize_filename(raw: str, expected: str) -> None:
    assert sanitize_filename(raw) == expected


def test_safe_path_stays_inside_the_approved_directory(tmp_path: Path) -> None:
    assert safe_download_path(tmp_path, "invoice.pdf") == (tmp_path / "invoice.pdf").resolve()
    for bad in ("../x.pdf", "sub/x.pdf", "..", ""):
        with pytest.raises(DownloadBlockedError):
            safe_download_path(tmp_path, bad)


@pytest.mark.parametrize("name", ["setup.exe", "run.BAT", "script.ps1", "tool.jar", "app.apk", "x.py"])
def test_dangerous_types_are_refused(tmp_path: Path, name: str) -> None:
    with pytest.raises(DownloadBlockedError):
        safe_download_path(tmp_path, name)


async def test_a_real_download_is_blocked_and_reported_by_name_only(session: BrowserSession, telemetry: RecordingTelemetry) -> None:
    await session.page.set_content(
        "<a id='dl' download='report.csv' href='data:text/csv,secret%2Cvalue'>Download</a>"
    )
    await session.page.click("#dl")
    for _ in range(40):
        if "browser.download_blocked" in telemetry.types():
            break
        await session.page.wait_for_timeout(50)
    blocked = [e for e in telemetry.events if e[1] == "browser.download_blocked"]
    assert blocked, telemetry.types()
    payload = blocked[0][2]
    assert payload.get("filename") == "report.csv"
    assert "secret" not in str(payload) and "data:" not in str(payload)
