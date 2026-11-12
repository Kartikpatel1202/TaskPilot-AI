import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  initialTaskPilotState,
  mapEventToActions,
  taskPilotReducer,
  type TaskPilotAction,
  type TaskPilotState,
} from "@/context/taskPilotReducer";
import { useAgentPlan } from "@/hooks/useAgentPlan";
import { parseTaskPlan } from "@/lib/planValidators";
import { parseServerMessage } from "@/lib/validators";
import { EventDeduplicator } from "@/lib/websocket";

import { PLAN_ID, SESSION, TASK, samplePlan, uuidFor } from "./fixtures";

import type { AnyTelemetryEvent } from "@/types/telemetry";

let seq = 0;

function ev(type: string, data: Record<string, unknown>): AnyTelemetryEvent {
  seq += 1;
  const raw = { event_id: uuidFor(5000 + seq), session_id: SESSION, task_id: TASK, sequence: seq, type, occurred_at: "2026-11-05T10:00:00.5Z", data };
  const parsed = parseServerMessage(JSON.stringify(raw));
  if (!parsed.ok || parsed.message.kind !== "event") throw new Error(`invalid event ${type}: ${JSON.stringify(parsed)}`);
  return parsed.message.event;
}

const apply = (state: TaskPilotState, event: AnyTelemetryEvent) => mapEventToActions(event).reduce(taskPilotReducer, state);

function accepted(): TaskPilotState {
  return apply(
    initialTaskPilotState,
    ev("task.accepted", { task_id: TASK, state: "IDLE", command: "Order milk.", input_mode: "TEXT", created_at: "2026-11-05T10:00:00Z", is_demo: false }),
  );
}

const started = () => ev("agent.planning_started", { status: "PLANNING", message: "Kamlesh Bhai is preparing your action plan.", is_clarification: false });
const planReady = () =>
  ev("task.plan_ready", {
    plan_id: PLAN_ID, status: "READY", intent: "ECOMMERCE_SHOPPING", summary: "Prepare cart", step_count: 5,
    requires_human_approval: true, provider: "mock", model: "taskpilot-mock-v1", is_mock: true,
  });

describe("agent telemetry validation", () => {
  it("accepts every Phase 2 event type", () => {
    expect(() => [
      started(),
      ev("agent.planning_progress", { stage: "BUILDING_PLAN", progress: 50, message: "Building an action plan…" }),
      ev("agent.intent_detected", { intent: "MEDIA_SEARCH", confidence: 0.9, target_website: "youtube.com", language: "en", requires_clarification: false, is_follow_up: false }),
      planReady(),
      ev("task.clarification_required", { plan_id: PLAN_ID, question: "Which brand?", missing_information: ["brand"] }),
      ev("task.planning_failed", { code: "LLM_PROVIDER_TIMEOUT", message: "Try again.", retryable: true }),
      ev("agent.response_generated", { message: "Haan bhai!", language: "hinglish", kind: "plan_ready" }),
    ]).not.toThrow();
  });

  it("rejects malformed agent events safely", () => {
    const bad = [
      { type: "agent.intent_detected", data: { intent: "HACK", confidence: 2 } },
      { type: "agent.planning_progress", data: { stage: "MADE_UP", progress: 500, message: "x" } },
      { type: "task.plan_ready", data: { plan_id: "not-a-uuid" } },
    ];
    for (const b of bad) {
      const result = parseServerMessage(JSON.stringify({ event_id: uuidFor(1), session_id: SESSION, task_id: TASK, sequence: 1, occurred_at: "2026-11-05T10:00:00Z", ...b }));
      expect(result.ok).toBe(false);
    }
  });

  it("validates REST plans and rejects unsafe or out-of-order ones", () => {
    expect(parseTaskPlan(samplePlan())).not.toBeNull();
    const badUrl = samplePlan();
    badUrl.steps[0] = { ...badUrl.steps[0]!, action: { type: "navigate", url: "not a url", purpose: "x" } };
    expect(parseTaskPlan(badUrl)).toBeNull();
    const reordered = samplePlan();
    reordered.steps = [reordered.steps[1]!, reordered.steps[0]!];
    expect(parseTaskPlan(reordered)).toBeNull();
  });
});

describe("agent reducer", () => {
  it("tracks planning → intent → plan announced → plan ready", () => {
    let state = accepted();
    expect(state.agentStatus).toBe("IDLE");
    state = apply(state, started());
    expect(state.isPlanning).toBe(true);
    expect(state.agentStatus).toBe("PLANNING");
    state = apply(state, ev("agent.planning_progress", { stage: "CLASSIFYING_INTENT", progress: 33, message: "Identifying the task…" }));
    expect(state.planningProgress?.stage).toBe("CLASSIFYING_INTENT");
    state = apply(state, ev("agent.intent_detected", { intent: "ECOMMERCE_SHOPPING", confidence: 0.95, target_website: "amazon.in", language: "hinglish", requires_clarification: false, is_follow_up: false }));
    expect(state.intentClassification?.intent).toBe("ECOMMERCE_SHOPPING");
    state = apply(state, planReady());
    expect(state.planFetch).toEqual({ taskId: TASK, planId: PLAN_ID, status: "pending", error: null });
    state = taskPilotReducer(state, { type: "PLAN_READY", plan: samplePlan() });
    expect(state.activePlan?.plan_id).toBe(PLAN_ID);
    expect(state.agentStatus).toBe("PLAN_READY");
    expect(state.isPlanning).toBe(false);
    expect(state.planFetch).toBeNull();
    expect(state.logs.some((l) => l.message.includes("Not executed"))).toBe(true);
  });

  it("never rewinds planning progress on late or replayed stages", () => {
    let state = apply(accepted(), started());
    state = apply(state, ev("agent.planning_progress", { stage: "VALIDATING_PLAN", progress: 67, message: "Checking…" }));
    state = apply(state, ev("agent.planning_progress", { stage: "UNDERSTANDING_COMMAND", progress: 17, message: "Understanding…" }));
    expect(state.planningProgress?.stage).toBe("VALIDATING_PLAN");
  });

  it("handles clarification required and submission", () => {
    let state = apply(apply(accepted(), started()), ev("task.clarification_required", { plan_id: PLAN_ID, question: "Which brand?", missing_information: ["brand", "quantity"] }));
    expect(state.agentStatus).toBe("NEEDS_CLARIFICATION");
    expect(state.clarification).toEqual({ taskId: TASK, planId: PLAN_ID, question: "Which brand?", missingInformation: ["brand", "quantity"] });
    expect(state.isPlanning).toBe(false);
    state = taskPilotReducer(state, { type: "CLARIFICATION_SUBMITTED", taskId: TASK });
    expect(state.clarification).toBeNull();
    expect(state.agentStatus).toBe("PLANNING");
  });

  it("records planning failures and plan fetch failures", () => {
    let state = apply(apply(accepted(), started()), ev("task.planning_failed", { code: "LLM_AUTH_FAILED", message: "Credentials rejected.", retryable: false }));
    expect(state.agentStatus).toBe("ERROR");
    expect(state.planningFailure).toEqual({ taskId: TASK, code: "LLM_AUTH_FAILED", message: "Credentials rejected." });
    state = apply(apply(accepted(), started()), planReady());
    state = taskPilotReducer(state, { type: "PLAN_FETCH_FAILED", planId: PLAN_ID, error: "Network down" });
    expect(state.planFetch?.status).toBe("error");
  });

  it("assistant replies become Kamlesh Bhai log entries", () => {
    const state = apply(accepted(), ev("agent.response_generated", { message: "Haan bhai! Plan ready hai.", language: "hinglish", kind: "plan_ready" }));
    const log = state.logs.at(-1)!;
    expect(log.source).toBe("assistant");
    expect(log.language).toBe("hinglish");
    expect(log.message).toBe("Haan bhai! Plan ready hai.");
  });

  it("ignores agent events for tasks that are not active", () => {
    const state = accepted();
    const other = { ...started(), task_id: uuidFor(9999) } as AnyTelemetryEvent;
    expect(apply(state, other).isPlanning).toBe(false);
  });

  it("does not wipe agent state when the same task is accepted twice (REST + WebSocket)", () => {
    let state = apply(accepted(), started());
    state = taskPilotReducer(state, {
      type: "TASK_ACCEPTED",
      message: "Task accepted.",
      task: { task_id: TASK, session_id: SESSION, command: "Order milk.", input_mode: "TEXT", state: "IDLE", created_at: "2026-11-05T10:00:00Z", updated_at: "2026-11-05T10:00:00Z" },
    });
    expect(state.isPlanning).toBe(true);
  });

  it("does not process a duplicated plan_ready event twice", () => {
    const dedup = new EventDeduplicator();
    const event = planReady();
    let state = apply(accepted(), started());
    for (const copy of [event, event]) if (dedup.markIfNew(copy.event_id)) state = apply(state, copy);
    expect(state.logs.filter((l) => l.message.startsWith("Plan ready")).length).toBe(1);
  });

  it("tracks the visited states without inventing EXECUTING", () => {
    let state = accepted();
    state = apply(state, ev("task.state_changed", { previous_state: "IDLE", new_state: "PLANNING", is_demo: false }));
    state = apply(state, ev("task.state_changed", { previous_state: "PLANNING", new_state: "PLANNED", is_demo: false }));
    expect(state.taskHistory[TASK]).toEqual(["IDLE", "PLANNING", "PLANNED"]);
    expect(state.activeTask?.state).toBe("PLANNED");
  });
});

describe("useAgentPlan", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("fetches an announced plan once and dispatches PLAN_READY", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(samplePlan()), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    const dispatch = vi.fn<(a: TaskPilotAction) => void>();
    const planFetch = { taskId: TASK, planId: PLAN_ID, status: "pending" as const, error: null };
    const { rerender } = renderHook(() => useAgentPlan({ planFetch, sessionId: SESSION, dispatch }));
    rerender();
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: "PLAN_READY" })));
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0]![0])).toContain(`/tasks/${TASK}/plan?session_id=${SESSION}`);
  });

  it("reports plan fetch failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({ code: "PLAN_NOT_FOUND", message: "No plan exists for this task." }), { status: 404 })));
    const dispatch = vi.fn<(a: TaskPilotAction) => void>();
    renderHook(() => useAgentPlan({ planFetch: { taskId: TASK, planId: PLAN_ID, status: "pending", error: null }, sessionId: SESSION, dispatch }));
    await waitFor(() =>
      expect(dispatch).toHaveBeenCalledWith({ type: "PLAN_FETCH_FAILED", planId: PLAN_ID, error: "No plan exists for this task." }),
    );
  });

  it("rejects a plan that fails client-side validation", async () => {
    const bad = { ...samplePlan(), steps: [{ ...samplePlan().steps[0]!, order: 9 }] };
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify(bad), { status: 200 })));
    const dispatch = vi.fn<(a: TaskPilotAction) => void>();
    renderHook(() => useAgentPlan({ planFetch: { taskId: TASK, planId: PLAN_ID, status: "pending", error: null }, sessionId: SESSION, dispatch }));
    await waitFor(() => expect(dispatch).toHaveBeenCalledWith(expect.objectContaining({ type: "PLAN_FETCH_FAILED" })));
    expect(dispatch).not.toHaveBeenCalledWith(expect.objectContaining({ type: "PLAN_READY" }));
  });
});

describe("demo tasks never look like agent planning", () => {
  it("does not show the planning indicator for the Phase 1 demo simulation", () => {
    let state = apply(
      initialTaskPilotState,
      ev("task.accepted", { task_id: TASK, state: "IDLE", command: "[DEMO] walkthrough", input_mode: "TEXT", created_at: "2026-11-05T10:00:00Z", is_demo: true }),
    );
    state = apply(state, ev("task.state_changed", { previous_state: "IDLE", new_state: "PLANNING", is_demo: true }));
    expect(state.isPlanning).toBe(false);
    expect(state.agentStatus).toBe("IDLE");
  });

  it("clears a spinning indicator when the task fails without a planning event", () => {
    let state = apply(apply(accepted(), started()), ev("task.state_changed", { previous_state: "IDLE", new_state: "PLANNING", is_demo: false }));
    state = apply(state, ev("task.state_changed", { previous_state: "PLANNING", new_state: "FAILED", is_demo: false }));
    expect(state.isPlanning).toBe(false);
  });
});
