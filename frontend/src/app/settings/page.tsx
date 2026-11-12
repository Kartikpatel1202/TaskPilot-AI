"use client";

import { AppShell } from "@/components/layout/AppShell";
import { SettingsForm } from "@/components/settings/SettingsForm";
import { ErrorBoundary } from "@/components/system/ErrorBoundary";

export default function SettingsPage() {
  return (
    <AppShell>
      <div className="mx-auto w-full max-w-3xl">
        <ErrorBoundary label="Settings" inline>
          <SettingsForm />
        </ErrorBoundary>
      </div>
    </AppShell>
  );
}
