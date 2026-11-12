"""File type validation for the safe downloader (Phase 5).

Defence in depth — a file is accepted only when ALL of these agree:
1. its (sanitised) name has an allow-listed final extension and no dangerous inner extension;
2. the server's Content-Type is compatible with that extension;
3. the first bytes (magic) match the extension, and never look like an executable/script;
4. Office files are real OOXML containers without macros; text files are UTF-8 without NUL bytes.
Downloaded files are never opened, rendered or executed by TaskPilot.
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import PurePath

from app.browser.download_guard import DANGEROUS_EXTENSIONS, sanitize_filename

ARCHIVE_EXTENSIONS = frozenset({".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".cab", ".zst", ".lz", ".lzma"})
ALWAYS_BLOCKED = DANGEROUS_EXTENSIONS | frozenset({
    ".bin", ".elf", ".run", ".appimage", ".scpt", ".command", ".workflow", ".action", ".csh", ".ksh", ".fish", ".pl", ".rb",
    ".php", ".asp", ".aspx", ".jsp", ".cgi", ".html", ".htm", ".svg", ".xhtml", ".mht", ".chm", ".docm", ".xlsm", ".pptm",
    ".dotm", ".xlam", ".ppam", ".sys", ".drv", ".ocx", ".vbe", ".wsh", ".msp", ".mst", ".gadget", ".inf", ".url", ".desktop",
})
MIME_FOR = {
    "pdf": {"application/pdf"},
    "txt": {"text/plain"},
    "csv": {"text/csv", "text/plain", "application/csv", "application/vnd.ms-excel"},
    "png": {"image/png"},
    "jpg": {"image/jpeg"},
    "jpeg": {"image/jpeg"},
    "webp": {"image/webp"},
    "docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    "xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    "pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
}
CANONICAL_MIME = {ext: sorted(m)[0] for ext, m in MIME_FOR.items()} | {"txt": "text/plain", "csv": "text/csv"}
GENERIC_MIME = {"application/octet-stream", "binary/octet-stream", "application/force-download", ""}
_EXEC_MAGIC = (b"MZ", b"\x7fELF", b"\xfe\xed\xfa", b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"#!")


class FileValidationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


def check_name(raw_name: str, allowed: list[str]) -> tuple[str, str]:
    """(sanitised name, extension without dot) or FileValidationError."""
    name = sanitize_filename(raw_name)
    suffixes = [s.lower() for s in PurePath(name).suffixes]
    if not suffixes:
        raise FileValidationError("FILE_TYPE_NOT_ALLOWED", "The file has no extension, so its type cannot be verified.")
    final = suffixes[-1]
    if final in ARCHIVE_EXTENSIONS:
        raise FileValidationError("FILE_TYPE_BLOCKED", f"Archives ({final}) are not downloaded: they can hide executables.")
    if final in ALWAYS_BLOCKED or any(s in ALWAYS_BLOCKED for s in suffixes[:-1]):
        raise FileValidationError("FILE_TYPE_BLOCKED", f"Files of type {''.join(suffixes)} are never downloaded (executable/script/active content).")
    ext = final.lstrip(".")
    if ext not in allowed:
        raise FileValidationError("FILE_TYPE_NOT_ALLOWED", f".{ext} files are not on the allowed download list.")
    return name, ext


def check_content_type(content_type: str | None, ext: str) -> str:
    mime = (content_type or "").split(";")[0].strip().lower()
    if mime in GENERIC_MIME:
        return CANONICAL_MIME.get(ext, "application/octet-stream")
    if mime not in MIME_FOR.get(ext, set()):
        raise FileValidationError("FILE_MIME_MISMATCH", f"The server says this is {mime or 'unknown'}, not a .{ext} file.")
    return mime


def check_magic(head: bytes, ext: str) -> None:
    if any(head.startswith(m) for m in _EXEC_MAGIC):
        raise FileValidationError("FILE_EXECUTABLE_CONTENT", "The file content looks like an executable or script; it was deleted.")
    ok = {
        "pdf": head.startswith(b"%PDF-"),
        "png": head.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": head.startswith(b"\xff\xd8\xff"),
        "jpeg": head.startswith(b"\xff\xd8\xff"),
        "webp": head[:4] == b"RIFF" and head[8:12] == b"WEBP",
        "docx": head.startswith(b"PK\x03\x04"),
        "xlsx": head.startswith(b"PK\x03\x04"),
        "pptx": head.startswith(b"PK\x03\x04"),
    }.get(ext)
    if ok is False:
        raise FileValidationError("FILE_MAGIC_MISMATCH", f"The file content does not match a real .{ext} file; it was deleted.")
    if ext in ("txt", "csv"):
        if b"\x00" in head:
            raise FileValidationError("FILE_MAGIC_MISMATCH", "This “text” file contains binary data; it was deleted.")
        try:
            head.decode("utf-8")
        except UnicodeDecodeError as exc:
            if exc.start < len(head) - 4:  # a multi-byte char cut at the sniff boundary is fine
                raise FileValidationError("FILE_MAGIC_MISMATCH", "This text file is not valid UTF-8; it was deleted.") from exc


def check_office(data: bytes, ext: str) -> None:
    if ext not in ("docx", "xlsx", "pptx"):
        return
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            names = z.namelist()
    except zipfile.BadZipFile as exc:
        raise FileValidationError("FILE_MAGIC_MISMATCH", "The Office file is damaged; it was deleted.") from exc
    if "[Content_Types].xml" not in names:
        raise FileValidationError("FILE_MAGIC_MISMATCH", "This is not a real Office document; it was deleted.")
    if any(re.search(r"vbaProject\.bin$|\.(exe|dll|js|vbs|bat|cmd|ps1)$", n, re.IGNORECASE) for n in names):
        raise FileValidationError("FILE_EXECUTABLE_CONTENT", "The Office file contains macros or embedded programs; it was deleted.")


def filename_from(url_path: str, content_disposition: str | None) -> str:
    if content_disposition:
        m = re.search(r"filename\*\s*=\s*UTF-8''([^;]+)", content_disposition, re.IGNORECASE) or re.search(
            r'filename\s*=\s*"?([^";]+)"?', content_disposition, re.IGNORECASE)
        if m:
            from urllib.parse import unquote

            return unquote(m.group(1)).strip()
    from urllib.parse import unquote

    return unquote(PurePath(url_path or "/download").name) or "download"
