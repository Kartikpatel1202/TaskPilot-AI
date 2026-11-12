import { memo } from "react";

import { formatTime } from "@/lib/utils";

import type { LiveFrame } from "@/types/browser";

interface LiveBrowserFrameProps {
  frame: LiveFrame;
  /** No newer frame has arrived for a while (e.g. privacy pause or idle browser). */
  stale?: boolean;
}

/** One real Chromium viewport screenshot (JPEG object URL from the stream socket). */
export const LiveBrowserFrame = memo(function LiveBrowserFrame({ frame, stale = false }: LiveBrowserFrameProps) {
  return (
    <figure className="relative h-full w-full bg-black/40" data-testid="live-frame" data-sequence={frame.meta.sequence}>
      {/* eslint-disable-next-line @next/next/no-img-element -- live object-URL frames, not static assets */}
      <img
        src={frame.url}
        alt={`Live browser screenshot #${frame.meta.sequence}`}
        width={frame.meta.width}
        height={frame.meta.height}
        className="h-full w-full object-contain"
        draggable={false}
      />
      <figcaption className="pointer-events-none absolute bottom-2 right-2 flex items-center gap-1.5 rounded bg-black/60 px-1.5 py-0.5 font-mono text-[10px] text-white/80">
        <span className={stale ? "h-1.5 w-1.5 rounded-full bg-level-warning" : "h-1.5 w-1.5 animate-pulse rounded-full bg-level-success"} aria-hidden />
        {stale ? "Last frame" : "Live"} · #{frame.meta.sequence} · {formatTime(frame.meta.captured_at)}
      </figcaption>
    </figure>
  );
});
