import { render, screen } from "@testing-library/react";
import { createElement } from "react";
import { describe, expect, it } from "vitest";

import { TaskStatusCard } from "@/components/dashboard/TaskStatusCard";
import {
  initialTaskPilotState,
  mapEventToActions,
  taskPilotReducer,
  type TaskPilotState,
} from "@/context/taskPilotReducer";
import { MAX_LOGS } from "@/lib/constants";
import { parseServerMessage } from "@/lib/validators";
import { EventDeduplicator, buildWebSocketUrl, computeBackoffDelay, createSessionId, isUuid } from "@/lib/websocket";

import type { AnyTelemetryEvent } from "@/types/telemetry";

const SESSION = "0a9b8c7d-6e5f-4d3c-9b2a-1f0e9d8c7b6a";
const TASK = "1f2e3d4c-5b6a-4978-8a6b-5c4d3e2f1a0b";
let seq = 0;
let idCounter = 0;

function uuidFor(n: number): string {
  const hex = n.toString(16).padStart(12, "0");
  return `00000000-0000-4000-8000-${hex}`;
}

function event(type: string, data: Record<string, unknown>, overrides: Record<string, unknown> = {}) {
  seq += 1;
  idCounter += 1;
  return {
    event_id: uuidFor(idCounter),
    session_id: SESSION,
    task_id: TASK,
    sequence: seq,
    type,
    occurred_at: "2026-11-05T10:00:00.123456Z",
    data,
    ...overrides,
  };
}

function parseEvent(raw: unknown): AnyTelemetryEvent {
  const result = parseServerMessage(JSON.stringify(raw));
  if (!result.ok || result.message.kind !== "event") throw new Error(`expected event, got ${JSON.stringify(result)}`);
  return result.message.event;
}

function apply(state: TaskPilotState, ev: AnyTelemetryEvent): TaskPilotState {
  return mapEventToActions(ev).reduce(taskPilotReducer, state);
}

const accepted = () =>
  event("task.accepted", {
    task_id: TASK,
    state: "IDLE",
    command: "Open Blinkit and prepare my grocery cart",
    input_mode: "TEXT",
    created_at: "2026-11-05T10:00:00Z",
    is_demo: false,
  });

describe("telemetry validation", () => {
  it("accepts a valid event", () => {
    const result = parseServerMessage(
      JSON.stringify(event("log.created", { level: "INFO", message: "Task accepted successfully", source: "system", is_demo: false })),
    );
    expect(result.ok).toBe(true);
    if (result.ok) expect(result.message.kind).toBe("event");
  });

  it("accepts control frames", () => {
    const pong = parseServerMessage('{"type":"pong"}');
    expect(pong).toEqual({ ok: true, message: { kind: "control", message: { type: "pong" } } });
  });

  it("safely ignores unknown event types", () => {
    const result = parseServerMessage(JSON.stringify(event("browser.hijack", { anything: true })));
    expect(result.ok).toBe(false);
    if (!result.ok) expect(result.reason).toContain("browser.hijack");
  });

  it("rejects malformed messages without throwing", () => {
    for (const raw of ["{not json", "null", "[]", '{"type":"log.created"}', 42]) {
      expect(() => parseServerMessage(raw)).not.toThrow();
      expect(parseServerMessage(raw).ok).toBe(false);
    }
    const badLevel = event("log.created", { level: "LOUD", message: "x", source: "system", is_demo: false });
    expect(parseServerMessage(JSON.stringify(badLevel)).ok).toBe(false);
    const badSession = event("log.created", { level: "INFO", message: "x", source: "system", is_demo: false }, { session_id: "nope" });
    expect(parseServerMessage(JSON.stringify(badSession)).ok).toBe(false);
  });

  it("rejects browser frames that are not image data URLs", () => {
    const ev = event("browser.preview", { mode: "FRAME", message: "x", frame_data_url: "javascript:alert(1)", is_demo: false });
    expect(parseServerMessage(JSON.stringify(ev)).ok).toBe(false);
  });
});

describe("deduplication and ordering", () => {
  it("does not process the same event id twice", () => {
    const dedup = new EventDeduplicator(3);
    expect(dedup.markIfNew("a")).toBe(true);
    expect(dedup.markIfNew("a")).toBe(false);
    dedup.markIfNew("b");
    dedup.markIfNew("c");
    dedup.markIfNew("d"); // evicts "a" (bounded)
    expect(dedup.size).toBe(3);
    expect(dedup.has("a")).toBe(false);
  });

  it("reducer ignores a duplicated event (same log id is processed once via dedupe)", () => {
    const dedup = new EventDeduplicator();
    const ev = parseEvent(event("log.created", { level: "INFO", message: "hello", source: "system", is_demo: false }));
    let state = initialTaskPilotState;
    for (const copy of [ev, ev]) {
      if (dedup.markIfNew(copy.event_id)) state = apply(state, copy);
    }
    expect(state.logs).toHaveLength(1);
  });

  it("ignores stale (out-of-order) state changes", () => {
    let state = apply(initialTaskPilotState, parseEvent(accepted()));
    const planning = parseEvent(event("task.state_changed", { previous_state: "IDLE", new_state: "PLANNING", is_demo: false }));
    const executing = parseEvent(event("task.state_changed", { previous_state: "PLANNING", new_state: "EXECUTING", is_demo: false }));
    state = apply(state, executing);
    state = apply(state, planning); // arrives late
    expect(state.activeTask?.state).toBe("EXECUTING");
    // late log entries are inserted in sequence order
    const seqs = state.logs.map((l) => l.sequence);
    expect(seqs).toEqual([...seqs].sort((a, b) => (a ?? 0) - (b ?? 0)));
  });
});

describe("reducer state updates", () => {
  it("adds logs from log.created events", () => {
    const ev = parseEvent(
      event("log.created", {
        level: "SUCCESS",
        message: "Samajh gaya bhai!",
        source: "assistant",
        language: "hinglish",
        is_demo: false,
      }),
    );
    const state = apply(initialTaskPilotState, ev);
    expect(state.logs).toHaveLength(1);
    expect(state.logs[0]).toMatchObject({ level: "SUCCESS", message: "Samajh gaya bhai!", source: "assistant", language: "hinglish" });
  });

  it("caps the client-side log list", () => {
    let state = initialTaskPilotState;
    for (let i = 0; i < MAX_LOGS + 25; i += 1) {
      state = apply(state, parseEvent(event("log.created", { level: "DEBUG", message: `m${i}`, source: "system", is_demo: false })));
    }
    expect(state.logs).toHaveLength(MAX_LOGS);
    expect(state.logs.at(-1)?.message).toBe(`m${MAX_LOGS + 24}`);
  });

  it("tracks the task lifecycle through to completion and approval flow", () => {
    let state = apply(initialTaskPilotState, parseEvent(accepted()));
    expect(state.activeTask?.state).toBe("IDLE");
    for (const [from, to] of [
      ["IDLE", "PLANNING"],
      ["PLANNING", "EXECUTING"],
      ["EXECUTING", "WAITING_APPROVAL"],
    ]) {
      state = apply(state, parseEvent(event("task.state_changed", { previous_state: from, new_state: to, is_demo: true })));
    }
    expect(state.activeTask?.state).toBe("WAITING_APPROVAL");

    const approvalId = uuidFor(999);
    state = apply(
      state,
      parseEvent(
        event("approval.required", {
          approval_id: approvalId,
          task_id: TASK,
          session_id: SESSION,
          action_summary: "Place order",
          domain: "example.test",
          reason: "Purchase",
          risk_level: "HIGH",
          status: "PENDING",
          estimated_impact: null,
          expires_at: "2026-11-05T10:02:00Z",
          is_demo: true,
        }),
      ),
    );
    expect(state.activeApproval?.approval_id).toBe(approvalId);

    state = apply(
      state,
      parseEvent(event("approval.resolved", { approval_id: approvalId, decision: "APPROVE", status: "APPROVED", resolved_at: "2026-11-05T10:01:00Z", is_demo: true })),
    );
    expect(state.activeApproval).toBeNull();

    state = apply(state, parseEvent(event("task.completed", { summary: "Done", is_demo: true })));
    expect(state.activeTask?.state).toBe("COMPLETED");
    expect(state.logs.some((l) => l.level === "SUCCESS" && l.message === "Done")).toBe(true);
  });

  it("records failures with a safe message", () => {
    let state = apply(initialTaskPilotState, parseEvent(accepted()));
    state = apply(state, parseEvent(event("task.failed", { error_code: "APPROVAL_REJECTED", error_message: "Rejected by user", is_demo: true })));
    expect(state.activeTask?.state).toBe("FAILED");
    expect(state.activeTask?.error_message).toBe("Rejected by user");
  });

  it("updates the browser preview from browser.preview events", () => {
    const state = apply(
      initialTaskPilotState,
      parseEvent(event("browser.preview", { mode: "PLACEHOLDER", message: "Demo placeholder", url: null, frame_data_url: null, is_demo: true })),
    );
    expect(state.browserPreview).toMatchObject({ mode: "PLACEHOLDER", isDemo: true, frameDataUrl: null });
  });

  it("reflects state updates in the UI", () => {
    let state = apply(initialTaskPilotState, parseEvent(accepted()));
    const { rerender } = render(createElement(TaskStatusCard, { task: state.activeTask }));
    expect(screen.getByTestId("task-state-badge")).toHaveTextContent(/queued for planning/i);
    state = apply(state, parseEvent(event("task.state_changed", { previous_state: "IDLE", new_state: "PLANNING", is_demo: false })));
    rerender(createElement(TaskStatusCard, { task: state.activeTask }));
    expect(screen.getByTestId("task-state-badge")).toHaveTextContent("Planning");
  });
});

describe("websocket utilities", () => {
  it("uses 1/2/4/8/16s exponential backoff with bounded jitter", () => {
    const noJitter = () => 0;
    expect([0, 1, 2, 3, 4, 9].map((a) => computeBackoffDelay(a, undefined, 400, noJitter))).toEqual([
      1000, 2000, 4000, 8000, 16000, 16000,
    ]);
    const withJitter = computeBackoffDelay(0, undefined, 400, () => 0.999);
    expect(withJitter).toBeGreaterThanOrEqual(1000);
    expect(withJitter).toBeLessThan(1400);
  });

  it("creates valid UUID session ids and websocket URLs", () => {
    const id = createSessionId();
    expect(isUuid(id)).toBe(true);
    expect(buildWebSocketUrl("ws://localhost:8000/", id)).toBe(`ws://localhost:8000/api/v1/ws/${id}`);
  });
});
