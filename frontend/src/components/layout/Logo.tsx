import { useId } from "react";

import { cn } from "@/lib/utils";

/** TaskPilot mark: a stylised pilot "compass" made of two chevrons. */
export function LogoMark({ className }: { className?: string }) {
  // Unique per instance: a shared id breaks when the first instance is display:none.
  const gradientId = `tp-grad-${useId().replace(/:/g, "")}`;
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={cn("h-8 w-8", className)}>
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="hsl(187 92% 55%)" />
          <stop offset="100%" stopColor="hsl(262 83% 70%)" />
        </linearGradient>
      </defs>
      <rect x="1" y="1" width="30" height="30" rx="9" fill="hsl(225 35% 9%)" stroke={`url(#${gradientId})`} strokeOpacity="0.55" />
      <path d="M9 19.5 16 8l7 11.5-7-3.2-7 3.2Z" fill={`url(#${gradientId})`} />
      <path d="M12 23.5 16 21.6l4 1.9" stroke={`url(#${gradientId})`} strokeWidth="1.6" strokeLinecap="round" fill="none" />
    </svg>
  );
}
