import { Bot, FlaskConical, Info, MonitorPlay, ShieldAlert, ShieldCheck } from "lucide-react";
import { memo } from "react";

import { ASSISTANT_NAME } from "@/lib/persona";
import { cn } from "@/lib/utils";

import { IntentBadge } from "./IntentBadge";
import { PlanRiskIndicator } from "./PlanRiskIndicator";
import { PlanStep } from "./PlanStep";

import { ExecutionTimeline } from "@/components/execution/ExecutionTimeline";

import type { ExecutionState } from "@/types/execution";
import type { TaskPlan } from "@/types/plan";

const HEADLINE: Record<TaskPlan["status"], string> = {
  READY: "PLAN READY",
  NEEDS_CLARIFICATION: "NEEDS YOUR INPUT",
  REJECTED: "NOT PLANNED",
  FAILED: "PLANNING FAILED",
};

function Fact({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-1">
      <dt className="text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">{label}</dt>
      <dd className="min-w-0 text-sm text-foreground">{children}</dd>
    </div>
  );
}

/**
 * Renders a validated plan. Before Run Plan, steps are always shown as *planned*;
 * once this plan runs, each step shows only the status observed in the browser.
 */
export const PlanPreview = memo(function PlanPreview({ plan, execution = null }: { plan: TaskPlan; execution?: ExecutionState | null }) {
  const ready = plan.status === "READY";
  const run = execution && execution.taskId === plan.task_id ? execution : null;
  const isChat = plan.intent === "GENERAL_CHAT";
  const checkpoints = plan.steps.filter((s) => s.action.type === "request_approval");

  return (
    <article className="flex flex-col gap-4" aria-labelledby="plan-headline" data-testid="plan-preview">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="plan-headline" className="text-xs font-bold uppercase tracking-[0.18em]">
          <span className="text-violet-brand">{ASSISTANT_NAME}</span>{" "}
          <span className={ready ? "text-cyan-brand" : "text-level-warning"}>— {HEADLINE[plan.status]}</span>
        </h3>
        {plan.is_mock && (
          <span className="inline-flex items-center gap-1 rounded border border-violet-brand/30 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-violet-brand" title="Offline mock planner — no real LLM was called">
            <FlaskConical className="h-3 w-3" aria-hidden /> Mock plan
          </span>
        )}
      </header>

      <div className="flex gap-3 rounded-lg border border-violet-brand/20 bg-violet-brand/[0.05] p-3">
        <Bot className="mt-0.5 h-4 w-4 shrink-0 text-violet-brand" aria-hidden />
        <p className="text-sm text-foreground" lang={plan.language === "hi" ? "hi" : undefined} data-testid="plan-message">
          {plan.user_facing_message}
        </p>
      </div>

      {!isChat && (
        <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div className="col-span-2 sm:col-span-4">
            <Fact label="Objective">{plan.summary}</Fact>
          </div>
          <Fact label="Intent">
            <IntentBadge intent={plan.intent} />
          </Fact>
          <Fact label="Website">
            <span className="font-mono text-[13px]">{plan.target_website ?? "—"}</span>
          </Fact>
          <Fact label="Steps">{plan.steps.length}</Fact>
          <Fact label="Confidence">
            <span className="flex items-center gap-2">
              <span className="h-1.5 w-14 overflow-hidden rounded-full bg-white/[0.08]" aria-hidden>
                <span className="block h-full rounded-full bg-cyan-brand" style={{ width: `${Math.round(plan.confidence * 100)}%` }} />
              </span>
              <span className="tabular-nums">{Math.round(plan.confidence * 100)}%</span>
            </span>
          </Fact>
          {ready && plan.steps.length > 0 && (
            <div className="col-span-2 sm:col-span-4">
              <Fact label="Risk">
                <PlanRiskIndicator steps={plan.steps} />
              </Fact>
            </div>
          )}
        </dl>
      )}

      {plan.assumptions.length > 0 && (
        <div className="rounded-lg border border-white/[0.06] bg-white/[0.02] p-3">
          <p className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
            <Info className="h-3 w-3" aria-hidden /> Assumptions
          </p>
          <ul className="list-disc space-y-1 pl-4 text-xs text-muted-foreground">
            {plan.assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        </div>
      )}

      {checkpoints.length > 0 && (
        <p className="flex items-start gap-2 rounded-lg border border-level-warning/30 bg-level-warning/[0.06] px-3 py-2 text-xs text-level-warning">
          <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {checkpoints.length} approval checkpoint{checkpoints.length === 1 ? "" : "s"} planned. While running, TaskPilot stops and
          asks for your explicit approval before {checkpoints.length === 1 ? "that step" : "those steps"}. Payments and orders stay
          manual even if approved.
        </p>
      )}

      {run && plan.steps.length > 0 && <ExecutionTimeline plan={plan} execution={run} />}
      {!run && plan.steps.length > 0 && (
        <ol className="flex flex-col gap-2" aria-label="Planned actions">
          {plan.steps.map((step) => (
            <PlanStep key={step.step_id} step={step} />
          ))}
        </ol>
      )}

      {plan.clarification_history.length > 0 && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer select-none">Clarifications ({plan.clarification_history.length})</summary>
          <ul className="mt-2 space-y-1.5">
            {plan.clarification_history.map((c) => (
              <li key={c.answered_at}>
                <span className="text-foreground/80">Q:</span> {c.question}
                <br />
                <span className="text-foreground/80">A:</span> {c.answer}
              </li>
            ))}
          </ul>
        </details>
      )}

      {ready && !isChat && !run && plan.steps.length > 0 && (
        <footer
          className={cn(
            "flex items-center gap-2 rounded-lg border border-cyan-brand/25 bg-cyan-brand/[0.06] px-3 py-2 text-[11px] font-semibold uppercase tracking-[0.14em] text-cyan-brand",
          )}
          data-testid="execution-notice"
        >
          <MonitorPlay className="h-3.5 w-3.5" aria-hidden />
          Plan ready — not executed. Nothing runs in a browser until you click Run Plan
        </footer>
      )}
      {isChat && (
        <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden /> No browser actions needed.
        </p>
      )}
    </article>
  );
});
