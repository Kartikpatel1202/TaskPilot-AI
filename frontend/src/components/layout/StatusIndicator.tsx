import { cn } from "@/lib/utils";

import type { ConnectionStatus } from "@/types/telemetry";

const STATUS_META: Record<ConnectionStatus, { label: string; dot: string; text: string; pulse: boolean }> = {
  CONNECTED: { label: "Connected", dot: "bg-level-success", text: "text-level-success", pulse: false },
  CONNECTING: { label: "Connecting", dot: "bg-level-info", text: "text-level-info", pulse: true },
  RECONNECTING: { label: "Reconnecting", dot: "bg-level-warning", text: "text-level-warning", pulse: true },
  DISCONNECTED: { label: "Disconnected", dot: "bg-level-debug", text: "text-muted-foreground", pulse: false },
  ERROR: { label: "Offline", dot: "bg-level-error", text: "text-level-error", pulse: false },
};

export function connectionLabel(status: ConnectionStatus): string {
  return STATUS_META[status].label;
}

interface StatusIndicatorProps {
  status: ConnectionStatus;
  attempt?: number;
  compact?: boolean;
  className?: string;
}

export function StatusIndicator({ status, attempt = 0, compact = false, className }: StatusIndicatorProps) {
  const meta = STATUS_META[status];
  const label = status === "RECONNECTING" && attempt > 0 ? `${meta.label} (${attempt})` : meta.label;
  return (
    <span
      role="status"
      aria-live="polite"
      aria-label={`Backend connection: ${label}`}
      title={`Backend connection: ${label}`}
      className={cn("inline-flex items-center gap-2 text-xs font-medium", meta.text, className)}
    >
      <span className="relative inline-flex h-2 w-2">
        {meta.pulse && <span className={cn("absolute inline-flex h-full w-full animate-ping rounded-full opacity-60", meta.dot)} />}
        <span className={cn("relative inline-flex h-2 w-2 rounded-full", meta.dot)} />
      </span>
      {!compact && <span>{label}</span>}
    </span>
  );
}
