"use client";

import { Activity } from "lucide-react";

import type { IntegrationsState } from "@/context/taskPilotReducer";

/** The latest integration events of the active task (bounded; messages only — no bodies or paths). */
export function IntegrationActivity({ activity, limit = 6 }: { activity: IntegrationsState["activity"]; limit?: number }) {
  if (activity.length === 0) return null;
  const recent = activity.slice(-limit).reverse();
  return (
    <section aria-label="Integration activity" className="flex flex-col gap-1" data-testid="integration-activity">
      <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
        <Activity className="h-3 w-3" aria-hidden /> Activity
      </p>
      <ul className="flex flex-col gap-0.5">
        {recent.map((e, i) => (
          <li key={`${e.at}-${i}`} className="flex gap-2 text-[11px]">
            <span className="shrink-0 font-mono text-muted-foreground">{e.type}</span>
            <span className="text-foreground/80">{e.message}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
