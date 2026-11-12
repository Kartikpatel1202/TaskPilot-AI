import { Eye, EyeOff, Lock, LockOpen } from "lucide-react";

interface BrowserToolbarProps {
  url: string | null;
  title?: string | null;
  headless?: boolean | null;
}

/**
 * Read-only address bar for the real Chromium session. TaskPilot drives the browser
 * from the plan; the dashboard never sends free-form navigation or clicks.
 * The backend only reports URLs without query strings or fragments.
 */
export function BrowserToolbar({ url, title, headless }: BrowserToolbarProps) {
  const secure = url?.startsWith("https://") ?? false;
  return (
    <div className="flex items-center gap-2 border-b border-white/[0.06] bg-surface-sunken/70 px-3 py-2">
      <div className="flex gap-1.5" aria-hidden>
        <span className="h-2.5 w-2.5 rounded-full bg-[#ff5f57]/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#febc2e]/70" />
        <span className="h-2.5 w-2.5 rounded-full bg-[#28c840]/70" />
      </div>
      <div
        className="flex min-w-0 flex-1 items-center gap-1.5 rounded-md border border-white/[0.06] bg-black/30 px-2.5 py-1 font-mono text-[11px] text-muted-foreground"
        aria-label="Browser address"
        title={title ?? undefined}
      >
        {url && !secure ? (
          <LockOpen className="h-3 w-3 shrink-0 text-level-warning/80" aria-label="Not HTTPS" />
        ) : (
          <Lock className="h-3 w-3 shrink-0 opacity-60" aria-hidden />
        )}
        <span className="truncate" data-testid="browser-url">
          {url ?? "about:blank — no page loaded"}
        </span>
      </div>
      {headless !== null && headless !== undefined && (
        <span
          className="hidden items-center gap-1 text-[10px] uppercase tracking-wider text-muted-foreground sm:inline-flex"
          title={headless ? "Chromium runs headless; this preview shows its real screenshots." : "Chromium runs in a visible window."}
        >
          {headless ? <EyeOff className="h-3 w-3" aria-hidden /> : <Eye className="h-3 w-3" aria-hidden />}
          {headless ? "Headless" : "Visible"}
        </span>
      )}
    </div>
  );
}
