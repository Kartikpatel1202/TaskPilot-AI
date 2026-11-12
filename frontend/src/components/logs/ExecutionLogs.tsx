"use client";

import { ArrowDown, ScrollText, Trash2 } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { LogEntry } from "./LogEntry";
import { ALL_LEVELS, LogFilters } from "./LogFilters";

import type { ExecutionLog, LogLevel } from "@/types/telemetry";

interface ExecutionLogsProps {
  logs: ExecutionLog[];
  onClear: () => void;
  className?: string;
}

const BOTTOM_THRESHOLD_PX = 32;
// useLayoutEffect warns during SSR; fall back to useEffect there.
const useIsoLayoutEffect = typeof window === "undefined" ? useEffect : useLayoutEffect;

export function ExecutionLogs({ logs, onClear, className }: ExecutionLogsProps) {
  const [enabled, setEnabled] = useState<Set<LogLevel>>(() => new Set(ALL_LEVELS));
  const [followTail, setFollowTail] = useState(true);
  const scrollRef = useRef<HTMLDivElement>(null);

  const counts = useMemo(() => {
    const c: Record<LogLevel, number> = { DEBUG: 0, INFO: 0, WARNING: 0, ERROR: 0, SUCCESS: 0 };
    for (const log of logs) c[log.level] += 1;
    return c;
  }, [logs]);

  const visible = useMemo(() => logs.filter((log) => enabled.has(log.level)), [logs, enabled]);
  const lastId = visible[visible.length - 1]?.id;

  const toggleLevel = useCallback((level: LogLevel) => {
    setEnabled((prev) => {
      const next = new Set(prev);
      if (next.has(level)) next.delete(level);
      else next.add(level);
      return next;
    });
  }, []);

  const scrollToBottom = useCallback(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, []);

  // Auto-scroll to the newest entry only while the user is following the tail.
  useIsoLayoutEffect(() => {
    if (followTail) scrollToBottom();
  }, [lastId, followTail, scrollToBottom]);

  const handleScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= BOTTOM_THRESHOLD_PX;
    if (atBottom !== followTail) setFollowTail(atBottom);
  };

  return (
    <Card className={cn("flex min-h-[340px] flex-col overflow-hidden lg:h-[460px]", className)} aria-labelledby="execution-logs-title">
      <CardHeader className="flex-wrap">
        <CardTitle id="execution-logs-title">
          <ScrollText className="h-3.5 w-3.5" aria-hidden /> Execution logs
        </CardTitle>
        <Button variant="ghost" size="sm" onClick={onClear} disabled={logs.length === 0} aria-label="Clear logs">
          <Trash2 aria-hidden /> Clear
        </Button>
      </CardHeader>
      <div className="border-b border-white/[0.05] px-4 py-2">
        <LogFilters enabled={enabled} counts={counts} onToggle={toggleLevel} />
      </div>
      <div className="relative min-h-0 flex-1">
        <div
          ref={scrollRef}
          onScroll={handleScroll}
          className="h-full max-h-[420px] overflow-y-auto px-2 scrollbar-thin lg:max-h-none"
          role="log"
          aria-live="polite"
          aria-relevant="additions"
          aria-label="Execution log entries"
          tabIndex={0}
        >
          {visible.length === 0 ? (
            <div className="flex h-full min-h-[200px] flex-col items-center justify-center gap-2 px-6 text-center">
              <ScrollText className="h-6 w-6 text-muted-foreground/50" aria-hidden />
              <p className="text-sm text-muted-foreground">
                {logs.length === 0 ? "No activity yet. Live events will stream in here." : "No entries match the selected levels."}
              </p>
            </div>
          ) : (
            <ol className="divide-y divide-white/[0.04]">
              {visible.map((log) => (
                <LogEntry key={log.id} log={log} />
              ))}
            </ol>
          )}
        </div>
        {!followTail && visible.length > 0 && (
          <button
            type="button"
            onClick={() => {
              setFollowTail(true);
              scrollToBottom();
            }}
            className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-white/10 bg-surface-raised px-3 py-1 text-xs text-foreground shadow-lg hover:border-cyan-brand/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <ArrowDown className="h-3 w-3" aria-hidden /> Jump to latest
          </button>
        )}
      </div>
    </Card>
  );
}
