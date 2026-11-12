import {
  Ban,
  CalendarClock,
  Download,
  FileText,
  Globe,
  Mail,
  MessageCircle,
  PlayCircle,
  Receipt,
  Search,
  Send,
  ShoppingCart,
  Table2,
  Workflow,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/utils";

import type { IntentType } from "@/types/intent";

export const INTENT_META: Record<IntentType, { label: string; icon: LucideIcon }> = {
  GENERAL_CHAT: { label: "General chat", icon: MessageCircle },
  BROWSER_NAVIGATION: { label: "Browser navigation", icon: Globe },
  ECOMMERCE_SEARCH: { label: "E-commerce search", icon: Search },
  ECOMMERCE_SHOPPING: { label: "E-commerce shopping", icon: ShoppingCart },
  ECOMMERCE_CART_REVIEW: { label: "Cart review", icon: ShoppingCart },
  ECOMMERCE_CHECKOUT_REVIEW: { label: "Checkout review", icon: Receipt },
  ECOMMERCE_PURCHASE: { label: "Purchase", icon: Receipt },
  MEDIA_SEARCH: { label: "Media search", icon: PlayCircle },
  EMAIL_DRAFT: { label: "Email draft", icon: Mail },
  EMAIL_SEND: { label: "Email send", icon: Send },
  CALENDAR_MANAGEMENT: { label: "Calendar", icon: CalendarClock },
  FILE_DOWNLOAD: { label: "File download", icon: Download },
  YOUTUBE_SEARCH: { label: "YouTube search", icon: Search },
  YOUTUBE_PLAYBACK: { label: "YouTube playback", icon: PlayCircle },
  MULTI_DOMAIN_WORKFLOW: { label: "Multi-domain workflow", icon: Workflow },
  FORM_SUBMISSION: { label: "Form submission", icon: FileText },
  DATA_EXTRACTION: { label: "Data extraction", icon: Table2 },
  UNSUPPORTED: { label: "Unsupported", icon: Ban },
};

export function IntentBadge({ intent, className }: { intent: IntentType; className?: string }) {
  const meta = INTENT_META[intent];
  const Icon = meta.icon;
  return (
    <span
      data-testid="intent-badge"
      data-intent={intent}
      title={intent}
      aria-label={`Intent: ${meta.label}`}
      className={cn(
        "inline-flex items-center gap-1.5 whitespace-nowrap rounded-md border px-2 py-0.5 text-[11px] font-semibold tracking-wide",
        intent === "UNSUPPORTED"
          ? "border-level-error/30 bg-level-error/10 text-level-error"
          : "border-cyan-brand/30 bg-cyan-brand/10 text-cyan-brand",
        className,
      )}
    >
      <Icon className="h-3.5 w-3.5" aria-hidden />
      {meta.label}
    </span>
  );
}
