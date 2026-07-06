/** SSE helpers: tail run events (GET, replayed) or stream a run (POST). */

import { useCallback, useEffect, useRef, useState } from "react";

import type { RunEvent } from "./types";

export interface SseHandle {
  close: () => void;
}

const EVENT_NAMES = [
  "run_started",
  "node_started",
  "node_token",
  "node_status",
  "node_log",
  "node_finished",
  "node_error",
  "interrupt_raised",
  "run_resumed",
  "run_finished",
  "run_cancelled",
  "heartbeat",
];

/** Tail /api/v1/runs/{id}/events — replay (Last-Event-ID) then live. */
export function tailRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  options?: { onEnd?: () => void },
): SseHandle {
  const source = new EventSource(`/api/v1/runs/${runId}/events`);
  const handler = (raw: MessageEvent) => {
    try {
      const event = JSON.parse(raw.data) as RunEvent;
      onEvent(event);
      if (event.event === "run_finished" || event.event === "run_cancelled") {
        source.close();
        options?.onEnd?.();
      }
    } catch {
      /* heartbeat frames are not RunEvents */
    }
  };
  for (const name of EVENT_NAMES) source.addEventListener(name, handler);
  source.onmessage = handler; // custom.<type> events arrive unnamed
  return { close: () => source.close() };
}

/** POST-based streaming run: parse the SSE body of POST /flows/{id}/run. */
export async function streamRun(
  flowId: string,
  body: Record<string, unknown>,
  onEvent: (event: RunEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`/api/v1/flows/${flowId}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, stream: true }),
    signal,
  });
  if (!response.ok || !response.body) {
    throw new Error(`stream failed: ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      try {
        onEvent(JSON.parse(dataLine.slice(5).trim()) as RunEvent);
      } catch {
        /* heartbeat frames carry non-RunEvent payloads */
      }
    }
  }
}

/** React hook: accumulate the event tail of a run (replay + live). */
export function useRunEvents(runId: string | null, maxEvents = 2000) {
  const [events, setEvents] = useState<RunEvent[]>([]);
  const handleRef = useRef<SseHandle | null>(null);

  useEffect(() => {
    setEvents([]);
    handleRef.current?.close();
    if (!runId) return;
    handleRef.current = tailRunEvents(runId, (event) => {
      setEvents((prev) => {
        const next = [...prev, event];
        return next.length > maxEvents ? next.slice(-maxEvents) : next;
      });
    });
    return () => handleRef.current?.close();
  }, [runId, maxEvents]);

  const clear = useCallback(() => setEvents([]), []);
  return { events, clear };
}
