import {
  CircleStop,
  Compass,
  Keyboard,
  MousePointerClick,
  ScanSearch,
  ShieldCheck,
  CalendarPlus,
  Download,
  MailPlus,
  PlayCircle,
  ShoppingBag,
  Youtube,
  type LucideIcon,
} from "lucide-react";
import { memo } from "react";

import { RiskBadge } from "@/components/approval/RiskBadge";
import { cn } from "@/lib/utils";

import type { CommerceAction } from "@/types/commerce";
import type { ActionType, PlannedAction, SupportedAction } from "@/types/plan";

const ACTION_META: Record<ActionType, { icon: LucideIcon; label: string }> = {
  navigate: { icon: Compass, label: "Navigate" },
  click: { icon: MousePointerClick, label: "Click" },
  type: { icon: Keyboard, label: "Type" },
  extract: { icon: ScanSearch, label: "Read" },
  request_approval: { icon: ShieldCheck, label: "Approval" },
  stop: { icon: CircleStop, label: "Stop" },
  commerce: { icon: ShoppingBag, label: "Shop" },
  youtube_search: { icon: Youtube, label: "YouTube" },
  youtube_play: { icon: PlayCircle, label: "Play" },
  gmail_create_draft: { icon: MailPlus, label: "Draft" },
  calendar_create_event: { icon: CalendarPlus, label: "Event" },
  file_download: { icon: Download, label: "Download" },
};

const COMMERCE_OP: Record<CommerceAction["operation"], string> = {
  open_store: "Open store",
  search_products: "Search & compare",
  search_and_add: "Find & add",
  verify_cart: "Verify cart",
  checkout_review: "Review checkout",
  place_order: "Final approval",
};

function actionDetail(action: SupportedAction): string | null {
  switch (action.type) {
    case "navigate":
      return action.url;
    case "click":
      return action.target_description;
    case "type":
      return action.sensitive ? `${action.target_description}: [hidden]` : `"${action.text}" → ${action.target_description}`;
    case "extract":
      return `${action.target_description}: ${action.fields.join(", ")}`;
    case "request_approval":
      return action.reason;
    case "stop":
      return action.reason;
    case "commerce": {
      const req = action.requirement;
      const what = req ? `${req.query}${req.quantity && req.unit !== "UNKNOWN" ? ` · ${req.quantity} ${req.unit.toLowerCase()}` : ""}` : null;
      const pay = action.operation === "place_order" ? ` · ${action.payment_preference === "COD" ? "cash on delivery" : "you pay"}` : "";
      return `${COMMERCE_OP[action.operation]}${what ? `: ${what}` : ""}${pay}`;
    }
    case "youtube_search":
      return `“${action.query}”${action.select ? " · pick one video" : ""}`;
    case "youtube_play":
      return action.video_reference === "selected_from_search" ? "The video chosen in the previous step" : action.video_reference;
    case "gmail_create_draft":
      return `To ${action.recipient_emails.join(", ")} · “${action.subject}” · draft only, never sent`;
    case "calendar_create_event":
      return `“${action.title}” · ${new Date(action.start_at).toLocaleString()} (${action.timezone}) · needs your approval`;
    case "file_download":
      return `${action.file_description} · ${action.source_url}`;
    default:
      return null;
  }
}

/** One planned (never executed) step. There is deliberately no "done" state here. */
export const PlanStep = memo(function PlanStep({ step }: { step: PlannedAction }) {
  const meta = ACTION_META[step.action.type];
  const Icon = meta.icon;
  const isGate = step.action.type === "request_approval";
  const detail = actionDetail(step.action);

  return (
    <li
      className={cn(
        "relative flex gap-3 rounded-lg border px-3 py-2.5",
        isGate ? "border-level-warning/30 bg-level-warning/[0.05]" : "border-white/[0.06] bg-white/[0.015]",
      )}
      data-testid="plan-step"
      data-action={step.action.type}
      data-status="planned"
    >
      <span className="mt-0.5 font-mono text-xs tabular-nums text-muted-foreground" aria-label={`Step ${step.order}`}>
        {String(step.order).padStart(2, "0")}
      </span>
      <span
        className={cn(
          "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-md border",
          isGate ? "border-level-warning/40 text-level-warning" : "border-white/10 text-cyan-brand",
        )}
        title={meta.label}
      >
        <Icon className="h-3.5 w-3.5" aria-hidden />
      </span>
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
          <p className="text-sm text-foreground">{step.description}</p>
          {step.requires_approval && (
            <span className="inline-flex items-center gap-1 rounded border border-level-warning/40 px-1.5 text-[10px] font-semibold uppercase tracking-wider text-level-warning">
              <ShieldCheck className="h-3 w-3" aria-hidden />
              {isGate ? "Approval checkpoint" : "Requires approval"}
            </span>
          )}
        </div>
        {detail && <p className="mt-0.5 break-words font-mono text-[11px] text-muted-foreground">{detail}</p>}
        <p className="mt-0.5 text-xs text-muted-foreground/80">
          <span className="text-muted-foreground">Expected:</span> {step.expected_outcome}
        </p>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        {step.risk_level !== "LOW" && <RiskBadge level={step.risk_level} />}
        <span className="text-[10px] uppercase tracking-wider text-muted-foreground/60">Planned</span>
      </div>
    </li>
  );
});
