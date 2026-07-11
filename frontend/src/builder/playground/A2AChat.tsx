/** A2A lifecycle view: talks to the PUBLISHED agent over real JSON-RPC
 * `message/stream` and renders the raw task lifecycle — Task →
 * TaskStatusUpdateEvents → TaskArtifactUpdateEvents (SPEC §7.5/§7.7). This is
 * exactly what an external A2A client sees. */

import { Radio, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import {
  type A2APart,
  cancelTask,
  fetchAgentCard,
  interruptFromStatus,
  streamMessage,
  textFromParts,
} from "@/api/a2a";
import type { InterruptPayload } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { InterruptModal } from "./InterruptModal";
import { shortId } from "./format";
import { Markdown } from "./Markdown";

interface A2AEntry {
  type: "user" | "artifact" | "status" | "error";
  text: string;
  state?: string; // task state for status rows; artifactId for artifact rows
  final?: boolean;
}

const A2A_STATE_TONES: Record<string, string> = {
  submitted: "bg-surface-2 text-text-2",
  working: "bg-port-toolset/15 text-port-toolset",
  "input-required": "bg-warning/15 text-warning",
  completed: "bg-success/15 text-success",
  failed: "bg-danger/15 text-danger",
  canceled: "bg-surface-2 text-text-3",
};

export function A2AChat({ slug }: { slug: string }) {
  const [entries, setEntries] = useState<A2AEntry[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [contextId, setContextId] = useState<string | null>(null);
  const [pendingPayload, setPendingPayload] = useState<InterruptPayload | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetchAgentCard(slug).then((card) => setAvailable(card !== null));
  }, [slug]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  const push = (entry: A2AEntry) => setEntries((prev) => [...prev, entry]);

  const stream = async (parts: A2APart[], resumeTaskId?: string | null) => {
    setBusy(true);
    setPendingPayload(null);
    const artifactText: Record<string, string> = {}; // accumulated per artifactId
    try {
      await streamMessage(
        slug,
        { parts, taskId: resumeTaskId, contextId },
        {
          onTask: (task) => {
            setTaskId(task.id);
            setContextId(task.contextId ?? "");
            push({
              type: "status",
              text: `task ${shortId(task.id)}`,
              state: task.status?.state ?? "submitted",
            });
          },
          onStatus: (update) => {
            push({
              type: "status",
              text: "",
              state: update.status?.state ?? "",
              final: update.final,
            });
            const interrupt = interruptFromStatus(update.status);
            if (interrupt) setPendingPayload(interrupt);
          },
          onArtifact: (update) => {
            const id = update.artifact?.artifactId ?? "artifact";
            const text = textFromParts(update.artifact?.parts);
            artifactText[id] = (update.append ? (artifactText[id] ?? "") : "") + text;
            const name = update.artifact?.name ?? "artifact";
            setEntries((prev) => {
              const entry: A2AEntry = {
                type: "artifact",
                text: `**${name}**\n\n${artifactText[id]}`,
                state: id,
              };
              const index = prev.findIndex((e) => e.type === "artifact" && e.state === id);
              if (index >= 0) {
                return [...prev.slice(0, index), entry, ...prev.slice(index + 1)];
              }
              return [...prev, entry];
            });
          },
          onError: (error) => push({ type: "error", text: `${error.code}: ${error.message}` }),
        },
      );
    } catch (error) {
      push({ type: "error", text: (error as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const send = async () => {
    if (!input.trim() || busy) return;
    const text = input.trim();
    setInput("");
    push({ type: "user", text });
    // answering an open input-required continues the SAME task; otherwise a
    // new task starts in the same contextId (multi-turn, SPEC §7.6)
    await stream([{ kind: "text", text }], pendingPayload ? taskId : null);
  };

  const cancel = async () => {
    if (!taskId) return;
    try {
      await cancelTask(slug, taskId);
      toast.info("cancel requested");
    } catch (error) {
      toast.error((error as Error).message);
    }
  };

  if (available === null) {
    return (
      <div className="flex-1 space-y-2 px-3 py-3">
        <div className="h-4 w-3/4 animate-pulse rounded bg-surface-2" />
        <div className="h-4 w-1/2 animate-pulse rounded bg-surface-2" />
      </div>
    );
  }

  if (available === false) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-1.5 px-6 py-10 text-center">
        <Radio className="h-6 w-6 text-text-3" strokeWidth={1.75} />
        <p className="text-[13px] text-text-2">Agent not served yet</p>
        <p className="text-xs text-text-3">
          This view talks to the <b>published</b> agent at <code>/a2a/{slug}/</code>. Enable
          A2A in the Share dialog and publish the flow first.
        </p>
      </div>
    );
  }

  return (
    <>
      <div className="flex-1 space-y-1.5 overflow-y-auto px-3 py-2" aria-live="polite">
        <p className="text-[11px] text-text-3">
          real JSON-RPC message/stream — Task → status-updates → artifact-updates
          {contextId && (
            <>
              {" · "}contextId <code>{shortId(contextId)}</code>
            </>
          )}
        </p>
        {entries.map((entry, index) =>
          entry.type === "status" ? (
            <p key={index} className="flex items-center gap-1.5 font-mono text-[10.5px]">
              <span
                className={cn(
                  "rounded-[6px] px-1.5 py-0.5",
                  A2A_STATE_TONES[entry.state ?? ""] ?? "bg-surface-2 text-text-2",
                )}
              >
                {entry.state}
              </span>
              {entry.final && <span className="text-text-3">final</span>}
              <span className="text-text-3">{entry.text}</span>
            </p>
          ) : entry.type === "user" ? (
            <div
              key={index}
              className="ml-auto max-w-[92%] whitespace-pre-wrap rounded-lg bg-accent/15 px-3 py-1.5 text-[13px] leading-[1.45] text-text-1"
            >
              {entry.text}
            </div>
          ) : entry.type === "error" ? (
            <div
              key={index}
              className="max-w-[92%] rounded-lg border-l-2 border-danger bg-danger/10 px-3 py-1.5 text-[13px] leading-[1.45] text-danger"
            >
              {entry.text}
            </div>
          ) : (
            <div
              key={index}
              className="max-w-[92%] rounded-lg border border-success/40 bg-surface-1 px-3 py-1.5"
            >
              <Markdown text={entry.text} />
            </div>
          ),
        )}
        <div ref={bottom} />
      </div>

      {pendingPayload && (
        <InterruptModal
          payload={pendingPayload}
          onAnswer={(answer) => stream([{ kind: "data", data: answer }], taskId)}
        />
      )}

      <footer className="flex gap-2 border-t border-border p-3">
        <Input
          value={input}
          placeholder={busy ? "streaming…" : "Message the published agent…"}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        {busy ? (
          <Button variant="danger" aria-label="Cancel task" onClick={cancel}>
            <Square className="h-3.5 w-3.5" strokeWidth={1.75} />
            Stop
          </Button>
        ) : (
          <Button onClick={send} disabled={!input.trim()}>
            Send
          </Button>
        )}
      </footer>
    </>
  );
}
