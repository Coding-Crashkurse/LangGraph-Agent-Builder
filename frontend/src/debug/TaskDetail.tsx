import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, X } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import { useEventStream } from "@/api/sse";
import type { A2AMessage, Flow } from "@/api/types";
import { StateChip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/controls";
import { toast } from "@/components/ui/toast";
import { cn, shortId } from "@/lib/utils";
import { EventTail } from "./EventTail";
import { GraphReplay } from "./GraphReplay";
import { InputPanel } from "./InputPanel";

export function TaskDetail({
  flow,
  taskId,
  onClose,
}: {
  flow: Flow;
  taskId: string;
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"events" | "conversation" | "graph">("events");
  const stream = useEventStream(`/api/debug/tasks/${taskId}/events`);

  const detail = useQuery({
    queryKey: ["task", taskId],
    queryFn: () => api.debug.task(taskId),
  });

  // status/artifact events refresh the persisted detail
  useEffect(() => {
    const last = stream.events[stream.events.length - 1];
    if (last && ["status", "artifact", "interrupt", "error"].includes(last.type)) {
      queryClient.invalidateQueries({ queryKey: ["task", taskId] });
    }
  }, [stream.events, queryClient, taskId]);

  const cancel = useMutation({
    mutationFn: () => api.debug.cancel(taskId),
    onSuccess: (data) => {
      toast.info(`cancel → ${data.state}`);
      queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const run = detail.data?.run;
  const task = detail.data?.task;
  const state = run?.state ?? "unknown";

  return (
    <aside className="flex w-[520px] shrink-0 flex-col border-l border-surface-800 bg-surface-900">
      <div className="flex shrink-0 items-center gap-2 border-b border-surface-800 px-4 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-mono text-[11px] text-zinc-200">{shortId(taskId, 14)}</span>
            <StateChip state={state} />
          </div>
          <div className="font-mono text-[9px] text-zinc-600">
            ctx {run ? shortId(run.context_id, 14) : "…"} · {run?.source ?? ""}
          </div>
        </div>
        <div className="ml-auto flex items-center gap-1">
          {(state === "working" || state === "submitted") && (
            <Button
              variant="destructive"
              size="sm"
              disabled={cancel.isPending}
              onClick={() => cancel.mutate()}
            >
              <Ban className="h-3 w-3" /> Cancel
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={onClose} aria-label="close detail">
            <X className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {run?.error ? (
        <div className="border-b border-red-900/40 bg-red-950/30 px-4 py-2 text-[11px] text-red-300">
          {run.error}
        </div>
      ) : null}

      <div className="shrink-0 border-b border-surface-800 px-3 py-2">
        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            { value: "events", label: "Events" },
            { value: "conversation", label: "Conversation" },
            { value: "graph", label: "Graph" },
          ]}
        />
      </div>

      <div className="min-h-0 flex-1">
        {tab === "events" && <EventTail events={stream.events} connected={stream.connected} />}
        {tab === "conversation" && (
          <Conversation history={task?.history ?? []} artifacts={task?.artifacts ?? []} />
        )}
        {tab === "graph" && <GraphReplay flow={flow} events={stream.events} />}
      </div>

      {state === "input-required" && <InputPanel taskId={taskId} events={stream.events} />}
    </aside>
  );
}

function partText(message: A2AMessage): string {
  return message.parts
    .map((part) => {
      if (part.kind === "text") return part.text ?? "";
      if (part.kind === "data") return JSON.stringify(part.data);
      return "[file]";
    })
    .filter(Boolean)
    .join("\n");
}

function Conversation({
  history,
  artifacts,
}: {
  history: A2AMessage[];
  artifacts: { name?: string; parts: { kind: string; text?: string }[] }[];
}) {
  return (
    <div className="h-full space-y-2 overflow-y-auto px-4 py-3">
      {history.length === 0 && (
        <p className="text-xs text-zinc-600">No messages recorded for this task.</p>
      )}
      {history.map((message, index) => (
        <div
          key={index}
          className={cn(
            "max-w-[92%] rounded-lg border px-3 py-2 text-xs leading-relaxed",
            message.role === "user"
              ? "ml-auto border-accent-600/40 bg-accent-600/10 text-zinc-100"
              : "border-surface-700 bg-surface-850 text-zinc-300",
          )}
        >
          <div className="mb-0.5 font-mono text-[9px] uppercase tracking-wider text-zinc-500">
            {message.role}
          </div>
          <div className="whitespace-pre-wrap break-words font-mono text-[11px]">
            {partText(message) || "(empty)"}
          </div>
        </div>
      ))}
      {artifacts.map((artifact, index) => (
        <div
          key={`artifact-${index}`}
          className="rounded-lg border border-emerald-800/40 bg-emerald-950/20 px-3 py-2"
        >
          <div className="mb-0.5 font-mono text-[9px] uppercase tracking-wider text-emerald-400">
            artifact · {artifact.name ?? "response"}
          </div>
          <div className="whitespace-pre-wrap break-words text-xs text-emerald-100">
            {artifact.parts.map((part) => part.text ?? "").join("\n")}
          </div>
        </div>
      ))}
    </div>
  );
}
