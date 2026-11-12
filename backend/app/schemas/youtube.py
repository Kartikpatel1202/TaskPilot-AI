"""YouTube schemas (Phase 5). Mirrors `frontend/src/types/youtube.ts`. Only observed values."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class YouTubeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    preferred_channel: str | None = None
    max_results: int = Field(default=10, ge=1, le=20)
    preferred_language: str | None = None


class YouTubeVideo(BaseModel):
    option_id: str  # stable id within this search ("v1", "v2", ...)
    video_id: str | None = None
    title: str
    channel_name: str | None = None
    duration: str | None = None
    views: str | None = None
    published_label: str | None = None
    video_url: str
    thumbnail_url: str | None = None
    relevance: float = Field(ge=0, le=1)
    observed_at: datetime


class PlaybackState(str, Enum):
    PLAYING = "PLAYING"
    PAUSED = "PAUSED"
    BUFFERING = "BUFFERING"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    PLAYBACK_BLOCKED = "PLAYBACK_BLOCKED"
    UNKNOWN = "UNKNOWN"


class YouTubePlayback(BaseModel):
    state: PlaybackState
    video: YouTubeVideo | None = None
    page_url: str | None = None
    current_time: float | None = None
    message: str
    observed_at: datetime
