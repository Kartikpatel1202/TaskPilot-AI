"""Settings page API: GET/PUT the signed-in user's preferences (or the local profile in development)."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.auth.context import current_user
from app.schemas.preferences import PreferencesUpdate, UserPreferences

router = APIRouter(prefix="/preferences", tags=["settings"])


def _user_id() -> str | None:
    user = current_user.get()
    return str(user.user_id) if user is not None else None


@router.get("", response_model=UserPreferences, summary="Your saved preferences")
async def get_preferences(request: Request) -> UserPreferences:
    return await request.app.state.container.preferences.get(_user_id())


@router.put("", response_model=UserPreferences, summary="Update your preferences (partial)")
async def update_preferences(body: PreferencesUpdate, request: Request) -> UserPreferences:
    container = request.app.state.container
    prefs = await container.preferences.update(_user_id(), body)
    await container.audit.record("preferences.updated", outcome="SUCCESS",
                                 metadata={"fields": ",".join(sorted(body.model_dump(exclude_none=True)))})
    return prefs
