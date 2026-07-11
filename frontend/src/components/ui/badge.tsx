import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * Canonical tones (design brief): muted · accent · success · warning · danger,
 * plus "toolset" (port-family sky) for MCP/toolset chrome.
 */
export type BadgeTone = "muted" | "accent" | "success" | "warning" | "danger" | "toolset";

const tones: Record<BadgeTone, string> = {
  muted: "border-border bg-surface-2/80 text-text-2",
  accent: "border-accent/30 bg-accent/10 text-accent",
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  danger: "border-danger/30 bg-danger/10 text-danger",
  toolset: "border-port-toolset/30 bg-port-toolset/10 text-port-toolset",
};

export function Badge({
  children,
  className,
  tone = "muted",
}: {
  children: ReactNode;
  className?: string;
  tone?: BadgeTone;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-[11px] font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
