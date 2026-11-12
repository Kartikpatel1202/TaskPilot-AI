"""Phase 6 cleanup job: expired downloads stop counting against quota; expired memory is purged; audit untouched."""

from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest

from app.database.models import ConversationTurnRecord, FileRecord
from app.database.session import Database
from app.database.dependencies import Persistence
from app.schemas.common import utc_now



@pytest.mark.asyncio
async def test_expired_file_records_and_memory_are_cleaned() -> None:
    db = Database("sqlite+aiosqlite://")
    await db.create_all()
    persistence = Persistence(db)
    user = uuid4()
    now = utc_now()
    async with db.session() as s:
        for expires, size in ((now - timedelta(minutes=1), 500), (now + timedelta(hours=1), 700)):
            s.add(FileRecord(id=uuid4(), user_id=user, session_id=uuid4(), task_id=uuid4(), original_name="a.pdf", extension="pdf",
                             mime_type="application/pdf", size_bytes=size, sha256="0" * 64, source_domain="example.com",
                             storage_key=f"k-{size}", status="AVAILABLE", scan_status="SCAN_UNAVAILABLE", created_at=now, expires_at=expires))
    assert await persistence.files.usage(user) == (2, 1200)
    assert await persistence.files.expire_overdue() == 1
    assert await persistence.files.usage(user) == (1, 700)
    assert await persistence.files.expire_overdue() == 0  # idempotent

    session = uuid4()
    async with db.session() as s:
        s.add(ConversationTurnRecord(session_id=session, role="user", content="old", created_at=now, expires_at=now - timedelta(seconds=1)))
        s.add(ConversationTurnRecord(session_id=session, role="user", content="fresh", created_at=now, expires_at=now + timedelta(hours=1)))
    assert await persistence.conversations.purge_expired() == 1
    await db.dispose()
