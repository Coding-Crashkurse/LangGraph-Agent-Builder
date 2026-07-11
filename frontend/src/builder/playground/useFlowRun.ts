/** Run orchestration for the playground chat (§11.7): streams POST /run over
 * SSE, folds node_token / tool_call / tool_result into chat items, drives the
 * canvas run-state visuals, resolves interrupts, supports cancel during any
 * active run, and manages sessions (threads) incl. delete. */

import { useCallback, useEffect, useRef, useState } from "react";

import { api } from "@/api/client";
import { streamRun } from "@/api/sse";
import type { FlowInfo, InterruptPayload, RunEvent, ThreadInfo } from "@/api/types";
import { toast } from "@/components/ui/toast";
import { useBuilder } from "../store";
import type { ChatItem } from "./ChatPane";

export interface PendingInterrupt {
  runId: string;
  payload: InterruptPayload;
}

export function useFlowRun(flow: FlowInfo) {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [busy, setBusy] = useState(false);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [threads, setThreads] = useState<ThreadInfo[]>([]);
  const [pending, setPending] = useState<PendingInterrupt | null>(null);
  const [runId, setRunId] = useState<string | null>(null);
  const [eventLog, setEventLog] = useState<RunEvent[]>([]);
  const [threadState, setThreadState] = useState<Record<string, unknown> | null>(null);
  const eventsRef = useRef<RunEvent[]>([]); // sync view of the stream (state lags)

  const refreshThreads = useCallback(() => {
    api.threads.list(flow.slug).then(setThreads).catch(() => {});
  }, [flow.slug]);
  useEffect(refreshThreads, [refreshThreads]);

  const handleEvent = useCallback((event: RunEvent) => {
    eventsRef.current = [...eventsRef.current.slice(-800), event];
    setEventLog(eventsRef.current);
    useBuilder.getState().applyRunEvent(event); // drive node run-state visuals (§11.2)
    if (event.event === "node_token") {
      const delta = String(event.data.delta ?? "");
      setItems((prev) => {
        const last = prev[prev.length - 1];
        if (last?.role === "assistant") {
          return [...prev.slice(0, -1), { ...last, text: last.text + delta }];
        }
        return [...prev, { role: "assistant", text: delta }];
      });
    } else if (event.event === "tool_call") {
      setItems((prev) => [
        ...prev,
        {
          role: "tool",
          name: String(event.data.tool_name ?? "tool"),
          args: event.data.args_preview,
          done: false,
        },
      ]);
    } else if (event.event === "tool_result") {
      setItems((prev) => {
        for (let i = prev.length - 1; i >= 0; i--) {
          const item = prev[i];
          if (item.role === "tool" && !item.done) {
            const updated: ChatItem = {
              ...item,
              done: true,
              result: String(event.data.result_preview ?? ""),
              durationMs:
                event.data.duration_ms != null ? Number(event.data.duration_ms) : undefined,
            };
            return [...prev.slice(0, i), updated, ...prev.slice(i + 1)];
          }
        }
        return prev;
      });
    }
  }, []);

  const finish = useCallback(async (finalRunId: string) => {
    // the stream events are the source of truth (the run row can lag a beat)
    const events = eventsRef.current;
    const finished = [...events].reverse().find((e) => e.event === "run_finished");
    const cancelled = events.some((e) => e.event === "run_cancelled");
    const interrupted = [...events].reverse().find((e) => e.event === "interrupt_raised");

    if (interrupted && !finished && !cancelled) {
      setPending({
        runId: finalRunId,
        payload: (interrupted.data.payload as InterruptPayload) ?? { prompt: "input?" },
      });
      return;
    }
    if (cancelled) {
      setItems((prev) => [...prev, { role: "error", text: "run cancelled" }]);
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

  const send = async (text: string, debugMode: boolean) => {
    if (!text.trim() || busy) return;
    setItems((prev) => [...prev, { role: "user", text }]);
    setBusy(true);
    eventsRef.current = [];
    setEventLog([]);
    useBuilder.getState().resetRunStates();
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
          if (!currentRunId) {
            currentRunId = event.run_id;
            setRunId(event.run_id); // known immediately → Stop works mid-run
          }
          if (!sessionId && event.thread_id) setSessionId(event.thread_id);
          handleEvent(event);
        },
      );
      if (currentRunId) await finish(currentRunId);
    } catch (error) {
      setItems((prev) => [...prev, { role: "error", text: (error as Error).message }]);
    } finally {
      setBusy(false);
      refreshThreads();
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
    if (!runId) return;
    await api.runs.cancel(runId).catch(() => {});
    toast.info("cancel requested");
  };

  const selectSession = (threadId: string | null) => {
    if (threadId === sessionId) return;
    setSessionId(threadId);
    setItems([]);
    setEventLog([]);
    eventsRef.current = [];
    setRunId(null);
    setPending(null);
    setThreadState(null);
    useBuilder.getState().resetRunStates();
  };

  const deleteSession = async (threadId: string) => {
    try {
      await api.threads.delete(threadId);
      if (sessionId === threadId) selectSession(null);
      refreshThreads();
      toast.info("session deleted");
    } catch (error) {
      toast.error((error as Error).message);
    }
  };

  const inspectState = async () => {
    if (!sessionId) return;
    const state = await api.threads.state(sessionId).catch(() => null);
    setThreadState(state ?? { error: "no state" });
  };

  return {
    items,
    busy,
    sessionId,
    threads,
    pending,
    runId,
    eventLog,
    threadState,
    send,
    resume,
    cancel,
    selectSession,
    deleteSession,
    inspectState,
    clearThreadState: () => setThreadState(null),
  };
}
