import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PlanPreview } from "@/components/agent/PlanPreview";
import { ExecutionSummary } from "@/components/execution/ExecutionSummary";
import { ExecutionTimeline } from "@/components/execution/ExecutionTimeline";
import {
  initialTaskPilotState,
  mapEventToActions,
  taskPilotReducer,
  type TaskPilotAction,
  type TaskPilotState,
} from "@/context/taskPilotReducer";
import { parseServerMessage } from "@/lib/validators";

import { SESSION, TASK, samplePlan, uuidFor } from "../fixtures";

import type { ExecutionState } from "@/types/execution";
import type { AnyTelemetryEvent } from "@/types/telemetry";

const plan = samplePlan();
const [s1, s2, s3] = plan.steps;

function execution(patch: Partial<ExecutionState> = {}): ExecutionState {
  return {
    taskId: TASK, planId: plan.plan_id, status: "EXECUTING", totalSteps: 5, steps: {}, currentStepId: null,
    pausedApprovalId: null, message: null, errorCode: null, counts: null, headless: true,
    startedAt: "2026-11-05T10:00:02Z", finishedAt: null, stopRequested: false, ...patch,
  };
}

function view(stepId: string, status: ExecutionState["steps"][string]["status"], extra: Partial<ExecutionState["steps"][string]> = {}) {
  return {
    stepId, order: 1, actionType: "navigate", description: null, status, message: null, errorCode: null,
    durationMs: null, verified: false, extractedData: null, ...extra,
  };
}

describe("ExecutionTimeline", () => {
  it("shows unreported steps as pending while running", () => {
    render(<ExecutionTimeline plan={plan} execution={execution({ steps: { [s1!.step_id]: view(s1!.step_id, "RUNNING") } })} />);
    const steps = screen.getAllByTestId("execution-step");
    expect(steps.map((s) => s.getAttribute("data-status"))).toEqual(["RUNNING", "PENDING", "PENDING", "PENDING", "PENDING"]);
    expect(steps[0]).toHaveAttribute("aria-current", "step");
  });

  it("shows observed results, verification, errors and 'not run' after the end", () => {
    render(
      <ExecutionTimeline
        plan={plan}
        execution={execution({
          status: "FAILED",
          finishedAt: "2026-11-05T10:00:09Z",
          steps: {
            [s1!.step_id]: view(s1!.step_id, "SUCCEEDED", { message: "Opened Amazon.", durationMs: 1200, verified: true }),
            [s2!.step_id]: view(s2!.step_id, "FAILED", { message: "No unique element matched.", errorCode: "SELECTOR_NOT_FOUND" }),
          },
        })}
      />,
    );
    const steps = screen.getAllByTestId("execution-step");
    expect(steps.map((s) => s.getAttribute("data-status"))).toEqual(["SUCCEEDED", "FAILED", "SKIPPED", "SKIPPED", "SKIPPED"]);
    expect(steps[0]).toHaveTextContent("verified");
    expect(steps[0]).toHaveTextContent("1.2s");
    expect(steps[1]).toHaveTextContent("SELECTOR_NOT_FOUND");
    expect(steps[2]).toHaveTextContent("Not run");
  });

  it("renders extracted data as observed, with missing fields called out", () => {
    const extract = { ...s3!, action: { type: "extract" as const, target_description: "search results", fields: ["name", "price"] } };
    const p = samplePlan({ steps: [extract] });
    render(
      <ExecutionTimeline
        plan={p}
        execution={execution({
          steps: {
            [extract.step_id]: view(extract.step_id, "SUCCEEDED", {
              actionType: "extract",
              extractedData: {
                source: "observed_dom",
                items: [{ name: "Amul Taaza Toned Milk", price: "₹54" }, { name: "Mother Dairy Toned Milk", price: null }],
                missing_fields: ["price"],
              },
            }),
          },
        })}
      />,
    );
    const table = screen.getByTestId("extracted-data");
    expect(within(table).getByText("Amul Taaza Toned Milk")).toBeInTheDocument();
    expect(within(table).getByText("₹54")).toBeInTheDocument();
    expect(within(table).getByText("not shown")).toBeInTheDocument();
    expect(table).toHaveTextContent("Not found on the page: price");
  });

  it("PlanPreview switches from planned steps to observed execution", () => {
    const { rerender } = render(<PlanPreview plan={plan} />);
    expect(screen.getAllByTestId("plan-step")).toHaveLength(5);
    rerender(<PlanPreview plan={plan} execution={execution()} />);
    expect(screen.queryAllByTestId("plan-step")).toHaveLength(0);
    expect(screen.getAllByTestId("execution-step")).toHaveLength(5);
    expect(screen.queryByTestId("execution-notice")).not.toBeInTheDocument();
  });
});

describe("ExecutionSummary", () => {
  it("summarises a cancelled run honestly", () => {
    render(
      <ExecutionSummary
        execution={execution({
          status: "CANCELLED",
          message: "“Place order and pay” is manual-only in Phase 3.",
          errorCode: "SENSITIVE_ACTION_BLOCKED",
          counts: { succeeded: 2, failed: 0, blocked: 1, skipped: 2 },
          finishedAt: "2026-11-05T10:00:09Z",
        })}
      />,
    );
    const summary = screen.getByTestId("execution-summary");
    expect(summary).toHaveAttribute("data-status", "CANCELLED");
    expect(summary).toHaveTextContent("Execution stopped");
    expect(summary).toHaveTextContent("1 blocked");
    expect(summary).toHaveTextContent("SENSITIVE_ACTION_BLOCKED");
  });

  it("renders nothing while running", () => {
    const { container } = render(<ExecutionSummary execution={execution()} />);
    expect(container).toBeEmptyDOMElement();
  });
});

// ------------------------------------------------------------------ telemetry -> reducer

let seq = 0;
function event(type: string, data: Record<string, unknown>, taskId: string | null = TASK): AnyTelemetryEvent {
  seq += 1;
  const raw = {
    event_id: uuidFor(5000 + seq), session_id: SESSION, task_id: taskId, sequence: seq,
    occurred_at: "2026-11-05T10:00:05.000000+00:00", type, data,
  };
  const parsed = parseServerMessage(JSON.stringify(raw));
  if (!parsed.ok || parsed.message.kind !== "event") throw new Error(`invalid ${type}: ${parsed.ok ? "" : parsed.reason}`);
  return parsed.message.event;
}

function apply(state: TaskPilotState, ...events: AnyTelemetryEvent[]): TaskPilotState {
  return events.reduce((s, e) => mapEventToActions(e).reduce<TaskPilotState>((acc, a: TaskPilotAction) => taskPilotReducer(acc, a), s), state);
}

function plannedState(): TaskPilotState {
  const task = {
    task_id: TASK, session_id: SESSION, command: "c", input_mode: "TEXT" as const, state: "PLANNED" as const,
    created_at: "2026-11-05T10:00:00Z", updated_at: "2026-11-05T10:00:00Z",
  };
  const s = taskPilotReducer(initialTaskPilotState, { type: "TASK_ACCEPTED", task });
  return taskPilotReducer(s, { type: "PLAN_READY", plan });
}

describe("execution telemetry", () => {
  it("rejects malformed execution events", () => {
    const bad = parseServerMessage(
      JSON.stringify({
        event_id: uuidFor(1), session_id: SESSION, task_id: TASK, sequence: 1, occurred_at: "2026-11-05T10:00:05Z",
        type: "task.step_completed", data: { step_id: "nope", order: 0, status: "DONE" },
      }),
    );
    expect(bad.ok).toBe(false);
  });

  it("builds execution state from backend events, in order", () => {
    let state = apply(
      plannedState(),
      event("task.execution_started", { plan_id: plan.plan_id, total_steps: 5, engine: "chromium", headless: true }),
      event("task.step_started", { step_id: s1!.step_id, order: 1, action_type: "navigate", description: "Navigate to Amazon." }),
    );
    expect(state.execution?.status).toBe("EXECUTING");
    expect(state.execution?.steps[s1!.step_id]?.status).toBe("RUNNING");

    state = apply(
      state,
      event("task.step_completed", { step_id: s1!.step_id, order: 1, status: "SUCCEEDED", duration_ms: 900, message: "Opened.", verified: true }),
      event("task.step_blocked", { step_id: s2!.step_id, order: 2, status: "BLOCKED", error_code: "SENSITIVE_ACTION_BLOCKED", message: "Manual only." }),
      event("task.execution_cancelled", {
        status: "CANCELLED", total_steps: 5, succeeded_steps: 1, failed_steps: 0, blocked_steps: 1, skipped_steps: 3,
        message: "Manual only.", error_code: "SENSITIVE_ACTION_BLOCKED",
      }),
    );
    expect(state.execution?.status).toBe("CANCELLED");
    expect(state.execution?.steps[s2!.step_id]?.errorCode).toBe("SENSITIVE_ACTION_BLOCKED");
    expect(state.execution?.counts).toEqual({ succeeded: 1, failed: 0, blocked: 1, skipped: 3 });
    expect(state.logs.some((l) => l.message.includes("Execution cancelled"))).toBe(true);

    // a replayed execution_started never wipes progress
    const replay = apply(state, event("task.execution_started", { plan_id: plan.plan_id, total_steps: 5, engine: "chromium", headless: true }));
    expect(replay.execution?.steps[s1!.step_id]?.status).toBe("SUCCEEDED");
  });

  it("ignores execution events of another task", () => {
    const other = uuidFor(777);
    const state = apply(
      plannedState(),
      event("task.execution_started", { plan_id: plan.plan_id, total_steps: 5, engine: "chromium", headless: true }, other),
      event("task.step_started", { step_id: s1!.step_id, order: 1, action_type: "navigate", description: "x" }, other),
    );
    expect(state.execution).toBeNull();
  });

  it("tracks browser page, frames and auth notices", () => {
    const state = apply(
      plannedState(),
      event("browser.session_ready", { status: "READY", engine: "chromium", headless: true }),
      event("browser.page_updated", { url: "https://www.amazon.in/s", domain: "www.amazon.in", title: "Amazon" }),
      event("browser.frame_available", { frame_id: uuidFor(9), sequence: 4, width: 1440, height: 900, bytes: 20000, captured_at: "2026-11-05T10:00:05Z" }),
      event("browser.frame_available", { frame_id: uuidFor(8), sequence: 3, width: 1440, height: 900, bytes: 20000, captured_at: "2026-11-05T10:00:04Z" }),
      event("browser.authentication_required", { domain: "www.amazon.in", message: "Please sign in yourself.", headless: true }),
    );
    expect(state.browser.url).toBe("https://www.amazon.in/s");
    expect(state.browser.lastFrameSequence).toBe(4); // stale frame announcement ignored
    expect(state.browser.sessionStatus).toBe("AUTH_REQUIRED");
    expect(state.browser.notice?.kind).toBe("authentication_required");
  });

  it("marks the browser busy during a run and ready again when it ends", () => {
    let state = apply(
      plannedState(),
      event("browser.session_ready", { status: "READY", engine: "chromium", headless: true }),
      event("task.execution_started", { plan_id: plan.plan_id, total_steps: 5, engine: "chromium", headless: true }),
    );
    expect(state.browser.sessionStatus).toBe("BUSY");
    state = apply(
      state,
      event("task.execution_completed", {
        status: "COMPLETED", total_steps: 5, succeeded_steps: 5, failed_steps: 0, blocked_steps: 0, skipped_steps: 0,
        message: "All 5 steps ran in the browser and were checked.",
      }),
    );
    expect(state.browser.sessionStatus).toBe("READY");
  });

  it("a CANCELLED task state is accepted and terminal", () => {
    const state = apply(
      plannedState(),
      event("task.state_changed", { previous_state: "PLANNED", new_state: "EXECUTING", is_demo: false }),
      event("task.state_changed", { previous_state: "EXECUTING", new_state: "CANCELLED", reason: "Stopped by you.", is_demo: false }),
    );
    expect(state.activeTask?.state).toBe("CANCELLED");
  });
});
