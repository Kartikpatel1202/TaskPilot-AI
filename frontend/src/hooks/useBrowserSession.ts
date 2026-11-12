"use client";

import { useCallback, useEffect, useRef, type Dispatch } from "react";

import { ApiError } from "@/lib/api";
import { closeBrowserSession, getBrowserSession, getBrowserStatus } from "@/lib/browserApi";

import type { TaskPilotAction } from "@/context/taskPilotReducer";
import type { BrowserSessionStatus } from "@/types/browser";

interface UseBrowserSessionOptions {
  sessionId: string | null;
  connected: boolean;
  /** Re-fetch status/session info whenever the session status changes (e.g. after a run). */
  sessionStatus: BrowserSessionStatus | null;
  dispatch: Dispatch<TaskPilotAction>;
}

/** Browser availability + this session's browser info (REST), and the explicit Close action. */
export function useBrowserSession({ sessionId, connected, sessionStatus, dispatch }: UseBrowserSessionOptions) {
  const inFlight = useRef(false);

  const refresh = useCallback(async () => {
    try {
      dispatch({ type: "BROWSER_STATUS_LOADED", status: await getBrowserStatus() });
    } catch {
      // availability is advisory; Run Plan reports the authoritative error
    }
    if (!sessionId) return;
    try {
      dispatch({ type: "BROWSER_SESSION_LOADED", info: await getBrowserSession(sessionId) });
    } catch (error) {
      if (!(error instanceof ApiError) || error.status !== 404) return;
      // 404: no browser for this session yet (planning never launches one)
    }
  }, [sessionId, dispatch]);

  useEffect(() => {
    if (connected) void refresh();
  }, [connected, sessionStatus, refresh]);

  const closeSession = useCallback(async (): Promise<{ ok: boolean; error?: string }> => {
    if (!sessionId || inFlight.current) return { ok: false, error: "Nothing to close." };
    inFlight.current = true;
    try {
      await closeBrowserSession(sessionId);
      return { ok: true };
    } catch (error) {
      return { ok: false, error: error instanceof ApiError ? error.message : "The browser could not be closed." };
    } finally {
      inFlight.current = false;
    }
  }, [sessionId]);

  return { refresh, closeSession };
}
