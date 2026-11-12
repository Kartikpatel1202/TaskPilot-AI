import { ListOrdered, ShieldCheck } from "lucide-react";

import { IntentBadge } from "./IntentBadge";

import type { TaskPlan } from "@/types/plan";

/** Compact one-glance summary of a plan (used in the task status card). */
export function PlanSummary({ plan }: { plan: TaskPlan }) {
  const checkpoints = plan.steps.filter((s) => s.action.type === "request_approval").length;
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-white/[0.06] bg-white/[0.02] p-3" data-testid="plan-summary">
      <div className="flex flex-wrap items-center gap-2">
        <IntentBadge intent={plan.intent} />
        {plan.target_website && <span className="font-mono text-[11px] text-muted-foreground">{plan.target_website}</span>}
      </div>
      <p className="line-clamp-2 text-xs text-foreground/90">{plan.summary}</p>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
        <span className="inline-flex items-center gap-1">
          <ListOrdered className="h-3 w-3" aria-hidden /> {plan.steps.length} planned step{plan.steps.length === 1 ? "" : "s"}
        </span>
        {checkpoints > 0 && (
          <span className="inline-flex items-center gap-1 text-level-warning">
            <ShieldCheck className="h-3 w-3" aria-hidden /> {checkpoints} approval checkpoint{checkpoints === 1 ? "" : "s"}
          </span>
        )}
        <span>{Math.round(plan.confidence * 100)}% confidence</span>
      </p>
    </div>
  );
}
