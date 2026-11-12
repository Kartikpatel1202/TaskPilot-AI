"use client";

import { AppShell } from "@/components/layout/AppShell";
import { TaskHistory } from "@/components/history/TaskHistory";
import { SystemStatus } from "@/components/system/SystemStatus";
import { ErrorBoundary } from "@/components/system/ErrorBoundary";
import { useTaskPilotState } from "@/hooks/useTaskPilot";

export default function HistoryPage() {
  const { sessionId } = useTaskPilotState();
  return (
    <AppShell>
      <div className="grid gap-6 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <ErrorBoundary label="Task history" inline>
            <TaskHistory sessionId={sessionId} />
          </ErrorBoundary>
        </div>
        <ErrorBoundary label="System status" inline>
          <SystemStatus />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
