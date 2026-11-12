"use client";

import { ActivityLog } from "@/components/activity/ActivityLog";
import { AppShell } from "@/components/layout/AppShell";
import { ErrorBoundary } from "@/components/system/ErrorBoundary";

export default function ActivityPage() {
  return (
    <AppShell>
      <ErrorBoundary label="Activity logs" inline>
        <ActivityLog />
      </ErrorBoundary>
    </AppShell>
  );
}
