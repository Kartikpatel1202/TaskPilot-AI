import { Ban, Download, KeyRound, ShieldAlert, X } from "lucide-react";

import type { BrowserNotice } from "@/types/browser";

const META: Record<BrowserNotice["kind"], { title: string; icon: typeof Ban; tone: "warning" | "error" }> = {
  navigation_blocked: { title: "Navigation blocked", icon: ShieldAlert, tone: "warning" },
  authentication_required: { title: "Please sign in yourself", icon: KeyRound, tone: "warning" },
  popup_blocked: { title: "Pop-up blocked", icon: Ban, tone: "warning" },
  download_blocked: { title: "Download blocked", icon: Download, tone: "warning" },
  session_error: { title: "Browser error", icon: ShieldAlert, tone: "error" },
};

interface BrowserErrorBannerProps {
  notice: BrowserNotice | null;
  /** Shown when the backend cannot run a browser at all (e.g. Chromium not installed). */
  unavailableMessage?: string | null;
  onDismiss?: () => void;
}

export function BrowserErrorBanner({ notice, unavailableMessage, onDismiss }: BrowserErrorBannerProps) {
  if (!notice && !unavailableMessage) return null;
  if (!notice) {
    return (
      <div role="status" className="mx-3 flex items-start gap-2 rounded-md border border-level-error/30 bg-level-error/[0.07] px-3 py-2 text-xs text-level-error" data-testid="browser-unavailable">
        <ShieldAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        <span>{unavailableMessage}</span>
      </div>
    );
  }
  const meta = META[notice.kind];
  const Icon = meta.icon;
  const tone =
    meta.tone === "error"
      ? "border-level-error/30 bg-level-error/[0.07] text-level-error"
      : "border-level-warning/30 bg-level-warning/[0.07] text-level-warning";
  return (
    <div role="alert" className={`mx-3 flex items-start gap-2 rounded-md border px-3 py-2 text-xs ${tone}`} data-testid="browser-notice" data-kind={notice.kind}>
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="font-semibold">{meta.title}</p>
        <p className="text-foreground/80">{notice.message}</p>
        {notice.kind === "authentication_required" && (
          <p className="mt-1 text-muted-foreground">TaskPilot never types passwords, OTPs or CAPTCHAs. The task was stopped safely.</p>
        )}
      </div>
      {onDismiss && notice.kind !== "authentication_required" && (
        <button type="button" onClick={onDismiss} className="rounded p-0.5 text-muted-foreground hover:text-foreground" aria-label="Dismiss browser notice">
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}
