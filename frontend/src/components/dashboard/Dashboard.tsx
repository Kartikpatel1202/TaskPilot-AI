"use client";

import { useState } from "react";

import { AgentPanel } from "@/components/agent/AgentPanel";
import { ShoppingPanel } from "@/components/commerce/ShoppingPanel";
import { IntegrationPanel, planUsesIntegrations } from "@/components/integrations/IntegrationPanel";
import { ErrorBoundary } from "@/components/system/ErrorBoundary";
import { ApprovalDialog } from "@/components/approval/ApprovalDialog";
import { BrowserPreview } from "@/components/browser/BrowserPreview";
import { ExecutionLogs } from "@/components/logs/ExecutionLogs";
import { useBrowserStream } from "@/hooks/useBrowserStream";
import { useTaskPilotActions, useTaskPilotState, useTaskPilotUi } from "@/hooks/useTaskPilot";

import { CommandCenter } from "./CommandCenter";
import { QuickActionCards } from "./QuickActionCards";
import { TaskStatusCard } from "./TaskStatusCard";
import { WelcomeHeader } from "./WelcomeHeader";

export function Dashboard() {
  const {
    activeTask,
    tasks,
    logs,
    activeApproval,
    browserPreview,
    connectionStatus,
    taskHistory,
    activePlan,
    sessionId,
    browser,
    browserStatus,
    execution,
    agentInfo,
    commerce,
    integrations,
  } = useTaskPilotState();
  const {
    decideApproval,
    dismissApproval,
    clearLogs,
    runDemoTelemetry,
    runDemoApproval,
    closeBrowser,
    dismissBrowserNotice,
    chooseProduct,
    refreshCart,
    changeCartQuantity,
  } = useTaskPilotActions();
  const [cartBusy, setCartBusy] = useState(false);
  const withBusy = (work: () => Promise<unknown>) => {
    setCartBusy(true);
    void work().finally(() => setCartBusy(false));
  };
  const { demoAvailable, executionAvailable } = useTaskPilotUi();
  // Live Chromium frames (binary stream socket, separate from telemetry).
  const stream = useBrowserStream({ sessionId, enabled: connectionStatus === "CONNECTED" && executionAvailable });
  const executing = execution !== null && ["QUEUED", "EXECUTING", "WAITING_APPROVAL"].includes(execution.status);
  // The user may close a pending approval to review later; it never auto-resolves.
  const [hiddenApprovalId, setHiddenApprovalId] = useState<string | null>(null);

  const dialogOpen = activeApproval !== null && hiddenApprovalId !== activeApproval.approval_id;
  const planReady = activePlan?.status === "READY" && activePlan.steps.length > 0;

  const handleOpenChange = (open: boolean) => {
    if (open || !activeApproval) return;
    if (activeApproval.status === "PENDING") setHiddenApprovalId(activeApproval.approval_id);
    else dismissApproval(activeApproval.approval_id);
  };

  return (
    <div className="flex flex-col gap-6">
      <WelcomeHeader />
      <CommandCenter />

      <div className="grid gap-6 lg:grid-cols-5">
        <AgentPanel className="lg:col-span-3" />
        <ExecutionLogs logs={logs} onClear={clearLogs} className="lg:col-span-2" />
      </div>

      {commerce?.summary && commerce.taskId === activeTask?.task_id && (
        <ShoppingPanel
          summary={commerce.summary}
          busy={cartBusy}
          allowCartEdits={!executing}
          onChooseProduct={chooseProduct}
          onRefreshCart={() => withBusy(refreshCart)}
          onChangeQuantity={(itemId, quantity) => withBusy(() => changeCartQuantity(itemId, quantity))}
        />
      )}

      {activePlan && activePlan.task_id === activeTask?.task_id && planUsesIntegrations(activePlan) && (
        <ErrorBoundary label="Integrations panel" inline>
          <IntegrationPanel
            key={activePlan.task_id}
            sessionId={sessionId}
            plan={activePlan}
            integrations={integrations}
            connected={connectionStatus === "CONNECTED"}
          />
        </ErrorBoundary>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <BrowserPreview
          preview={browserPreview}
          browser={browser}
          sessionId={sessionId}
          frame={stream.frame}
          streamStatus={stream.status}
          droppedFrames={stream.droppedFrames}
          planReady={planReady}
          executing={executing}
          executionAvailable={agentInfo === null || executionAvailable}
          unavailableMessage={browserStatus?.message ?? "Real browser execution is disabled on this server."}
          onReconnect={stream.reconnect}
          onClose={closeBrowser}
          onDismissNotice={dismissBrowserNotice}
          className="lg:col-span-3"
        />
        <TaskStatusCard
          task={activeTask}
          visitedStates={activeTask ? taskHistory[activeTask.task_id] : undefined}
          plan={activePlan}
          pendingApproval={activeApproval}
          onReviewApproval={() => setHiddenApprovalId(null)}
          className="lg:col-span-2"
        />
      </div>

      <QuickActionCards
        tasks={tasks}
        demoAvailable={demoAvailable}
        connected={connectionStatus === "CONNECTED"}
        onRunDemoTelemetry={runDemoTelemetry}
        onRunDemoApproval={runDemoApproval}
      />

      {activeApproval && (
        <ApprovalDialog
          key={activeApproval.approval_id}
          approval={activeApproval}
          open={dialogOpen}
          onOpenChange={handleOpenChange}
          onDecide={decideApproval}
        />
      )}
    </div>
  );
}
