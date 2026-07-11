/** Chat transcript (§11.7): user bubbles right on accent tint, assistant left
 * on surface-1 with markdown, inline tool-call blocks, danger error panels. */

import { ChevronDown, ChevronRight, Loader2, MessageSquare, Wrench } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { cn } from "@/lib/utils";
import { Markdown } from "./Markdown";

export type ChatItem =
  | { role: "user" | "assistant" | "error"; text: string }
  | {
      role: "tool";
      name: string;
      args?: unknown;
      result?: string;
      durationMs?: number;
      done: boolean;
    };

/** Inline tool call: collapsed row expanding to mono args/result previews.
 * Shared with the Timeline's per-node tool listing. */
export function ToolCallBlock({ item }: { item: Extract<ChatItem, { role: "tool" }> }) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <div className="max-w-[92%] rounded-lg border border-border bg-surface-1">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-left",
          "hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        )}
      >
        <Wrench className="h-3.5 w-3.5 shrink-0 text-port-toolset" strokeWidth={1.75} />
        <span className="truncate font-mono text-xs text-text-1">{item.name}</span>
        {!item.done && (
          <Loader2
            className="h-3 w-3 shrink-0 motion-safe:animate-spin text-text-3"
            strokeWidth={1.75}
            aria-label="tool running"
          />
        )}
        {item.durationMs != null && (
          <span className="font-mono text-[11px] tabular-nums text-text-3">
            {item.durationMs}ms
          </span>
        )}
        <Chevron className="ml-auto h-3.5 w-3.5 shrink-0 text-text-3" strokeWidth={1.75} />
      </button>
      {open && (
        <div className="space-y-1.5 border-t border-border px-2.5 py-1.5">
          <div>
            <p className="text-[11px] uppercase tracking-wider text-text-3">args</p>
            <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-surface-2 p-1.5 font-mono text-[11px] leading-relaxed text-text-2">
              {JSON.stringify(item.args ?? {}, null, 2)}
            </pre>
          </div>
          {item.result !== undefined && (
            <div>
              <p className="text-[11px] uppercase tracking-wider text-text-3">result</p>
              <pre className="max-h-32 overflow-auto whitespace-pre-wrap rounded bg-surface-2 p-1.5 font-mono text-[11px] leading-relaxed text-text-2">
                {item.result}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

export function ChatPane({ items, busy }: { items: ChatItem[]; busy: boolean }) {
  const bottom = useRef<HTMLDivElement>(null);
  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [items]);

  if (items.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-1.5 px-6 py-10 text-center">
        <MessageSquare className="h-6 w-6 text-text-3" strokeWidth={1.75} />
        <p className="text-[13px] text-text-2">Test your flow</p>
        <p className="text-xs text-text-3">
          Messages run the draft spec — switch on debug to step node by node.
        </p>
      </div>
    );
  }

  return (
    <div className="flex-1 space-y-2 overflow-y-auto px-3 py-2" aria-live="polite">
      {items.map((item, index) => {
        if (item.role === "tool") return <ToolCallBlock key={index} item={item} />;
        if (item.role === "user") {
          return (
            <div
              key={index}
              className="ml-auto max-w-[92%] whitespace-pre-wrap rounded-lg bg-accent/15 px-3 py-1.5 text-[13px] leading-[1.45] text-text-1"
            >
              {item.text}
            </div>
          );
        }
        if (item.role === "error") {
          return (
            <div
              key={index}
              className="max-w-[92%] rounded-lg border-l-2 border-danger bg-danger/10 px-3 py-1.5 text-[13px] leading-[1.45] text-danger"
            >
              {item.text}
            </div>
          );
        }
        return (
          <div
            key={index}
            className="max-w-[92%] rounded-lg border border-border bg-surface-1 px-3 py-1.5"
          >
            <Markdown text={item.text} />
          </div>
        );
      })}
      {busy && items[items.length - 1]?.role === "user" && (
        <div className="flex max-w-[92%] items-center gap-2 rounded-lg border border-border bg-surface-1 px-3 py-2">
          <span className="h-2 w-16 animate-pulse rounded bg-surface-2" />
          <span className="h-2 w-8 animate-pulse rounded bg-surface-2" />
        </div>
      )}
      <div ref={bottom} />
    </div>
  );
}
