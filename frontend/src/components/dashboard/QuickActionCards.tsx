"use client";

import { FlaskConical, History, Loader2, Mic, ShieldCheck, Type, Waves } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatTime, shortId } from "@/lib/utils";

import { TASK_STATE_BADGE } from "./TaskStatusCard";

import type { Task } from "@/types/task";

interface QuickActionCardsProps {
  tasks: Task[];
  demoAvailable: boolean;
  connected: boolean;
  onRunDemoTelemetry: () => Promise<void>;
  onRunDemoApproval: () => Promise<void>;
}

export function QuickActionCards({ tasks, demoAvailable, connected, onRunDemoTelemetry, onRunDemoApproval }: QuickActionCardsProps) {
  const [running, setRunning] = useState<"telemetry" | "approval" | null>(null);

  const run = async (kind: "telemetry" | "approval") => {
    if (running) return;
    setRunning(kind);
    try {
      await (kind === "telemetry" ? onRunDemoTelemetry() : onRunDemoApproval());
    } finally {
      setRunning(null);
    }
  };

  return (
    <Card className="flex flex-col" aria-labelledby="recent-tasks-title">
      <CardHeader>
        <CardTitle id="recent-tasks-title">
          <History className="h-3.5 w-3.5" aria-hidden /> Recent tasks
        </CardTitle>
        <span className="text-[11px] text-muted-foreground">This session · in memory</span>
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {tasks.length === 0 ? (
          <p className="py-4 text-center text-sm text-muted-foreground">Tasks you send will be listed here.</p>
        ) : (
          <ul className="flex max-h-56 flex-col divide-y divide-white/[0.05] overflow-y-auto scrollbar-thin">
            {tasks.slice(0, 8).map((task) => (
              <li key={task.task_id} className="flex items-center gap-3 py-2">
                {task.input_mode === "VOICE" ? (
                  <Mic className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label="Voice command" />
                ) : (
                  <Type className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-label="Text command" />
                )}
                <span className="min-w-0 flex-1 truncate text-sm" title={task.command}>
                  {task.command}
                </span>
                <span className="hidden font-mono text-[10px] text-muted-foreground sm:inline">{formatTime(task.created_at)}</span>
                <Badge variant={TASK_STATE_BADGE[task.state].variant} className="shrink-0" title={`Task ${shortId(task.task_id)}`}>
                  {task.state === "IDLE" ? "Idle" : TASK_STATE_BADGE[task.state].label}
                </Badge>
              </li>
            ))}
          </ul>
        )}

        {demoAvailable && (
          <div className="mt-auto flex flex-col gap-2 rounded-lg border border-dashed border-violet-brand/30 bg-violet-brand/[0.04] p-3">
            <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-violet-brand">
              <FlaskConical className="h-3.5 w-3.5" aria-hidden /> Developer simulation
            </p>
            <p className="text-xs text-muted-foreground">
              Generates clearly labelled demo events. Nothing touches a real browser or website.
            </p>
            <div className="grid gap-2 sm:grid-cols-2">
              {(
                [
                  { kind: "telemetry", label: "Run demo telemetry", icon: Waves },
                  { kind: "approval", label: "Trigger demo approval", icon: ShieldCheck },
                ] as const
              ).map(({ kind, label, icon: Icon }) => (
                <button
                  key={kind}
                  type="button"
                  disabled={!connected || running !== null}
                  onClick={() => void run(kind)}
                  className={cn(
                    "flex items-center justify-center gap-2 rounded-md border border-white/10 bg-white/[0.03] px-3 py-2 text-xs font-medium transition-colors hover:border-violet-brand/40 hover:bg-violet-brand/[0.08] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                  )}
                >
                  {running === kind ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Icon className="h-3.5 w-3.5" aria-hidden />}
                  {label}
                </button>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
