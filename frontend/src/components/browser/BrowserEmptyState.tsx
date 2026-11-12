import { FlaskConical, Loader2, MonitorDot } from "lucide-react";

export type BrowserEmptyReason = "idle" | "plan_ready" | "starting" | "waiting_frame" | "closed" | "unavailable" | "demo";

interface BrowserEmptyStateProps {
  reason?: BrowserEmptyReason;
  /** @deprecated kept for the Phase 1 demo placeholder; use `reason="demo"`. */
  isDemoPlaceholder?: boolean;
  /** @deprecated use `reason="plan_ready"`. */
  planReady?: boolean;
  message?: string;
}

const TEXT: Record<BrowserEmptyReason, string> = {
  idle: "No browser is running. Planning never opens one — a real Chromium browser starts only when you click Run Plan.",
  plan_ready: "Plan ready. Click Run Plan to start a real Chromium browser; its screenshots will stream here live.",
  starting: "Starting Chromium…",
  waiting_frame: "Browser running — waiting for the first screenshot.",
  closed: "The browser for this session was closed.",
  unavailable: "Real browser execution is unavailable on this server.",
  demo: "Demo placeholder — this is a simulation. No real browser is running and no website is being shown.",
};

export function BrowserEmptyState({ reason, isDemoPlaceholder = false, planReady = false, message }: BrowserEmptyStateProps) {
  const resolved: BrowserEmptyReason = reason ?? (isDemoPlaceholder ? "demo" : planReady ? "plan_ready" : "idle");
  const busy = resolved === "starting" || resolved === "waiting_frame";
  return (
    <div className="grid-backdrop flex h-full flex-col items-center justify-center gap-3 px-6 py-10 text-center" data-testid="browser-empty" data-reason={resolved}>
      <div className="relative flex h-14 w-14 items-center justify-center rounded-2xl border border-white/10 bg-gradient-to-br from-cyan-brand/10 to-violet-brand/10">
        {resolved === "demo" ? (
          <FlaskConical className="h-6 w-6 text-violet-brand" aria-hidden />
        ) : busy ? (
          <Loader2 className="h-6 w-6 animate-spin text-cyan-brand/80" aria-hidden />
        ) : (
          <MonitorDot className="h-6 w-6 text-cyan-brand/80" aria-hidden />
        )}
      </div>
      <p className="max-w-sm text-sm text-foreground/90">{TEXT[resolved]}</p>
      {message && <p className="max-w-sm text-xs text-muted-foreground">{message}</p>}
    </div>
  );
}
