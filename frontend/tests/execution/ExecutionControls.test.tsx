import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ExecutionControls, type ExecutionControlsProps } from "@/components/execution/ExecutionControls";

import { SESSION, TASK, samplePlan } from "../fixtures";

import type { ExecutionState } from "@/types/execution";
import type { Task } from "@/types/task";

const task: Task = {
  task_id: TASK,
  session_id: SESSION,
  command: "Demo shop par 1 litre Amul milk cart mein add karo",
  input_mode: "TEXT",
  state: "PLANNED",
  created_at: "2026-11-05T10:00:00Z",
  updated_at: "2026-11-05T10:00:01Z",
};

function running(patch: Partial<ExecutionState> = {}): ExecutionState {
  return {
    taskId: TASK, planId: null, status: "EXECUTING", totalSteps: 5, steps: {}, currentStepId: null, pausedApprovalId: null,
    message: null, errorCode: null, counts: null, headless: true, startedAt: "2026-11-05T10:00:02Z", finishedAt: null,
    stopRequested: false, ...patch,
  };
}

function renderControls(props: Partial<ExecutionControlsProps> = {}) {
  const onRun = vi.fn().mockResolvedValue({ ok: true });
  const onStop = vi.fn().mockResolvedValue({ ok: true });
  render(
    <ExecutionControls
      plan={samplePlan()}
      task={task}
      execution={null}
      executionAvailable
      connected
      isStarting={false}
      error={null}
      onRun={onRun}
      onStop={onStop}
      {...props}
    />,
  );
  return { onRun, onStop };
}

describe("ExecutionControls", () => {
  it("offers Run Plan for a ready, unexecuted plan and states the safety limits", () => {
    renderControls();
    expect(screen.getByTestId("run-plan")).toBeEnabled();
    expect(screen.getByTestId("execution-controls")).toHaveTextContent(/real chromium browser on amazon\.in/i);
    expect(screen.getByTestId("execution-controls")).toHaveTextContent(/payments, checkout, placing orders .* never automated/i);
  });

  it("runs only on an explicit click, exactly once", async () => {
    let resolve: () => void = () => undefined;
    const onRun = vi.fn(() => new Promise<void>((r) => (resolve = r)));
    renderControls({ onRun });
    expect(onRun).not.toHaveBeenCalled(); // never automatic
    const button = screen.getByTestId("run-plan");
    await userEvent.click(button);
    await userEvent.click(button);
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(onRun).toHaveBeenCalledWith(TASK);
    resolve();
  });

  it("is disabled with a reason when execution is unavailable or offline", () => {
    renderControls({ executionAvailable: false });
    expect(screen.getByTestId("run-plan")).toBeDisabled();
    expect(screen.getByText(/unavailable on this server/i)).toBeInTheDocument();
  });

  it("is disabled while the request is starting", () => {
    renderControls({ isStarting: true });
    expect(screen.getByTestId("run-plan")).toBeDisabled();
    expect(screen.getByTestId("run-plan")).toHaveTextContent("Starting…");
  });

  it("does not render for chat, rejected or step-less plans, or tasks that are not PLANNED", () => {
    const { container: chat } = render(
      <ExecutionControls plan={samplePlan({ intent: "GENERAL_CHAT", steps: [], requires_human_approval: false })} task={task} execution={null}
        executionAvailable connected isStarting={false} error={null} onRun={vi.fn()} onStop={vi.fn()} />,
    );
    expect(chat).toBeEmptyDOMElement();
    renderControls({ task: { ...task, state: "COMPLETED" } });
    expect(screen.queryByTestId("run-plan")).not.toBeInTheDocument();
  });

  it("shows Stop while running and locks it after one click", async () => {
    const { onStop } = renderControls({ task: { ...task, state: "EXECUTING" }, execution: running() });
    expect(screen.queryByTestId("run-plan")).not.toBeInTheDocument();
    await userEvent.click(screen.getByTestId("stop-execution"));
    expect(onStop).toHaveBeenCalledWith(TASK);
  });

  it("shows the paused state and a disabled Stop after a stop request", () => {
    renderControls({ task: { ...task, state: "WAITING_APPROVAL" }, execution: running({ status: "WAITING_APPROVAL", stopRequested: true }) });
    expect(screen.getByTestId("stop-execution")).toBeDisabled();
    expect(screen.getByRole("status")).toHaveTextContent(/stopping after the current browser action/i);
  });

  it("surfaces backend errors from Run Plan", () => {
    renderControls({ error: "Another plan is already running in this session's browser." });
    expect(screen.getByRole("alert")).toHaveTextContent(/already running/i);
  });
});
