/** Chat box against the published A2A endpoint via the backend's A2A client
 * (message/stream vs message/send toggle) — CLAUDE.md §14.2. */

import { useMutation } from "@tanstack/react-query";
import { ExternalLink, RotateCcw, Send } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import type { A2ATask, Flow } from "@/api/types";
import { StateChip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/controls";
import { Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { cn, shortId } from "@/lib/utils";

interface Turn {
  role: "user" | "agent";
  text: string;
  taskId?: string;
  state?: string;
}

export function Playground({
  flow,
  onOpenTask,
}: {
  flow: Flow;
  onOpenTask: (taskId: string) => void;
}) {
  const [message, setMessage] = useState("");
  const [streaming, setStreaming] = useState(true);
  const [contextId, setContextId] = useState<string | null>(null);
  const [turns, setTurns] = useState<Turn[]>([]);

  const send = useMutation({
    mutationFn: (text: string) =>
      api.debug.sendMessage(flow.id, {
        message: text,
        context_id: contextId ?? undefined,
        stream: streaming,
      }),
    onSuccess: (result, text) => {
      const task = result.task;
      setTurns((previous) => [
        ...previous,
        { role: "user", text },
        {
          role: "agent",
          text: agentText(task),
          taskId: task?.id,
          state: task?.status.state,
        },
      ]);
      if (task?.contextId) setContextId(task.contextId);
      setMessage("");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const published = flow.is_published && Boolean(flow.endpoints.a2a_url);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex shrink-0 items-center gap-3 border-b border-surface-800 px-4 py-2">
        <label className="flex items-center gap-2 text-xs text-zinc-400">
          <Switch checked={streaming} onCheckedChange={setStreaming} label="streaming" />
          {streaming ? "message/stream" : "message/send"}
        </label>
        <span className="font-mono text-[10px] text-zinc-600">
          context: {contextId ? shortId(contextId, 12) : "new conversation"}
        </span>
        <Button
          variant="ghost"
          size="sm"
          onClick={() => {
            setContextId(null);
            setTurns([]);
          }}
        >
          <RotateCcw className="h-3 w-3" /> reset
        </Button>
      </div>

      <div className="min-h-0 flex-1 space-y-2.5 overflow-y-auto px-5 py-4">
        {!published && (
          <div className="rounded-lg border border-amber-900/50 bg-amber-950/20 px-3 py-2.5 text-xs text-amber-300">
            This flow is not published with A2A enabled — publish it from the builder first.
          </div>
        )}
        {turns.map((turn, index) => (
          <div
            key={index}
            className={cn(
              "max-w-[75%] rounded-xl border px-3.5 py-2.5 text-sm leading-relaxed",
              turn.role === "user"
                ? "ml-auto border-accent-600/40 bg-accent-600/15 text-zinc-100"
                : "border-surface-700 bg-surface-850 text-zinc-200",
            )}
          >
            <div className="whitespace-pre-wrap break-words">{turn.text || "(no output)"}</div>
            {turn.role === "agent" && turn.taskId ? (
              <div className="mt-1.5 flex items-center gap-2">
                {turn.state ? <StateChip state={turn.state as never} /> : null}
                <button
                  type="button"
                  className="inline-flex items-center gap-1 font-mono text-[10px] text-zinc-500 hover:text-accent-300"
                  onClick={() => onOpenTask(turn.taskId!)}
                >
                  <ExternalLink className="h-3 w-3" />
                  {shortId(turn.taskId, 10)}
                </button>
              </div>
            ) : null}
          </div>
        ))}
        {send.isPending && (
          <div className="max-w-[75%] rounded-xl border border-surface-700 bg-surface-850 px-3.5 py-2.5 text-sm text-zinc-500">
            running…
          </div>
        )}
      </div>

      <div className="shrink-0 border-t border-surface-800 px-5 py-3">
        <div className="flex items-end gap-2">
          <Textarea
            value={message}
            rows={2}
            placeholder={published ? "Ask the published agent…" : "Publish the flow first"}
            disabled={!published || send.isPending}
            onChange={(e) => setMessage(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && message.trim()) {
                e.preventDefault();
                send.mutate(message.trim());
              }
            }}
          />
          <Button
            disabled={!published || !message.trim() || send.isPending}
            onClick={() => send.mutate(message.trim())}
          >
            <Send className="h-4 w-4" />
          </Button>
        </div>
        <p className="mt-1.5 text-[10px] text-zinc-600">
          Runs through the real A2A endpoint ({streaming ? "SSE stream" : "blocking send"}).
          HITL tasks pause as <em>input-required</em> — answer them from the task detail panel.
        </p>
      </div>
    </div>
  );
}

function agentText(task: A2ATask | null): string {
  if (!task) return "(no task returned)";
  const artifact = task.artifacts
    ?.flatMap((a) => a.parts)
    .map((part) => part.text ?? "")
    .filter(Boolean)
    .join("\n");
  if (artifact) return artifact;
  const status = task.status.message?.parts
    ?.map((part) => (part.kind === "text" ? (part.text ?? "") : JSON.stringify(part.data)))
    .join("\n");
  if (task.status.state === "input-required") {
    return `⏸ waiting for human input${status ? `\n${status}` : ""}`;
  }
  return status || `(state: ${task.status.state})`;
}
