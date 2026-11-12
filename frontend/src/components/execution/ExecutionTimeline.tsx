import { memo } from "react";

import { ExecutionStep } from "./ExecutionStep";

import type { ActionExecutionStatus, ExecutionState } from "@/types/execution";
import type { TaskPlan } from "@/types/plan";

const TERMINAL = new Set(["COMPLETED", "FAILED", "CANCELLED"]);

/** The plan's steps, each with the status actually observed during execution. */
export const ExecutionTimeline = memo(function ExecutionTimeline({ plan, execution }: { plan: TaskPlan; execution: ExecutionState }) {
  const finished = TERMINAL.has(execution.status);
  return (
    <ol className="flex flex-col gap-2" aria-label="Execution progress" data-testid="execution-timeline">
      {plan.steps.map((step) => {
        const seen = execution.steps[step.step_id];
        // Steps the backend never reported are pending while running, and "not run" afterwards.
        const status: ActionExecutionStatus = seen?.status ?? (finished ? "SKIPPED" : "PENDING");
        return (
          <ExecutionStep
            key={step.step_id}
            order={step.order}
            description={step.description}
            actionType={step.action.type}
            status={status}
            message={seen?.message ?? null}
            errorCode={seen?.errorCode ?? null}
            durationMs={seen?.durationMs ?? null}
            verified={seen?.verified ?? false}
            extractedData={seen?.extractedData ?? null}
          />
        );
      })}
    </ol>
  );
});
