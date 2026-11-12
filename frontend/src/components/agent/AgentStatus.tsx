import { Bot, FlaskConical } from "lucide-react";

import { ASSISTANT_NAME } from "@/lib/persona";
import { cn } from "@/lib/utils";

import type { AgentStatus as AgentStatusValue, AgentStatusResponse } from "@/types/agent";

const STATUS_META: Record<AgentStatusValue, { label: string; dot: string; pulse?: boolean }> = {
  IDLE: { label: "Available", dot: "bg-level-success" },
  PLANNING: { label: "Planning…", dot: "bg-violet-brand", pulse: true },
  NEEDS_CLARIFICATION: { label: "Waiting for your answer", dot: "bg-level-warning" },
  PLAN_READY: { label: "Plan ready", dot: "bg-cyan-brand" },
  REJECTED: { label: "Request not planned", dot: "bg-level-warning" },
  ERROR: { label: "Planning error", dot: "bg-level-error" },
};

interface AgentStatusProps {
  status: AgentStatusValue;
  info: AgentStatusResponse | null;
  connected: boolean;
}

export function AgentStatus({ status, info, connected }: AgentStatusProps) {
  const disabled = info !== null && info.status !== "available";
  const meta = !connected
    ? { label: "Offline", dot: "bg-level-debug" }
    : disabled
      ? { label: info?.status === "disabled" ? "Planning disabled" : "Planner unavailable", dot: "bg-level-error" }
      : STATUS_META[status];

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="agent-status">
      <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/[0.03] px-2.5 py-1 text-xs">
        <Bot className="h-3.5 w-3.5 text-violet-brand" aria-hidden />
        <span className="font-medium">{info?.agent_name ?? ASSISTANT_NAME}</span>
        <span className="relative inline-flex h-2 w-2">
          {"pulse" in meta && meta.pulse && <span className={cn("absolute h-full w-full animate-ping rounded-full opacity-60", meta.dot)} />}
          <span className={cn("relative h-2 w-2 rounded-full", meta.dot)} />
        </span>
        <span className="text-muted-foreground" role="status">
          {meta.label}
        </span>
      </span>
      {info?.is_mock && (
        <span
          className="inline-flex items-center gap-1 rounded-full border border-violet-brand/30 bg-violet-brand/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider text-violet-brand"
          title={info.setup_hint ?? "Plans come from the offline, rule-based planner — no real LLM is called."}
        >
          <FlaskConical className="h-3 w-3" aria-hidden /> Offline mock planner (no AI)
        </span>
      )}
      {info && !info.is_mock && (
        <span className="font-mono text-[10px] text-muted-foreground" title="Configured LLM provider">
          {info.provider} · {info.model}
        </span>
      )}
    </div>
  );
}
