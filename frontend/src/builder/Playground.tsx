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
  const [items, setItems] = useState<ChatItem[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [debugMode, setDebugMode] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [pending, setPending] = useState<PendingInterrupt | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [eventLog, setEventLog] = useState<RunEvent[]>([]);
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
    setEventLog((prev) => [...prev.slice(-800), event]);
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

  const finish = useCallback(
    async (finalRunId: string) => {
      const run = await api.runs.get(finalRunId).catch(() => null);
      if (!run) return;
      if (run.status === "input_required") {
        const interruptEvent = [...eventLog]
          .reverse()
          .find((e) => e.event === "interrupt_raised");
        setPending({
          runId: finalRunId,
          payload: (interruptEvent?.data.payload as InterruptPayload) ?? { prompt: "input?" },
        });
      } else if (run.status === "completed") {
        setItems((prev) => {
          const last = prev[prev.length - 1];
          if (last?.role === "assistant" && last.text) return prev; // token-streamed already
          return [...prev, { role: "assistant", text: run.result_preview || "(done)" }];
        });
      } else if (run.status === "failed") {
        setItems((prev) => [
          ...prev,
          { role: "error", text: `${run.error_code}: ${run.error_message}` },
        ]);
      }
    },
    [eventLog],
  );

  const send = async () => {
    if (!input.trim() || busy) return;
    const text = input.trim();
    setInput("");
    setItems((prev) => [...prev, { role: "user", text }]);
    setBusy(true);
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
        <span className="flex items-center gap-1 text-[10px] text-zinc-500">
          debug
          <Switch checked={debugMode} onCheckedChange={setDebugMode} />
        </span>
        <Select
          className="!h-7 w-36 text-xs"
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
        <button className="ml-auto text-zinc-500 hover:text-zinc-200" onClick={onClose}>
          ✕
        </button>
      </header>

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
    </div>
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
