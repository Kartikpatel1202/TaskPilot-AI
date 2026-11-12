"use client";

import { Activity, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

import { useAuth } from "@/components/auth/AuthGate";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { getHealthDetails, getReadiness, type HealthDetails, type Readiness } from "@/lib/systemApi";

const TONE: Record<string, "success" | "warning" | "destructive" | "secondary"> = {
  ok: "success", available: "success", ready: "success", not_configured: "secondary", unavailable: "destructive", stopped: "warning",
  unreachable: "destructive",
};
const LABEL: Record<string, string> = {
  database: "Database", redis: "Redis / queue", planner_queue: "Planner", configuration: "Configuration", browser: "Browser worker", api: "API",
};

/** Operational status for everyone (readiness) plus subsystem details for OWNERs only (server-enforced). */
export function SystemStatus({ className }: { className?: string }) {
  const { user, authRequired } = useAuth();
  const [ready, setReady] = useState<Readiness | null>(null);
  const [details, setDetails] = useState<HealthDetails | null>(null);
  const isOwner = !authRequired || user?.role === "OWNER";

  const load = useCallback(async () => {
    setReady(await getReadiness());
    if (isOwner) {
      try {
        setDetails(await getHealthDetails());
      } catch {
        setDetails(null);
      }
    }
  }, [isOwner]);

  useEffect(() => {
    void load();
    const id = setInterval(() => void load(), 30_000);
    return () => clearInterval(id);
  }, [load]);

  return (
    <Card className={className} aria-labelledby="system-status-title" data-testid="system-status">
      <CardHeader className="flex-wrap gap-2">
        <CardTitle id="system-status-title"><Activity className="h-3.5 w-3.5" aria-hidden /> System status</CardTitle>
        <Button size="sm" variant="ghost" onClick={() => void load()} aria-label="Refresh system status"><RefreshCw aria-hidden /></Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        {ready && (
          <ul className="grid grid-cols-2 gap-2 text-xs" aria-live="polite">
            {Object.entries(ready.checks).map(([key, value]) => (
              <li key={key} className="flex items-center justify-between gap-2 rounded-md border border-white/[0.06] px-2 py-1.5" data-testid="status-check">
                <span>{LABEL[key] ?? key}</span>
                <Badge variant={TONE[value] ?? "secondary"}>{value.replace(/_/g, " ")}</Badge>
              </li>
            ))}
          </ul>
        )}
        {details && (
          <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px] text-muted-foreground" data-testid="status-details">
            <dt>LLM</dt><dd>{details.llm.provider} · {details.llm.model} · circuit {details.llm.circuit.state.toLowerCase()}</dd>
            <dt>Pending approvals</dt><dd>{details.approvals_pending}</dd>
            <dt>Queue</dt><dd>{details.queue_backend}</dd>
            <dt>Egress proxy</dt><dd>{details.egress_proxy_configured ? "configured" : "not configured"}</dd>
            <dt>Write failures</dt><dd>{details.persistence_write_failures + details.audit_write_failures}</dd>
            <dt>Rate limiter</dt><dd>{details.rate_limiter_degraded ? "degraded (local)" : "ok"}</dd>
          </dl>
        )}
      </CardContent>
    </Card>
  );
}
