"use client";

import { CalendarDays, Download, Mail, PlayCircle, Plug } from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import type { DomainStatus, DomainStatusEntry, DomainType } from "@/types/integration";

const ICON: Partial<Record<DomainType, typeof Plug>> = {
  YOUTUBE: PlayCircle,
  GMAIL: Mail,
  GOOGLE_CALENDAR: CalendarDays,
  FILES: Download,
};

const STATUS: Record<DomainStatus, { label: string; variant: "secondary" | "default" | "success" | "warning" | "destructive" }> = {
  NOT_CONFIGURED: { label: "Off", variant: "secondary" },
  AVAILABLE: { label: "Available", variant: "default" },
  AUTHENTICATION_REQUIRED: { label: "Sign in yourself", variant: "warning" },
  CONNECTED: { label: "Connected", variant: "success" },
  BLOCKED: { label: "Blocked", variant: "warning" },
  ERROR: { label: "Error", variant: "destructive" },
};

/** One integration domain's status as last OBSERVED in this session's browser (never assumed). */
export function DomainStatusCard({ entry, className }: { entry: DomainStatusEntry; className?: string }) {
  const Icon = ICON[entry.domain] ?? Plug;
  const status = STATUS[entry.status];
  return (
    <div
      className={cn("flex flex-col gap-1.5 rounded-lg border border-white/[0.06] bg-white/[0.015] px-3 py-2.5", className)}
      data-testid="domain-status-card"
      data-domain={entry.domain}
      data-status={entry.status}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-1.5 text-sm font-medium">
          <Icon className="h-3.5 w-3.5 text-muted-foreground" aria-hidden /> {entry.label}
        </span>
        <Badge variant={status.variant}>{status.label}</Badge>
      </div>
      <p className="text-[11px] leading-snug text-muted-foreground">{entry.message}</p>
    </div>
  );
}
