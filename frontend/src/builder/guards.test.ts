/** Guards run against the GENERATED /node-types fixture, mirroring core rules. */

import { describe, expect, it } from "vitest";

import type { DefinitionNode } from "@/api/types";

import { catalogFixture } from "./fixtures";
import { danglingEdgeIds, judgeConnection, nodePorts, portsCompatible } from "./guards";

const infoByType = new Map(catalogFixture.node_types.map((t) => [t.type, t]));

function node(type: string, config: Record<string, unknown>): DefinitionNode {
  return { id: `${type}_1`, type, version: 1, config };
}

describe("nodePorts", () => {
  it("derives llm_call inputs from {vars} in prompt + system_prompt", () => {
    const call = node("llm_call", {
      prompt: "Answer {question} using {context}",
      system_prompt: "You are {persona}. Not {{a_port}}.",
    });
    const { inputs, outputs } = nodePorts(call, infoByType.get("llm_call"), catalogFixture);
    expect(inputs.map((p) => p.name)).toEqual(["question", "context", "persona"]);
    expect(outputs.map((p) => p.name)).toEqual(["text"]);
  });

  it("adds a json output when structured_output is set", () => {
    const call = node("llm_call", { prompt: "{q}", structured_output: { type: "object" } });
    const { outputs } = nodePorts(call, infoByType.get("llm_call"), catalogFixture);
    expect(outputs.map((p) => `${p.name}:${p.type}`)).toEqual(["text:text", "json:json"]);
  });

  it("derives start outputs from input_schema properties (string→text, else json)", () => {
    const start = node("start", {
      input_schema: {
        type: "object",
        properties: { query: { type: "string" }, options: { type: "object" } },
      },
    });
    const { outputs } = nodePorts(start, infoByType.get("start"), catalogFixture);
    expect(outputs).toEqual([
      { name: "query", type: "text", label: "query" },
      { name: "options", type: "json", label: "options" },
    ]);
  });

  it("derives mcp_tool inputs from args keys", () => {
    const tool = node("mcp_tool", { tool: "t", args: { city: "location" } });
    const { inputs, outputs } = nodePorts(tool, infoByType.get("mcp_tool"), catalogFixture);
    expect(inputs.map((p) => p.name)).toEqual(["city"]);
    expect(outputs[0]).toMatchObject({ name: "result", type: "json" });
  });
});

describe("portsCompatible", () => {
  it("same type always connects", () => {
    expect(portsCompatible("text", "text", catalogFixture)).toBe(true);
  });
  it("honours the extra pairs served by the backend", () => {
    expect(portsCompatible("documents", "text", catalogFixture)).toBe(true);
    expect(portsCompatible("json", "text", catalogFixture)).toBe(true);
    expect(portsCompatible("text", "documents", catalogFixture)).toBe(false);
  });
});

describe("judgeConnection", () => {
  const retrieval = node("retrieval", { resource: "kb", collection: "docs" });
  const call = node("llm_call", { prompt: "{docs}" });

  it("accepts documents → text prompt var", () => {
    const verdict = judgeConnection(
      { node: retrieval, port: "documents" },
      { node: call, port: "docs" },
      infoByType,
      catalogFixture,
    );
    expect(verdict.ok).toBe(true);
  });

  it("rejects unknown ports with a reason", () => {
    const verdict = judgeConnection(
      { node: retrieval, port: "nope" },
      { node: call, port: "docs" },
      infoByType,
      catalogFixture,
    );
    expect(verdict.ok).toBe(false);
    expect(verdict.reason).toContain("no output port");
  });
});

describe("danglingEdgeIds", () => {
  it("flags edges whose ports vanished after a config change", () => {
    const call = node("llm_call", { prompt: "{message}" });
    const start = node("start", {
      input_schema: { type: "object", properties: { message: { type: "string" } } },
    });
    const edges = [{ from: "start_1.message", to: "llm_call_1.message" }];
    expect(danglingEdgeIds([start, call], edges, infoByType, catalogFixture).size).toBe(0);
    const retargeted = { ...call, config: { prompt: "{other}" } };
    const gone = danglingEdgeIds([start, retargeted], edges, infoByType, catalogFixture);
    expect([...gone]).toEqual(["start_1.message->llm_call_1.message"]);
  });
});
