"use client";

import { Bot } from "lucide-react";

import { useTaskPilotState } from "@/hooks/useTaskPilot";
import { ASSISTANT_NAME } from "@/lib/persona";

export function WelcomeHeader() {
  const { serverInfo, connectionStatus } = useTaskPilotState();
  const name = serverInfo?.assistant_name ?? ASSISTANT_NAME;
  const ready = connectionStatus === "CONNECTED";

  return (
    <div className="flex flex-col gap-1">
      <h1 className="text-2xl font-semibold tracking-tight sm:text-[28px]">Welcome back</h1>
      <p className="flex flex-wrap items-center gap-x-1.5 text-sm text-muted-foreground">
        Your AI-powered workspace is {ready ? "ready" : "warming up"}.
        <span className="inline-flex items-center gap-1 text-foreground/80">
          <Bot className="h-3.5 w-3.5 text-violet-brand" aria-hidden />
          {name}
        </span>
        is your co-pilot and replies in whichever you use: English, Hindi or Hinglish.
      </p>
    </div>
  );
}
