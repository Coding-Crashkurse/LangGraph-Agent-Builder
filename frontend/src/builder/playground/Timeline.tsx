/** Per-node run timeline (§11.6): one row per node execution with a status
 * chip, duration in tabular mono, and an expandable output preview. */

import { ChevronDown, ChevronRight, ListTree, X } from "lucide-react";
import { useMemo, useState } from "react";

import type { RunEvent } from "@/api/types";
import { cn } from "@/lib/utils";
import { type ChatItem, ToolCallBlock } from "./ChatPane";
import { OutputValue } from "./JsonTree";

type RowStatus = "running" | "ok" | "error" | "interrupted";

type ToolEntry = Extract<ChatItem, { role: "tool" }>;

export interface TimelineRow {
  nodeId: string;
  status: RowStatus;
  durationMs: number | null;
  notes: string[];
  outputs: Record<string, unknown> | null;
  error: string | null;
  tools: ToolEntry[];
}

/** Fold the event stream into one row per node execution (pure, testable). */
export function buildTimelineRows(events: RunEvent[]): TimelineRow[] {
  const rows: TimelineRow[] = [];
  const open = new Map<string, TimelineRow>(); // node_id → row still running

  const rowFor = (nodeId: string): TimelineRow => {
    const existing = open.get(nodeId) ?? (nodeId === "" ? [...rows].reverse().find((r) => r.status === "running") : undefined);
    if (existing) return existing;
    const row: TimelineRow = {
      nodeId,
      status: "running",
      durationMs: null,
      notes: [],
      outputs: null,
      error: null,
      tools: [],
    };
    rows.push(row);
    open.set(nodeId, row);
    return row;
  };

  for (const event of events) {
    const nodeId = String(event.data.node_id ?? "");
    switch (event.event) {
      case "node_started":
        open.delete(nodeId); // a repeat execution (loop) opens a fresh row
        rowFor(nodeId);
        break;
      case "node_finished": {
        const row = rowFor(nodeId);
        row.status = "ok";
        row.durationMs = Number(event.data.duration_ms ?? 0);
        const outputs = event.data.outputs_preview;
        if (outputs && typeof outputs === "object" && Object.keys(outputs).length > 0) {
          row.outputs = outputs as Record<string, unknown>;
        }
        open.delete(nodeId);
        break;
      }
      case "node_error": {
        const row = rowFor(nodeId);
        row.status = "error";
        row.error = `${String(event.data.code ?? "RT103")}: ${String(event.data.message ?? "")}`;
        open.delete(nodeId);
        break;
      }
      case "interrupt_raised": {
        const row = rowFor(nodeId);
        row.status = "interrupted";
        break;
      }
      case "node_status":
        rowFor(nodeId).notes.push(String(event.data.text ?? ""));
        break;
      case "tool_call":
        rowFor(nodeId).tools.push({
          role: "tool",
          name: String(event.data.tool_name ?? "tool"),
          args: event.data.args_preview,
          done: false,
        });
        break;
      case "tool_result": {
        const tools = rowFor(nodeId).tools;
        const pending = [...tools].reverse().find((tool) => !tool.done);
        if (pending) {
          pending.done = true;
          pending.result = String(event.data.result_preview ?? "");
          if (event.data.duration_ms != null) {
            pending.durationMs = Number(event.data.duration_ms);
          }
        }
        break;
      }
    }
  }
  return rows;
}

const CHIP_TONES: Record<RowStatus, string> = {
  running: "bg-accent/15 text-accent",
  ok: "bg-success/15 text-success",
  error: "bg-danger/15 text-danger",
  interrupted: "bg-warning/15 text-warning",
};

function TimelineRowView({ row }: { row: TimelineRow }) {
  const [open, setOpen] = useState(false);
  const expandable =
    row.outputs !== null || row.tools.length > 0 || row.notes.length > 0 || row.error !== null;
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div className="rounded-lg border border-border bg-surface-1/60">
      <button
        type="button"
        aria-expanded={expandable ? open : undefined}
        disabled={!expandable}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-2 py-1 text-left",
          expandable && "hover:bg-surface-2",
          "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        )}
      >
        <span
          className={cn(
            "shrink-0 rounded-[6px] px-1.5 py-px text-[10.5px] font-medium uppercase tracking-wider",
            CHIP_TONES[row.status],
          )}
        >
          {row.status}
        </span>
        <span className="truncate font-mono text-[11px] text-text-1">{row.nodeId || "(run)"}</span>
        {row.tools.length > 0 && (
          <span className="shrink-0 text-[11px] text-text-3">
            {row.tools.length} tool{row.tools.length === 1 ? "" : "s"}
          </span>
        )}
        <span className="ml-auto shrink-0 font-mono text-[11px] tabular-nums text-text-3">
          {row.durationMs != null ? `${row.durationMs}ms` : ""}
        </span>
        {expandable && (
          <Chevron className="h-3.5 w-3.5 shrink-0 text-text-3" strokeWidth={1.75} />
        )}
      </button>
      {open && expandable && (
        <div className="space-y-1.5 border-t border-border px-2 py-1.5">
          {row.error && (
            <p className="rounded border-l-2 border-danger bg-danger/10 px-2 py-1 font-mono text-[11px] text-danger">
              {row.error}
            </p>
          )}
          {row.notes.map((note, index) => (
            <p key={index} className="text-[11px] text-text-2">
              {note}
            </p>
          ))}
          {row.tools.map((tool, index) => (
            <ToolCallBlock key={index} item={tool} />
          ))}
          {row.outputs &&
            Object.entries(row.outputs).map(([port, value]) => (
              <div key={port} className="space-y-0.5">
                <p className="font-mono text-[11px] text-text-3">{port}</p>
                <OutputValue value={value} />
              </div>
            ))}
        </div>
      )}
    </div>
  );
}

export function Timeline({ events, onClose }: { events: RunEvent[]; onClose: () => void }) {
  const [showRaw, setShowRaw] = useState(false);
  const rows = useMemo(() => buildTimelineRows(events), [events]);

  return (
    <div className="absolute left-2 right-2 top-11 z-20 flex max-h-[75%] flex-col rounded-[10px] border border-border bg-surface-1 shadow-xl shadow-black/50">
      <div className="flex items-center justify-between border-b border-border px-3 py-2">
        <p className="text-[11px] font-semibold uppercase tracking-widest text-text-2">
          node timeline
        </p>
        <div className="flex items-center gap-1.5">
          {rows.length > 0 && (
            <button
              type="button"
              className="rounded px-1 text-[11px] text-text-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
              onClick={() => setShowRaw((v) => !v)}
            >
              {showRaw ? "pretty" : "raw json"}
            </button>
          )}
          <button
            type="button"
            aria-label="Close timeline"
            className="rounded p-0.5 text-text-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
            onClick={onClose}
          >
            <X className="h-3.5 w-3.5" strokeWidth={1.75} />
          </button>
        </div>
      </div>
      <div className="overflow-y-auto p-2">
        {rows.length === 0 ? (
          <div className="flex flex-col items-center gap-1.5 px-4 py-6 text-center">
            <ListTree className="h-5 w-5 text-text-3" strokeWidth={1.75} />
            <p className="text-[13px] text-text-2">No run yet</p>
            <p className="text-xs text-text-3">Send a message to see the node timeline.</p>
          </div>
        ) : showRaw ? (
          <pre className="overflow-auto font-mono text-[10.5px] leading-relaxed text-text-2">
            {JSON.stringify(events, null, 1)}
          </pre>
        ) : (
          <div className="space-y-1">
            {rows.map((row, index) => (
              <TimelineRowView key={`${row.nodeId}-${index}`} row={row} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
