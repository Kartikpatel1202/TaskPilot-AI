"""Downloaded-file metadata. Bytes live in private storage, referenced by an opaque storage key."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UtcDateTime


class FileRecord(Base):
    __tablename__ = "files"
    __table_args__ = (Index("ix_files_user_created", "user_id", "created_at"), Index("ix_files_session", "session_id"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    task_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    original_name: Mapped[str] = mapped_column(String(120), nullable=False)
    extension: Mapped[str] = mapped_column(String(10), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    source_domain: Mapped[str] = mapped_column(String(253), nullable=False)
    storage_key: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    scan_status: Mapped[str] = mapped_column(String(24), nullable=False, default="SCAN_UNAVAILABLE")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
