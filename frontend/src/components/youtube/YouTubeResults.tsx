"use client";

import { CheckCircle2, ExternalLink, PlayCircle } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { PLAYBACK_LABEL, type YouTubeResults as Results } from "@/types/youtube";

/** Results exactly as read from the YouTube page; the selected video and its VERIFIED playback state. */
export function YouTubeResults({ data }: { data: Results }) {
  const { results, selected, playback } = data;
  const playing = playback?.state === "PLAYING";
  return (
    <section className="flex flex-col gap-2" aria-label="YouTube results" data-testid="youtube-results">
      <div className="flex items-center justify-between gap-2">
        <p className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
          <PlayCircle className="h-3 w-3" aria-hidden /> YouTube · {results.length} result(s)
        </p>
        {playback && (
          <Badge variant={playing ? "success" : "warning"} data-testid="playback-state">{PLAYBACK_LABEL[playback.state]}</Badge>
        )}
      </div>
      {playback && <p className="text-xs text-muted-foreground" data-testid="playback-message">{playback.message}</p>}
      <ol className="flex flex-col gap-1">
        {results.slice(0, 8).map((v) => {
          const isSelected = selected?.option_id === v.option_id;
          return (
            <li key={v.option_id} className={cn("flex items-start justify-between gap-2 rounded-md px-2 py-1.5 text-sm",
              isSelected ? "border border-level-success/30 bg-level-success/[0.06]" : "border border-transparent")}
              data-testid="youtube-result" data-selected={isSelected}>
              <span className="flex flex-col">
                <span className="flex items-center gap-1.5">
                  {isSelected && <CheckCircle2 className="h-3.5 w-3.5 text-level-success" aria-label="Selected" />}
                  {v.title}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {[v.channel_name, v.duration, v.views, v.published_label].filter(Boolean).join(" · ")}
                </span>
              </span>
              <a href={v.video_url} target="_blank" rel="noopener noreferrer nofollow" className="mt-0.5 text-muted-foreground hover:text-foreground"
                aria-label={`Open “${v.title}” on YouTube`}>
                <ExternalLink className="h-3.5 w-3.5" aria-hidden />
              </a>
            </li>
          );
        })}
      </ol>
      <p className="text-[11px] text-muted-foreground">Nothing is downloaded; ads are never skipped or blocked by TaskPilot.</p>
    </section>
  );
}
