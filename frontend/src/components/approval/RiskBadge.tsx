import { ShieldAlert, ShieldCheck, ShieldX, Shield } from "lucide-react";

import { cn } from "@/lib/utils";

import type { RiskLevel } from "@/types/approval";

const RISK_STYLE: Record<RiskLevel, { className: string; icon: typeof Shield; description: string }> = {
  LOW: { className: "border-level-success/40 bg-level-success/10 text-level-success", icon: ShieldCheck, description: "Low risk" },
  MEDIUM: { className: "border-level-info/40 bg-level-info/10 text-level-info", icon: Shield, description: "Medium risk" },
  HIGH: { className: "border-level-warning/40 bg-level-warning/10 text-level-warning", icon: ShieldAlert, description: "High risk" },
  CRITICAL: { className: "border-level-error/50 bg-level-error/15 text-level-error", icon: ShieldX, description: "Critical risk" },
};

export function RiskBadge({ level, className }: { level: RiskLevel; className?: string }) {
  const style = RISK_STYLE[level];
  const Icon = style.icon;
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wider", style.className, className)}
      aria-label={`Risk level: ${style.description}`}
      data-testid="risk-badge"
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {level}
    </span>
  );
}
