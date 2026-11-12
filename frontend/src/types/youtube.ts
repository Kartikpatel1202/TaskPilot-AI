/** Phase 5 YouTube. Mirrors `backend/app/schemas/youtube.py`. Only observed values. */

import type { PendingChoice } from "./integration";

export interface YouTubeVideo {
  option_id: string;
  video_id?: string | null;
  title: string;
  channel_name?: string | null;
  duration?: string | null;
  views?: string | null;
  published_label?: string | null;
  video_url: string;
  thumbnail_url?: string | null;
  relevance: number;
  observed_at: string;
}

export type PlaybackState = "PLAYING" | "PAUSED" | "BUFFERING" | "LOGIN_REQUIRED" | "PLAYBACK_BLOCKED" | "UNKNOWN";

export interface YouTubePlayback {
  state: PlaybackState;
  video?: YouTubeVideo | null;
  page_url?: string | null;
  current_time?: number | null;
  message: string;
  observed_at: string;
}

export interface YouTubeResults {
  results: YouTubeVideo[];
  selected: YouTubeVideo | null;
  playback: YouTubePlayback | null;
  pending_choice: PendingChoice | null;
}

export const PLAYBACK_LABEL: Record<PlaybackState, string> = {
  PLAYING: "Playing (verified)",
  PAUSED: "Paused",
  BUFFERING: "Buffering",
  LOGIN_REQUIRED: "Sign-in needed",
  PLAYBACK_BLOCKED: "Blocked by YouTube",
  UNKNOWN: "Not verified",
};
