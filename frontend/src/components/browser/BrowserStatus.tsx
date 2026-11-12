import { Badge } from "@/components/ui/badge";

import type { BrowserSessionStatus, StreamStatus } from "@/types/browser";

type Variant = "secondary" | "default" | "violet" | "warning" | "success" | "destructive";

export function describeBrowserStatus(
  sessionStatus: BrowserSessionStatus | null,
  streamStatus: StreamStatus,
  hasFrame: boolean,
): { label: string; variant: Variant } {
  if (sessionStatus === "AUTH_REQUIRED") return { label: "Sign-in needed", variant: "warning" };
  if (sessionStatus === "ERROR") return { label: "Browser error", variant: "destructive" };
  if (sessionStatus === "CLOSED") return { label: "Browser closed", variant: "secondary" };
  if (sessionStatus === "BUSY") return { label: "Executing", variant: "default" };
  if (sessionStatus === "INITIALIZING") return { label: "Starting Chromium", variant: "violet" };
  if (streamStatus === "live" && hasFrame) return { label: "Live", variant: "success" };
  if (sessionStatus === "READY") return { label: "Browser ready", variant: "success" };
  if (streamStatus === "reconnecting" || streamStatus === "connecting") return { label: "Connecting preview", variant: "secondary" };
  if (streamStatus === "error") return { label: "Preview offline", variant: "destructive" };
  return { label: "No browser running", variant: "secondary" };
}

interface BrowserStatusProps {
  sessionStatus: BrowserSessionStatus | null;
  streamStatus: StreamStatus;
  hasFrame: boolean;
}

export function BrowserStatus({ sessionStatus, streamStatus, hasFrame }: BrowserStatusProps) {
  const { label, variant } = describeBrowserStatus(sessionStatus, streamStatus, hasFrame);
  return (
    <Badge variant={variant} data-testid="browser-status" data-stream={streamStatus}>
      {label}
    </Badge>
  );
}
