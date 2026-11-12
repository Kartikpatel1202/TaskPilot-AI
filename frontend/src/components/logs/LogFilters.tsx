"use client";

import { memo } from "react";

import { cn } from "@/lib/utils";

import { LEVEL_STYLE } from "./LogEntry";

import type { LogLevel } from "@/types/telemetry";

export const ALL_LEVELS: readonly LogLevel[] = ["DEBUG", "INFO", "WARNING", "ERROR", "SUCCESS"];

interface LogFiltersProps {
  enabled: ReadonlySet<LogLevel>;
  counts: Record<LogLevel, number>;
  onToggle: (level: LogLevel) => void;
}

export const LogFilters = memo(function LogFilters({ enabled, counts, onToggle }: LogFiltersProps) {
  return (
    <div role="group" aria-label="Filter logs by level" className="flex flex-wrap gap-1.5">
      {ALL_LEVELS.map((level) => {
        const active = enabled.has(level);
        const style = LEVEL_STYLE[level];
        return (
          <button
            key={level}
            type="button"
            aria-pressed={active}
            onClick={() => onToggle(level)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-md border px-2 py-0.5 text-[10px] font-semibold tracking-wider transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
              active ? "border-white/15 bg-white/[0.06] text-foreground" : "border-white/[0.06] text-muted-foreground/50 line-through",
            )}
          >
            <span aria-hidden className={cn("h-1.5 w-1.5 rounded-full", style.bar)} />
            {style.label}
            <span className="tabular-nums text-muted-foreground">{counts[level]}</span>
          </button>
        );
      })}
    </div>
  );
});
