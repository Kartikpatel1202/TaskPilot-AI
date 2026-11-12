"use client";

import { FlaskConical, Fingerprint, Menu, RotateCw, Volume2, VolumeX } from "lucide-react";

import { usePathname } from "next/navigation";

import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/components/auth/AuthGate";
import { NAV_ITEMS } from "@/config/navigation";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { useTaskPilotActions, useTaskPilotState, useTaskPilotUi } from "@/hooks/useTaskPilot";
import { ASSISTANT_NAME } from "@/lib/persona";
import { cn, shortId } from "@/lib/utils";

import { LogoMark } from "./Logo";
import { StatusIndicator } from "./StatusIndicator";

export function TopNavbar({ onOpenMenu }: { onOpenMenu: () => void }) {
  const pathname = usePathname();
  const { connectionStatus, sessionId } = useTaskPilotState();
  const { demoAvailable, voiceReplies, speechSupported, reconnectAttempt } = useTaskPilotUi();
  const { reconnect, setVoiceReplies } = useTaskPilotActions();
  const canRetry = connectionStatus === "ERROR" || connectionStatus === "DISCONNECTED";
  const auth = useAuth();

  return (
    <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-background/75 px-4 backdrop-blur-xl sm:px-6">
      <Button variant="ghost" size="icon-sm" className="md:hidden" onClick={onOpenMenu} aria-label="Open navigation">
        <Menu />
      </Button>

      <div className="flex min-w-0 items-center gap-2">
        <LogoMark className="h-7 w-7 shrink-0 sm:hidden" />
        <span className="hidden truncate text-sm font-semibold tracking-tight sm:inline">
          TaskPilot <span className="text-gradient">AI</span>
        </span>
        <span className="hidden text-xs text-muted-foreground sm:inline">/ {NAV_ITEMS.find((item) => item.href === pathname)?.label ?? "Overview"}</span>
      </div>

      <div className="ml-auto flex items-center gap-2 sm:gap-3">
        {auth.user && (
          <span className="hidden items-center gap-2 text-xs text-muted-foreground md:flex" data-testid="signed-in-user">
            {auth.user.email} · {auth.user.role.toLowerCase().replace("_", " ")}
            <Button variant="ghost" size="sm" onClick={() => void auth.signOut()}>Sign out</Button>
          </span>
        )}
        {demoAvailable && (
          <Badge variant="violet" title="Development demo endpoints are enabled. Demo events are simulated.">
            <FlaskConical className="h-3 w-3" aria-hidden />
            <span className="hidden sm:inline">Demo mode</span>
            <span className="sm:hidden">Demo</span>
          </Badge>
        )}

        {!sessionId && <Skeleton className="hidden h-6 w-24 md:block" aria-label="Loading session" />}
        {sessionId && (
          <span
            className="hidden items-center gap-1.5 rounded-md border border-border px-2 py-1 font-mono text-[11px] text-muted-foreground md:inline-flex"
            title="Session identifier (abbreviated)"
          >
            <Fingerprint className="h-3 w-3" aria-hidden />
            {shortId(sessionId)}
          </span>
        )}

        <div className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1">
          <StatusIndicator status={connectionStatus} attempt={reconnectAttempt} />
          {canRetry && (
            <button
              type="button"
              onClick={reconnect}
              className="ml-1 inline-flex items-center gap-1 rounded px-1 text-xs text-cyan-brand hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <RotateCw className="h-3 w-3" aria-hidden /> Retry
            </button>
          )}
        </div>

        {speechSupported && (
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={() => setVoiceReplies(!voiceReplies)}
            aria-pressed={voiceReplies}
            aria-label={voiceReplies ? `Mute ${ASSISTANT_NAME}'s spoken replies` : `Let ${ASSISTANT_NAME} speak replies aloud`}
            title={voiceReplies ? "Spoken replies on" : "Spoken replies off"}
            className={cn(voiceReplies && "text-cyan-brand")}
          >
            {voiceReplies ? <Volume2 /> : <VolumeX />}
          </Button>
        )}

        <div
          className="flex h-8 w-8 items-center justify-center rounded-full border border-white/10 bg-gradient-to-br from-cyan-brand/25 to-violet-brand/25 text-xs font-semibold"
          role="img"
          aria-label="Profile (authentication arrives in a later phase)"
          title="Profile — authentication arrives in a later phase"
        >
          You
        </div>
      </div>
    </header>
  );
}
