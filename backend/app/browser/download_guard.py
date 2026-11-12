"""Download guard. Phase 3 blocks every download.

Contexts are created with `accept_downloads=False`; this module additionally
cancels any download event, reports safe metadata (file name only — never the
URL, which can carry tokens) and provides path helpers for future phases that
refuse traversal, dangerous file types and paths outside an approved directory.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from pathlib import Path, PurePath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Download, Page

DANGEROUS_EXTENSIONS = frozenset(
    {
        ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".ps1", ".vbs", ".js", ".jse", ".wsf", ".hta", ".jar",
        ".sh", ".bash", ".zsh", ".app", ".dmg", ".pkg", ".deb", ".rpm", ".apk", ".dll", ".so", ".lnk", ".reg",
        ".iso", ".msc", ".cpl", ".py", ".pyw",
    }
)
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


class DownloadBlockedError(ValueError):
    pass


def sanitize_filename(name: str | None) -> str:
    base = PurePath((name or "download").replace("\\", "/")).name
    cleaned = _SAFE_NAME.sub("_", base).strip(" .") or "download"
    return cleaned[:120]


def safe_download_path(approved_dir: str | Path, filename: str) -> Path:
    """Resolve a destination inside `approved_dir` or raise. Never used automatically in Phase 3."""
    root = Path(approved_dir).resolve()
    if "/" in filename or "\\" in filename or filename in ("", ".", ".."):
        raise DownloadBlockedError("File names must not contain path separators.")
    name = sanitize_filename(filename)
    if Path(name).suffix.lower() in DANGEROUS_EXTENSIONS:
        raise DownloadBlockedError(f"Files of type {Path(name).suffix} are never downloaded.")
    target = (root / name).resolve()
    if root not in target.parents:
        raise DownloadBlockedError("Download path escapes the approved directory.")
    return target


def attach_download_guard(page: Page, on_blocked: Callable[[str], Awaitable[None]]) -> None:
    async def _handle(download: Download) -> None:
        filename = sanitize_filename(download.suggested_filename)
        try:
            await download.cancel()
        except Exception:  # already cancelled because accept_downloads=False
            pass
        await on_blocked(filename)

    page.on("download", _handle)
