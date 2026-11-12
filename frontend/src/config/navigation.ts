import { Activity, Globe, LayoutDashboard, ListChecks, Settings, type LucideIcon } from "lucide-react";

export interface NavItem {
  id: string;
  label: string;
  icon: LucideIcon;
  /** Only items with an href are navigable in Phase 1. */
  href?: string;
  availableIn?: string;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "overview", label: "Overview", icon: LayoutDashboard, href: "/" },
  { id: "tasks", label: "Task History", icon: ListChecks, href: "/history" },
  { id: "sessions", label: "Browser Sessions", icon: Globe, href: "/sessions" },
  { id: "activity", label: "Activity Logs", icon: Activity, href: "/activity" },
  { id: "settings", label: "Settings", icon: Settings, href: "/settings" },
];
