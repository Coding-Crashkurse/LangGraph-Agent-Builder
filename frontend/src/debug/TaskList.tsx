import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { api } from "@/api/client";
import type { RunState } from "@/api/types";
import { StateChip } from "@/components/ui/badge";
import { Select } from "@/components/ui/controls";
import { cn, duration, formatTime, shortId } from "@/lib/utils";

const STATES: RunState[] = [
  "submitted",
  "working",
  "input-required",
  "completed",
  "failed",
  "canceled",
];

export function TaskList({
  flowId,
  selected,
  onSelect,
}: {
  flowId: string;
  selected: string | null;
  onSelect: (taskId: string) => void;
}) {
  const [state, setState] = useState("");
  const [source, setSource] = useState("");

  const tasks = useQuery({
    queryKey: ["tasks", flowId, state, source],
    queryFn: () =>
      api.debug.tasks(flowId, { state: state || undefined, source: source || undefined }),
    refetchInterval: 5000, // safety net; the firehose invalidates faster
  });

  return (
    <div className="p-4">
      <div className="mb-3 flex items-center gap-2">
        <h2 className="text-xs font-semibold uppercase tracking-widest text-zinc-500">Tasks</h2>
        <div className="ml-auto flex items-center gap-1.5">
          <Select value={state} onChange={(e) => setState(e.target.value)} className="h-7 w-36 text-xs">
            <option value="">all states</option>
            {STATES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </Select>
          <Select value={source} onChange={(e) => setSource(e.target.value)} className="h-7 w-24 text-xs">
            <option value="">all</option>
            <option value="a2a">a2a</option>
            <option value="mcp">mcp</option>
          </Select>
        </div>
      </div>

      {tasks.data?.length ? (
        <table className="w-full border-separate border-spacing-0 text-left">
          <thead>
            <tr className="text-[10px] uppercase tracking-wider text-zinc-600">
              <th className="pb-2 pr-3 font-medium">task</th>
              <th className="pb-2 pr-3 font-medium">context</th>
              <th className="pb-2 pr-3 font-medium">src</th>
              <th className="pb-2 pr-3 font-medium">state</th>
              <th className="pb-2 pr-3 font-medium">input</th>
              <th className="pb-2 pr-3 font-medium">started</th>
              <th className="pb-2 font-medium">duration</th>
            </tr>
          </thead>
          <tbody>
            {tasks.data.map((run) => (
              <tr
                key={run.id}
                onClick={() => onSelect(run.id)}
                className={cn(
                  "cursor-pointer text-xs transition-colors [&>td]:border-t [&>td]:border-surface-800 [&>td]:py-2 [&>td]:pr-3",
                  selected === run.id ? "bg-surface-800/70" : "hover:bg-surface-850",
                )}
              >
                <td className="font-mono text-[10px] text-zinc-300">{shortId(run.id, 10)}</td>
                <td className="font-mono text-[10px] text-zinc-500">{shortId(run.context_id, 10)}</td>
                <td>
                  <span className="font-mono text-[10px] uppercase text-zinc-400">{run.source}</span>
                </td>
                <td>
                  <StateChip state={run.state} />
                </td>
                <td className="max-w-[240px] truncate text-zinc-400">{run.input_preview}</td>
                <td className="whitespace-nowrap font-mono text-[10px] text-zinc-500">
                  {formatTime(run.created_at)}
                </td>
                <td className="whitespace-nowrap font-mono text-[10px] text-zinc-500">
                  {duration(
                    run.created_at,
                    ["completed", "failed", "canceled"].includes(run.state)
                      ? run.updated_at
                      : undefined,
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : (
        <div className="rounded-lg border border-dashed border-surface-700 py-14 text-center text-xs text-zinc-600">
          No tasks yet — send a message from the Playground tab or from an external A2A/MCP
          client.
        </div>
      )}
    </div>
  );
}
