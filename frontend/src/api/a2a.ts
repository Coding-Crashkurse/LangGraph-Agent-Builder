/**
 * Minimal A2A v1.0 client for the playground chat (SPEC §2.5).
 *
 * The chat talks to the ephemeral draft endpoint (`…/a2a/_draft/{name}`)
 * THROUGH the gateway, with the user's token. The protocol binding is
 * discovered from the agent card (`supportedInterfaces[].protocolBinding`):
 * JSONRPC uses gRPC-style method names (`SendMessage`,
 * `SendStreamingMessage`); otherwise the REST shape (`message:send`) is used.
 */

import { authHeaders } from "./auth";
import { parseSseStream } from "./sse";

const VERSION_HEADERS = { "A2A-Version": "1.0" } as const;

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

type Binding = "jsonrpc" | "rest";

const bindingCache = new Map<string, Binding>();

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

function base(endpoint: string): string {
  return endpoint.replace(/\/$/, "");
}

interface AgentCard {
  supportedInterfaces?: { protocolBinding?: string }[];
}

/** Discover the protocol binding from the agent card (cached per endpoint). */
export async function detectBinding(endpoint: string): Promise<Binding> {
  const cached = bindingCache.get(endpoint);
  if (cached) return cached;
  let binding: Binding = "jsonrpc";
  try {
    const response = await fetch(`${base(endpoint)}/.well-known/agent-card.json`, {
      headers: { ...authHeaders() },
    });
    if (response.ok) {
      const card = (await response.json()) as AgentCard;
      const bindings = (card.supportedInterfaces ?? [])
        .map((i) => i.protocolBinding ?? "")
        .filter(Boolean);
      if (bindings.length > 0 && !bindings.includes("JSONRPC")) binding = "rest";
    }
  } catch {
    // card unreachable — keep the default and let the send call surface errors
  }
  bindingCache.set(endpoint, binding);
  return binding;
}

interface RpcEnvelope {
  result?: StreamResult;
  error?: { code?: number; message?: string };
}

interface StreamResult {
  task?: A2aTask;
  message?: A2aMessage;
  statusUpdate?: { status?: { state?: string; message?: A2aMessage } };
  artifactUpdate?: { artifact?: { parts?: A2aPart[] } };
}

function partsText(parts: A2aPart[] | undefined): string {
  return (parts ?? []).map((p) => p.text ?? "").join("");
}

export async function sendMessage(endpoint: string, message: A2aMessage): Promise<A2aTask> {
  const binding = await detectBinding(endpoint);
  const headers = { "Content-Type": "application/json", ...VERSION_HEADERS, ...authHeaders() };
  if (binding === "jsonrpc") {
    const response = await fetch(`${base(endpoint)}/`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        jsonrpc: "2.0",
        id: crypto.randomUUID(),
        method: "SendMessage",
        params: { message },
      }),
    });
    if (!response.ok) throw new Error(`A2A send failed: HTTP ${response.status}`);
    const envelope = (await response.json()) as RpcEnvelope;
    if (envelope.error) throw new Error(`A2A error: ${envelope.error.message}`);
    const task = envelope.result?.task;
    if (task) return task;
    const reply = envelope.result?.message;
    if (reply) return { id: "", status: { state: "TASK_STATE_COMPLETED", message: reply } };
    throw new Error("A2A response carried no task");
  }
  const response = await fetch(`${base(endpoint)}/message:send`, {
    method: "POST",
    headers,
    body: JSON.stringify({ message }),
  });
  if (!response.ok) throw new Error(`A2A send failed: HTTP ${response.status}`);
  const payload = (await response.json()) as { task?: A2aTask };
  if (!payload.task) throw new Error("A2A response carried no task");
  return payload.task;
}

export interface StreamCallbacks {
  onDelta: (text: string) => void;
  onTask?: (task: A2aTask) => void;
}

/**
 * Stream a message; resolves with the final task (when the server sent one).
 * Falls back to a plain send when the endpoint rejects streaming. Token
 * deltas arrive as status updates; artifact updates are only used when no
 * deltas were seen (avoids double-printing the final text).
 */
export async function streamMessage(
  endpoint: string,
  message: A2aMessage,
  callbacks: StreamCallbacks,
  signal?: AbortSignal,
): Promise<A2aTask | null> {
  const binding = await detectBinding(endpoint);
  const headers = { "Content-Type": "application/json", ...VERSION_HEADERS, ...authHeaders() };
  const url = binding === "jsonrpc" ? `${base(endpoint)}/` : `${base(endpoint)}/message:stream`;
  const body =
    binding === "jsonrpc"
      ? JSON.stringify({
          jsonrpc: "2.0",
          id: crypto.randomUUID(),
          method: "SendStreamingMessage",
          params: { message },
        })
      : JSON.stringify({ message });
  const response = await fetch(url, { method: "POST", headers, body, signal });
  if (!response.ok || !response.body) {
    const task = await sendMessage(endpoint, message);
    callbacks.onDelta(taskText(task));
    callbacks.onTask?.(task);
    return task;
  }
  let finalTask: A2aTask | null = null;
  let sawDelta = false;
  let artifactText = "";
  await parseSseStream(response.body, (payload) => {
    const envelope = payload as RpcEnvelope;
    const frame: StreamResult = envelope.result ?? (payload as StreamResult);
    const statusMessage = frame.statusUpdate?.status?.message;
    if (statusMessage) {
      const delta = partsText(statusMessage.parts);
      if (delta) {
        sawDelta = true;
        callbacks.onDelta(delta);
      }
    }
    if (frame.message) {
      const delta = partsText(frame.message.parts);
      if (delta) {
        sawDelta = true;
        callbacks.onDelta(delta);
      }
    }
    if (frame.artifactUpdate?.artifact?.parts) {
      artifactText += partsText(frame.artifactUpdate.artifact.parts);
    }
    if (frame.task) {
      finalTask = frame.task;
      callbacks.onTask?.(frame.task);
    }
  });
  if (!sawDelta && artifactText) callbacks.onDelta(artifactText);
  return finalTask;
}
