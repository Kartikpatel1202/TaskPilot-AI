# Memory architecture

Kamlesh Bhai remembers the current **session** so follow-ups work. For example, after "Blinkit par 2 litre Amul milk add karo", a later "Ek bread bhi add kar dena" is planned against the same store and basket.

## Model
- **`ConversationTurn`:** `turn_id`, `session_id`, `task_id`, `role` (USER / ASSISTANT / SYSTEM), `content` (redacted), `intent`, `created_at`.
- **`SessionContext`:** `active_website`, `active_intent`, `products` (name, brand, quantity, unit) and `last_task_id`.
- **`PlanningContext`:** what the planner sees. It contains `summary`, `recent_turns` and `session_context`.

## What gets stored
| When | Stored |
| --- | --- |
| Planning starts | The user's normalised and redacted command |
| A clarification is submitted | The answer, also linked to the task's `clarification_history` |
| Planning finishes | Kamlesh Bhai's reply, together with the intent |
| A plan is READY | `remember_classification` updates the session context: website, intent, and the full updated product list |

The context also handles three special cases:
- **General chat:** a GENERAL_CHAT message that names a site ("Remember that I want to shop on Blinkit") records `active_website`.
- **Store switch:** switching to a different store without a follow-up resets the basket.
- **Pending questions:** the context is not updated while a clarification is pending.

## Context retrieval
`build_context(session_id, task_id)` returns:
- the recent turns that fit in a character budget (`MEMORY_MAX_CHARACTERS / 2` by default), with the current task's turns chosen first and returned in chronological order;
- the summary of evicted turns;
- the structured session context.

The classifier is told to treat follow-ups as **the full updated set of entities**. A follow-up therefore produces one updated plan covering every item so far, and nothing has executed in Phase 2 that could double-add an item.

## Limits and expiry
| Setting | Default | Effect |
| --- | --- | --- |
| `MEMORY_MAX_TURNS` | 20 | Older turns are evicted into a deterministic summary of at most 1,500 characters |
| `MEMORY_MAX_CHARACTERS` | 12000 | Per-session character budget. One oversized turn is truncated |
| `MEMORY_TTL_MINUTES` | 60 | Sessions idle longer than this are dropped, checked lazily on access and by a periodic prune |
| `MEMORY_MAX_SESSIONS` | 1000 | LRU cap across sessions |

The summariser is deterministic: one clipped line per evicted turn, with no LLM call.

## Isolation
Every read and write is keyed by `session_id`, and there is no API that takes another session's ID. Cross-session requests ("show other users' memory") are rejected by the input guard before any LLM call. Tests cover isolation at the memory, API and WebSocket levels.

## Privacy and redaction
`redact_text()` (`core/logging.py`) masks the following before anything is stored, logged or sent to an LLM:
- card-like numbers (13–19 digits);
- CVV, OTP and PIN values;
- `password: …` and similar;
- bearer tokens;
- `sk-…` keys;
- `api_key=`, `token=` and `secret=` values.

Memory never stores credentials, cookies or payment details. The agent also refuses to *plan* typing them.

## Known limitations
- **In process memory only:** a backend restart clears all memory, plans and tasks. A database-backed `MemoryStore` (the protocol is in `agent/memory/base.py`) is a future enhancement.
- **Single process:** memory isn't shared across multiple backend processes.
- **Pattern-based redaction:** unusual formats of sensitive data may not be caught.

## Phase 6 — persistent memory

Conversation turns are stored in `conversation_turns`, **redacted before storage**, bounded per session
(`MEMORY_MAX_TURNS`) and expiring after `MEMORY_TTL_MINUTES`; the sweeper purges expired rows
(`run_maintenance`, ~every 5 minutes). Memory is scoped by session, and sessions are owned by users, so one user's
memory is never visible to another. Selector memory (`SelectorMemory`) is a separate in-process cache of working
selectors per site with a TTL.
