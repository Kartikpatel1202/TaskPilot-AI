# Agent architecture (Phase 2 — Kamlesh Bhai's brain)

Phase 2 turns a natural-language command into a **validated, structured action plan**. It is a custom Pydantic-based orchestrator. It does not use LangChain or LangGraph, and the module boundaries are kept clean enough that a graph runtime could replace the orchestrator later. **Nothing is executed.** The LLM never touches a browser, and only trusted code changes task state.

## Flow

```
POST /api/v1/tasks ──► PlanningService.accept_command
                         ├─ TaskService.create_task  (IDLE, task.accepted, Kamlesh Bhai acknowledgement log)
                         └─ PlannerQueue.submit      (bounded; 503 PLANNER_BUSY when full)
                                    │  worker (PLANNER_CONCURRENCY)
                                    ▼
                         AgentOrchestrator.process_task
  1  IDLE → PLANNING                         task.state_changed
  2  agent.planning_started                  "Kamlesh Bhai is preparing your action plan."
  3  normalize_command                       NFC, strip control/bidi chars and wake word, redact secrets
  4  input_guard.screen_request              obvious injection/abuse → REJECTED, no LLM call
  5  MemoryManager.build_context             this session only: recent turns + summary + session context
  6  IntentClassifier (LLM #1)               → IntentClassification → agent.intent_detected
  7a needs clarification                     → NEEDS_CLARIFICATION plan (no 2nd LLM call)
  7b UNSUPPORTED                             → REJECTED plan (persona message, no 2nd LLM call)
  7c otherwise Planner (LLM #2)              → PlanDraft
        convert (server step IDs, order→ID deps) → risk_classifier → approval_policy
        → PlanValidator; invalid → retry with validation feedback (≤ AGENT_MAX_RETRIES)
  8  store plan, transition                  PLANNED | NEEDS_CLARIFICATION | FAILED(REQUEST_REJECTED)
  9  task.plan_ready / task.clarification_required, then agent.response_generated
 10  memory: assistant turn; READY plans update session context (website, intent, products)
  on ProviderError / PlanValidationError → task.planning_failed + FAILED (never a false plan_ready)
```

`agent.planning_progress` is emitted at each real stage: UNDERSTANDING_COMMAND, CLASSIFYING_INTENT, BUILDING_PLAN, VALIDATING_PLAN and FINALIZING. The progress value comes from the stage's position, not from a timer.

## Modules

| Concern | Module |
| --- | --- |
| Provider boundary | `agent/providers/base.py` (`LLMProvider`, `LLMResult`, `ProviderError` hierarchy, strict JSON schema) |
| Providers | `openai_provider.py`, `anthropic_provider.py`, `mock_provider.py` (+ `mock_scenarios.py`) |
| Retry / timeout policy | `agent/llm_runner.py` (`StructuredLLMRunner`) |
| Prompts and persona | `agent/prompts.py`, `core/persona.py` (Kamlesh Bhai persona, language detection, reply templates) |
| Normalisation | `agent/normalizer.py` |
| Intent classification | `agent/intent_classifier.py`, `agent/websites.py` (alias → domain catalog) |
| Planning | `agent/planner.py` |
| Safety | `agent/policies/{input_guard,url_policy,risk_classifier,approval_policy}.py` |
| Validation | `agent/validation/{plan_validator,action_validator,dependency_validator}.py` |
| Tools | `agent/tools/{registry,definitions,catalog}.py` (planning contracts only) |
| Memory | `agent/memory/{memory_manager,conversation_memory,summarizer,base}.py` |
| Replies | `agent/response_generator.py` (sanitises model text; blocks completion claims) |
| Orchestration | `agent/orchestrator.py`, `agent/plan_store.py` |
| Background work | `core/planner_queue.py`, `services/planning_service.py` |

Wiring is in `app/container.py`. `create_app(settings, provider=...)` lets tests inject a fake provider.

## Provider abstraction
Everything outside `agent/providers/` deals only with `LLMResult.parsed_output`, which has already been validated against the requested Pydantic schema. SDK objects and SDK errors never leak out. See [LLM_PROVIDERS.md](LLM_PROVIDERS.md).

## Intent classification
The LLM classifies the command into one of 12 `IntentType` values and extracts typed entities: products (name, brand, quantity, unit), search query, recipient, subject, topic, date/time and URL. It also reports the language (`en`, `hi`, `hinglish`), `is_follow_up`, and any missing information. Deterministic post-processing then:
- normalises the website to a canonical domain;
- forces `requires_clarification` when information is missing;
- clears clarification fields for GENERAL_CHAT and UNSUPPORTED.

It never invents missing values.

## Plan generation and validation
The LLM returns a `PlanDraft` with ordered steps that use only the six action primitives. Trusted code then:
- assigns UUID step IDs;
- resolves `depends_on_orders` to IDs;
- redacts typed text;
- raises risk levels using deterministic rules;
- inserts missing approval checkpoints;
- runs the full validator.

The validator's rules are listed in [ACTION_PLAN_SCHEMA.md](ACTION_PLAN_SCHEMA.md#validation-rules).

## Task lifecycle (Phase 2)
```
IDLE ─► PLANNING ─► PLANNED                (plan ready; Phase 3 will move PLANNED ─► EXECUTING)
                 ├► NEEDS_CLARIFICATION ─► PLANNING   (POST /tasks/{id}/clarification)
                 └► FAILED                 (rejected request, provider failure, invalid plan, queue full/timeout)
```
Phase 2 never moves a task to EXECUTING. The `PLANNING → EXECUTING` edge exists only for the clearly labelled Phase 1 demo simulation.

## WebSocket communication
New events are listed in [WEBSOCKET_PROTOCOL.md](WEBSOCKET_PROTOCOL.md#phase-2-agent-events). `task.plan_ready` deliberately carries only a summary. The dashboard fetches the full plan from `GET /api/v1/tasks/{id}/plan`, so large plans never pass through the bounded WebSocket queues.

## Frontend rendering
```
WebSocket ─► Zod (validators.ts) ─► dedupe ─► mapEventToActions ─► reducer (agent state)
task.plan_ready ─► PLAN_ANNOUNCED ─► useAgentPlan ─► GET /plan ─► Zod (planValidators.ts) ─► PLAN_READY
```
`AgentPanel` shows one of five views: the clarification panel, the thinking indicator (only stages the server has reported), a planning failure, the plan preview, or an empty state. Steps always render as **Planned**. The task lifecycle shows only the states the task actually visited, and execution is labelled "Execute · Phase 3".

## Phase 5: integration planning
- New intents: `YOUTUBE_SEARCH`, `YOUTUBE_PLAYBACK`, `MULTI_DOMAIN_WORKFLOW` (existing ones are kept;
  `MEDIA_SEARCH` on YouTube is routed to the integration planner). `IntentEntities.workflow` lists the steps of
  a multi-domain request in order.
- The orchestrator routes integration intents (when `INTEGRATIONS_ENABLED`) to the deterministic
  `IntegrationPlanner`, validates the plan with the Phase 2 validator **and** `workflow_validator`, and
  rejects `MULTI_DOMAIN_WORKFLOW` politely when integrations are disabled.
- Calendar dates/times/durations are parsed in Python from the user's own words with an injected clock; missing
  or ambiguous details (recipient, duration, AM/PM, dd/mm, past time, DST gap) become clarification questions.
- The offline mock classifier detects multi-domain commands by clause (see [MULTI_DOMAIN_WORKFLOWS.md](MULTI_DOMAIN_WORKFLOWS.md)).

## Phase 6 — agent changes

* Plans and conversation turns are persisted (memory redacted, TTL-bound) so a restart keeps context.
* LLM calls go through a circuit breaker, bounded retries with jitter, a daily token budget
  (`LLM_DAILY_TOKEN_BUDGET`, `LLM_BUDGET_EXCEEDED`) and usage accounting (`llm_usage`: tokens, latency, estimated
  cost). Never a silent fallback to the mock in production.
* The self-correction replanner is an optional LLM consumer with strictly validated output — see
  [SELF_CORRECTION_ENGINE.md](SELF_CORRECTION_ENGINE.md).
* OpenTelemetry spans: `planning.job`, `llm.structured_output`.
