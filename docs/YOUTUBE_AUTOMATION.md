# YouTube automation

Capabilities: search, read results, choose a video (automatically only when clearly best), open it
and **verify** playback. No downloading, no ad skipping/blocking, no DRM handling, no sign-in.

## Flow

1. `youtube_search` opens `https://www.youtube.com/results?search_query=…` through the guarded
   controller (fixture: `…/youtube/results.html`). The query passes the Phase 3 typing policy.
2. Results are read from `ytd-video-renderer` elements (`a#video-title` title/href, channel, duration,
   metadata line). Only links of the validated site with a real `watch?v=` id are kept (no shorts, ads,
   channels). Values are exactly what the page shows.
3. Ranking (`youtube/ranking.py`): relevance = share of meaningful query words in title/channel
   (+0.2 for a preferred channel). A video is auto-selected only if relevance ≥ 0.6 **and** it leads the
   runner-up by ≥ 0.15. Otherwise the user picks from up to 5 options (`PendingChoice`; the task shows
   `WAITING_APPROVAL`; `POST /tasks/{id}/workflow/choice`, `option_id: null` skips →
   `YOUTUBE_SELECTION_SKIPPED`, run cancelled).
4. `youtube_play` opens the watch page and samples the real `<video>` element twice (1.5 s apart):

| State | Meaning |
| --- | --- |
| PLAYING | not paused **and** `currentTime` advanced |
| PAUSED | paused (TaskPilot presses the player's own Play control once, policy-checked, then re-checks) |
| BUFFERING | not paused, time not advancing, `readyState < 3` |
| LOGIN_REQUIRED | a sign-in/age gate is shown — the user signs in personally |
| PLAYBACK_BLOCKED | the player shows an error ("Video unavailable", region lock…) |
| UNKNOWN | the player could not be read in time |

Only PLAYING makes the step succeed. If an ad is playing it is reported; TaskPilot never skips it.

## Policy

`IntegrationPolicy.check_click(YOUTUBE_PLAY, label)` allows only Play/Resume labels and refuses
Subscribe, Join, Buy/Rent, Download, Sign in, Premium. Downloading a YouTube video is refused at
planning time (REJECTED plan) even if a URL is given.

## Events

`youtube.search_started`, `youtube.search_completed`, `youtube.results_found`, `youtube.video_selected`,
`youtube.playback_started`, `youtube.playback_paused`, `youtube.playback_error`.

## Testing status

Verified on the local fixture (generated canvas test pattern as the video source) with real Chromium.
**Not tested against youtube.com.** Real-site selectors may need adjustment when YouTube changes its markup.
