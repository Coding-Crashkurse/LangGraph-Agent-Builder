/** Session (thread) picker (§11.7): dropdown of previous conversations with
 * per-session delete. Rename needs a backend endpoint the threads API does not
 * expose yet — hidden until it exists. */

import { Check, ChevronDown, History, Plus, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { ThreadInfo } from "@/api/types";
import { cn } from "@/lib/utils";
import { formatTime, shortId } from "./format";

export function SessionPicker({
  threads,
  value,
  onChange,
  onDelete,
}: {
  threads: ThreadInfo[];
  value: string | null;
  onChange: (threadId: string | null) => void;
  onDelete: (threadId: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!container.current?.contains(event.target as Node)) setOpen(false);
    };
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current = threads.find((thread) => thread.thread_id === value);

  return (
    <div ref={container} className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Session"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex h-7 w-36 items-center gap-1.5 rounded-lg border border-border bg-surface-1 px-2",
          "text-xs text-text-2 hover:border-border-strong hover:text-text-1",
          "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        )}
      >
        <History className="h-3.5 w-3.5 shrink-0 text-text-3" strokeWidth={1.75} />
        <span className={cn("truncate", current && "font-mono")}>
          {current ? shortId(current.thread_id, 10) : "new session"}
        </span>
        <ChevronDown className="ml-auto h-3.5 w-3.5 shrink-0 text-text-3" strokeWidth={1.75} />
      </button>

      {open && (
        <div
          role="listbox"
          aria-label="Sessions"
          className="absolute right-0 top-full z-30 mt-1 w-64 rounded-[10px] border border-border bg-surface-1 p-1 shadow-xl shadow-black/50"
        >
          <button
            type="button"
            role="option"
            aria-selected={value === null}
            onClick={() => {
              onChange(null);
              setOpen(false);
            }}
            className={cn(
              "flex w-full items-center gap-1.5 rounded-md px-2 py-1.5 text-left text-xs",
              "hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
              value === null ? "text-text-1" : "text-text-2",
            )}
          >
            <Plus className="h-3.5 w-3.5 shrink-0 text-text-3" strokeWidth={1.75} />
            New session
            {value === null && (
              <Check className="ml-auto h-3.5 w-3.5 shrink-0 text-accent" strokeWidth={1.75} />
            )}
          </button>

          {threads.length > 0 && <div className="mx-1 my-1 border-t border-border" />}

          <div className="max-h-56 overflow-y-auto">
            {threads.map((thread) => {
              const selected = thread.thread_id === value;
              return (
                <div
                  key={thread.thread_id}
                  className={cn(
                    "group flex items-center gap-1 rounded-md",
                    selected && "bg-accent/15",
                  )}
                >
                  <button
                    type="button"
                    role="option"
                    aria-selected={selected}
                    onClick={() => {
                      onChange(thread.thread_id);
                      setOpen(false);
                    }}
                    className={cn(
                      "flex min-w-0 flex-1 items-center gap-2 rounded-md px-2 py-1.5 text-left",
                      "hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
                    )}
                  >
                    <span className="truncate font-mono text-xs text-text-1">
                      {shortId(thread.thread_id, 10)}
                    </span>
                    <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-text-3">
                      {thread.runs} run{thread.runs === 1 ? "" : "s"} ·{" "}
                      {formatTime(thread.last_run_at)}
                    </span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Delete session ${shortId(thread.thread_id, 10)}`}
                    onClick={() => onDelete(thread.thread_id)}
                    className={cn(
                      "mr-1 shrink-0 rounded p-1 text-text-3 opacity-0 transition-opacity",
                      "hover:bg-danger/15 hover:text-danger",
                      "focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
                      "group-hover:opacity-100",
                    )}
                  >
                    <Trash2 className="h-3.5 w-3.5" strokeWidth={1.75} />
                  </button>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
