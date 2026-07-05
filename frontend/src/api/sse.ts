import { useEffect, useRef, useState } from "react";

import type { TaskEvent } from "./types";

export interface EventStreamState {
  events: TaskEvent[];
  connected: boolean;
  clear: () => void;
}

/** Subscribe to a GraphForge SSE endpoint (named event: "task_event").
 * Native EventSource handles reconnect + Last-Event-ID replay automatically. */
export function useEventStream(url: string | null, maxEvents = 2000): EventStreamState {
  const [events, setEvents] = useState<TaskEvent[]>([]);
  const [connected, setConnected] = useState(false);
  const seen = useRef<Set<string>>(new Set());

  useEffect(() => {
    if (!url) return;
    seen.current = new Set();
    setEvents([]);
    const source = new EventSource(url);
    source.onopen = () => setConnected(true);
    source.onerror = () => setConnected(false);
    const handler = (raw: MessageEvent) => {
      try {
        const event = JSON.parse(raw.data) as TaskEvent;
        if (seen.current.has(event.id)) return;
        seen.current.add(event.id);
        setEvents((previous) => {
          const next = [...previous, event];
          return next.length > maxEvents ? next.slice(next.length - maxEvents) : next;
        });
      } catch {
        /* ignore malformed frames */
      }
    };
    source.addEventListener("task_event", handler);
    return () => {
      source.removeEventListener("task_event", handler);
      source.close();
      setConnected(false);
    };
  }, [url, maxEvents]);

  return {
    events,
    connected,
    clear: () => {
      seen.current = new Set();
      setEvents([]);
    },
  };
}
