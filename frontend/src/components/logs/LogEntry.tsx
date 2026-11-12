"use client";

import { Bot, CheckCircle2, ChevronRight, CircleAlert, Info, Bug, TriangleAlert } from "lucide-react";
import { memo, useState } from "react";

import { ASSISTANT_NAME } from "@/lib/persona";
import { cn, formatTime, redactSensitive, shortId } from "@/lib/utils";

import type { ExecutionLog, LogLevel } from "@/types/telemetry";

export const LEVEL_STYLE: Record<LogLevel, { icon: typeof Info; text: string; bar: string; label: string }> = {
  DEBUG: { icon: Bug, text: "text-level-debug", bar: "bg-level-debug/50", label: "DEBUG" },
  INFO: { icon: Info, text: "text-level-info", bar: "bg-level-info", label: "INFO" },
  WARNING: { icon: TriangleAlert, text: "text-level-warning", bar: "bg-level-warning", label: "WARN" },
  ERROR: { icon: CircleAlert, text: "text-level-error", bar: "bg-level-error", label: "ERROR" },
  SUCCESS: { icon: CheckCircle2, text: "text-level-success", bar: "bg-level-success", label: "OK" },
};

export const LogEntry = memo(function LogEntry({ log }: { log: ExecutionLog }) {
  const [open, setOpen] = useState(false);
  const style = LEVEL_STYLE[log.level];
  const Icon = log.source === "assistant" ? Bot : style.icon;
  const hasMeta = log.metadata !== null && Object.keys(log.metadata).length > 0;

  return (
    <li className="group relative flex gap-2.5 py-2 pl-3 pr-2 text-[13px] leading-snug" data-level={log.level}>
      <span aria-hidden className={cn("absolute inset-y-2 left-0 w-0.5 rounded-full", style.bar)} />
      <Icon className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", log.source === "assistant" ? "text-violet-brand" : style.text)} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[10px] text-muted-foreground">
          <time dateTime={log.timestamp} className="font-mono tabular-nums">
            {formatTime(log.timestamp)}
          </time>
          <span className={cn("font-semibold tracking-wider", style.text)}>{style.label}</span>
          {log.source === "assistant" && <span className="font-medium text-violet-brand">{ASSISTANT_NAME}</span>}
          {log.isDemo && (
            <span className="rounded border border-violet-brand/30 px-1 font-semibold uppercase tracking-wider text-violet-brand">demo</span>
          )}
          {log.source === "client" && <span className="uppercase tracking-wider">client</span>}
          {log.taskId && <span className="font-mono">#{shortId(log.taskId)}</span>}
        </div>
        <p className={cn("mt-0.5 break-words text-foreground/90", log.source === "assistant" && "text-foreground")} lang={log.language === "hi" ? "hi" : undefined}>
          {log.message}
        </p>
        {hasMeta && (
          <div className="mt-1">
            <button
              type="button"
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
              className="inline-flex items-center gap-0.5 rounded text-[10px] text-muted-foreground hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <ChevronRight className={cn("h-3 w-3 transition-transform", open && "rotate-90")} aria-hidden />
              metadata
            </button>
            {open && (
              <pre className="mt-1 max-h-40 overflow-auto rounded-md border border-white/[0.06] bg-black/30 p-2 font-mono text-[11px] text-muted-foreground scrollbar-thin">
                {JSON.stringify(redactSensitive(log.metadata), null, 2)}
              </pre>
            )}
          </div>
        )}
      </div>
    </li>
  );
});
