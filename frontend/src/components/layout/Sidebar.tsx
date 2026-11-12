"use client";

import { ChevronsLeft, ChevronsRight } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { NAV_ITEMS } from "@/config/navigation";
import { useTaskPilotState } from "@/hooks/useTaskPilot";
import { PRODUCT_NAME } from "@/lib/persona";
import { cn } from "@/lib/utils";

import { LogoMark } from "./Logo";
import { StatusIndicator, connectionLabel } from "./StatusIndicator";

interface SidebarProps {
  /** Desktop only: icon rail vs. full width. Ignored in the mobile drawer. */
  collapsed?: boolean;
  onToggleCollapse?: () => void;
  variant?: "desktop" | "mobile";
  onNavigate?: () => void;
}

export function Sidebar({ collapsed = false, onToggleCollapse, variant = "desktop", onNavigate }: SidebarProps) {
  const pathname = usePathname();
  const { connectionStatus } = useTaskPilotState();
  const isMobile = variant === "mobile";
  // On tablets (md) the rail is always compact; on desktop (lg+) it follows `collapsed`.
  const showLabels = isMobile ? "inline" : collapsed ? "hidden" : "hidden lg:inline";

  return (
    <nav aria-label="Primary" className="flex h-full flex-col gap-2 px-3 py-4">
      <div className={cn("flex items-center gap-2.5 px-1.5 pb-4", !isMobile && "justify-center lg:justify-start", !isMobile && collapsed && "lg:justify-center")}>
        <LogoMark className="h-8 w-8 shrink-0" />
        <span className={cn("truncate text-[15px] font-semibold tracking-tight", showLabels)}>
          TaskPilot <span className="text-gradient">AI</span>
        </span>
      </div>

      <ul className="flex flex-1 flex-col gap-1">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = item.href !== undefined && pathname === item.href;
          const base = cn(
            "group relative flex w-full items-center gap-3 rounded-lg px-2.5 py-2 text-sm transition-colors",
            !isMobile && "justify-center lg:justify-start",
            !isMobile && collapsed && "lg:justify-center",
          );
          if (item.href) {
            return (
              <li key={item.id}>
                <Link
                  href={item.href}
                  onClick={onNavigate}
                  aria-current={active ? "page" : undefined}
                  title={item.label}
                  className={cn(
                    base,
                    "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
                    active ? "bg-white/[0.06] text-foreground" : "text-muted-foreground hover:bg-white/[0.04] hover:text-foreground",
                  )}
                >
                  {active && (
                    <span aria-hidden className="absolute inset-y-1.5 left-0 w-0.5 rounded-full bg-gradient-to-b from-cyan-brand to-violet-brand" />
                  )}
                  <Icon className={cn("h-[18px] w-[18px] shrink-0", active && "text-cyan-brand")} aria-hidden />
                  <span className={showLabels}>{item.label}</span>
                </Link>
              </li>
            );
          }
          // Not yet available: rendered as a disabled control, never a dead link.
          return (
            <li key={item.id}>
              <button
                type="button"
                disabled
                aria-disabled="true"
                title={`${item.label} — coming in ${item.availableIn}`}
                className={cn(base, "cursor-not-allowed text-muted-foreground/50")}
              >
                <Icon className="h-[18px] w-[18px] shrink-0" aria-hidden />
                <span className={cn("flex-1 text-left", showLabels)}>{item.label}</span>
                <span
                  className={cn(
                    "rounded border border-white/10 px-1.5 py-px text-[10px] uppercase tracking-wider text-muted-foreground/60",
                    showLabels,
                  )}
                >
                  Soon
                </span>
              </button>
            </li>
          );
        })}
      </ul>

      <div className="mt-auto flex flex-col gap-2 border-t border-border pt-3">
        <div
          className={cn(
            "flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs text-muted-foreground",
            !isMobile && "justify-center lg:justify-start",
            !isMobile && collapsed && "lg:justify-center",
          )}
          title={`Backend: ${connectionLabel(connectionStatus)}`}
        >
          <StatusIndicator status={connectionStatus} compact />
          <span className={showLabels}>Backend {connectionLabel(connectionStatus).toLowerCase()}</span>
        </div>
        {!isMobile && onToggleCollapse && (
          <button
            type="button"
            onClick={onToggleCollapse}
            aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
            aria-expanded={!collapsed}
            className={cn(
              "hidden items-center gap-3 rounded-lg px-2.5 py-2 text-xs text-muted-foreground transition hover:bg-white/[0.04] hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring lg:flex",
              collapsed && "justify-center",
            )}
          >
            {collapsed ? <ChevronsRight className="h-4 w-4" /> : <ChevronsLeft className="h-4 w-4" />}
            <span className={collapsed ? "sr-only" : undefined}>Collapse</span>
          </button>
        )}
        <p className={cn("px-2.5 text-[10px] text-muted-foreground/50", showLabels)}>{PRODUCT_NAME} · Phase 1</p>
      </div>
    </nav>
  );
}
