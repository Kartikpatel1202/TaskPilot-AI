"""Isolated per-session download storage with an in-memory registry and TTL (Phase 5).

Files live at `<storage>/<sha256(session)[:24]>/<file_id>.<ext>` with owner-only permissions.
Paths never leave this module: APIs and telemetry only see file ids and metadata. Every
lookup checks the owning session. Expired files are deleted from disk.
"""

from __future__ import annotations

import contextlib
import hashlib
import os
import threading
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from app.schemas.common import utc_now
from app.schemas.files import DownloadedFile


class FileRequestError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 404) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


@dataclass
class StoredFile:
    meta: DownloadedFile
    path: Path


class FileStore:
    def __init__(self, root: str | Path, *, ttl_hours: int, max_storage_bytes: int) -> None:
        self.root = Path(root).resolve()
        self.ttl = timedelta(hours=ttl_hours)
        self.max_storage_bytes = max_storage_bytes
        self._files: dict[UUID, StoredFile] = {}
        self._lock = threading.Lock()

    def session_dir(self, session_id: UUID) -> Path:
        directory = (self.root / hashlib.sha256(str(session_id).encode()).hexdigest()[:24]).resolve()
        if self.root not in directory.parents:
            raise FileRequestError("FILE_STORAGE_ERROR", "Invalid storage location.", 500)
        directory.mkdir(parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            os.chmod(directory, 0o700)
        return directory

    def path_for(self, session_id: UUID, file_id: UUID, ext: str, *, partial: bool = False) -> Path:
        name = f"{file_id}.{ext}" + (".part" if partial else "")
        target = (self.session_dir(session_id) / name).resolve()
        if self.root not in target.parents:
            raise FileRequestError("FILE_STORAGE_ERROR", "Invalid storage location.", 500)
        return target

    def used_bytes(self) -> int:
        with self._lock:
            return sum(f.meta.size_bytes for f in self._files.values())

    def add(self, meta: DownloadedFile, path: Path) -> None:
        with contextlib.suppress(OSError):
            os.chmod(path, 0o600)  # never executable
        with self._lock:
            self._files[meta.file_id] = StoredFile(meta, path)

    def get(self, file_id: UUID, session_id: UUID) -> StoredFile:
        self.purge_expired()
        with self._lock:
            stored = self._files.get(file_id)
        if stored is None:
            raise FileRequestError("FILE_NOT_FOUND", "No such file.", 404)
        if stored.meta.session_id != session_id:
            raise FileRequestError("FILE_ACCESS_DENIED", "This file belongs to a different session.", 403)
        if not stored.path.is_file():
            with self._lock:
                self._files.pop(file_id, None)
            raise FileRequestError("FILE_NOT_FOUND", "The file is no longer stored.", 404)
        return stored

    def list(self, session_id: UUID) -> list[DownloadedFile]:
        self.purge_expired()
        with self._lock:
            return sorted((f.meta for f in self._files.values() if f.meta.session_id == session_id), key=lambda m: m.created_at, reverse=True)

    def delete(self, file_id: UUID, session_id: UUID) -> DownloadedFile:
        stored = self.get(file_id, session_id)
        with contextlib.suppress(FileNotFoundError):
            stored.path.unlink()
        with self._lock:
            self._files.pop(file_id, None)
        return stored.meta

    def purge_expired(self) -> int:
        now = utc_now()
        with self._lock:
            expired = [f for f in self._files.values() if f.meta.expires_at is not None and f.meta.expires_at <= now]
            for f in expired:
                self._files.pop(f.meta.file_id, None)
        for f in expired:
            with contextlib.suppress(OSError):
                f.path.unlink()
        return len(expired)

    def expires_at(self):  # noqa: ANN201
        return utc_now() + self.ttl
