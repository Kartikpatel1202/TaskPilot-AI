"use client";

import { AuthGate } from "@/components/auth/AuthGate";
import { PreferencesProvider } from "@/components/settings/PreferencesProvider";
import { ErrorBoundary } from "@/components/system/ErrorBoundary";
import { TaskPilotProvider } from "@/context/TaskPilotContext";

export function Providers({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary label="TaskPilot">
      <AuthGate>
        <PreferencesProvider>
          <TaskPilotProvider>{children}</TaskPilotProvider>
        </PreferencesProvider>
      </AuthGate>
    </ErrorBoundary>
  );
}
