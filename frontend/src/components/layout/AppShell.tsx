"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";

import { Sheet, SheetContent, SheetDescription, SheetTitle } from "@/components/ui/sheet";
import { SIDEBAR_STORAGE_KEY } from "@/lib/constants";
import { cn, safeStorageGet, safeStorageSet } from "@/lib/utils";

import { Sidebar } from "./Sidebar";
import { TopNavbar } from "./TopNavbar";

export function AppShell({ children }: { children: ReactNode }) {
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    setCollapsed(safeStorageGet("local", SIDEBAR_STORAGE_KEY) === "true");
  }, []);

  const toggleCollapsed = useCallback(() => {
    setCollapsed((prev) => {
      safeStorageSet("local", SIDEBAR_STORAGE_KEY, String(!prev));
      return !prev;
    });
  }, []);

  return (
    <div className="flex min-h-dvh">
      <a
        href="#main"
        className="sr-only z-50 rounded bg-surface px-3 py-2 focus:not-sr-only focus:fixed focus:left-3 focus:top-3"
      >
        Skip to content
      </a>

      {/* Desktop / tablet rail */}
      <aside
        className={cn(
          "sticky top-0 hidden h-dvh shrink-0 border-r border-border bg-surface-sunken/60 backdrop-blur-xl transition-[width] duration-200 md:block",
          collapsed ? "w-[68px]" : "w-[68px] lg:w-60",
        )}
      >
        <Sidebar collapsed={collapsed} onToggleCollapse={toggleCollapsed} />
      </aside>

      {/* Mobile drawer */}
      <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
        <SheetContent>
          <SheetTitle className="sr-only">Navigation</SheetTitle>
          <SheetDescription className="sr-only">TaskPilot AI sections</SheetDescription>
          <Sidebar variant="mobile" onNavigate={() => setMobileOpen(false)} />
        </SheetContent>
      </Sheet>

      <div className="flex min-w-0 flex-1 flex-col">
        <TopNavbar onOpenMenu={() => setMobileOpen(true)} />
        <main id="main" className="mx-auto w-full max-w-[1440px] flex-1 px-4 py-6 sm:px-6 lg:px-8">
          {children}
        </main>
      </div>
    </div>
  );
}
