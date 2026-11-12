"use client";

import { useCallback } from "react";

import { getCalendarReview } from "@/lib/integrationApi";

import { useRevisionFetch } from "./useRevisionFetch";

import type { CalendarEventReview } from "@/types/calendar";

/** The exact event under review (planned, awaiting approval, or created and verified). */
export function useCalendar({ sessionId, taskId, enabled, revision }: { sessionId: string | null; taskId: string | null; enabled: boolean; revision: number }) {
  const load = useCallback(() => getCalendarReview(taskId as string, sessionId as string), [taskId, sessionId]);
  const state = useRevisionFetch<CalendarEventReview>(enabled && sessionId && taskId ? load : null, revision);
  return { review: state.data, error: state.error, reload: state.reload };
}
