import { describe, expect, it } from "vitest";

import type { ComponentInfo, Flow } from "@/api/types";
import { canvasToSpec, specToCanvas } from "./convert";
import { checkConnection } from "./guards";

const components: Record<string, ComponentInfo> = {
  fake_llm: {
    name: "fake_llm",
    display_name: "Fake LLM",
    description: "",
    category: "llm",
    version: 1,
    kind: "node",
    accepts_attachments: [],
    state_reads: [],
    state_writes: [],
    config_json_schema: {},
  },
  llm_agent: {
    name: "llm_agent",
    display_name: "Agent",
    description: "",
    category: "llm",
    version: 1,
    kind: "node",
    accepts_attachments: ["tools"],
    state_reads: [],
    state_writes: [],
    config_json_schema: {},
  },
  human_approval: {
    name: "human_approval",
    display_name: "Approval",
    description: "",
    category: "flow",
    version: 1,
    kind: "router",
    accepts_attachments: [],
    state_reads: [],
    state_writes: [],
    config_json_schema: {},
    outputs_static: ["approved", "rejected"],
  },
  mcp_toolset: {
    name: "mcp_toolset",
    display_name: "MCP Toolset",
    description: "",
    category: "tools",
    version: 1,
    kind: "tool_provider",
    accepts_attachments: [],
    state_reads: [],
    state_writes: [],
    config_json_schema: {},
    attachment_kind: "tools",
  },
};

const flow: Flow = {
  id: "f1",
  slug: "demo",
  name: "Demo",
  description: "",
  version: 1,
  nodes: [
    {
      id: "agent",
      component: "llm_agent",
      component_version: 1,
      config: { model: "openai:gpt-4o-mini" },
      position: { x: 100, y: 50 },
    },
    {
      id: "tools",
      component: "mcp_toolset",
      component_version: 1,
      config: { url: "http://x/mcp" },
      position: { x: 100, y: 220 },
    },
    {
      id: "review",
      component: "human_approval",
      component_version: 1,
      config: {},
      position: { x: 340, y: 50 },
    },
  ],
  edges: [
    { kind: "control", source: "__start__", source_handle: null, target: "agent" },
    { kind: "control", source: "agent", source_handle: null, target: "review" },
    { kind: "attach", source: "tools", target: "agent" },
    { kind: "control", source: "review", source_handle: "approved", target: "__end__" },
    { kind: "control", source: "review", source_handle: "rejected", target: "agent" },
  ],
  publish: {
    a2a: true,
    mcp: false,
    agent_card: {
      name: "",
      description: "",
      skills: [],
      default_input_modes: [],
      default_output_modes: [],
      provider_organization: "",
      provider_url: "",
    },
    mcp_tool: { name: "run", description: "" },
  },
  is_published: false,
  endpoints: {},
  created_at: "",
  updated_at: "",
};

describe("spec <-> canvas round trip", () => {
  it("survives specToCanvas -> canvasToSpec unchanged", () => {
    const { nodes, edges } = specToCanvas(flow, components);
    const spec = canvasToSpec(nodes, edges);
    expect(spec.nodes.map((n) => n.id).sort()).toEqual(["agent", "review", "tools"]);
    expect(spec.edges).toEqual(flow.edges);
  });

  it("adds start/end terminals to the canvas only", () => {
    const { nodes } = specToCanvas(flow, components);
    expect(nodes.filter((n) => n.type === "terminal")).toHaveLength(2);
    const spec = canvasToSpec(nodes, []);
    expect(spec.nodes.find((n) => n.id.startsWith("__"))).toBeUndefined();
  });
});

describe("edge guards mirror compiler rules", () => {
  const { nodes, edges } = specToCanvas(flow, components);

  it("rejects a second outgoing control edge from a plain node", () => {
    const verdict = checkConnection(
      { source: "agent", sourceHandle: "out", target: "__end__", targetHandle: "in" },
      nodes,
      edges,
    );
    expect(verdict.ok).toBe(false);
    expect(verdict.reason).toMatch(/one outgoing/);
  });

  it("rejects attach edges into non-accepting nodes", () => {
    const verdict = checkConnection(
      { source: "tools", sourceHandle: "attach-out", target: "review", targetHandle: "attach" },
      nodes,
      edges,
    );
    expect(verdict.ok).toBe(false);
  });

  it("rejects rewiring an already-wired router output", () => {
    const verdict = checkConnection(
      { source: "review", sourceHandle: "approved", target: "agent", targetHandle: "in" },
      nodes,
      edges,
    );
    expect(verdict.ok).toBe(false);
    expect(verdict.reason).toMatch(/already wired/);
  });

  it("rejects control edges from tool providers", () => {
    const verdict = checkConnection(
      { source: "tools", sourceHandle: "out", target: "review", targetHandle: "in" },
      nodes,
      edges,
    );
    expect(verdict.ok).toBe(false);
  });

  it("accepts a valid attach edge", () => {
    const withoutAttach = edges.filter((e) => e.targetHandle !== "attach");
    const verdict = checkConnection(
      { source: "tools", sourceHandle: "attach-out", target: "agent", targetHandle: "attach" },
      nodes,
      withoutAttach,
    );
    expect(verdict.ok).toBe(true);
  });
});
