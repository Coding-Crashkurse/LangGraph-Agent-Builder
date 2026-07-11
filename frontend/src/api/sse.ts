/** SSE helpers: one shared frame parser + the POST-based run stream (§6.2). */

import type { RunEvent } from "./types";

/**
 * Parse an SSE byte stream, invoking `onData` with the JSON payload of every
 * `data:` line. The frame separator is a blank line — sse-starlette emits CRLF
 * (`\r\n\r\n`), the a2a-sdk emits LF (`\n\n`); accept both or we parse zero
 * events. Frames whose payload is not JSON (heartbeats) are skipped.
 *
 * This is THE SSE parser — the run stream and the A2A JSON-RPC stream both go
 * through it so a framing fix lands everywhere at once.
 */
export async function parseSseStream(
  body: ReadableStream<Uint8Array>,
  onData: (payload: unknown) => void,
): Promise<void> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const frames = buffer.split(/\r?\n\r?\n/);
    buffer = frames.pop() ?? "";
    for (const frame of frames) {
      const dataLine = frame.split("\n").find((line) => line.startsWith("data:"));
      if (!dataLine) continue;
      let payload: unknown;
      try {
        payload = JSON.parse(dataLine.slice(5).trim());
      } catch {
        continue; // heartbeat frames carry non-JSON payloads
      }
      onData(payload);
    }
  }
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
  await parseSseStream(response.body, (payload) => onEvent(payload as RunEvent));
}
