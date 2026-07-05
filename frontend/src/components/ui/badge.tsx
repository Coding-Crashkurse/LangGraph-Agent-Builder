import type { ReactNode } from "react";

import { cn } from "@/lib/utils";
import type { RunState } from "@/api/types";

export function Badge({
  children,
  className,
  color = "zinc",
}: {
  children: ReactNode;
  className?: string;
  color?: "zinc" | "violet" | "emerald" | "amber" | "sky" | "red" | "blue";
}) {
  const colors: Record<string, string> = {
    zinc: "bg-zinc-800/80 text-zinc-300 border-zinc-700/60",
    violet: "bg-violet-950/60 text-violet-300 border-violet-800/50",
    emerald: "bg-emerald-950/60 text-emerald-300 border-emerald-800/50",
    amber: "bg-amber-950/60 text-amber-300 border-amber-800/50",
    sky: "bg-sky-950/60 text-sky-300 border-sky-800/50",
    blue: "bg-blue-950/60 text-blue-300 border-blue-800/50",
    red: "bg-red-950/60 text-red-300 border-red-800/50",
  };
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        colors[color],
        className,
      )}
    >
      {children}
    </span>
  );
}

const stateColors: Record<RunState, Parameters<typeof Badge>[0]["color"]> = {
  submitted: "zinc",
  working: "blue",
  "input-required": "amber",
  completed: "emerald",
  failed: "red",
  canceled: "zinc",
  rejected: "red",
  unknown: "zinc",
};

export function StateChip({ state }: { state: RunState }) {
  return (
    <Badge color={stateColors[state] ?? "zinc"}>
      {state === "working" ? (
        <span className="relative flex h-1.5 w-1.5">
          <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-blue-400 opacity-60" />
          <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-blue-400" />
        </span>
      ) : null}
      {state}
    </Badge>
  );
}

export function CategoryDot({ category }: { category: string }) {
  return (
    <span
      className="inline-block h-2 w-2 shrink-0 rounded-sm"
      style={{ background: `var(--color-cat-${category}, #71717a)` }}
    />
  );
}
