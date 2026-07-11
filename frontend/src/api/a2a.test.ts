/** Tests for the A2A JSON-RPC client (SPEC §7.5–§7.7): stream dispatch by
 * result.kind, interrupt extraction from input-required, cancel + card. */

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  cancelTask,
  fetchAgentCard,
  interruptFromStatus,
  streamMessage,
  textFromParts,
  type A2AStatusUpdate,
  type A2ATask,
} from "./a2a";

function sseBody(frames: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const frame of frames) controller.enqueue(encoder.encode(`data: ${frame}\n\n`));
      controller.close();
    },
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("streamMessage", () => {
  it("dispatches task / status-update / artifact-update / error frames", async () => {
    const frames = [
      '{"jsonrpc":"2.0","id":1,"result":{"kind":"task","id":"t1","contextId":"c1","status":{"state":"submitted"}}}',
      '{"result":{"kind":"status-update","taskId":"t1","contextId":"c1","final":false,"status":{"state":"working"}}}',
      '{"result":{"kind":"artifact-update","taskId":"t1","artifact":{"artifactId":"a1","name":"result","parts":[{"kind":"text","text":"hi"}]}}}',
      '{"error":{"code":-32001,"message":"boom"}}',
    ];
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200, body: sseBody(frames) }));
    vi.stubGlobal("fetch", fetchMock);

    const tasks: A2ATask[] = [];
    const statuses: A2AStatusUpdate[] = [];
    const artifacts: string[] = [];
    const errors: string[] = [];
    await streamMessage(
      "my-agent",
      { parts: [{ kind: "text", text: "hello" }], taskId: "t0", contextId: "c1" },
      {
        onTask: (task) => tasks.push(task),
        onStatus: (update) => statuses.push(update),
        onArtifact: (update) => artifacts.push(textFromParts(update.artifact.parts)),
        onError: (error) => errors.push(`${error.code}: ${error.message}`),
      },
    );

    expect(tasks.map((t) => t.id)).toEqual(["t1"]);
    expect(statuses.map((s) => s.status.state)).toEqual(["working"]);
    expect(artifacts).toEqual(["hi"]);
    expect(errors).toEqual(["-32001: boom"]);

    // wire shape: JSON-RPC message/stream against the slug mount, with the
    // resume taskId + contextId threaded into the message
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/a2a/my-agent/");
    const sent = JSON.parse(String(init.body)) as {
      method: string;
      params: { message: Record<string, unknown> };
    };
    expect(sent.method).toBe("message/stream");
    expect(sent.params.message.taskId).toBe("t0");
    expect(sent.params.message.contextId).toBe("c1");
    expect(sent.params.message.parts).toEqual([{ kind: "text", text: "hello" }]);
    expect(sent.params.message.messageId).toBeTruthy();
  });

  it("rejects on a non-OK response", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404, body: null })));
    await expect(
      streamMessage("nope", { parts: [{ kind: "text", text: "x" }] }, {}),
    ).rejects.toThrow("HTTP 404");
  });
});

describe("interruptFromStatus (§5.5)", () => {
  it("returns the DataPart payload verbatim for input-required", () => {
    const payload = interruptFromStatus({
      state: "input-required",
      message: {
        role: "agent",
        messageId: "m1",
        parts: [
          { kind: "text", text: "approve?" },
          { kind: "data", data: { kind: "approval", prompt: "approve?", options: ["approve"] } },
        ],
      },
    });
    expect(payload).toEqual({ kind: "approval", prompt: "approve?", options: ["approve"] });
  });

  it("falls back to the TextPart prompt when no DataPart exists", () => {
    const payload = interruptFromStatus({
      state: "input-required",
      message: { role: "agent", messageId: "m1", parts: [{ kind: "text", text: "name?" }] },
    });
    expect(payload).toEqual({ prompt: "name?" });
  });

  it("returns null for non-interrupt states", () => {
    expect(interruptFromStatus({ state: "working" })).toBeNull();
    expect(interruptFromStatus({ state: "completed" })).toBeNull();
  });
});

describe("cancelTask / fetchAgentCard", () => {
  it("POSTs tasks/cancel with the task id", async () => {
    const fetchMock = vi.fn(async () => ({ ok: true, status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    await cancelTask("my-agent", "t9");
    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/a2a/my-agent/");
    const sent = JSON.parse(String(init.body)) as { method: string; params: { id: string } };
    expect(sent.method).toBe("tasks/cancel");
    expect(sent.params.id).toBe("t9");
  });

  it("fetchAgentCard returns null when the agent is not served", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: false, status: 404 })));
    expect(await fetchAgentCard("ghost")).toBeNull();
  });

  it("fetchAgentCard returns the card JSON when served", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ name: "agent" }) })),
    );
    expect(await fetchAgentCard("live")).toEqual({ name: "agent" });
  });
});
