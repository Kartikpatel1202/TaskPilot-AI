"use client";

import { CheckCircle2, Circle, CircleSlash, Hourglass, Loader2, ShieldAlert, XCircle } from "lucide-react";
import { useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import type { ChoiceResult } from "@/hooks/useWorkflow";
import { DOMAIN_LABEL } from "@/types/integration";
import { STEP_STATUS_LABEL, WORKFLOW_STATUS_LABEL, type WorkflowState, type WorkflowStepStatus } from "@/types/workflow";

const STEP_ICON: Record<WorkflowStepStatus, typeof Circle> = {
  NOT_STARTED: Circle,
  RUNNING: Loader2,
  WAITING_USER: Hourglass,
  COMPLETED: CheckCircle2,
  FAILED: XCircle,
  BLOCKED: ShieldAlert,
  SKIPPED: CircleSlash,
};
const STEP_TONE: Record<WorkflowStepStatus, string> = {
  NOT_STARTED: "text-muted-foreground",
  RUNNING: "text-cyan-brand animate-spin",
  WAITING_USER: "text-level-warning",
  COMPLETED: "text-level-success",
  FAILED: "text-level-error",
  BLOCKED: "text-level-warning",
  SKIPPED: "text-muted-foreground",
};
const BADGE = {
  PLANNED: "secondary", RUNNING: "violet", WAITING_USER: "warning", COMPLETED: "success", PARTIAL: "warning", FAILED: "destructive", CANCELLED: "secondary",
} as const;

export interface WorkflowSummaryProps {
  workflow: WorkflowState;
  onChoose?: (choiceId: string, optionId: string | null) => Promise<ChoiceResult>;
}

/** Ordered steps with their REAL status, the typed hand-offs between them and any pending choice. */
export function WorkflowSummary({ workflow, onChoose }: WorkflowSummaryProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const choice = workflow.pending_choice ?? null;
  const multi = workflow.steps.length > 1;

  const answer = async (optionId: string | null) => {
    if (!choice || !onChoose || busy) return;
    setBusy(true);
    setError(null);
    const result = await onChoose(choice.choice_id, optionId);
    setBusy(false);
    if (!result.ok) setError(result.error ?? "Your choice could not be sent.");
  };

  return (
    <section className="flex flex-col gap-3" aria-label="Workflow" data-testid="workflow-summary">
      <div className="flex items-center justify-between gap-2">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          {multi ? `Workflow · ${workflow.domains.map((d) => DOMAIN_LABEL[d]).join(" → ")}` : DOMAIN_LABEL[workflow.domains[0] ?? "FILES"]}
        </p>
        <Badge variant={BADGE[workflow.status]} data-testid="workflow-status">{WORKFLOW_STATUS_LABEL[workflow.status]}</Badge>
      </div>
      <ol className="flex flex-col gap-1.5">
        {workflow.steps.map((step) => {
          const Icon = STEP_ICON[step.status];
          return (
            <li key={step.step_id} className="flex items-start gap-2 text-sm" data-testid="workflow-step" data-status={step.status}>
              <Icon className={cn("mt-0.5 h-4 w-4 shrink-0", STEP_TONE[step.status])} aria-hidden />
              <div className="flex flex-col">
                <span>
                  <span className="font-mono text-xs text-muted-foreground">{step.order}.</span> {step.label}{" "}
                  <span className="text-xs text-muted-foreground">· {STEP_STATUS_LABEL[step.status]}</span>
                </span>
                {step.message && <span className="text-[11px] text-muted-foreground">{step.message}</span>}
                {step.consumes.length > 0 && step.status === "NOT_STARTED" && (
                  <span className="text-[11px] text-muted-foreground">Uses the result of an earlier step.</span>
                )}
              </div>
            </li>
          );
        })}
      </ol>
      {workflow.final_result && (
        <p className="text-xs text-muted-foreground" data-testid="workflow-result">{workflow.final_result}</p>
      )}
      {choice && (
        <div className="flex flex-col gap-2 rounded-lg border border-level-warning/30 bg-level-warning/[0.05] p-3" role="group" aria-label="Your choice">
          <p className="text-sm font-medium">{choice.question}</p>
          <div className="flex flex-col gap-1.5" data-testid="choice-options">
            {choice.options.map((o) => (
              <Button key={o.option_id} variant="outline" size="sm" className="h-auto justify-start whitespace-normal py-1.5 text-left"
                disabled={busy} onClick={() => void answer(o.option_id)} data-testid="choice-option">
                <span className="flex flex-col">
                  <span>{o.label}</span>
                  {o.detail && <span className="text-[11px] text-muted-foreground">{o.detail}</span>}
                </span>
              </Button>
            ))}
          </div>
          <Button variant="ghost" size="sm" className="self-start" disabled={busy} onClick={() => void answer(null)}>Skip — choose none</Button>
          {error && <p role="alert" className="text-xs text-level-error">{error}</p>}
        </div>
      )}
    </section>
  );
}
