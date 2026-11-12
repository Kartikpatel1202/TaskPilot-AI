"use client";

import { useCallback, useRef } from "react";

import { ApiError } from "@/lib/api";
import { answerChoice, getWorkflow } from "@/lib/integrationApi";

import { useRevisionFetch } from "./useRevisionFetch";

import type { WorkflowState } from "@/types/workflow";

export interface ChoiceResult {
  ok: boolean;
  error?: string;
}

/** The active task's workflow (planned view before Run Plan, observed state afterwards). */
export function useWorkflow({ sessionId, taskId, enabled, revision }: { sessionId: string | null; taskId: string | null; enabled: boolean; revision: number }) {
  const load = useCallback(() => getWorkflow(taskId as string, sessionId as string), [taskId, sessionId]);
  const state = useRevisionFetch<WorkflowState>(enabled && sessionId && taskId ? load : null, revision);
  const inFlight = useRef(false);

  const choose = useCallback(
    async (choiceId: string, optionId: string | null): Promise<ChoiceResult> => {
      if (!sessionId || !taskId) return { ok: false, error: "No active task." };
      if (inFlight.current) return { ok: false, error: "Your previous answer is still being sent." };
      inFlight.current = true;
      try {
        await answerChoice(taskId, sessionId, choiceId, optionId);
        await state.reload();
        return { ok: true };
      } catch (err) {
        return { ok: false, error: err instanceof ApiError ? err.message : "Your choice could not be sent." };
      } finally {
        inFlight.current = false;
      }
    },
    [sessionId, taskId, state],
  );

  return { workflow: state.data, error: state.error, reload: state.reload, choose };
}
