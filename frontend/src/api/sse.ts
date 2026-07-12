/** SSE frame parser shared by every streaming consumer (A2A message:stream). */

/**
 * Parse an SSE byte stream, invoking `onData` with the JSON payload of every
 * `data:` line. The frame separator is a blank line — servers emit CRLF
 * (`\r\n\r\n`) or LF (`\n\n`); accept both or we parse zero events. Frames
 * whose payload is not JSON (heartbeats) are skipped.
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
