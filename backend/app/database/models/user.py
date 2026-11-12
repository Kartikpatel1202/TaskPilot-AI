"""Users and refresh tokens (only token HASHES are stored)."""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from sqlalchemy import ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, UtcDateTime


class UserRole(str, Enum):
    OWNER = "OWNER"
    MEMBER = "MEMBER"
    READ_ONLY = "READ_ONLY"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    email: Mapped[str] = mapped_column(String(254), unique=True, nullable=False)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16), nullable=False, default=UserRole.MEMBER.value)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=UserStatus.ACTIVE.value)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    token_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # bump = logout everywhere


class RefreshTokenRecord(Base):
    __tablename__ = "refresh_tokens"
    __table_args__ = (Index("ix_refresh_tokens_user_family", "user_id", "family_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    family_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime)  # rotated (a second use = replay)
    revoked_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
