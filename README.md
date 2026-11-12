# TaskPilot AI

**Voice-controlled autonomous browser agent.** Tell TaskPilot — or its assistant persona, **Kamlesh Bhai** — what you want done on the web, by voice or text, and it plans the steps, then — only when you click **Run Plan** — drives a real Chromium browser, streams it live to the dashboard and asks for your approval before anything sensitive.

> Example (future): *"Open Blinkit, search for 2 litres Amul milk, one bread packet and one dozen eggs, then add them to my cart."*

This repository is at **Phase 5 of 6: multi-domain agentic workflows (YouTube, Gmail drafts, Google Calendar, safe downloads)** on top of Phase 4 e-commerce automation. Kamlesh Bhai:
- understands commands in English, Hindi or Hinglish;
- classifies intent and extracts entities;
- remembers the current session's context;
- asks clarifying questions instead of guessing;
- produces validated, risk-classified, step-by-step browser action plans with approval checkpoints.

- executes a validated plan in **real Chromium** (Playwright) after an explicit **Run Plan** click, with a live screenshot stream, per-step results, Stop, and real approval checkpoints.

**Planning never opens a browser.** Payments, checkout, placing orders, **sending email**, and deletions are **never automated**, even with approval; Gmail work stops at a saved draft and calendar events need an exact-event approval. Passwords, OTPs, CAPTCHAs and sign-ins are never automated either.

---

## Conversation, hands-free voice, Activity Logs and Settings

* **Chat vs tasks.** Greetings and questions ("Hello Kamlesh Bhai", "kaise ho?", "what can you do?") get a natural reply
  in your language and use your name from Settings; no browser task runs. Store names garbled by speech recognition
  ("blink it", "billing kit") are understood, "Blinkit kholo" / "Amazon open karo" open the site, and a spoken product
  list after "kya kya add karna hai?" continues the same shopping task.
* **Planner.** `AGENT_PROVIDER=auto` uses Anthropic or OpenAI when its API key is set in `backend/.env`. Without a key the
  offline rule-based planner is used and the dashboard says so with setup instructions — it is never shown as AI.
  ChatGPT-like open conversation needs a real API key.
* **Visible browser.** Development uses `BROWSER_HEADLESS=false` (a Chromium window opens on your machine) and
  `BROWSER_NETWORK_GUARD=proxy` (needed for bot-protected sites such as Blinkit; see docs/BROWSER_SECURITY.md).
* **Hands-free voice.** Click the mic: speak, pause, and the request is sent automatically; low-risk plans (open, search,
  add to cart) start by themselves; Kamlesh Bhai answers out loud and listens again. Orders, payments, sending and
  deleting never auto-run and always need your approval. "Stop voice" ends it; "Interrupt" cuts a spoken reply.
* **Activity Logs** (`/activity`) shows persisted tasks, browser steps, approvals and events with filters and per-task
  details. **Settings** (`/settings`) stores name, language, voice and store preferences in the database.

## What Phase 5 adds
| Area | Status |
| --- | --- |
| **YouTube**: search, observed results, auto-select only a clear winner (else you choose), open and **verify** playback (PLAYING / PAUSED / BUFFERING / LOGIN_REQUIRED / PLAYBACK_BLOCKED / UNKNOWN); no downloading, no ad/DRM bypass | ✅ fixture-verified · ❌ **not run on youtube.com** ([docs/YOUTUBE_AUTOMATION.md](docs/YOUTUBE_AUTOMATION.md)) |
| **Gmail drafts only**: compose, save, verify in Drafts; asking to *send* still saves a draft (*"Haan bhai, main email ka draft prepare kar sakta hoon. Final Send tum Gmail se manually kar sakte ho."*); no invented recipients; editable before Run Plan | ✅ fixture-verified · ❌ **not run on Gmail** ([docs/GMAIL_DRAFT_AUTOMATION.md](docs/GMAIL_DRAFT_AUTOMATION.md)) |
| **Google Calendar**: deterministic timezone/DST-aware parsing (asks when ambiguous or duration missing), conflict and duplicate check, **exact-event approval** (*Reject Event Creation / Confirm This Exact Event*), single Save, verified creation or UNKNOWN | ✅ fixture-verified · ❌ **not run on Google Calendar** ([docs/GOOGLE_CALENDAR_AUTOMATION.md](docs/GOOGLE_CALENDAR_AUTOMATION.md)) |
| **Safe downloads**: domain allow-list, hop-by-hop redirect checks, extension/MIME/magic validation, size cap, SHA-256, isolated per-session storage with TTL, `/files` APIs with ownership and delete confirmation; executables/archives refused; never executed | ✅ ([docs/FILE_DOWNLOAD_SECURITY.md](docs/FILE_DOWNLOAD_SECURITY.md)) |
| Capability registry, domain router, **multi-domain workflows** with typed result hand-off, dependency skipping and honest partial success | ✅ ([docs/MULTI_DOMAIN_ARCHITECTURE.md](docs/MULTI_DOMAIN_ARCHITECTURE.md), [docs/DOMAIN_CAPABILITY_REGISTRY.md](docs/DOMAIN_CAPABILITY_REGISTRY.md), [docs/MULTI_DOMAIN_WORKFLOWS.md](docs/MULTI_DOMAIN_WORKFLOWS.md)) |
| 36 new telemetry events (`integration.*`, `youtube.*`, `gmail.*`, `calendar.*`, `file.*`, `workflow.*`), 13 new REST endpoints, dashboard **Integrations** panel, calendar approval dialog | ✅ |

Quick try (dev only, local fixtures): with `INTEGRATION_ENABLE_FIXTURES=true` plus the Phase 3/4 fixture settings in `backend/.env`, type *"Find a Python tutorial for beginners on fixture youtube and email the link to friend@example.com on fixture gmail"* → Run Plan, or *"Schedule a meeting with Rahul tomorrow at 3pm for 30 minutes on fixture calendar"* → Run Plan → review the exact event.

## What Phase 4 added
| Area | Status |
| --- | --- |
| Commerce adapters for **Blinkit** and **Amazon India** on the Phase 3 browser engine (registry selects by validated domain) | ✅ fixture-verified · ❌ **not run on the live sites** ([docs/COMMERCE_ARCHITECTURE.md](docs/COMMERCE_ARCHITECTURE.md)) |
| Deterministic product matching: brand, product line/variant, size and unit conversion, multipacks, specs (RAM/SSD), budget, ambiguity → **you choose** | ✅ ([docs/PRODUCT_MATCHING.md](docs/PRODUCT_MATCHING.md)) |
| Cart reconciliation (adds only the missing quantity), verified add-to-cart, quantity updates, cart verification (VERIFIED / PARTIAL / MISMATCH), Decimal INR prices, price-change disclosure | ✅ ([docs/CART_VERIFICATION.md](docs/CART_VERIFICATION.md)) |
| Checkout review (never purchases), **exact-order purchase approval**, stale-approval detection, single **COD** submission after approval, prepaid → **you pay** | ✅ ([docs/CHECKOUT_AND_PURCHASE_SAFETY.md](docs/CHECKOUT_AND_PURCHASE_SAFETY.md)) |
| 23 `commerce.*` telemetry events, 8 commerce REST endpoints, dashboard Shopping panel, product-choice dialog, final purchase review, `/sessions` page | ✅ |
| Phase 3 carry-forward: hop-by-hop redirect validation for scripts/XHR/fetch/frames, enforced `BROWSER_MAX_PAGES_PER_SESSION`, Browser Sessions page | ✅ |
| Mock planner: quantity answers ("1 litre", "दो लीटर", "ek dozen") are used instead of asked again | ✅ fixed |

Quick try (dev only, local fixture shops): with `COMMERCE_ENABLE_FIXTURES=true`, `BROWSER_TEST_ALLOWED_ORIGINS=http://127.0.0.1:8000` and `BROWSER_DEV_FIXTURES_ENABLED=true` in `backend/.env`, type *"fixture Blinkit par 2 litre Amul Taaza milk, 1 bread packet aur 12 eggs cart mein add karo"* → Run Plan → pick the bread when asked. Or *"fixture Blinkit par 12 eggs order karo, cash on delivery"* to see the final purchase review (fixture orders are fake).

## What Phase 3 added
| Area | Status |
| --- | --- |
| Playwright (Python, async) browser manager: lazy Chromium, one isolated context per session, limits, idle expiry, crash handling | ✅ ([docs/BROWSER_SESSION_MANAGEMENT.md](docs/BROWSER_SESSION_MANAGEMENT.md)) |
| Trusted DOM inspector + selector resolver (role/name/label/placeholder/text, semantic scoring, ambiguity refusal, bounded healing) | ✅ ([docs/PLAYWRIGHT_CONTROLLER.md](docs/PLAYWRIGHT_CONTROLLER.md)) |
| Action handlers: navigate, click, type, extract, request_approval, stop — results from observed behaviour | ✅ |
| Navigation guard (allow-list, public-IP DNS check, validated redirects), download guard, pop-up blocking | ✅ ([docs/BROWSER_SECURITY.md](docs/BROWSER_SECURITY.md)) |
| Runtime action policy: manual-only payments/orders/checkout/sending; no credential typing; sign-in walls stop safely | ✅ |
| Execution engine: Run Plan / Stop APIs, bounded queue, sequential steps, dependencies, timeouts, real approvals | ✅ ([docs/EXECUTION_ENGINE.md](docs/EXECUTION_ENGINE.md)) |
| Live preview: real JPEG screenshots over a binary WebSocket, newest frame only, privacy pause | ✅ ([docs/BROWSER_STREAM_PROTOCOL.md](docs/BROWSER_STREAM_PROTOCOL.md)) |
| Dashboard: Run Plan, Stop, execution timeline with extracted data, live browser preview, `CANCELLED` state | ✅ |
| Local fixture shop + real-Chromium tests | ✅ (public sites **not** tested — see limitations) |

Quick try (dev only, fixture shop): set `BROWSER_TEST_ALLOWED_ORIGINS=http://127.0.0.1:8000` and `BROWSER_DEV_FIXTURES_ENABLED=true` in `backend/.env`, install Chromium (`python -m playwright install chromium`), then type *"Demo shop par 1 litre Amul milk cart mein add karo"* and click **Run Plan**.

## What Phase 2 added
| Area | Status |
| --- | --- |
| Provider-independent LLM layer: **mock** (offline, default), **OpenAI**, **Anthropic** | ✅ ([docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md)) |
| Intent classification (12 intents) with typed entities and language detection | ✅ |
| Structured planning: 6 action primitives, deterministic validation, URL policy, risk floors, approval checkpoints | ✅ ([docs/ACTION_PLAN_SCHEMA.md](docs/ACTION_PLAN_SCHEMA.md)) |
| Session memory, multi-turn follow-ups, clarification workflow | ✅ ([docs/MEMORY_ARCHITECTURE.md](docs/MEMORY_ARCHITECTURE.md)) |
| Bounded background planning queue (no LLM calls inside requests) | ✅ |
| New task states `PLANNED` and `NEEDS_CLARIFICATION`; new REST endpoints and 7 WebSocket events | ✅ |
| Dashboard agent panel: thinking stages, plan preview, clarification panel, intent and risk badges | ✅ |
| Prompt-injection and safety layers | ✅ ([docs/AGENT_SAFETY.md](docs/AGENT_SAFETY.md)) |

Quick try with the default mock planner: type *"Blinkit kholo aur 2 litre Amul milk, ek bread packet aur 12 eggs cart mein add karo"*, then *"Order milk."*, then *"Amazon par laptop order karo aur payment kar do"*.

## What Phase 1 delivered

| Area | Status |
| --- | --- |
| Dark, responsive dashboard (sidebar, navbar, command center, browser preview, execution logs) | ✅ |
| Text commands → `POST /api/v1/tasks` (validated, recorded in memory, stays `IDLE`) | ✅ |
| Voice-to-text via the Web Speech API (English / Hindi / Hinglish, never auto-submits) | ✅ |
| Optional spoken replies (Web Speech Synthesis) in the user's language | ✅ |
| Real-time WebSocket telemetry with ordering, dedupe, replay and reconnect/backoff | ✅ |
| Human-in-the-loop approval dialog driven by backend events | ✅ |
| Explicit task state machine with validated transitions | ✅ |
| Development-only, clearly labelled demo telemetry and demo approvals | ✅ |
| Backend (pytest) and frontend (Vitest + RTL) tests | ✅ |

### Kamlesh Bhai (assistant persona)
Friendly, sharp, a little witty and reliable. Kamlesh Bhai **mirrors your language**: English in, English out; Hindi (Devanagari) in, Hindi out; Hinglish in, Hinglish out. The classifier reports the language, and the plan's reply from Kamlesh Bhai (`agent.response_generated`) is written in that language. The dashboard can read replies aloud with a matching voice (`hi-IN` / `en-IN`). The persona and system prompt are defined in `app/core/persona.py`.

## Architecture overview

```
┌───────────────────────── Browser (Next.js 14) ─────────────────────────┐
│ CommandCenter ─ useSpeechRecognition                                    │
│      │ REST (lib/api.ts, Zod-validated)                                 │
│      ▼                                                                  │
│ TaskPilotContext (useReducer) ◀─ mapEventToActions ◀─ Zod ◀─ useWebSocket│
│      │                                                                  │
│      ▼                                                                  │
│ BrowserPreview · ExecutionLogs · TaskStatusCard · ApprovalDialog        │
└───────────────┬───────────────────────────────────────▲─────────────────┘
          HTTP  │ /api/v1/*                         WS  │ /api/v1/ws/{session_id}
┌───────────────▼───────────────────────────────────────┴─────────────────┐
│ FastAPI  routes (thin) → services (TaskService, ApprovalService)         │
│          → EventManager (ids, per-session sequence) → WebSocketManager   │
│          (per-connection bounded queues, bounded history, replay)        │
│          StateMachine · DemoSimulator (dev only) · Planner/Browser       │
│          Protocols (Phase 2/3 extension points, unimplemented)          │
└──────────────────────────────────────────────────────────────────────────┘
```

Details are in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Technology stack
- **Frontend:** Next.js 14 (App Router), React 18, TypeScript (strict), Tailwind CSS 3.4, ShadCN UI (Radix Dialog), Lucide icons, Zod, native WebSocket, Web Speech API. State uses React Context + `useReducer` (no Redux).
- **Backend:** Python 3.11+, FastAPI, Uvicorn, Pydantic v2, pydantic-settings, asyncio, native FastAPI WebSockets.
- **Quality:** ESLint (`next/core-web-vitals`), `tsc --noEmit`, Vitest + React Testing Library, pytest + pytest-asyncio + httpx.
- **Persistence:** none in Phase 1. All state is in memory and bounded.

## Repository structure
```
TaskPilot-AI/
├── frontend/              Next.js dashboard
│   ├── src/app/           layout, page, globals.css, providers
│   ├── src/components/    layout · dashboard · command · browser · logs · approval · ui
│   ├── src/hooks/         useWebSocket · useSpeechRecognition · useSpeechSynthesis · useTaskPilot
│   ├── src/context/       TaskPilotContext + pure reducer (taskPilotReducer.ts)
│   ├── src/lib/           api · websocket · validators (Zod) · utils · constants · persona
│   ├── src/types/         task · telemetry · approval · voice
│   └── tests/             Vitest suites
├── backend/
│   ├── app/api/           health · tasks · approvals · websocket (thin routers)
│   ├── app/core/          state_machine · event_manager · logging · persona
│   ├── app/schemas/       Pydantic contracts (mirror the TS types)
│   ├── app/services/      task_service · approval_service · interfaces (Phase 2/3 protocols)
│   ├── app/websocket/     manager.py (transport)
│   ├── app/dev/           demo_events.py (development-only simulation)
│   └── tests/             pytest suites
├── docs/                  ARCHITECTURE · API_CONTRACT · WEBSOCKET_PROTOCOL · DEVELOPMENT
└── docker-compose.yml
```

## Prerequisites
- Python **3.11+**
- Node.js **18.17+** (tested with Node 24) and npm
- A Chromium-based browser (Chrome or Edge) for voice input. Firefox does not ship `SpeechRecognition`; the dashboard detects this and says so.

## Installation and startup (Windows PowerShell)

**Backend** (terminal 1):
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```
- API: http://localhost:8000. Swagger docs: http://localhost:8000/docs

**Frontend** (terminal 2):
```powershell
cd frontend
npm install
Copy-Item .env.example .env.local
npm run dev
```
- Dashboard: http://localhost:3000

On Linux/macOS, use `python3 -m venv .venv`, `source .venv/bin/activate`, and `cp` instead of `Copy-Item`. See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

**Docker (optional):** `docker compose up` runs both services with stock images.

## Environment

| File | Variable | Default | Notes |
| --- | --- | --- | --- |
| `backend/.env` | `APP_NAME` | `TaskPilot AI` | |
| | `APP_ENV` | `development` | Demo endpoints work only in `development`/`test` |
| | `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | |
| | `LOG_LEVEL` | `INFO` | JSON-lines logs with secret redaction |
| | `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated. `*` is ignored (credentials are allowed) |
| | `ENABLE_DEMO_ENDPOINTS` | `true` | Returns 404 when false or outside dev |
| | `MAX_COMMAND_LENGTH` | `4000` | |
| | `WEBSOCKET_MAX_CONNECTIONS` | `10` | Total concurrent sockets |
| | `TELEMETRY_HISTORY_LIMIT` | `500` | Per-session replay buffer (raised for execution events) |
| `frontend/.env.local` | `NEXT_PUBLIC_API_BASE_URL` | `http://localhost:8000` | Browser-visible, so no secrets |
| | `NEXT_PUBLIC_WS_BASE_URL` | `ws://localhost:8000` | |
| | `NEXT_PUBLIC_DEMO_MODE` | `true` | Shows demo controls (only if the backend also allows them) |

Phase 2 agent settings (`AGENT_PROVIDER`, API keys, models, timeouts, retries, plan and queue limits, memory limits) are listed in `backend/.env.example` and explained in [docs/LLM_PROVIDERS.md](docs/LLM_PROVIDERS.md). The default `AGENT_PROVIDER=mock` works with no API key.

Phase 3 browser and execution settings (`AGENT_BROWSER_EXECUTION_ENABLED`, `BROWSER_*`, `EXECUTION_*`) are listed and commented in `backend/.env.example`; see [docs/BROWSER_SECURITY.md](docs/BROWSER_SECURITY.md) and [docs/BROWSER_SESSION_MANAGEMENT.md](docs/BROWSER_SESSION_MANAGEMENT.md). After `pip install -r requirements.txt`, run `python -m playwright install chromium` once.

## Testing and quality
```powershell
# backend (579 tests, offline; real Chromium against the local fixture sites; no LLM keys needed)
cd backend; .\.venv\Scripts\python.exe -m pytest -v

# frontend (182 tests)
cd frontend
npm test            # Vitest + React Testing Library
npm run typecheck   # tsc --noEmit (strict)
npm run lint        # next lint
npm run build       # production build (stop `npm run dev` first)
```

## Using the dashboard
1. Wait for **Connected** in the top bar. The agent panel shows **Kamlesh Bhai · Available**, plus a **MOCK PLANNER** badge in mock mode.
2. Type a command (or click the mic, speak, and click again to stop), then press **Execute** or Enter. Shift+Enter adds a new line.
3. The agent panel shows the planning stages the server reports, followed by the **plan preview**: objective, intent, website, confidence, risk, assumptions, approval checkpoints and numbered steps. Every step is marked *Planned* — nothing has run.
4. Click **Run Plan** to execute it in Chromium. Each step then shows its observed result (Done / Failed / Blocked / Not run, verification, extracted data), the **browser preview** streams real screenshots, and **Stop** halts after the current browser action. Approval checkpoints open the approval dialog; payments and orders stay manual even if approved.
5. If something is missing, Kamlesh Bhai asks in the **clarification panel**. Your answer re-plans the same task.
6. Follow-ups ("Also add one bread packet") reuse the session's context.
7. With demo mode on, **Developer simulation → Run demo telemetry / Trigger demo approval** still exercises the Phase 1 UI with clearly labelled simulated events.

## Current limitations
- **YouTube / Gmail / Google Calendar not live-tested.** Phase 5 was verified only against the **local YouTube-, Gmail- and Calendar-like fixtures** and local download test files (automated with real Chromium, plus live dashboard runs on the fixtures). No run against youtube.com, mail.google.com or calendar.google.com has been performed; real markup, sign-in walls and consent screens may make runs stop (safely). Real-site downloads are off until `FILE_DOWNLOAD_ALLOWED_DOMAINS` is set.
- **Blinkit / Amazon not live-tested.** Phase 4 commerce was verified only against the **local Blinkit-like and Amazon-like fixtures**; no automated or manual run on blinkit.com or amazon.in has been performed (public smoke tests are opt-in and need your explicit go-ahead). Phase 3 was likewise verified only against the **local fixture shop** (real Chromium, real screenshots). Blinkit, Amazon, YouTube and Google are allow-listed but were **not** exercised; their markup changes, bot protection and sign-in walls may make runs fail (safely).
- **Manual-only actions.** Payments, checkout, placing orders, sending, publishing and deleting are refused even after approval. Sign-in, OTP and CAPTCHA are never automated; runs stop with `AUTHENTICATION_REQUIRED`.
- **Network egress.** The navigation guard is application-level; public deployments must also restrict egress to private networks at the infrastructure level (see [docs/BROWSER_SECURITY.md](docs/BROWSER_SECURITY.md)).
- **Real providers not tested live.** The OpenAI and Anthropic providers are unit-tested against mocked SDKs but haven't been called against the live APIs in this phase.
- **Memory-only state.** Tasks, plans, approvals, session memory and telemetry history are lost when the backend restarts. Task history persistence is deferred to a later phase.
- **No authentication.** The session ID is a per-tab UUID kept in `sessionStorage`.
- **Browser-dependent voice.** Voice recognition depends on the browser's Web Speech implementation, and Chrome sends audio to Google's speech service.
- **One page.** Only **Overview** is navigable. The other sidebar items are disabled and marked "Soon".

## Roadmap
| Phase | Focus |
| --- | --- |
| 1 | ✅ Core system, telemetry, approvals, dashboard |
| 2 | ✅ LLM agent brain: intent, planning, memory, clarification, safety policies |
| 3 | ✅ Playwright browser control: Run Plan / Stop, live binary screenshot stream, runtime safety policy, real approvals |
| 4 | ✅ E-commerce automation: Blinkit & Amazon India adapters, matching, cart verification, exact-order approval, COD-only submission (fixture-verified) |
| 4b | Execution monitoring, failure recovery, activity log views |
| 5 | ✅ Multi-domain workflows: YouTube, Gmail drafts, Google Calendar (exact-event approval), safe downloads, typed hand-offs (fixture-verified) |
| 6 | Hardening: auth, multi-user, deployment, observability |
