import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

export type BadgeTone = "muted" | "violet" | "green" | "amber" | "sky" | "red";

const tones: Record<BadgeTone, string> = {
  muted: "bg-zinc-800/80 text-zinc-300 border-zinc-700/60",
  violet: "bg-violet-950/60 text-violet-300 border-violet-800/50",
  green: "bg-emerald-950/60 text-emerald-300 border-emerald-800/50",
  amber: "bg-amber-950/60 text-amber-300 border-amber-800/50",
  sky: "bg-sky-950/60 text-sky-300 border-sky-800/50",
  red: "bg-red-950/60 text-red-300 border-red-800/50",
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
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
