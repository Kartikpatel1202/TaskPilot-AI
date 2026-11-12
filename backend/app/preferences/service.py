"""Load/save user preferences. The database is authoritative; a small cache avoids a query per planning call.
Without authentication (development) there is one local profile."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from app.core.logging import get_logger
from app.database.models import UserPreferencesRecord
from app.database.session import Database
from app.schemas.common import utc_now
from app.schemas.preferences import PreferencesUpdate, UserPreferences

logger = get_logger("preferences")
LOCAL_OWNER = "local"


def owner_key(user_id: UUID | str | None) -> str:
    return str(user_id) if user_id else LOCAL_OWNER


class PreferencesService:
    def __init__(self, db: Database) -> None:
        self._db = db
        self._cache: dict[str, UserPreferences] = {}

    async def get(self, user_id: UUID | str | None) -> UserPreferences:
        key = owner_key(user_id)
        if key in self._cache:
            return self._cache[key]
        prefs = UserPreferences()
        try:
            async with self._db.session() as s:
                row = await s.get(UserPreferencesRecord, key)
                if row is not None:
                    prefs = UserPreferences.model_validate({**UserPreferences().model_dump(), **_known(row.data)})
        except Exception:  # noqa: BLE001 - defaults are always safe; never block planning on settings
            logger.warning("preferences.load_failed")
            return prefs
        self._cache[key] = prefs
        return prefs

    async def update(self, user_id: UUID | str | None, update: PreferencesUpdate) -> UserPreferences:
        key = owner_key(user_id)
        current = await self.get(user_id)
        merged = UserPreferences.model_validate({**current.model_dump(), **update.model_dump(exclude_none=True)})
        async with self._db.session() as s:
            row = await s.get(UserPreferencesRecord, key)
            if row is None:
                s.add(UserPreferencesRecord(owner_key=key, data=merged.model_dump(), updated_at=utc_now()))
            else:
                row.data = merged.model_dump()
                row.updated_at = utc_now()
        self._cache[key] = merged
        return merged


def _known(data: Any) -> dict[str, Any]:
    fields = UserPreferences.model_fields
    return {k: v for k, v in (data or {}).items() if k in fields}
