import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium leading-4 tracking-wide transition-colors",
  {
    variants: {
      variant: {
        default: "border-cyan-brand/30 bg-cyan-brand/10 text-cyan-brand",
        secondary: "border-border bg-white/5 text-muted-foreground",
        violet: "border-violet-brand/30 bg-violet-brand/10 text-violet-brand",
        success: "border-level-success/30 bg-level-success/10 text-level-success",
        warning: "border-level-warning/30 bg-level-warning/10 text-level-warning",
        destructive: "border-level-error/30 bg-level-error/10 text-level-error",
        outline: "border-border text-foreground",
      },
    },
    defaultVariants: { variant: "default" },
  },
);

export interface BadgeProps extends React.HTMLAttributes<HTMLSpanElement>, VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
