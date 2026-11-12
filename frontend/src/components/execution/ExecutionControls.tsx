"use client";

import { AlertTriangle, Loader2, Play, ShieldCheck, Square, X } from "lucide-react";
import { useRef } from "react";

import { Button } from "@/components/ui/button";

import type { ExecutionState } from "@/types/execution";
import type { TaskPlan } from "@/types/plan";
import type { Task } from "@/types/task";

export interface ExecutionControlsProps {
  plan: TaskPlan;
  task: Task | null;
  execution: ExecutionState | null;
  executionAvailable: boolean;
  connected: boolean;
  isStarting: boolean;
  error: string | null;
  onRun: (taskId: string) => Promise<unknown>;
  onStop: (taskId: string) => Promise<unknown>;
  onDismissError?: () => void;
}

const ACTIVE = new Set(["QUEUED", "EXECUTING", "WAITING_APPROVAL"]);

export function isRunnablePlan(plan: TaskPlan): boolean {
  return plan.status === "READY" && plan.intent !== "GENERAL_CHAT" && plan.steps.length > 0;
}

/**
 * Run Plan / Stop. Running a plan always needs an explicit click here — planning
 * never starts a browser, and nothing is clicked on the user's behalf.
 */
export function ExecutionControls({
  plan,
  task,
  execution,
  executionAvailable,
  connected,
  isStarting,
  error,
  onRun,
  onStop,
  onDismissError,
}: ExecutionControlsProps) {
  const clicked = useRef(false);
  if (!isRunnablePlan(plan) || !task || task.task_id !== plan.task_id) return null;

  const mine = execution?.taskId === plan.task_id ? execution : null;
  const running = mine !== null && ACTIVE.has(mine.status);
  const canRun = task.state === "PLANNED" && mine === null;
  const site = plan.target_website ?? "the planned website";

  const run = async () => {
    if (clicked.current) return; // one click = one request
    clicked.current = true;
    try {
      await onRun(plan.task_id);
    } finally {
      clicked.current = false;
    }
  };

  const disabledReason = !executionAvailable
    ? "Browser execution is unavailable on this server."
    : !connected
      ? "Reconnect to TaskPilot first."
      : null;

  return (
    <section className="flex flex-col gap-2" aria-label="Plan execution" data-testid="execution-controls">
      {canRun && (
        <div className="flex flex-col gap-2 rounded-lg border border-cyan-brand/25 bg-cyan-brand/[0.05] p-3">
          <p className="flex items-start gap-2 text-xs text-muted-foreground">
            <ShieldCheck className="mt-0.5 h-3.5 w-3.5 shrink-0 text-cyan-brand" aria-hidden />
            <span>
              Run Plan opens a real Chromium browser on <span className="font-mono text-foreground/90">{site}</span> and performs
              these {plan.steps.length} steps. Payments, checkout, placing orders and sending messages are never automated —
              TaskPilot stops and asks before any sensitive step.
            </span>
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button onClick={run} disabled={isStarting || disabledReason !== null} data-testid="run-plan">
              {isStarting ? <Loader2 className="animate-spin" aria-hidden /> : <Play aria-hidden />}
              {isStarting ? "Starting…" : "Run Plan"}
            </Button>
            {disabledReason && <span className="text-xs text-level-warning">{disabledReason}</span>}
          </div>
        </div>
      )}

      {running && mine && (
        <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/[0.08] bg-white/[0.03] px-3 py-2">
          <span className="flex items-center gap-2 text-xs text-foreground/90" role="status">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-brand" aria-hidden />
            {mine.stopRequested
              ? "Stopping after the current browser action…"
              : mine.status === "WAITING_APPROVAL"
                ? "Paused — waiting for your approval."
                : mine.status === "QUEUED"
                  ? "Queued — the browser is starting."
                  : "Running in Chromium…"}
          </span>
          <Button
            size="sm"
            variant="destructive"
            onClick={() => void onStop(plan.task_id)}
            disabled={mine.stopRequested}
            data-testid="stop-execution"
          >
            <Square aria-hidden /> {mine.stopRequested ? "Stopping…" : "Stop"}
          </Button>
        </div>
      )}

      {error && (
        <p role="alert" className="flex items-start gap-2 rounded-md border border-level-error/30 bg-level-error/[0.07] px-3 py-2 text-xs text-level-error">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span className="flex-1">Run Plan failed: {error}</span>
          {onDismissError && (
            <button type="button" onClick={onDismissError} aria-label="Dismiss error" className="text-muted-foreground hover:text-foreground">
              <X className="h-3.5 w-3.5" aria-hidden />
            </button>
          )}
        </p>
      )}
    </section>
  );
}
