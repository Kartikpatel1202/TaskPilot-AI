import { Clock } from "lucide-react";

import { cn, formatRelativeSeconds, shortId } from "@/lib/utils";

import { RiskBadge } from "./RiskBadge";

import type { ApprovalRequest } from "@/types/approval";

interface ApprovalSummaryProps {
  approval: ApprovalRequest;
  secondsRemaining: number | null;
}

function Row({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("grid grid-cols-[110px_1fr] gap-3 py-2 sm:grid-cols-[130px_1fr]", className)}>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="min-w-0 break-words text-sm text-foreground">{children}</dd>
    </div>
  );
}

export function ApprovalSummary({ approval, secondsRemaining }: ApprovalSummaryProps) {
  const expired = approval.status === "EXPIRED" || (secondsRemaining !== null && secondsRemaining <= 0);
  return (
    <dl className="divide-y divide-white/[0.06] rounded-lg border border-white/[0.08] bg-black/20 px-3">
      <Row label="Requested action">
        <span className="font-medium">{approval.action_summary}</span>
      </Row>
      <Row label="Website">
        <span className="font-mono text-[13px]">{approval.domain}</span>
      </Row>
      <Row label="Risk">
        <RiskBadge level={approval.risk_level} />
      </Row>
      <Row label="Why approval">{approval.reason}</Row>
      {approval.estimated_impact && <Row label="Expected impact">{approval.estimated_impact}</Row>}
      <Row label="Task">
        <span className="font-mono text-xs text-muted-foreground" title={approval.task_id}>
          #{shortId(approval.task_id)}
        </span>
      </Row>
      <Row label="Expires">
        <span className={cn("inline-flex items-center gap-1.5 text-xs", expired ? "text-level-error" : "text-muted-foreground")}>
          <Clock className="h-3.5 w-3.5" aria-hidden />
          {expired
            ? "Expired"
            : secondsRemaining !== null
              ? `in ${formatRelativeSeconds(secondsRemaining)}`
              : new Date(approval.expires_at).toLocaleTimeString()}
        </span>
      </Row>
    </dl>
  );
}
