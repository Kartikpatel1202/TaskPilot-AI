"""YouTube adapter (Phase 5): search, observed result extraction, playback verification.

Never downloads media, never skips/blocks ads, never touches DRM, never signs in. The only
click is a Play control (IntegrationPolicy); everything reported comes from the live page.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit

from app.integrations.adapter_base import IntegrationAdapterBase, wait_for
from app.integrations.base import AccessStatus, IntegrationContext, IntegrationError
from app.integrations.policies import FieldKind, Purpose
from app.integrations.youtube.ranking import relevance
from app.schemas.common import utc_now
from app.schemas.youtube import PlaybackState, YouTubePlayback, YouTubeVideo

VIDEO_ID = re.compile(r"^[\w-]{6,20}$")

RESULTS_JS = r"""
(max) => {
  const out = [];
  for (const r of document.querySelectorAll('ytd-video-renderer')) {
    const a = r.querySelector('a#video-title');
    if (!a) continue;
    const meta = [...r.querySelectorAll('#metadata-line span, .inline-metadata-item')].map((s) => s.innerText.trim()).filter(Boolean);
    const ch = r.querySelector('ytd-channel-name a, #channel-name a, ytd-channel-name');
    const dur = r.querySelector('.ytd-thumbnail-overlay-time-status-renderer, badge-shape .badge-shape-wiz__text');
    const img = r.querySelector('img');
    out.push({ title: (a.getAttribute('title') || a.innerText || '').trim(), href: a.href, channel: ch ? ch.innerText.trim() : null,
               duration: dur ? dur.innerText.trim() : null, meta, thumb: img ? img.src : null });
    if (out.length >= max) break;
  }
  return { items: out, empty: !!document.querySelector('#no-results') || /No results found/i.test(document.body.innerText.slice(0, 5000)) };
}
"""

PLAYER_JS = r"""
() => {
  const vis = (el) => { if (!el) return false; const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const err = document.querySelector('.ytp-error, ytd-player-error-message-renderer');
  const v = document.querySelector('video.html5-main-video, #movie_player video, video');
  const player = document.querySelector('#movie_player');
  const title = document.querySelector('h1.ytd-watch-metadata, h1.title');
  return {
    error: vis(err) ? (err.innerText || '').trim().slice(0, 200) : null,
    has_video: !!v, paused: v ? v.paused : null, time: v ? v.currentTime : null, ready: v ? v.readyState : null,
    ad: !!(player && player.classList.contains('ad-showing')),
    title: title ? title.innerText.trim().slice(0, 300) : null,
    gate: /sign in to confirm/i.test((document.body ? document.body.innerText : '').slice(0, 4000)),
  };
}
"""


class YouTubeAdapter(IntegrationAdapterBase):
    def search_url(self, ctx: IntegrationContext, query: str) -> str:
        if ctx.binding.is_fixture:
            return ctx.binding.url(f"results.html?search_query={quote_plus(query)}")
        return f"https://www.youtube.com/results?search_query={quote_plus(query)}"

    def watch_url(self, ctx: IntegrationContext, video_id: str) -> str:
        if ctx.binding.is_fixture:
            return ctx.binding.url(f"watch.html?v={video_id}")
        return f"https://www.youtube.com/watch?v={video_id}"

    def video_id_from(self, ctx: IntegrationContext, url: str | None) -> str | None:
        """Only links of THIS validated site, with a real watch id (no shorts/ads/channels)."""
        if not url or not ctx.binding.owns(url):
            return None
        parts = urlsplit(url)
        if not (parts.path.endswith("/watch") or parts.path.endswith("/watch.html")):
            return None
        vid = (parse_qs(parts.query).get("v") or [""])[0]
        return vid if VIDEO_ID.match(vid) else None

    async def search(self, ctx: IntegrationContext, query: str, max_results: int, preferred_channel: str | None = None) -> list[YouTubeVideo]:
        decision = ctx.policy.check_fill(FieldKind.SEARCH, query)
        if not decision.allowed:
            raise IntegrationError(decision.code or "SENSITIVE_ACTION_BLOCKED", decision.message or "Blocked.", status="BLOCKED")
        await self.goto(ctx, self.search_url(ctx, query))
        await self.require_access(ctx, login_code="YOUTUBE_LOGIN_REQUIRED")

        async def ready() -> Any:
            data = await ctx.controller.evaluate(ctx.session_id, RESULTS_JS, max_results * 2)
            return data if (data.get("items") or data.get("empty")) else None

        data = await wait_for(ready, ctx.timeout)
        if data is None:
            await self.require_access(ctx, login_code="YOUTUBE_LOGIN_REQUIRED")
            raise IntegrationError("YOUTUBE_SEARCH_TIMEOUT", "YouTube results did not load in time.")
        videos: list[YouTubeVideo] = []
        seen: set[str] = set()
        for raw in data.get("items", []):
            vid = self.video_id_from(ctx, raw.get("href"))
            title = (raw.get("title") or "").strip()
            if not vid or not title or vid in seen:
                continue
            seen.add(vid)
            meta = raw.get("meta") or []
            views = next((m for m in meta if re.search(r"\b(views?|watching)\b", m, re.IGNORECASE)), None)
            published = next((m for m in meta if re.search(r"\bago\b|streamed", m, re.IGNORECASE)), None)
            videos.append(YouTubeVideo(
                option_id=f"v{len(videos) + 1}", video_id=vid, title=title[:300], channel_name=(raw.get("channel") or None),
                duration=raw.get("duration") or None, views=views, published_label=published, video_url=self.watch_url(ctx, vid),
                thumbnail_url=raw.get("thumb") if (raw.get("thumb") or "").startswith("https://") else None,
                relevance=relevance(query, title, raw.get("channel"), preferred_channel), observed_at=utc_now(),
            ))
            if len(videos) >= max_results:
                break
        return videos

    async def play(self, ctx: IntegrationContext, video: YouTubeVideo, timeout: float) -> YouTubePlayback:
        vid = video.video_id or self.video_id_from(ctx, video.video_url)
        if not vid:
            raise IntegrationError("YOUTUBE_VIDEO_INVALID", "That video link is not a valid YouTube watch link.", status="BLOCKED")
        await self.goto(ctx, self.watch_url(ctx, vid))
        status = await self.access(ctx)
        if status != AccessStatus.READY:
            return self._state(PlaybackState.LOGIN_REQUIRED if status == AccessStatus.LOGIN_REQUIRED else PlaybackState.PLAYBACK_BLOCKED,
                               video, ctx, None, "YouTube needs you to sign in / confirm in the browser. TaskPilot never signs in for you.")

        async def player() -> Any:
            s = await ctx.controller.evaluate(ctx.session_id, PLAYER_JS)
            return s if (s.get("has_video") or s.get("error") or s.get("gate")) else None

        state = await wait_for(player, timeout)
        if state is None:
            return self._state(PlaybackState.UNKNOWN, video, ctx, None, "The video player did not appear in time.")
        if state.get("gate"):
            return self._state(PlaybackState.LOGIN_REQUIRED, video, ctx, None,
                               "YouTube asks you to sign in to watch this video. TaskPilot never signs in for you.")
        if state.get("error"):
            return self._state(PlaybackState.PLAYBACK_BLOCKED, video, ctx, None, f"YouTube says: {state['error'][:150]}")
        observed = await self._sample(ctx)
        if observed is not None and observed[0] == PlaybackState.PAUSED:
            # Autoplay did not start: press the player's own Play control once (policy-checked).
            page = await self.page(ctx)
            button = page.locator(".ytp-play-button").first
            if await button.count():
                await self.click(ctx, button, Purpose.YOUTUBE_PLAY)
                observed = await self._sample(ctx)
        if observed is None:
            return self._state(PlaybackState.UNKNOWN, video, ctx, None, "Playback state could not be read.")
        kind, current, ad = observed
        msg = {
            PlaybackState.PLAYING: "The video is playing (playback time is advancing)." + (" An ad is playing first — TaskPilot does not skip or block ads." if ad else ""),
            PlaybackState.PAUSED: "The video is loaded but paused.",
            PlaybackState.BUFFERING: "The video is buffering.",
        }.get(kind, "Playback state is unknown.")
        return self._state(kind, video, ctx, current, msg)

    async def pause_state(self, ctx: IntegrationContext) -> tuple[PlaybackState, float | None, bool] | None:
        return await self._sample(ctx)

    async def _sample(self, ctx: IntegrationContext) -> tuple[PlaybackState, float | None, bool] | None:
        """Observe the real <video>: PLAYING only if not paused AND currentTime advances."""
        try:
            first = await ctx.controller.evaluate(ctx.session_id, PLAYER_JS)
            await asyncio.sleep(1.5)
            second = await ctx.controller.evaluate(ctx.session_id, PLAYER_JS)
        except Exception:  # noqa: BLE001
            return None
        if not second.get("has_video"):
            return None
        t0, t1 = first.get("time") or 0.0, second.get("time") or 0.0
        if second.get("paused"):
            return PlaybackState.PAUSED, t1, bool(second.get("ad"))
        if t1 > t0:
            return PlaybackState.PLAYING, t1, bool(second.get("ad"))
        if (second.get("ready") or 0) < 3:
            return PlaybackState.BUFFERING, t1, bool(second.get("ad"))
        return PlaybackState.UNKNOWN, t1, bool(second.get("ad"))

    def _state(self, state: PlaybackState, video: YouTubeVideo, ctx: IntegrationContext, current: float | None, message: str) -> YouTubePlayback:
        return YouTubePlayback(state=state, video=video, page_url=None, current_time=current, message=message, observed_at=utc_now())
