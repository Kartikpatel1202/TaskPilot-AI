"""Deterministic YouTube result ranking and selection (Phase 5).

Relevance is the share of meaningful query words found in the observed title/channel. A video
is auto-selected only when it clearly beats the runner-up; otherwise the user chooses.
"""

from __future__ import annotations

import re

from app.schemas.youtube import YouTubeVideo

_STOP = {"the", "a", "an", "of", "for", "to", "on", "in", "and", "video", "videos", "youtube",
         "ka", "ki", "ke", "pe", "par", "mein", "chalao", "play", "watch", "dikhao"}
AUTO_SELECT_MIN = 0.6
AUTO_SELECT_MARGIN = 0.15


def _words(text: str | None) -> list[str]:
    return [w for w in re.split(r"[^a-z0-9]+", (text or "").lower()) if len(w) > 1]


def relevance(query: str, title: str, channel: str | None = None, preferred_channel: str | None = None) -> float:
    terms = [w for w in _words(query) if w not in _STOP] or _words(query)
    if not terms:
        return 0.0
    hay = set(_words(title)) | set(_words(channel))
    score = sum(1 for t in terms if t in hay) / len(terms)
    if preferred_channel and channel and set(_words(preferred_channel)) <= set(_words(channel)):
        score = min(1.0, score + 0.2)
    return round(score, 3)


def choose(videos: list[YouTubeVideo]) -> tuple[YouTubeVideo | None, list[YouTubeVideo]]:
    """(auto-selected video, options to offer). Exactly one of them is meaningful."""
    ranked = sorted(videos, key=lambda v: (-v.relevance, int(v.option_id[1:])))
    if not ranked:
        return None, []
    best = ranked[0]
    runner = ranked[1].relevance if len(ranked) > 1 else 0.0
    if best.relevance >= AUTO_SELECT_MIN and best.relevance - runner >= AUTO_SELECT_MARGIN:
        return best, []
    return None, [v for v in ranked if v.relevance > 0][:5] or ranked[:5]
