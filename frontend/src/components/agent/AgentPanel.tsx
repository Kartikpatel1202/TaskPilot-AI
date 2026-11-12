"use client";

import { AlertTriangle, BrainCircuit, RotateCw, Sparkles } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { ExecutionControls } from "@/components/execution/ExecutionControls";
import { ExecutionSummary } from "@/components/execution/ExecutionSummary";
import { useTaskPilotActions, useTaskPilotState, useTaskPilotUi } from "@/hooks/useTaskPilot";
import { ASSISTANT_NAME } from "@/lib/persona";
import { cn } from "@/lib/utils";

import { AgentStatus } from "./AgentStatus";
import { AgentThinkingIndicator } from "./AgentThinkingIndicator";
import { ClarificationPanel } from "./ClarificationPanel";
import { PlanPreview } from "./PlanPreview";

/** Kamlesh Bhai's workspace: picks the right view for the active task's planning state. */
export function AgentPanel({ className }: { className?: string }) {
  const state = useTaskPilotState();
  const { submitClarification, retryPlanFetch, runPlan, stopExecution, clearExecutionError } = useTaskPilotActions();
  const { executionAvailable } = useTaskPilotUi();
  const {
    activePlan,
    agentStatus,
    agentInfo,
    clarification,
    connectionStatus,
    isPlanning,
    isSubmittingClarification,
    planFetch,
    planningFailure,
    planningProgress,
    activeTask,
    execution,
    isStartingExecution,
    executionError,
  } = state;
  const connected = connectionStatus === "CONNECTED";

  let body: React.ReactNode;
  if (clarification) {
    body = (
      <ClarificationPanel
        clarification={clarification}
        isSubmitting={isSubmittingClarification}
        disabled={!connected}
        onSubmit={(message) => submitClarification(message, "TEXT")}
      />
    );
  } else if (isPlanning) {
    body = <AgentThinkingIndicator progress={planningProgress} />;
  } else if (planningFailure) {
    body = (
      <div role="alert" className="flex items-start gap-3 rounded-lg border border-level-error/30 bg-level-error/[0.06] p-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-level-error" aria-hidden />
        <div>
          <p className="text-sm font-medium text-level-error">Planning failed</p>
          <p className="text-xs text-muted-foreground">{planningFailure.message}</p>
          <p className="mt-1 font-mono text-[10px] text-muted-foreground/70">{planningFailure.code}</p>
        </div>
      </div>
    );
  } else if (planFetch?.status === "error") {
    body = (
      <div role="alert" className="flex items-center justify-between gap-3 rounded-lg border border-level-error/30 bg-level-error/[0.06] p-3">
        <p className="text-xs text-level-error">The plan is ready but could not be loaded: {planFetch.error}</p>
        <Button size="sm" variant="outline" onClick={retryPlanFetch}>
          <RotateCw aria-hidden /> Retry
        </Button>
      </div>
    );
  } else if (planFetch) {
    body = (
      <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading plan">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="h-14 w-full" />
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </div>
    );
  } else if (activePlan) {
    const run = execution?.taskId === activePlan.task_id ? execution : null;
    body = (
      <div className="flex flex-col gap-4">
        {run && <ExecutionSummary execution={run} />}
        <ExecutionControls
          plan={activePlan}
          task={activeTask}
          execution={run}
          executionAvailable={executionAvailable}
          connected={connected}
          isStarting={isStartingExecution}
          error={executionError}
          onRun={runPlan}
          onStop={stopExecution}
          onDismissError={clearExecutionError}
        />
        <PlanPreview plan={activePlan} execution={run} />
      </div>
    );
  } else {
    body = (
      <div className="flex flex-1 flex-col items-center justify-center gap-3 py-10 text-center" data-testid="agent-empty">
        <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-white/10 bg-gradient-to-br from-cyan-brand/10 to-violet-brand/10">
          <Sparkles className="h-5 w-5 text-violet-brand" aria-hidden />
        </div>
        <p className="max-w-sm text-sm text-foreground/90">
          {ASSISTANT_NAME} is ready. Send a command and you&apos;ll get a step-by-step action plan here.
        </p>
        <p className="max-w-sm text-xs text-muted-foreground">Nothing runs in a browser until you review the plan and click Run Plan.</p>
      </div>
    );
  }

  return (
    <Card className={cn("flex min-h-[340px] flex-col", className)} aria-labelledby="agent-panel-title">
      <CardHeader className="flex-wrap">
        <CardTitle id="agent-panel-title">
          <BrainCircuit className="h-3.5 w-3.5" aria-hidden /> Agent plan
        </CardTitle>
        <AgentStatus status={agentStatus} info={agentInfo} connected={connected} />
        {agentInfo?.setup_hint ? (
          <p role="note" data-testid="planner-setup-hint"
            className="rounded-md border border-level-warning/30 bg-level-warning/10 px-3 py-2 text-[11px] leading-relaxed text-level-warning">
            {agentInfo.setup_hint}
          </p>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-1 flex-col overflow-y-auto scrollbar-thin lg:max-h-[640px]">{body}</CardContent>
    </Card>
  );
}
