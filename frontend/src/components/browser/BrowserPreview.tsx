"use client";

import { Globe } from "lucide-react";
import { memo, useEffect, useState } from "react";

import { Card, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

import { BrowserControls } from "./BrowserControls";
import { BrowserEmptyState, type BrowserEmptyReason } from "./BrowserEmptyState";
import { BrowserErrorBanner } from "./BrowserErrorBanner";
import { BrowserSessionInfo } from "./BrowserSessionInfo";
import { BrowserStatus } from "./BrowserStatus";
import { BrowserToolbar } from "./BrowserToolbar";
import { LiveBrowserFrame } from "./LiveBrowserFrame";

import type { BrowserLiveState, LiveFrame, StreamStatus } from "@/types/browser";
import type { BrowserPreviewState } from "@/types/telemetry";

const STALE_AFTER_MS = 8_000;

export interface BrowserPreviewProps {
  /** Legacy Phase 1 preview state (demo placeholder only). */
  preview: BrowserPreviewState;
  browser?: BrowserLiveState;
  sessionId?: string | null;
  frame?: LiveFrame | null;
  streamStatus?: StreamStatus;
  droppedFrames?: number;
  planReady?: boolean;
  executing?: boolean;
  executionAvailable?: boolean;
  unavailableMessage?: string | null;
  onReconnect?: () => void;
  onClose?: () => Promise<unknown>;
  onDismissNotice?: () => void;
  className?: string;
}

function useNow(intervalMs: number, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return undefined;
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, active]);
  return now;
}

/**
 * Live view of the session's real Chromium browser. Frames are genuine viewport
 * screenshots streamed over the binary socket; when there is no frame the panel
 * says so honestly instead of showing a picture.
 */
export const BrowserPreview = memo(function BrowserPreview({
  preview,
  browser,
  sessionId = null,
  frame = null,
  streamStatus = "idle",
  droppedFrames = 0,
  planReady = false,
  executing = false,
  executionAvailable = true,
  unavailableMessage = null,
  onReconnect,
  onClose,
  onDismissNotice,
  className,
}: BrowserPreviewProps) {
  const now = useNow(2_000, frame !== null);
  const sessionStatus = browser?.sessionStatus ?? null;
  const browserRunning = sessionStatus !== null && sessionStatus !== "CLOSED";
  const showFrame = frame !== null && sessionStatus !== "CLOSED";
  const stale = frame !== null && now - frame.receivedAt > STALE_AFTER_MS;

  let reason: BrowserEmptyReason;
  if (preview.mode === "PLACEHOLDER") reason = "demo";
  else if (!executionAvailable) reason = "unavailable";
  else if (sessionStatus === "CLOSED") reason = "closed";
  else if (sessionStatus === "INITIALIZING") reason = "starting";
  else if (browserRunning || executing) reason = "waiting_frame";
  else if (planReady) reason = "plan_ready";
  else reason = "idle";

  return (
    <Card className={cn("flex min-h-[340px] flex-col overflow-hidden lg:min-h-[460px]", className)} aria-labelledby="browser-preview-title">
      <CardHeader className="flex-wrap gap-2">
        <CardTitle id="browser-preview-title">
          <Globe className="h-3.5 w-3.5" aria-hidden /> Browser preview
        </CardTitle>
        <div className="flex items-center gap-2">
          {onReconnect && onClose && (
            <BrowserControls
              streamStatus={streamStatus}
              canClose={browserRunning && !executing}
              onReconnect={onReconnect}
              onClose={onClose}
            />
          )}
          {preview.mode === "PLACEHOLDER" && !browserRunning ? (
            <BrowserStatus sessionStatus={null} streamStatus="idle" hasFrame={false} />
          ) : (
            <BrowserStatus sessionStatus={sessionStatus} streamStatus={streamStatus} hasFrame={showFrame} />
          )}
        </div>
      </CardHeader>
      <BrowserErrorBanner
        notice={browser?.notice ?? null}
        unavailableMessage={!executionAvailable ? unavailableMessage : null}
        onDismiss={onDismissNotice}
      />
      <div className="m-3 flex flex-1 flex-col overflow-hidden rounded-lg border border-white/[0.06] bg-black/20">
        <BrowserToolbar url={browser?.url ?? preview.url} title={browser?.title} headless={browser?.headless ?? null} />
        <div className="relative min-h-[260px] flex-1 overflow-hidden">
          {showFrame ? (
            <LiveBrowserFrame frame={frame} stale={stale} />
          ) : (
            <BrowserEmptyState reason={reason} message={reason === "demo" ? preview.message : undefined} />
          )}
        </div>
      </div>
      {browser && (browserRunning || frame) && (
        <BrowserSessionInfo
          sessionId={sessionId}
          browser={browser}
          frame={frame}
          streamStatus={streamStatus}
          droppedFrames={droppedFrames}
        />
      )}
    </Card>
  );
});
