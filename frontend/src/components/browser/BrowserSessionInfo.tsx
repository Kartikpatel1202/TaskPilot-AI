import { shortId } from "@/lib/utils";

import type { BrowserLiveState, LiveFrame, StreamStatus } from "@/types/browser";

interface BrowserSessionInfoProps {
  sessionId: string | null;
  browser: BrowserLiveState;
  frame: LiveFrame | null;
  streamStatus: StreamStatus;
  droppedFrames: number;
}

/** Compact, non-sensitive facts about the session's browser (no cookies, no storage). */
export function BrowserSessionInfo({ sessionId, browser, frame, streamStatus, droppedFrames }: BrowserSessionInfoProps) {
  const items: Array<[string, string]> = [
    ["Session", sessionId ? `#${shortId(sessionId)}` : "—"],
    ["Engine", browser.engine ?? "chromium"],
    ["Mode", browser.headless === null ? "—" : browser.headless ? "headless" : "visible"],
    ["Stream", streamStatus],
    ["Frame", frame ? `#${frame.meta.sequence} · ${frame.meta.width}×${frame.meta.height}` : "—"],
  ];
  if (droppedFrames > 0) items.push(["Dropped", String(droppedFrames)]);
  return (
    <dl className="flex flex-wrap gap-x-4 gap-y-1 px-3 pb-3 text-[10px] text-muted-foreground" data-testid="browser-session-info">
      {items.map(([label, value]) => (
        <div key={label} className="flex gap-1">
          <dt className="uppercase tracking-wider">{label}</dt>
          <dd className="font-mono text-foreground/70">{value}</dd>
        </div>
      ))}
    </dl>
  );
}
