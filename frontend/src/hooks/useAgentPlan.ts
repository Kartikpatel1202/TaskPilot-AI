"use client";

import { useCallback, useEffect, useRef, type Dispatch } from "react";

import { ApiError, getTaskPlan } from "@/lib/api";

import type { TaskPilotAction } from "@/context/taskPilotReducer";
import type { PlanFetchState } from "@/types/agent";

interface UseAgentPlanOptions {
  planFetch: PlanFetchState | null;
  sessionId: string | null;
  dispatch: Dispatch<TaskPilotAction>;
}

/**
 * The WebSocket only announces that a plan exists (`task.plan_ready`); the full,
 * validated plan is fetched over REST. This hook performs that fetch exactly once
 * per announced plan id and ignores responses for plans that are no longer current.
 */
export function useAgentPlan({ planFetch, sessionId, dispatch }: UseAgentPlanOptions): { retryPlanFetch: () => void } {
  const inFlight = useRef<string | null>(null);

  const fetchPlan = useCallback(
    async (taskId: string, planId: string) => {
      if (inFlight.current === planId) return;
      inFlight.current = planId;
      dispatch({ type: "PLAN_FETCH_STARTED", planId });
      try {
        const plan = await getTaskPlan(taskId, sessionId ?? undefined);
        dispatch({ type: "PLAN_READY", plan });
      } catch (error) {
        const message = error instanceof ApiError ? error.message : "The plan could not be loaded.";
        dispatch({ type: "PLAN_FETCH_FAILED", planId, error: message });
      } finally {
        if (inFlight.current === planId) inFlight.current = null;
      }
    },
    [dispatch, sessionId],
  );

  useEffect(() => {
    if (planFetch?.status === "pending") void fetchPlan(planFetch.taskId, planFetch.planId);
  }, [planFetch, fetchPlan]);

  const retryPlanFetch = useCallback(() => {
    if (planFetch && planFetch.status === "error") void fetchPlan(planFetch.taskId, planFetch.planId);
  }, [planFetch, fetchPlan]);

  return { retryPlanFetch };
}
