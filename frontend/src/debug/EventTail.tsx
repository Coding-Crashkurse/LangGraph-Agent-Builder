import { Pause, Play } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import type { TaskEvent } from "@/api/types";
import { Switch } from "@/components/ui/controls";
import { cn, formatTime } from "@/lib/utils";

const TYPE_COLORS: Record<string, string> = {
  status: "text-zinc-400",
  "node.start": "text-blue-300",
  "node.end": "text-blue-500",
  "node.update": "text-violet-300",
  interrupt: "text-amber-300",
  artifact: "text-emerald-300",
  error: "text-red-400",
};

function typeColor(type: string): string {
  if (type.startsWith("custom.")) return "text-sky-300";
  return TYPE_COLORS[type] ?? "text-zinc-400";
}

export function EventTail({ events, connected }: { events: TaskEvent[]; connected: boolean }) {
  const [paused, setPaused] = useState(false);
  const [raw, setRaw] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!paused) bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [events.length, paused]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-surface-800 px-3 py-1.5">
        <span
          className={cn(
            "text-[10px] font-medium",
            connected ? "text-emerald-400" : "text-zinc-600",
          )}
        >
          ● {connected ? "live" : "disconnected"}
        </span>
        <span className="font-mono text-[10px] text-zinc-600">{events.length} events</span>
        <div className="ml-auto flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-[10px] text-zinc-500">
            raw JSON <Switch checked={raw} onCheckedChange={setRaw} label="raw json" />
          </label>
          <button
            type="button"
            className="flex items-center gap-1 text-[10px] text-zinc-400 hover:text-zinc-100"
            onClick={() => setPaused((p) => !p)}
          >
            {paused ? <Play className="h-3 w-3" /> : <Pause className="h-3 w-3" />}
            {paused ? "resume scroll" : "pause scroll"}
          </button>
        </div>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-3 py-2 font-mono text-[10.5px] leading-relaxed">
        {events.map((event) =>
          raw ? (
            <pre key={event.id} className="mb-1.5 whitespace-pre-wrap break-all rounded bg-surface-950 p-2 text-zinc-400">
              {JSON.stringify(event, null, 2)}
            </pre>
          ) : (
            <div key={event.id} className="flex gap-2 py-[1.5px]">
              <span className="shrink-0 text-zinc-700">{formatTime(event.ts)}</span>
              <span className={cn("w-40 shrink-0 truncate", typeColor(event.type))}>
                {event.type}
              </span>
              {event.node ? (
                <span className="shrink-0 text-amber-200/70">{event.node}</span>
              ) : null}
              <span className="truncate text-zinc-500">
                {Object.keys(event.data).length ? JSON.stringify(event.data) : ""}
              </span>
            </div>
          ),
        )}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}
