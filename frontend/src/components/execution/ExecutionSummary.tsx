import { Ban, CheckCircle2, XCircle } from "lucide-react";

import { cn } from "@/lib/utils";

import type { ExecutionState } from "@/types/execution";

const TONE = {
  COMPLETED: { icon: CheckCircle2, title: "Execution completed", cls: "border-level-success/30 bg-level-success/[0.07] text-level-success" },
  CANCELLED: { icon: Ban, title: "Execution stopped", cls: "border-level-warning/30 bg-level-warning/[0.07] text-level-warning" },
  FAILED: { icon: XCircle, title: "Execution failed", cls: "border-level-error/30 bg-level-error/[0.07] text-level-error" },
} as const;

/** Final, observed outcome of a run (rendered only once the backend reports a terminal status). */
export function ExecutionSummary({ execution }: { execution: ExecutionState }) {
  if (execution.status !== "COMPLETED" && execution.status !== "FAILED" && execution.status !== "CANCELLED") return null;
  const tone = TONE[execution.status];
  const Icon = tone.icon;
  const c = execution.counts;
  return (
    <section role="status" className={cn("flex flex-col gap-1.5 rounded-lg border px-3 py-2.5", tone.cls)} data-testid="execution-summary" data-status={execution.status}>
      <p className="flex items-center gap-2 text-sm font-semibold">
        <Icon className="h-4 w-4" aria-hidden /> {tone.title}
      </p>
      {execution.message && <p className="text-xs text-foreground/85">{execution.message}</p>}
      {c && (
        <p className="flex flex-wrap gap-x-3 text-[11px] text-muted-foreground">
          <span>{c.succeeded} done</span>
          {c.failed > 0 && <span>{c.failed} failed</span>}
          {c.blocked > 0 && <span>{c.blocked} blocked</span>}
          {c.skipped > 0 && <span>{c.skipped} not run</span>}
          <span>of {execution.totalSteps}</span>
          {execution.errorCode && <span className="font-mono">{execution.errorCode}</span>}
        </p>
      )}
    </section>
  );
}
