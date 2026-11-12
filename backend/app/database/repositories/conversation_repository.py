"""Bounded, redacted conversation turns with expiry."""

from __future__ import annotations

from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, func, select

from app.core.logging import redact_text
from app.database.models import ConversationTurnRecord
from app.database.session import Database
from app.schemas.common import utc_now


class ConversationRepository:
    def __init__(self, db: Database, *, max_turns: int = 20, ttl_minutes: int = 60) -> None:
        self.db = db
        self.max_turns = max_turns
        self.ttl = timedelta(minutes=ttl_minutes)

    async def add(self, *, session_id: UUID, user_id: UUID | None, task_id: UUID | None, role: str, content: str, intent: str | None) -> None:
        now = utc_now()
        async with self.db.session() as s:
            s.add(ConversationTurnRecord(session_id=session_id, user_id=user_id, task_id=task_id, role=role,
                                         content=redact_text(content)[:2000], intent=intent, created_at=now, expires_at=now + self.ttl))
            await s.flush()
            count = await s.scalar(select(func.count()).select_from(ConversationTurnRecord).where(ConversationTurnRecord.session_id == session_id))
            if count and count > self.max_turns:
                oldest = await s.scalars(select(ConversationTurnRecord.id).where(ConversationTurnRecord.session_id == session_id)
                                         .order_by(ConversationTurnRecord.created_at).limit(count - self.max_turns))
                await s.execute(delete(ConversationTurnRecord).where(ConversationTurnRecord.id.in_(list(oldest))))

    async def recent(self, session_id: UUID) -> list[ConversationTurnRecord]:
        async with self.db.session() as s:
            rows = await s.scalars(select(ConversationTurnRecord).where(ConversationTurnRecord.session_id == session_id,
                                                                        ConversationTurnRecord.expires_at > utc_now())
                                   .order_by(ConversationTurnRecord.created_at))
            return list(rows)

    async def purge_expired(self) -> int:
        async with self.db.session() as s:
            result = await s.execute(delete(ConversationTurnRecord).where(ConversationTurnRecord.expires_at <= utc_now()))
            return result.rowcount or 0
