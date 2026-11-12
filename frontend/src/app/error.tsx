"use client";

import { AlertTriangle } from "lucide-react";

import { Button } from "@/components/ui/button";

/** Route-level error boundary (Next.js). Never shows stack traces or internal details. */
export default function RouteError({ reset }: { error: Error; reset: () => void }) {
  return (
    <main role="alert" className="flex min-h-screen flex-col items-center justify-center gap-3 p-6 text-sm">
      <p className="flex items-center gap-2 text-level-error"><AlertTriangle className="h-4 w-4" aria-hidden /> Something went wrong on this page.</p>
      <p className="text-muted-foreground">Nothing was lost — tasks and approvals are stored on the server.</p>
      <Button onClick={reset}>Reload</Button>
    </main>
  );
}
