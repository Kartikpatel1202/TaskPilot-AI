import { Check, Loader2 } from "lucide-react";

import { ASSISTANT_NAME } from "@/lib/persona";
import { cn } from "@/lib/utils";

import type { PlanningProgress, PlanningStage } from "@/types/agent";

export const STAGE_LABELS: Record<PlanningStage, string> = {
  UNDERSTANDING_COMMAND: "Understanding your command…",
  CLASSIFYING_INTENT: "Identifying the task…",
  BUILDING_PLAN: "Building an action plan…",
  VALIDATING_PLAN: "Checking action safety…",
  FINALIZING: "Finalizing the plan…",
};
const STAGES = Object.keys(STAGE_LABELS) as PlanningStage[];

interface AgentThinkingIndicatorProps {
  progress: PlanningProgress | null;
}

/**
 * Shows only the stages the backend has actually reported. Future stages are not
 * displayed, and the bar uses the backend's stage-derived progress value.
 */
export function AgentThinkingIndicator({ progress }: AgentThinkingIndicatorProps) {
  const currentIndex = progress ? STAGES.indexOf(progress.stage) : -1;
  const reported = currentIndex >= 0 ? STAGES.slice(0, currentIndex + 1) : [];

  return (
    <div className="flex flex-col gap-4" role="status" aria-live="polite" data-testid="agent-thinking">
      <div className="flex items-center gap-3">
        <span className="relative flex h-9 w-9 items-center justify-center rounded-full border border-violet-brand/40 bg-violet-brand/10">
          <span aria-hidden className="absolute inset-0 animate-pulse-ring rounded-full border border-violet-brand/50" />
          <Loader2 className="h-4 w-4 animate-spin text-violet-brand" aria-hidden />
        </span>
        <div>
          <p className="text-sm font-medium">{ASSISTANT_NAME} is planning</p>
          <p className="text-xs text-muted-foreground">Thinking only — nothing is being done in a browser.</p>
        </div>
      </div>

      <div className="h-1 overflow-hidden rounded-full bg-white/[0.06]" aria-hidden>
        <div
          className="h-full rounded-full bg-gradient-to-r from-cyan-brand to-violet-brand transition-[width] duration-500"
          style={{ width: `${progress?.progress ?? 4}%` }}
        />
      </div>

      <ol className="flex flex-col gap-2" aria-label="Planning stages reported by the server">
        {reported.length === 0 && <li className="text-xs text-muted-foreground">Waiting for the planner to start…</li>}
        {reported.map((stage, index) => {
          const active = index === reported.length - 1;
          return (
            <li key={stage} className={cn("flex items-center gap-2 text-xs", active ? "text-foreground" : "text-muted-foreground")}>
              {active ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-brand" aria-hidden />
              ) : (
                <Check className="h-3.5 w-3.5 text-level-success" aria-hidden />
              )}
              {STAGE_LABELS[stage]}
            </li>
          );
        })}
      </ol>
    </div>
  );
}
