/** Typed client for the PUBLISHED agent's A2A JSON-RPC surface (`/a2a/{slug}/`,
 * SPEC §7.5–§7.7). This is deliberately NOT part of the OpenAPI client: the A2A
 * mount speaks JSON-RPC (protocol v0.3.x), not the Studio REST contract. The
 * types below are structural mirrors of the wire JSON an external A2A client
 * sees. Streaming frames go through the shared SSE parser in `sse.ts`.
 */

import { parseSseStream } from "./sse";
import type { InterruptPayload } from "./types";

// ------------------------------------------------------------------ wire types
export interface A2ATextPart {
  kind: "text";
  text: string;
}

export interface A2ADataPart {
  kind: "data";
  data: unknown;
}

export interface A2AFilePart {
  kind: "file";
  file: Record<string, unknown>;
}

export type A2APart = A2ATextPart | A2ADataPart | A2AFilePart;

export interface A2AMessage {
  role: string;
  messageId: string;
  parts: A2APart[];
  taskId?: string;
  contextId?: string;
}

export interface A2ATaskStatus {
  state: string; // submitted | working | input-required | completed | failed | canceled
  message?: A2AMessage;
  timestamp?: string;
}

export interface A2ATask {
  kind: "task";
  id: string;
  contextId: string;
  status: A2ATaskStatus;
}

export interface A2AStatusUpdate {
  kind: "status-update";
  taskId: string;
  contextId: string;
  status: A2ATaskStatus;
  final: boolean;
}

export interface A2AArtifact {
  artifactId: string;
  name?: string;
  parts: A2APart[];
}

export interface A2AArtifactUpdate {
  kind: "artifact-update";
  taskId: string;
  artifact: A2AArtifact;
  append?: boolean;
  lastChunk?: boolean;
}

export interface A2ARpcError {
  code: number;
  message: string;
  data?: unknown;
}

export interface A2AStreamHandlers {
  onTask?: (task: A2ATask) => void;
  onStatus?: (update: A2AStatusUpdate) => void;
  onArtifact?: (update: A2AArtifactUpdate) => void;
  onError?: (error: A2ARpcError) => void;
}

// ------------------------------------------------------------------ client
const endpoint = (slug: string) => `/a2a/${slug}/`;

let nextRpcId = 1;

async function rpcPost(slug: string, method: string, params: unknown): Promise<Response> {
  return fetch(endpoint(slug), {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: nextRpcId++, method, params }),
  });
}

/** GET the public agent card; `null` when the flow is not served over A2A. */
export async function fetchAgentCard(
  slug: string,
): Promise<Record<string, unknown> | null> {
  try {
    const response = await fetch(`/a2a/${slug}/.well-known/agent-card.json`);
    return response.ok ? ((await response.json()) as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

/**
 * `message/stream`: send a user message and consume the SSE stream of
 * Task → TaskStatusUpdateEvents → TaskArtifactUpdateEvents. Passing `taskId`
 * continues an open task (answering input-required); passing only `contextId`
 * starts a new task in the same conversation (multi-turn, SPEC §7.6).
 * Resolves when the server closes the stream.
 */
export async function streamMessage(
  slug: string,
  message: { parts: A2APart[]; taskId?: string | null; contextId?: string | null },
  handlers: A2AStreamHandlers,
): Promise<void> {
  const wire: Record<string, unknown> = {
    role: "user",
    messageId: crypto.randomUUID(),
    parts: message.parts,
  };
  if (message.taskId) wire.taskId = message.taskId;
  if (message.contextId) wire.contextId = message.contextId;

  const response = await rpcPost(slug, "message/stream", { message: wire });
  if (!response.ok || !response.body) {
    throw new Error(`A2A stream failed: HTTP ${response.status}`);
  }
  await parseSseStream(response.body, (payload) => {
    const frame = payload as { result?: { kind?: string }; error?: A2ARpcError };
    if (frame.error) {
      handlers.onError?.(frame.error);
      return;
    }
    const result = frame.result;
    if (!result) return;
    if (result.kind === "task") handlers.onTask?.(result as A2ATask);
    else if (result.kind === "status-update") handlers.onStatus?.(result as A2AStatusUpdate);
    else if (result.kind === "artifact-update") {
      handlers.onArtifact?.(result as A2AArtifactUpdate);
    }
  });
}

/** `tasks/cancel` — request cancellation of an open task. */
export async function cancelTask(slug: string, taskId: string): Promise<void> {
  const response = await rpcPost(slug, "tasks/cancel", { id: taskId });
  if (!response.ok) throw new Error(`A2A cancel failed: HTTP ${response.status}`);
}

// ------------------------------------------------------------------ helpers
/** Concatenate the text parts of a message/artifact. */
export function textFromParts(parts: A2APart[] | undefined): string {
  return (parts ?? [])
    .filter((part): part is A2ATextPart => part.kind === "text")
    .map((part) => String(part.text ?? ""))
    .join("");
}

/**
 * Extract the normative interrupt payload (§5.5) from an `input-required`
 * status — the DataPart carries the ApprovalRequest/InputRequest verbatim,
 * with the TextPart prompt as fallback. `null` for any other state.
 */
export function interruptFromStatus(status: A2ATaskStatus): InterruptPayload | null {
  if (status.state !== "input-required") return null;
  const parts = status.message?.parts ?? [];
  const data = parts.find((part): part is A2ADataPart => part.kind === "data")?.data;
  if (data && typeof data === "object") return data as InterruptPayload;
  const text = parts.find((part): part is A2ATextPart => part.kind === "text")?.text;
  return { prompt: text ?? "input required" };
}
