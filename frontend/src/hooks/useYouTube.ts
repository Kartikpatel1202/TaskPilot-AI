"use client";

import { useCallback } from "react";

import { getYouTubeResults } from "@/lib/integrationApi";

import { useRevisionFetch } from "./useRevisionFetch";

import type { YouTubeResults } from "@/types/youtube";

/** Observed YouTube results, the selected video and its verified playback state. */
export function useYouTube({ sessionId, taskId, enabled, revision }: { sessionId: string | null; taskId: string | null; enabled: boolean; revision: number }) {
  const load = useCallback(() => getYouTubeResults(taskId as string, sessionId as string), [taskId, sessionId]);
  const state = useRevisionFetch<YouTubeResults>(enabled && sessionId && taskId ? load : null, revision);
  return { results: state.data, error: state.error, reload: state.reload };
}
