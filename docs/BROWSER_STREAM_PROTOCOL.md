# Browser stream protocol (Phase 3)

Live preview frames use a **separate WebSocket** from JSON telemetry:

```
ws://<host>/api/v1/browser/sessions/{session_id}/stream
```

## Client → server (text JSON, ≤ 1 KiB)
| Message | Meaning |
| --- | --- |
| `{"type":"subscribe"}` | Start receiving frames for this session. |
| `{"type":"ping"}` | Keep-alive; answered with `{"type":"pong"}`. |

Anything else gets `{"type":"error","code":"INVALID_MESSAGE",...}`. Binary messages from the client are rejected.

## Server → client: control (text JSON)
```json
{"type":"stream.ready","session_id":"…","format":"jpeg","width":1440,"height":900,"status":"live|waiting","max_fps":1.0}
{"type":"pong"}
{"type":"stream.ended","reason":"Browser session closed"}
{"type":"error","code":"INVALID_MESSAGE","message":"…"}
```
`waiting` means no browser exists for the session yet. Frames start as soon as a run launches one.

## Server → client: frames (binary)
```
┌──────────────┬───────────────────────────┬──────────────┐
│ uint32 BE  N │ N bytes UTF-8 JSON meta   │ JPEG bytes   │
└──────────────┴───────────────────────────┴──────────────┘
```
Metadata:
```json
{"frame_id":"uuid","session_id":"uuid","task_id":"uuid|null","sequence":42,
 "captured_at":"2026-11-05T17:10:51.123456Z","mime_type":"image/jpeg","width":1440,"height":900}
```

## Rules
- **Validation** on both sides: `0 < N ≤ 4096`, metadata parses and matches the schema, the image starts with the JPEG magic `FF D8 FF`, and the image is ≤ `BROWSER_MAX_FRAME_BYTES` (300 000 by default). The client also drops frames whose `session_id` is not its own, and any `sequence` not newer than the frame shown.
- **Rate:** at most `BROWSER_SCREENSHOT_FPS` (default 1, hard maximum 5) while someone watches or a run is active, plus one frame after every step.
- **Backpressure:** each subscriber holds at most **one** pending frame, and a newer frame replaces an unsent one. One sender task per connection performs all writes. Control messages use a bounded queue (16).
- **Isolation:** frames are published only to subscribers of their own session. There are at most 4 subscribers per session (extra connections are closed with `1013`).
- **Privacy:** no frames are captured while a password, OTP or card field is visible.
- **Memory:** the server keeps only the latest frame per session. The client keeps one object URL and revokes the previous one.

## Related REST
`GET /browser/sessions/{id}/screenshot` returns the latest real frame as `image/jpeg` (`Cache-Control: no-store`, with `X-Frame-Id`, `X-Frame-Sequence` and `X-Captured-At` headers), or `404 SCREENSHOT_NOT_AVAILABLE`.

## Client (`frontend/src/hooks/useBrowserStream.ts`)
Connects when the dashboard is online and execution is available. It sends `subscribe`, pings every 25 s, reconnects with exponential backoff (1, 2, 4, 8, 16 s plus jitter) and then reports `error` with a Reconnect button. Status values: `idle`, `connecting`, `waiting`, `live`, `reconnecting`, `ended`, `error`.
