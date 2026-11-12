"use client";

import { Globe, Power, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useTaskPilotActions, useTaskPilotState } from "@/hooks/useTaskPilot";
import { ApiError } from "@/lib/api";
import { getBrowserSession, getBrowserStatus } from "@/lib/browserApi";
import { formatTime, shortId } from "@/lib/utils";

import type { BrowserSessionInfo, BrowserStatusResponse } from "@/types/browser";

const REFRESH_MS = 5_000;

/**
 * Browser sessions (Phase 3 carry-forward). Shows overall browser capacity and THIS tab's
 * own session; other users' sessions are never listed (session isolation).
 */
export function BrowserSessions() {
  const { sessionId, connectionStatus, activeTask } = useTaskPilotState();
  const { closeBrowser } = useTaskPilotActions();
  const [status, setStatus] = useState<BrowserStatusResponse | null>(null);
  const [info, setInfo] = useState<BrowserSessionInfo | null>(null);
  const [missing, setMissing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const load = useCallback(async () => {
    try {
      setStatus(await getBrowserStatus());
    } catch {
      setStatus(null);
    }
    if (!sessionId) return;
    try {
      setInfo(await getBrowserSession(sessionId));
      setMissing(false);
      setError(null);
    } catch (e) {
      if (e instanceof ApiError && e.status === 404) {
        setInfo(null);
        setMissing(true);
      } else {
        setError(e instanceof ApiError ? e.message : "Could not load the browser session.");
      }
    }
  }, [sessionId]);

  useEffect(() => {
    if (connectionStatus !== "CONNECTED") return undefined;
    void load();
    const id = setInterval(() => void load(), REFRESH_MS);
    return () => clearInterval(id);
  }, [connectionStatus, load]);

  const close = async () => {
    if (!confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    await closeBrowser();
    await load();
  };

  let domain: string | null = null;
  try {
    domain = info?.current_url ? new URL(info.current_url).host : null;
  } catch {
    domain = null;
  }

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-xl font-semibold">Browser sessions</h1>
        <p className="text-sm text-muted-foreground">The real Chromium browser used by this TaskPilot tab. Other people&apos;s sessions are never shown.</p>
      </header>
      <Card aria-labelledby="capacity-title">
        <CardHeader>
          <CardTitle id="capacity-title"><Globe className="h-3.5 w-3.5" aria-hidden /> Browser capacity</CardTitle>
          <Button size="sm" variant="ghost" onClick={() => void load()}><RefreshCw aria-hidden /> Refresh</Button>
        </CardHeader>
        <CardContent>
          {status ? (
            <dl className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4" data-testid="browser-capacity">
              <div><dt className="text-xs text-muted-foreground">Status</dt><dd>{status.status.replace("_", " ")}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Active sessions</dt><dd>{status.active_sessions} / {status.max_sessions}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Engine</dt><dd>{status.engine}</dd></div>
              <div><dt className="text-xs text-muted-foreground">Mode</dt><dd>{status.headless ? "headless" : "visible"}</dd></div>
            </dl>
          ) : (
            <p className="text-sm text-muted-foreground">Browser status unavailable.</p>
          )}
        </CardContent>
      </Card>
      <Card aria-labelledby="my-session-title">
        <CardHeader>
          <CardTitle id="my-session-title">This tab&apos;s session</CardTitle>
          {info && <Badge variant={info.status === "READY" ? "success" : info.status === "BUSY" ? "default" : "warning"} data-testid="session-status">{info.status}</Badge>}
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {error && <p role="alert" className="text-sm text-level-error">{error}</p>}
          {missing && !info && (
            <p className="text-sm text-muted-foreground" data-testid="no-session">No browser is running for this session. One starts only when you click Run Plan.</p>
          )}
          {info && (
            <>
              <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2" data-testid="session-details">
                <div><dt className="text-xs text-muted-foreground">Session</dt><dd className="font-mono">#{shortId(info.session_id)}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Website</dt><dd>{domain ?? "about:blank"}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Current task</dt>
                  <dd>{info.active_task_id ? `#${shortId(info.active_task_id)}${activeTask?.task_id === info.active_task_id ? ` · ${activeTask.command.slice(0, 60)}` : ""}` : "None (idle)"}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Last activity</dt><dd>{formatTime(info.last_activity_at)}</dd></div>
                <div><dt className="text-xs text-muted-foreground">Live preview</dt><dd>{info.stream_status.toLowerCase()} · {info.stream_subscribers} viewer(s)</dd></div>
                <div><dt className="text-xs text-muted-foreground">Sign-in needed</dt><dd>{info.auth_required ? "Yes — please sign in yourself" : "No"}</dd></div>
              </dl>
              <div>
                <Button variant={confirming ? "destructive" : "outline"} size="sm" onClick={() => void close()} disabled={info.status === "BUSY"}
                  onBlur={() => setConfirming(false)} aria-label={confirming ? "Confirm closing the browser" : "Close browser session"}>
                  <Power aria-hidden /> {confirming ? "Confirm close" : "Close browser session"}
                </Button>
                {info.status === "BUSY" && <p className="mt-1 text-xs text-muted-foreground">A plan is running; stop it before closing.</p>}
              </div>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
