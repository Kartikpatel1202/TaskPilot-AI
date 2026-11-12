"""Safe file download schemas (Phase 5). Mirrors `frontend/src/types/files.ts`. No filesystem paths."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel


class DownloadStatus(str, Enum):
    QUEUED = "QUEUED"
    DOWNLOADING = "DOWNLOADING"
    VALIDATING = "VALIDATING"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"


class DownloadedFile(BaseModel):
    file_id: UUID
    session_id: UUID
    task_id: UUID
    original_name: str
    stored_name: str
    extension: str
    mime_type: str
    size_bytes: int
    sha256: str
    source_domain: str
    status: DownloadStatus
    created_at: datetime
    expires_at: datetime | None = None
    validation: list[str] = []


class DownloadAttempt(BaseModel):
    """Outcome of one download step (blocked/failed attempts are recorded too, without content)."""

    status: DownloadStatus
    message: str
    code: str | None = None
    file: DownloadedFile | None = None
    source_domain: str | None = None


class FileDeleteRequest(BaseModel):
    session_id: UUID
    confirm: bool
