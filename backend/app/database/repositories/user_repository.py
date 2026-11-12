"""Users and refresh tokens (hashes only)."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select, update

from app.database.models import RefreshTokenRecord, UserRecord
from app.database.session import Database
from app.schemas.common import utc_now


class UserRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def count(self) -> int:
        async with self.db.session() as s:
            return int(await s.scalar(select(func.count()).select_from(UserRecord)) or 0)

    async def by_email(self, email: str) -> UserRecord | None:
        async with self.db.session() as s:
            return await s.scalar(select(UserRecord).where(UserRecord.email == email.strip().lower()))

    async def get(self, user_id: UUID) -> UserRecord | None:
        async with self.db.session() as s:
            return await s.get(UserRecord, user_id)

    async def add(self, *, email: str, password_hash: str | None, role: str) -> UserRecord:
        user = UserRecord(email=email.strip().lower(), password_hash=password_hash, role=role, created_at=utc_now())
        async with self.db.session() as s:
            s.add(user)
        return user

    async def touch_login(self, user_id: UUID) -> None:
        async with self.db.session() as s:
            await s.execute(update(UserRecord).where(UserRecord.id == user_id).values(last_login_at=utc_now()))

    async def set_status(self, user_id: UUID, status: str) -> None:
        async with self.db.session() as s:
            await s.execute(update(UserRecord).where(UserRecord.id == user_id).values(status=status, token_version=UserRecord.token_version + 1))

    async def bump_token_version(self, user_id: UUID) -> None:
        async with self.db.session() as s:
            await s.execute(update(UserRecord).where(UserRecord.id == user_id).values(token_version=UserRecord.token_version + 1))

    # ---------------------------------------------------------------- refresh tokens

    async def add_refresh(self, *, user_id: UUID, token_hash: str, family_id: UUID, expires_at: datetime) -> None:
        async with self.db.session() as s:
            s.add(RefreshTokenRecord(user_id=user_id, token_hash=token_hash, family_id=family_id, created_at=utc_now(), expires_at=expires_at))

    async def refresh_by_hash(self, token_hash: str) -> RefreshTokenRecord | None:
        async with self.db.session() as s:
            return await s.scalar(select(RefreshTokenRecord).where(RefreshTokenRecord.token_hash == token_hash))

    async def mark_refresh_used(self, token_id: UUID) -> bool:
        """Atomically consume a refresh token; False if it was already used (= replay)."""
        async with self.db.session() as s:
            result = await s.execute(update(RefreshTokenRecord).where(RefreshTokenRecord.id == token_id, RefreshTokenRecord.used_at.is_(None),
                                                                      RefreshTokenRecord.revoked_at.is_(None)).values(used_at=utc_now()))
            return (result.rowcount or 0) == 1

    async def revoke_family(self, family_id: UUID) -> None:
        async with self.db.session() as s:
            await s.execute(update(RefreshTokenRecord).where(RefreshTokenRecord.family_id == family_id, RefreshTokenRecord.revoked_at.is_(None))
                            .values(revoked_at=utc_now()))

    async def revoke_all(self, user_id: UUID) -> None:
        async with self.db.session() as s:
            await s.execute(update(RefreshTokenRecord).where(RefreshTokenRecord.user_id == user_id, RefreshTokenRecord.revoked_at.is_(None))
                            .values(revoked_at=utc_now()))
