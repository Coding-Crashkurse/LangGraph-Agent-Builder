/**
 * Minimal A2A v1.0 REST client for the playground chat (SPEC §2.5).
 *
 * The chat talks to the ephemeral draft endpoint (`…/a2a/_draft/{name}`)
 * THROUGH the gateway, with the user's token. Streaming uses
 * `message:stream` (SSE); non-streaming falls back to `message:send`.
 */

import { authHeaders } from "./auth";
import { parseSseStream } from "./sse";

export interface A2aPart {
  text?: string;
  data?: Record<string, unknown>;
}

export interface A2aMessage {
  role: string;
  messageId: string;
  parts: A2aPart[];
  taskId?: string;
  contextId?: string;
}

export interface A2aTask {
  id: string;
  contextId?: string;
  status?: { state?: string; message?: A2aMessage };
  artifacts?: { parts?: A2aPart[] }[];
}

export function userMessage(text: string, extra: Partial<A2aMessage> = {}): A2aMessage {
  return {
    role: "ROLE_USER",
    messageId: crypto.randomUUID(),
    parts: [{ text }],
    ...extra,
  };
}

export function taskText(task: A2aTask): string {
  const parts = task.artifacts?.flatMap((a) => a.parts ?? []) ?? [];
  const text = parts
    .map((p) => p.text ?? "")
    .join("")
    .trim();
  if (text) return text;
  return (task.status?.message?.parts ?? [])
    .map((p) => p.text ?? "")
    .join("")
    .trim();
}

export async function sendMessage(endpoint: string, message: A2aMessage): Promise<A2aTask> {
  const response = await fetch(`${endpoint.replace(/\/$/, "")}/message:send`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message }),
  });
  if (!response.ok) throw new Error(`A2A send failed: HTTP ${response.status}`);
  const payload = (await response.json()) as { task?: A2aTask };
  if (!payload.task) throw new Error("A2A response carried no task");
  return payload.task;
}

interface StreamFrame {
  task?: A2aTask;
  msg?: A2aMessage;
  statusUpdate?: { taskId?: string; status?: { state?: string; message?: A2aMessage } };
  artifactUpdate?: { artifact?: { parts?: A2aPart[] } };
}

export interface StreamCallbacks {
  onDelta: (text: string) => void;
  onTask?: (task: A2aTask) => void;
}

/**
 * Stream a message; resolves with the final task (when the server sent one).
 * Falls back to `message:send` when the endpoint rejects streaming.
 */
export async function streamMessage(
  endpoint: string,
  message: A2aMessage,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<A2aTask | null> {
  const response = await fetch(`${endpoint.replace(/\/$/, "")}/message:stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json", ...authHeaders() },
    body: JSON.stringify({ message }),
    signal,
  });
  if (!response.ok || !response.body) {
    const task = await sendMessage(endpoint, message);
    callbacks.onDelta(taskText(task));
    callbacks.onTask?.(task);
    return task;
  }
  let finalTask: A2aTask | null = null;
  await parseSseStream(response.body, (payload) => {
    const frame = payload as StreamFrame;
    if (frame.artifactUpdate?.artifact?.parts) {
      for (const part of frame.artifactUpdate.artifact.parts) {
        if (part.text) callbacks.onDelta(part.text);
      }
    }
    if (frame.msg?.parts) {
      for (const part of frame.msg.parts) if (part.text) callbacks.onDelta(part.text);
    }
    if (frame.task) {
      finalTask = frame.task;
      callbacks.onTask?.(frame.task);
    }
  });
  return finalTask;
}
