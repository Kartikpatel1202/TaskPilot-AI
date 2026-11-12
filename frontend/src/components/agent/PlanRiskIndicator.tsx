import { RiskBadge } from "@/components/approval/RiskBadge";

import type { RiskLevel } from "@/types/approval";
import type { PlannedAction } from "@/types/plan";

const ORDER: Record<RiskLevel, number> = { LOW: 0, MEDIUM: 1, HIGH: 2, CRITICAL: 3 };

export function overallRisk(steps: PlannedAction[]): RiskLevel {
  return steps.reduce<RiskLevel>((max, step) => (ORDER[step.risk_level] > ORDER[max] ? step.risk_level : max), "LOW");
}

const DESCRIPTION: Record<RiskLevel, string> = {
  LOW: "Read-only or search actions.",
  MEDIUM: "Changes reversible state, such as a cart.",
  HIGH: "Sends, submits or creates something — needs your approval.",
  CRITICAL: "Can spend money or delete data — needs your approval.",
};

export function PlanRiskIndicator({ steps }: { steps: PlannedAction[] }) {
  const level = overallRisk(steps);
  return (
    <span className="inline-flex flex-wrap items-center gap-2" data-testid="plan-risk">
      <RiskBadge level={level} />
      <span className="text-xs text-muted-foreground">{DESCRIPTION[level]}</span>
    </span>
  );
}
