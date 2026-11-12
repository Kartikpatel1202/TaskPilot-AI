"""Session ownership: every dashboard session id is bound to one user; ids alone never grant access."""

from __future__ import annotations

from collections import OrderedDict
from uuid import UUID

from app.database.repositories import SessionRepository


class SessionOwnership:
    def __init__(self, repo: SessionRepository, cache_size: int = 5000) -> None:
        self._repo = repo
        self._cache: OrderedDict[UUID, UUID] = OrderedDict()
        self._size = cache_size

    async def owner(self, session_id: UUID) -> UUID | None:
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached
        owner = await self._repo.owner(session_id)
        if owner is not None:
            self._remember(session_id, owner)
        return owner

    async def claim(self, session_id: UUID, user_id: UUID) -> bool:
        cached = self._cache.get(session_id)
        if cached is not None:
            return cached == user_id
        ok = await self._repo.claim(session_id, user_id)
        if ok:
            self._remember(session_id, user_id)
        return ok

    def owner_cached(self, session_id: UUID) -> UUID | None:
        return self._cache.get(session_id)

    def _remember(self, session_id: UUID, user_id: UUID) -> None:
        self._cache[session_id] = user_id
        self._cache.move_to_end(session_id)
        while len(self._cache) > self._size:
            self._cache.popitem(last=False)
