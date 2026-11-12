"""Downloaded-file metadata with per-user quotas and owner-scoped listing."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select, update

from app.database.models import FileRecord
from app.database.session import Database
from app.schemas.common import utc_now
from app.schemas.files import DownloadedFile


class FileRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def add(self, meta: DownloadedFile, *, user_id: UUID | None, storage_key: str, scan_status: str) -> None:
        async with self.db.session() as s:
            s.add(FileRecord(id=meta.file_id, user_id=user_id, session_id=meta.session_id, task_id=meta.task_id,
                             original_name=meta.original_name, extension=meta.extension, mime_type=meta.mime_type,
                             size_bytes=meta.size_bytes, sha256=meta.sha256, source_domain=meta.source_domain, storage_key=storage_key,
                             status=meta.status.value, scan_status=scan_status, created_at=meta.created_at, expires_at=meta.expires_at))

    async def mark_deleted(self, file_id: UUID) -> None:
        async with self.db.session() as s:
            row = await s.get(FileRecord, file_id)
            if row is not None and row.deleted_at is None:
                row.deleted_at = utc_now()
                row.status = "DELETED"

    async def usage(self, user_id: UUID) -> tuple[int, int]:
        """(live file count, live bytes) for quota checks."""
        async with self.db.session() as s:
            count, total = (await s.execute(select(func.count(), func.coalesce(func.sum(FileRecord.size_bytes), 0)).where(
                FileRecord.user_id == user_id, FileRecord.deleted_at.is_(None)))).one()
            return int(count), int(total)

    async def get(self, file_id: UUID) -> FileRecord | None:
        async with self.db.session() as s:
            return await s.get(FileRecord, file_id)

    async def live(self) -> list[FileRecord]:
        async with self.db.session() as s:
            return list(await s.scalars(select(FileRecord).where(FileRecord.deleted_at.is_(None))))

    async def expire_overdue(self) -> int:
        """Mark files past their expiry as deleted so they stop counting against quotas (bytes are purged by FileStore)."""
        now = utc_now()
        async with self.db.session() as s:
            result = await s.execute(update(FileRecord).where(FileRecord.deleted_at.is_(None), FileRecord.expires_at.is_not(None),
                                                              FileRecord.expires_at <= now).values(deleted_at=now, status="EXPIRED"))
            return result.rowcount or 0
