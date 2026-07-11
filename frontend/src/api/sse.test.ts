/** Fixture suite for THE shared SSE frame parser (§6.2). The CRLF-vs-LF and
 * split-chunk cases are the regressions that motivated deduplicating it. */

import { describe, expect, it } from "vitest";

import { parseSseStream } from "./sse";

function streamOf(chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

async function collect(chunks: string[]): Promise<unknown[]> {
  const payloads: unknown[] = [];
  await parseSseStream(streamOf(chunks), (payload) => payloads.push(payload));
  return payloads;
}

describe("parseSseStream", () => {
  it("parses LF-separated frames (a2a-sdk style)", async () => {
    const payloads = await collect(['data: {"a":1}\n\ndata: {"a":2}\n\n']);
    expect(payloads).toEqual([{ a: 1 }, { a: 2 }]);
  });

  it("parses CRLF-separated frames (sse-starlette style)", async () => {
    const payloads = await collect(['data: {"a":1}\r\n\r\ndata: {"a":2}\r\n\r\n']);
    expect(payloads).toEqual([{ a: 1 }, { a: 2 }]);
  });

  it("reassembles a frame split across chunk boundaries", async () => {
    const payloads = await collect(['data: {"eve', 'nt":"node_started"}', "\n\n"]);
    expect(payloads).toEqual([{ event: "node_started" }]);
  });

  it("skips heartbeat frames whose payload is not JSON", async () => {
    const payloads = await collect(['data: ping\n\ndata: {"ok":true}\n\n']);
    expect(payloads).toEqual([{ ok: true }]);
  });

  it("ignores frames without a data: line (comments / event-only)", async () => {
    const payloads = await collect([': keep-alive\n\nevent: end\n\ndata: {"n":3}\n\n']);
    expect(payloads).toEqual([{ n: 3 }]);
  });

  it("finds the data: line in multi-line frames", async () => {
    const payloads = await collect(['event: message\nid: 7\ndata: {"seq":7}\n\n']);
    expect(payloads).toEqual([{ seq: 7 }]);
  });

  it("does not emit the trailing unterminated buffer", async () => {
    const payloads = await collect(['data: {"a":1}\n\ndata: {"a":', "2}"]);
    expect(payloads).toEqual([{ a: 1 }]); // frame 2 never got its blank line
  });
});
