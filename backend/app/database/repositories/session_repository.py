"""Session ownership: a client session id is bound to exactly one user on first authenticated use."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.database.models import AppSessionRecord, BrowserSessionRecord, IntegrationStatusRecord
from app.database.session import Database
from app.schemas.common import utc_now


class SessionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    async def owner(self, session_id: UUID) -> UUID | None:
        async with self.db.session() as s:
            row = await s.get(AppSessionRecord, session_id)
            return row.user_id if row else None

    async def claim(self, session_id: UUID, user_id: UUID) -> bool:
        """True if the session belongs (now) to `user_id`; False if another user owns it."""
        current = await self.owner(session_id)
        if current is not None:
            if current == user_id:
                async with self.db.session() as s:
                    await s.execute(update(AppSessionRecord).where(AppSessionRecord.session_id == session_id).values(last_seen_at=utc_now()))
            return current == user_id
        now = utc_now()
        try:
            async with self.db.session() as s:
                s.add(AppSessionRecord(session_id=session_id, user_id=user_id, created_at=now, last_seen_at=now))
            return True
        except IntegrityError:  # raced with another claim
            return await self.owner(session_id) == user_id

    async def sessions_of(self, user_id: UUID) -> list[UUID]:
        async with self.db.session() as s:
            return list(await s.scalars(select(AppSessionRecord.session_id).where(AppSessionRecord.user_id == user_id)))

    async def save_browser(self, session_id: UUID, *, user_id: UUID | None, status: str, persisted: bool) -> None:
        now = utc_now()
        async with self.db.session() as s:
            row = await s.get(BrowserSessionRecord, session_id)
            if row is None:
                s.add(BrowserSessionRecord(id=session_id, user_id=user_id, status=status, persisted=persisted, metadata_json={},
                                           created_at=now, last_activity_at=now))
            else:
                row.status, row.last_activity_at = status, now

    async def save_integration_status(self, session_id: UUID, domain: str, status: str, message: str) -> None:
        async with self.db.session() as s:
            row = await s.get(IntegrationStatusRecord, (session_id, domain))
            if row is None:
                s.add(IntegrationStatusRecord(session_id=session_id, domain=domain, status=status, message=message[:300], observed_at=utc_now()))
            else:
                row.status, row.message, row.observed_at = status, message[:300], utc_now()
