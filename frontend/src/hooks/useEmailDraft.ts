"use client";

import { useCallback, useRef, useState } from "react";

import { ApiError } from "@/lib/api";
import { getEmailDraft, updateEmailDraft } from "@/lib/integrationApi";

import { useRevisionFetch } from "./useRevisionFetch";

import type { EmailDraftView } from "@/types/gmail";

/** The task's email draft: editable before Run Plan; read-only (and never sendable) afterwards. */
export function useEmailDraft({ sessionId, taskId, enabled, revision }: { sessionId: string | null; taskId: string | null; enabled: boolean; revision: number }) {
  const load = useCallback(() => getEmailDraft(taskId as string, sessionId as string), [taskId, sessionId]);
  const state = useRevisionFetch<EmailDraftView>(enabled && sessionId && taskId ? load : null, revision);
  const [saving, setSaving] = useState(false);
  const inFlight = useRef(false);

  const save = useCallback(
    async (subject: string, body: string): Promise<{ ok: boolean; error?: string }> => {
      if (!sessionId || !taskId) return { ok: false, error: "No active task." };
      if (inFlight.current) return { ok: false, error: "Already saving." };
      inFlight.current = true;
      setSaving(true);
      try {
        await updateEmailDraft(taskId, sessionId, subject, body);
        await state.reload();
        return { ok: true };
      } catch (err) {
        return { ok: false, error: err instanceof ApiError ? err.message : "The draft could not be updated." };
      } finally {
        inFlight.current = false;
        setSaving(false);
      }
    },
    [sessionId, taskId, state],
  );

  return { draft: state.data, error: state.error, saving, save, reload: state.reload };
}
