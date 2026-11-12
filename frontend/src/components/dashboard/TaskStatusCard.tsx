"use client";

import { Check, CircleDashed, Mic, ShieldAlert, Type, X } from "lucide-react";

import { PlanSummary } from "@/components/agent/PlanSummary";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn, formatTime, shortId } from "@/lib/utils";

import type { ApprovalRequest } from "@/types/approval";
import type { TaskPlan } from "@/types/plan";
import type { Task, TaskState } from "@/types/task";

interface PipelineStep {
  key: string;
  label: string;
  /** Visiting any of these states marks the step as reached. */
  states: TaskState[];
}

const PIPELINE: PipelineStep[] = [
  { key: "accepted", label: "Accepted", states: ["IDLE"] },
  { key: "planning", label: "Planning", states: ["PLANNING"] },
  { key: "planned", label: "Plan ready", states: ["PLANNED", "NEEDS_CLARIFICATION"] },
  { key: "executing", label: "Execute", states: ["EXECUTING"] },
  { key: "approval", label: "Approval", states: ["WAITING_APPROVAL"] },
  { key: "done", label: "Done", states: ["COMPLETED"] },
];

type BadgeVariant = "secondary" | "default" | "violet" | "warning" | "success" | "destructive";

export const TASK_STATE_BADGE: Record<TaskState, { label: string; variant: BadgeVariant }> = {
  IDLE: { label: "Queued for planning", variant: "secondary" },
  PLANNING: { label: "Planning", variant: "violet" },
  PLANNED: { label: "Plan ready · not executed", variant: "default" },
  NEEDS_CLARIFICATION: { label: "Needs your input", variant: "warning" },
  EXECUTING: { label: "Executing", variant: "default" },
  WAITING_APPROVAL: { label: "Waiting approval", variant: "warning" },
  COMPLETED: { label: "Completed", variant: "success" },
  FAILED: { label: "Failed", variant: "destructive" },
  CANCELLED: { label: "Cancelled", variant: "warning" },
};

interface TaskStatusCardProps {
  task: Task | null;
  /** States the task actually visited, in order (from telemetry). */
  visitedStates?: TaskState[];
  plan?: TaskPlan | null;
  pendingApproval?: ApprovalRequest | null;
  onReviewApproval?: () => void;
  className?: string;
}

export function TaskStatusCard({
  task,
  visitedStates = [],
  plan,
  pendingApproval,
  onReviewApproval,
  className,
}: TaskStatusCardProps) {
  const visited = new Set<TaskState>(task ? [...visitedStates, task.state] : []);
  const lastReachedIndex = PIPELINE.reduce((acc, step, i) => (step.states.some((s) => visited.has(s)) ? i : acc), -1);

  return (
    <Card className={cn("flex flex-col", className)} aria-labelledby="task-status-title">
      <CardHeader>
        <CardTitle id="task-status-title">Task status</CardTitle>
        {task && (
          <Badge variant={TASK_STATE_BADGE[task.state].variant} data-testid="task-state-badge">
            {TASK_STATE_BADGE[task.state].label}
          </Badge>
        )}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col gap-4">
        {!task ? (
          <div className="flex flex-1 flex-col items-center justify-center gap-2 py-6 text-center">
            <CircleDashed className="h-6 w-6 text-muted-foreground/60" aria-hidden />
            <p className="text-sm text-muted-foreground">No task yet. Send a command to see its lifecycle here.</p>
          </div>
        ) : (
          <>
            <div className="flex flex-col gap-1.5">
              <p className="line-clamp-2 text-sm text-foreground" title={task.command}>
                {task.command}
              </p>
              <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                <span className="font-mono">#{shortId(task.task_id)}</span>
                <span className="inline-flex items-center gap-1">
                  {task.input_mode === "VOICE" ? <Mic className="h-3 w-3" aria-hidden /> : <Type className="h-3 w-3" aria-hidden />}
                  {task.input_mode === "VOICE" ? "Voice" : "Text"}
                </span>
                <span>Updated {formatTime(task.updated_at)}</span>
                {task.is_demo && <Badge variant="violet">DEMO · simulated</Badge>}
              </p>
            </div>

            <ol className="grid grid-cols-3 gap-x-1.5 gap-y-3 sm:grid-cols-6" aria-label="Task lifecycle">
              {PIPELINE.map((step, index) => {
                const reached = step.states.some((s) => visited.has(s));
                const current = step.states.includes(task.state);
                const stopped = task.state === "FAILED" || task.state === "CANCELLED";
                const failed = stopped && index === lastReachedIndex + 1;
                const label =
                  failed
                    ? task.state === "CANCELLED"
                      ? "Cancelled"
                      : "Failed"
                    : step.key === "planned" && visited.has("NEEDS_CLARIFICATION") && task.state === "NEEDS_CLARIFICATION"
                      ? "Needs input"
                      : step.key === "executing" && !reached && task.state === "PLANNED"
                        ? "Execute · Run Plan"
                        : step.label;
                return (
                  <li
                    key={step.key}
                    className="flex flex-col gap-1.5"
                    aria-current={current ? "step" : undefined}
                    data-reached={reached || undefined}
                  >
                    <span
                      className={cn(
                        "h-1 rounded-full",
                        failed ? "bg-level-error" : reached ? "bg-gradient-to-r from-cyan-brand to-violet-brand" : "bg-white/[0.08]",
                      )}
                    />
                    <span
                      className={cn(
                        "flex items-center gap-1 truncate text-[10px] uppercase tracking-wider",
                        current || failed ? "text-foreground" : reached ? "text-muted-foreground" : "text-muted-foreground/50",
                      )}
                    >
                      {failed ? (
                        <X className="h-3 w-3 text-level-error" aria-hidden />
                      ) : reached && !current ? (
                        <Check className="h-3 w-3" aria-hidden />
                      ) : null}
                      {label}
                    </span>
                  </li>
                );
              })}
            </ol>

            {task.state === "IDLE" && !task.is_demo && (
              <p className="rounded-md border border-white/[0.06] bg-white/[0.02] px-3 py-2 text-xs text-muted-foreground">
                Accepted and queued for Kamlesh Bhai&apos;s planner. Nothing runs in a browser until you click Run Plan.
              </p>
            )}
            {plan && plan.task_id === task.task_id && plan.status === "READY" && plan.steps.length > 0 && <PlanSummary plan={plan} />}
            {task.error_message && (
              <p className="rounded-md border border-level-error/25 bg-level-error/[0.06] px-3 py-2 text-xs text-level-error">{task.error_message}</p>
            )}
          </>
        )}

        {pendingApproval && pendingApproval.status === "PENDING" && onReviewApproval && (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-level-warning/30 bg-level-warning/[0.07] px-3 py-2">
            <span className="flex items-center gap-2 text-xs text-level-warning">
              <ShieldAlert className="h-4 w-4" aria-hidden /> An action is waiting for your approval.
            </span>
            <Button size="sm" variant="outline" onClick={onReviewApproval}>
              Review
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
