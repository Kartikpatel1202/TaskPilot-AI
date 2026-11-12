"use client";

import { useCallback, useEffect, useRef, type Dispatch, type MutableRefObject } from "react";

import { ApiError } from "@/lib/api";
import { executeTask, getExecution, stopTask } from "@/lib/browserApi";

import type { TaskPilotAction, TaskPilotState } from "@/context/taskPilotReducer";

export interface ExecutionCommandResult {
  ok: boolean;
  error?: string;
}

const RECOVERABLE_STATES = new Set(["EXECUTING", "WAITING_APPROVAL", "COMPLETED", "FAILED", "CANCELLED"]);

/**
 * Run Plan / Stop. Execution starts ONLY through `runPlan`: an explicit Run Plan click, or voice mode's
 * auto-run (`voice_auto`), which the server limits to low-risk plans and the user's Settings.
 */
export function useExecution({
  stateRef,
  dispatch,
}: {
  stateRef: MutableRefObject<TaskPilotState>;
  dispatch: Dispatch<TaskPilotAction>;
}) {
  const runInFlight = useRef(false);
  const stopInFlight = useRef(false);

  const runPlan = useCallback(
    async (taskId: string, trigger: "run_plan_click" | "voice_auto" = "run_plan_click"): Promise<ExecutionCommandResult> => {
      const { sessionId, connectionStatus, activeTask, activePlan, execution } = stateRef.current;
      if (runInFlight.current) return { ok: false, error: "Run Plan is already being sent." };
      if (!sessionId || connectionStatus !== "CONNECTED") return { ok: false, error: "TaskPilot is offline." };
      if (activeTask?.task_id !== taskId || activeTask.state !== "PLANNED") {
        return { ok: false, error: "Only a ready, not-yet-run plan can be run." };
      }
      if (!activePlan || activePlan.task_id !== taskId || activePlan.status !== "READY" || activePlan.steps.length === 0) {
        return { ok: false, error: "This plan has no browser steps to run." };
      }
      if (execution?.taskId === taskId) return { ok: false, error: "This plan has already been run." };

      runInFlight.current = true;
      dispatch({ type: "EXECUTION_REQUESTED", taskId });
      try {
        await executeTask(taskId, sessionId, trigger);
        return { ok: true };
      } catch (error) {
        const message = error instanceof ApiError ? error.message : "Run Plan failed.";
        dispatch({ type: "EXECUTION_REQUEST_FAILED", taskId, error: message });
        return { ok: false, error: message };
      } finally {
        runInFlight.current = false;
      }
    },
    [stateRef, dispatch],
  );

  const stopExecution = useCallback(
    async (taskId: string): Promise<ExecutionCommandResult> => {
      const { sessionId } = stateRef.current;
      if (!sessionId || stopInFlight.current) return { ok: false };
      stopInFlight.current = true;
      try {
        await stopTask(taskId, sessionId);
        dispatch({ type: "EXECUTION_STOP_REQUESTED", taskId });
        return { ok: true };
      } catch (error) {
        return { ok: false, error: error instanceof ApiError ? error.message : "Stop failed." };
      } finally {
        stopInFlight.current = false;
      }
    },
    [stateRef, dispatch],
  );

  return { runPlan, stopExecution };
}

/** After a reload, fills in the active task's execution from REST if telemetry history no longer has it. */
export function useExecutionRecovery({
  sessionId,
  taskId,
  taskState,
  hasExecution,
  connected,
  dispatch,
}: {
  sessionId: string | null;
  taskId: string | null;
  taskState: string | null;
  hasExecution: boolean;
  connected: boolean;
  dispatch: Dispatch<TaskPilotAction>;
}) {
  const tried = useRef(new Set<string>());
  useEffect(() => {
    if (!connected || !sessionId || !taskId || !taskState || hasExecution) return undefined;
    if (!RECOVERABLE_STATES.has(taskState)) return undefined;
    const key = `${taskId}:${taskState}`;
    if (tried.current.has(key)) return undefined;
    let cancelled = false;
    // Give replayed telemetry a moment to arrive first.
    const timer = setTimeout(() => {
      tried.current.add(key);
      getExecution(taskId, sessionId)
        .then((summary) => {
          if (!cancelled) dispatch({ type: "EXECUTION_SUMMARY_LOADED", summary });
        })
        .catch(() => undefined); // 409: no execution for this task (e.g. planning failed)
    }, 600);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [connected, sessionId, taskId, taskState, hasExecution, dispatch]);
}
