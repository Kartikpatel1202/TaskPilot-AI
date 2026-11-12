import { Ban, CheckCircle2, Circle, CircleSlash, Loader2, ShieldCheck, XCircle, type LucideIcon } from "lucide-react";
import { memo } from "react";

import { cn } from "@/lib/utils";

import type { ActionExecutionStatus } from "@/types/execution";

const STATUS: Record<ActionExecutionStatus, { label: string; icon: LucideIcon; tone: string }> = {
  PENDING: { label: "Pending", icon: Circle, tone: "text-muted-foreground" },
  RUNNING: { label: "Running", icon: Loader2, tone: "text-cyan-brand" },
  SUCCEEDED: { label: "Done", icon: CheckCircle2, tone: "text-level-success" },
  FAILED: { label: "Failed", icon: XCircle, tone: "text-level-error" },
  BLOCKED: { label: "Blocked", icon: Ban, tone: "text-level-warning" },
  SKIPPED: { label: "Not run", icon: CircleSlash, tone: "text-muted-foreground/70" },
};

export interface ExecutionStepProps {
  order: number;
  description: string;
  actionType: string;
  status: ActionExecutionStatus;
  message?: string | null;
  errorCode?: string | null;
  durationMs?: number | null;
  verified?: boolean;
  extractedData?: Record<string, unknown> | null;
}

type Row = Record<string, string | null>;

function extractedRows(data: Record<string, unknown> | null | undefined): { rows: Row[]; fields: string[]; missing: string[] } {
  const items = Array.isArray(data?.items) ? (data?.items as unknown[]) : [];
  const rows = items.filter((r): r is Row => typeof r === "object" && r !== null).slice(0, 5);
  const fields = Array.from(new Set(rows.flatMap((r) => Object.keys(r)))).slice(0, 6);
  const missing = Array.isArray(data?.missing_fields) ? (data?.missing_fields as unknown[]).map(String) : [];
  return { rows, fields, missing };
}

/** One step's OBSERVED result. Nothing is shown as done unless the backend reported it. */
export const ExecutionStep = memo(function ExecutionStep({
  order,
  description,
  actionType,
  status,
  message,
  errorCode,
  durationMs,
  verified = false,
  extractedData,
}: ExecutionStepProps) {
  const meta = STATUS[status];
  const Icon = meta.icon;
  const data = actionType === "extract" ? extractedRows(extractedData) : null;
  return (
    <li
      className={cn(
        "flex gap-3 rounded-lg border px-3 py-2.5",
        status === "RUNNING" ? "border-cyan-brand/40 bg-cyan-brand/[0.05]" : "border-white/[0.06] bg-white/[0.02]",
      )}
      data-testid="execution-step"
      data-status={status}
      aria-current={status === "RUNNING" ? "step" : undefined}
    >
      <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center font-mono text-[11px] text-muted-foreground">{order}</span>
      <div className="flex min-w-0 flex-1 flex-col gap-1">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <p className="min-w-0 text-sm text-foreground">{description}</p>
          <span className={cn("inline-flex items-center gap-1 text-[11px] font-semibold uppercase tracking-wider", meta.tone)}>
            <Icon className={cn("h-3.5 w-3.5", status === "RUNNING" && "animate-spin")} aria-hidden />
            {meta.label}
          </span>
        </div>
        {message && <p className="text-xs text-muted-foreground">{message}</p>}
        <p className="flex flex-wrap items-center gap-x-3 gap-y-0.5 text-[10px] text-muted-foreground/80">
          <span className="uppercase tracking-wider">{actionType.replace("_", " ")}</span>
          {durationMs != null && <span className="font-mono">{(durationMs / 1000).toFixed(1)}s</span>}
          {verified && status === "SUCCEEDED" && (
            <span className="inline-flex items-center gap-0.5 text-level-success/80" title="A visible change was observed in the browser">
              <ShieldCheck className="h-3 w-3" aria-hidden /> verified
            </span>
          )}
          {errorCode && <span className="font-mono text-level-error/80">{errorCode}</span>}
        </p>
        {data && data.rows.length > 0 && (
          <div className="mt-1 overflow-x-auto rounded border border-white/[0.06]" data-testid="extracted-data">
            <table className="w-full text-left text-[11px]">
              <caption className="sr-only">Data read from the page</caption>
              <thead className="bg-white/[0.03] text-muted-foreground">
                <tr>
                  {data.fields.map((f) => (
                    <th key={f} scope="col" className="px-2 py-1 font-medium capitalize">
                      {f}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row, i) => (
                  <tr key={i} className="border-t border-white/[0.04]">
                    {data.fields.map((f) => (
                      <td key={f} className="px-2 py-1 text-foreground/85">
                        {row[f] ?? <span className="text-muted-foreground/60">not shown</span>}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
            {data.missing.length > 0 && (
              <p className="border-t border-white/[0.04] px-2 py-1 text-[10px] text-muted-foreground">
                Not found on the page: {data.missing.join(", ")}
              </p>
            )}
          </div>
        )}
      </div>
    </li>
  );
});
