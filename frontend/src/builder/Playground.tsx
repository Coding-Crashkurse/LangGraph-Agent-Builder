/** Playground & Debug drawer (SPEC §11.5): streaming chat, per-node timeline,
 * interrupt modals from ApprovalRequest/InputRequest, sessions, debug stepping. */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { streamRun } from "@/api/sse";
import type { FlowInfo, InterruptPayload, RunEvent, ThreadInfo } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, Switch } from "@/components/ui/controls";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

interface ChatItem {
  role: "user" | "assistant" | "event" | "error";
  text: string;
  events?: RunEvent[];
}

interface PendingInterrupt {
  runId: string;
  payload: InterruptPayload;
}

export function Playground({ flow, onClose }: { flow: FlowInfo; onClose: () => void }) {
  const [view, setView] = useState<"chat" | "a2a">("chat");
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [debugMode, setDebugMode] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [pending, setPending] = useState<PendingInterrupt | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [eventLog, setEventLog] = useState<RunEvent[]>([]);
  const eventsRef = useRef<RunEvent[]>([]); // sync view of the stream (state lags)
  const [showRaw, setShowRaw] = useState(false);
  const [stateJson, setStateJson] = useState<string | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    api.threads.list(flow.slug).then(setThreads).catch(() => {});
  }, [flow.slug]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [items, eventLog]);

  const handleEvent = useCallback((event: RunEvent) => {
    eventsRef.current = [...eventsRef.current.slice(-800), event];
    setEventLog(eventsRef.current);
    if (event.event === "node_token") {
      const delta = String(event.data.delta ?? "");
      setItems((prev) => {
        const last = prev[prev.length - 1];
        if (last?.role === "assistant") {
          return [...prev.slice(0, -1), { ...last, text: last.text + delta }];
        }
        return [...prev, { role: "assistant", text: delta }];
      });
    }
  }, []);

  const finish = useCallback(async (finalRunId: string) => {
    // the stream events are the source of truth (the run row can lag a beat)
    const events = eventsRef.current;
    const finished = [...events].reverse().find((e) => e.event === "run_finished");
    const interrupted = [...events].reverse().find((e) => e.event === "interrupt_raised");

    if (interrupted && !finished) {
      setPending({
        runId: finalRunId,
        payload: (interrupted.data.payload as InterruptPayload) ?? { prompt: "input?" },
      });
      return;
    }
    if (finished) {
      if (finished.data.status === "completed") {
        const preview = String(finished.data.result_preview ?? "");
        setItems((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.text) return prev; // token-streamed already
          return [...prev, { role: "assistant", text: preview || "(done)" }];
        });
      } else {
        setItems((prev) => [
          ...prev,
          {
            role: "error",
            text: `${String(finished.data.error_code ?? "error")}: ${String(
              finished.data.message ?? "run failed",
            )}`,
          },
        ]);
      }
      return;
    }
    // no terminal event seen — fall back to the run row
    const run = await api.runs.get(finalRunId).catch(() => null);
    if (!run) return;
    if (run.status === "input_required") {
      setPending({ runId: finalRunId, payload: { prompt: "input required" } });
    } else if (run.status === "completed") {
      setItems((prev) => [...prev, { role: "assistant", text: run.result_preview || "(done)" }]);
    } else if (run.status === "failed") {
      setItems((prev) => [
        ...prev,
        { role: "error", text: `${run.error_code}: ${run.error_message}` },
      ]);
    }
  }, []);

  const send = async () => {
    if (!input.trim() || busy) return;
    const text = input.trim();
    setInput("");
    setItems((prev) => [...prev, { role: "user", text }]);
    setBusy(true);
    eventsRef.current = [];
    setEventLog([]);
    let currentRunId: string | null = null;
    try {
      await streamRun(
        flow.id,
        {
          input_text: text,
          session_id: sessionId,
          mode: debugMode ? "debug" : "playground",
        },
        (event) => {
          currentRunId = event.run_id;
          if (!sessionId && event.thread_id) setSessionId(event.thread_id);
          handleEvent(event);
        },
      );
      if (currentRunId) {
        setRunId(currentRunId);
        await finish(currentRunId);
      }
    } catch (error) {
      setItems((prev) => [...prev, { role: "error", text: (error as Error).message }]);
    } finally {
      setBusy(false);
    }
  };

  const resume = async (payload: unknown, debugAction?: "step" | "continue") => {
    if (!pending && !debugAction) return;
    const target = pending?.runId ?? runId;
    if (!target) return;
    setPending(null);
    setBusy(true);
    try {
      const result = await api.runs.resume(target, payload, debugAction);
      if (result.status === "input_required" && result.interrupt) {
        setPending({ runId: target, payload: result.interrupt });
      } else if (result.status === "completed") {
        setItems((prev) => [...prev, { role: "assistant", text: result.result_text }]);
      } else if (result.status === "failed") {
        setItems((prev) => [
          ...prev,
          { role: "error", text: `${result.error_code}: ${result.error_message}` },
        ]);
      }
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    if (runId) {
      await api.runs.cancel(runId).catch(() => {});
      toast.info("cancel requested");
    }
  };

  const inspectState = async () => {
    if (!sessionId) return;
    const state = await api.threads.state(sessionId).catch(() => null);
    setStateJson(state ? JSON.stringify(state, null, 2) : "no state");
  };

  const nodeTimeline = eventLog.filter((e) =>
    ["node_started", "node_finished", "node_error", "node_status", "interrupt_raised"].includes(
      e.event,
    ),
  );

  return (
    <div className="flex w-[430px] flex-col border-l border-surface-800 bg-surface-950">
      <header className="flex items-center gap-2 border-b border-surface-800 px-3 py-2">
        <h2 className="text-sm font-semibold">Playground</h2>
        <span className="flex overflow-hidden rounded border border-surface-700 text-[10px]">
          <button
            className={cn(
              "px-2 py-0.5",
              view === "chat" ? "bg-accent-600 text-white" : "text-zinc-400",
            )}
            onClick={() => setView("chat")}
          >
            Chat
          </button>
          <button
            className={cn(
              "px-2 py-0.5",
              view === "a2a" ? "bg-accent-600 text-white" : "text-zinc-400",
            )}
            onClick={() => setView("a2a")}
            title="Talk to the PUBLISHED agent over real A2A (task lifecycle)"
          >
            A2A
          </button>
        </span>
        {view === "chat" && (
          <>
            <span className="flex items-center gap-1 text-[10px] text-zinc-500">
              debug
              <Switch checked={debugMode} onCheckedChange={setDebugMode} />
            </span>
            <Select
              className="!h-7 w-32 text-xs"
              value={sessionId ?? ""}
              onChange={(e) => setSessionId(e.target.value || null)}
            >
              <option value="">new session</option>
              {threads.map((t) => (
                <option key={t.thread_id} value={t.thread_id}>
                  {t.thread_id.slice(0, 10)}… ({t.runs})
                </option>
              ))}
            </Select>
          </>
        )}
        <button className="ml-auto text-zinc-500 hover:text-zinc-200" onClick={onClose}>
          ✕
        </button>
      </header>

      {view === "a2a" ? (
        <A2AChat slug={flow.slug} />
      ) : (
        <>
      <div className="flex-1 space-y-2 overflow-y-auto px-3 py-2">
        {items.map((item, index) => (
          <div
            key={index}
            className={cn(
              "max-w-[92%] whitespace-pre-wrap rounded-lg px-3 py-1.5 text-sm",
              item.role === "user" && "ml-auto bg-accent-600/30 text-zinc-100",
              item.role === "assistant" && "bg-surface-800 text-zinc-100",
              item.role === "error" && "bg-red-950/60 text-red-300",
            )}
          >
            {item.text}
          </div>
        ))}
        {nodeTimeline.length > 0 && (
          <div className="rounded border border-surface-800 bg-surface-900/70 p-2">
            <div className="flex items-center justify-between">
              <p className="text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
                node timeline
              </p>
              <button
                className="text-[10px] text-zinc-500 hover:text-zinc-300"
                onClick={() => setShowRaw((v) => !v)}
              >
                {showRaw ? "pretty" : "raw json"}
              </button>
            </div>
            {showRaw ? (
              <pre className="max-h-48 overflow-auto text-[9px] text-zinc-400">
                {JSON.stringify(eventLog, null, 1)}
              </pre>
            ) : (
              <div className="mt-1 space-y-0.5">
                {nodeTimeline.map((event, index) => (
                  <p key={index} className="font-mono text-[10px] text-zinc-400">
                    <span
                      className={cn(
                        event.event === "node_error" && "text-red-400",
                        event.event === "interrupt_raised" && "text-amber-400",
                        event.event === "node_finished" && "text-emerald-400",
                      )}
                    >
                      {event.event}
                    </span>{" "}
                    {String(event.data.node_id ?? "")}
                    {event.event === "node_finished" &&
                      ` ${String(event.data.duration_ms ?? "")}ms`}
                    {event.event === "node_status" && ` — ${String(event.data.text ?? "")}`}
                  </p>
                ))}
              </div>
            )}
          </div>
        )}
        {stateJson && (
          <div className="rounded border border-surface-800 bg-surface-900/70 p-2">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
              thread state
            </p>
            <pre className="max-h-48 overflow-auto text-[9px] text-zinc-400">{stateJson}</pre>
          </div>
        )}
        <div ref={bottom} />
      </div>

      {pending && <InterruptModal payload={pending.payload} onAnswer={resume} />}

      {debugMode && (
        <div className="flex items-center gap-2 border-t border-surface-800 px-3 py-1.5">
          <span className="text-[10px] uppercase tracking-widest text-zinc-500">debug</span>
          <Button variant="ghost" className="!h-6 !px-2 !text-xs"
                  onClick={() => resume(null, "step")}>
            Step
          </Button>
          <Button variant="ghost" className="!h-6 !px-2 !text-xs"
                  onClick={() => resume(null, "continue")}>
            Continue
          </Button>
          <Button variant="ghost" className="!h-6 !px-2 !text-xs" onClick={cancel}>
            Abort
          </Button>
          <Button variant="ghost" className="!h-6 !px-2 !text-xs" onClick={inspectState}>
            State
          </Button>
        </div>
      )}

      <footer className="flex gap-2 border-t border-surface-800 p-3">
        <Input
          value={input}
          placeholder={busy ? "running…" : "Message the flow…"}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <Button onClick={send} disabled={busy || !input.trim()}>
          Send
        </Button>
      </footer>
        </>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------- A2A view
interface A2AEntry {
  type: "user" | "artifact" | "status" | "error" | "info";
  text: string;
  state?: string;
  final?: boolean;
}

const A2A_STATE_TONES: Record<string, string> = {
  submitted: "bg-zinc-800 text-zinc-300",
  working: "bg-sky-950/70 text-sky-300",
  "input-required": "bg-amber-950/70 text-amber-300",
  completed: "bg-emerald-950/70 text-emerald-300",
  failed: "bg-red-950/70 text-red-300",
  canceled: "bg-zinc-800 text-zinc-400",
};

/** Talks to the PUBLISHED agent over real JSON-RPC `message/stream` and renders
 * the raw task lifecycle: Task → TaskStatusUpdateEvents → TaskArtifactUpdateEvents
 * (SPEC §7.5/§7.7). This is exactly what an external A2A client sees. */
function A2AChat({ slug }: { slug: string }) {
  const [entries, setEntries] = useState<A2AEntry[]>([]);
  const [available, setAvailable] = useState<boolean | null>(null);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [contextId, setContextId] = useState<string | null>(null);
  const [pendingPayload, setPendingPayload] = useState<InterruptPayload | null>(null);
  const bottom = useRef<HTMLDivElement>(null);

  useEffect(() => {
    fetch(`/a2a/${slug}/.well-known/agent-card.json`)
      .then((r) => setAvailable(r.ok))
      .catch(() => setAvailable(false));
  }, [slug]);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth" });
  }, [entries]);

  const push = (entry: A2AEntry) => setEntries((prev) => [...prev, entry]);

  const streamMessage = async (parts: unknown[], resumeTaskId?: string | null) => {
    setBusy(true);
    setPendingPayload(null);
    const message: Record<string, unknown> = {
      role: "user",
      messageId: crypto.randomUUID(),
      parts,
    };
    if (resumeTaskId) message.taskId = resumeTaskId;
    if (contextId) message.contextId = contextId;
    try {
      const response = await fetch(`/a2a/${slug}/`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          jsonrpc: "2.0",
          id: 1,
          method: "message/stream",
          params: { message },
        }),
      });
      if (!response.ok || !response.body) {
        push({ type: "error", text: `HTTP ${response.status}` });
        return;
      }
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      const artifactText: Record<string, string> = {};
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const frames = buffer.split("\n\n");
        buffer = frames.pop() ?? "";
        for (const frame of frames) {
          const dataLine = frame
            .split("\n")
            .find((line) => line.startsWith("data:"));
          if (!dataLine) continue;
          let body: Record<string, unknown>;
          try {
            body = JSON.parse(dataLine.slice(5));
          } catch {
            continue;
          }
          if (body.error) {
            const err = body.error as { code?: number; message?: string };
            push({ type: "error", text: `${err.code}: ${err.message}` });
            continue;
          }
          const result = body.result as Record<string, unknown> | undefined;
          if (!result) continue;
          const kind = String(result.kind ?? "");
          if (kind === "task") {
            setTaskId(String(result.id));
            setContextId(String(result.contextId ?? ""));
            const state = String(
              (result.status as Record<string, unknown> | undefined)?.state ?? "submitted",
            );
            push({ type: "status", text: `task ${String(result.id).slice(0, 8)}…`, state });
          } else if (kind === "status-update") {
            const status = result.status as Record<string, unknown>;
            const state = String(status?.state ?? "");
            const isFinal = Boolean(result.final);
            push({ type: "status", text: "", state, final: isFinal });
            if (state === "input-required") {
              const msg = status?.message as Record<string, unknown> | undefined;
              const parts_ = (msg?.parts as Record<string, unknown>[]) ?? [];
              const data = parts_.find((p) => p.kind === "data")?.data as
                | InterruptPayload
                | undefined;
              const text = parts_.find((p) => p.kind === "text")?.text as string | undefined;
              setPendingPayload(data ?? { prompt: text ?? "input required" });
            }
          } else if (kind === "artifact-update") {
            const artifact = result.artifact as Record<string, unknown>;
            const id = String(artifact?.artifactId ?? "a");
            const text = ((artifact?.parts as Record<string, unknown>[]) ?? [])
              .filter((p) => p.kind === "text")
              .map((p) => String(p.text ?? ""))
              .join("");
            artifactText[id] = (result.append ? (artifactText[id] ?? "") : "") + text;
            const name = String(artifact?.name ?? "artifact");
            setEntries((prev) => {
              const idx = prev.findIndex(
                (e) => e.type === "artifact" && e.state === id,
              );
              const entry: A2AEntry = {
                type: "artifact",
                text: `${name}: ${artifactText[id]}`,
                state: id,
              };
              if (idx >= 0) return [...prev.slice(0, idx), entry, ...prev.slice(idx + 1)];
              return [...prev, entry];
            });
          }
        }
      }
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
    await streamMessage([{ kind: "text", text }], pendingPayload ? taskId : null);
  };

  if (available === false) {
    return (
      <div className="flex-1 px-4 py-6 text-xs text-zinc-500">
        <p className="mb-2 text-sm text-zinc-300">Agent not served yet</p>
        This view talks to the <b>published</b> agent at <code>/a2a/{slug}/</code>. Enable
        A2A in the Share dialog and publish the flow first.
      </div>
    );
  }

  return (
    <>
      <div className="flex-1 space-y-1.5 overflow-y-auto px-3 py-2">
        <p className="text-[10px] text-zinc-600">
          real JSON-RPC message/stream — Task → status-updates → artifact-updates
          {contextId && (
            <>
              {" · "}contextId <code>{contextId.slice(0, 8)}…</code>
            </>
          )}
        </p>
        {entries.map((entry, index) =>
          entry.type === "status" ? (
            <p key={index} className="flex items-center gap-1.5 font-mono text-[10px]">
              <span
                className={cn(
                  "rounded px-1.5 py-0.5",
                  A2A_STATE_TONES[entry.state ?? ""] ?? "bg-zinc-800 text-zinc-400",
                )}
              >
                {entry.state}
              </span>
              {entry.final && <span className="text-zinc-600">final</span>}
              <span className="text-zinc-500">{entry.text}</span>
            </p>
          ) : (
            <div
              key={index}
              className={cn(
                "max-w-[92%] whitespace-pre-wrap rounded-lg px-3 py-1.5 text-sm",
                entry.type === "user" && "ml-auto bg-accent-600/30 text-zinc-100",
                entry.type === "artifact" &&
                  "border border-emerald-900/60 bg-surface-800 text-zinc-100",
                entry.type === "error" && "bg-red-950/60 text-red-300",
                entry.type === "info" && "text-xs text-zinc-500",
              )}
            >
              {entry.text}
            </div>
          ),
        )}
        <div ref={bottom} />
      </div>
      {pendingPayload && (
        <InterruptModal
          payload={pendingPayload}
          onAnswer={(answer) =>
            streamMessage([{ kind: "data", data: answer }], taskId)
          }
        />
      )}
      <footer className="flex gap-2 border-t border-surface-800 p-3">
        <Input
          value={input}
          placeholder={busy ? "streaming…" : "Message the published agent…"}
          disabled={busy}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && send()}
        />
        <Button onClick={send} disabled={busy || !input.trim()}>
          Send
        </Button>
      </footer>
    </>
  );
}

/** Interrupt modal rendered from the normative payloads (§5.5) — buttons from
 * `options`, form from `schema`. Same shapes as the A2A input-required message. */
function InterruptModal({
  payload,
  onAnswer,
}: {
  payload: InterruptPayload;
  onAnswer: (answer: unknown) => void;
}) {
  const [text, setText] = useState("");
  const [comment, setComment] = useState("");
  const isApproval = payload.kind === "approval";
  return (
    <div className="border-t border-amber-800/60 bg-amber-950/20 px-3 py-2">
      <p className="text-xs font-semibold text-amber-300">⏸ {payload.prompt ?? "input required"}</p>
      {isApproval ? (
        <div className="mt-2 space-y-2">
          <Input
            value={comment}
            placeholder="optional comment"
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex gap-2">
            {(payload.options ?? ["approve", "reject"]).map((option) => (
              <Button
                key={option}
                variant={option === "approve" ? "default" : "ghost"}
                className="!h-7 !text-xs"
                onClick={() => onAnswer({ decision: option, comment: comment || null })}
              >
                {option}
              </Button>
            ))}
          </div>
        </div>
      ) : (
        <div className="mt-2 flex gap-2">
          <Input
            value={text}
            placeholder={payload.schema ? "JSON matching the schema" : "your answer"}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key !== "Enter") return;
              if (payload.schema) {
                try {
                  onAnswer(JSON.parse(text));
                } catch {
                  toast.error("invalid JSON for the requested schema");
                }
              } else {
                onAnswer({ text });
              }
            }}
          />
          <Button
            className="!h-8 !text-xs"
            onClick={() => {
              if (payload.schema) {
                try {
                  onAnswer(JSON.parse(text));
                } catch {
                  toast.error("invalid JSON for the requested schema");
                }
              } else {
                onAnswer({ text });
              }
            }}
          >
            Answer
          </Button>
        </div>
      )}
    </div>
  );
}
