import { describe, expect, it } from "vitest";

import type { ComponentDescriptor, FieldDescriptor, FlowSpec } from "@/api/types";

import {
  canvasToSpec,
  defaultConfig,
  edgeSourceFamily,
  specToCanvas,
  withEdgeFamilies,
} from "./convert";

const FIXTURE: FlowSpec = {
  schema_version: "1",
  flow: {
    name: "hello",
    slug: "hello",
    description: "smoke test",
    a2a: { enabled: true, description: "Replies with a scripted greeting." },
  },
  nodes: [
    {
      id: "start",
      component_id: "lab.io.start",
      component_version: "1.0.0",
      config: {},
      position: { x: 0, y: 0 },
    },
    {
      id: "fake_llm_1",
      component_id: "lab.testing.fake_llm",
      component_version: "1.0.0",
      config: { replies: ["Hello from LAB!"] },
      position: { x: 300, y: 0 },
    },
    {
      id: "review",
      component_id: "lab.flow.human_approval",
      component_version: "1.0.0",
      config: {},
      position: { x: 450, y: 0 },
    },
    {
      id: "end",
      component_id: "lab.io.end",
      component_version: "1.0.0",
      config: {},
      position: { x: 600, y: 0 },
    },
  ],
  edges: [
    {
      id: "e1",
      kind: "data",
      source: { node: "start", output: "message" },
      target: { node: "fake_llm_1", input: "input" },
    },
    {
      id: "t1",
      kind: "tool",
      source: { node: "fake_llm_1", output: "toolset" },
      target: { node: "review", input: "tools" },
    },
    {
      id: "r1",
      kind: "router",
      source: { node: "review", output: "approve" },
      target: { node: "end", input: "" },
    },
  ],
};

/** minimal descriptor: `start` with a MESSAGE output named `message` */
const START_DESCRIPTOR = {
  component_id: "lab.io.start",
  version: "1.0.0",
  category: "io",
  node_kind: "task",
  dynamic_outputs_from: null,
  fields: [],
  outputs: [
    {
      name: "message",
      display_name: "Message",
      port: { schema_ref: "lab:Message", json_schema: {}, family: "MESSAGE", is_list: false },
      method: null,
      group: null,
    },
  ],
  input_ports: {},
} as unknown as ComponentDescriptor;

const DESCRIPTORS = new Map([["lab.io.start", START_DESCRIPTOR]]);

describe("FlowSpec ⇄ canvas mapping (SPEC §5.2)", () => {
  it("round-trips nodes and edges losslessly", () => {
    const { nodes, edges } = specToCanvas(FIXTURE);
    expect(nodes).toHaveLength(4);
    expect(edges).toHaveLength(3);
    const back = canvasToSpec(FIXTURE, nodes, edges);
    expect(back.nodes.map((n) => n.id)).toEqual(FIXTURE.nodes.map((n) => n.id));
    expect(back.edges).toEqual(FIXTURE.edges);
    expect(back.flow).toEqual(FIXTURE.flow); // flow-level settings untouched
  });

  it("keeps edge kinds on canvas edges (dashed tool / amber router rendering)", () => {
    const { edges } = specToCanvas(FIXTURE);
    expect(edges.map((e) => e.data?.kind)).toEqual(["data", "tool", "router"]);
  });

  it("router edges target the implicit control-in handle", () => {
    const { edges } = specToCanvas(FIXTURE);
    expect(edges[2].targetHandle).toBe("__in__");
  });

  it("resolves the SOURCE port family onto edges at load time (§11.3)", () => {
    const { edges } = specToCanvas(FIXTURE, DESCRIPTORS);
    // data edge: from the start descriptor's `message` output
    expect(edges[0].data?.family).toBe("MESSAGE");
    // tool / router edges have fixed families regardless of descriptors
    expect(edges[1].data?.family).toBe("TOOLSET");
    expect(edges[2].data?.family).toBe("ROUTE");
  });

  it("edge family is canvas-only — never leaks into the FlowSpec", () => {
    const { nodes, edges } = specToCanvas(FIXTURE, DESCRIPTORS);
    const back = canvasToSpec(FIXTURE, nodes, edges);
    expect(back.edges).toEqual(FIXTURE.edges);
  });

  it("withEdgeFamilies backfills only unresolved edges (descriptors arrive late)", () => {
    const { nodes, edges } = specToCanvas(FIXTURE); // no descriptors yet
    expect(edges[0].data?.family).toBeUndefined();
    const filled = withEdgeFamilies(nodes, edges, DESCRIPTORS);
    expect(filled[0].data?.family).toBe("MESSAGE");
    // unknown source components stay unresolved instead of guessing
    expect(
      edgeSourceFamily(
        { source: "fake_llm_1", sourceHandle: "toolset", data: { kind: "data" } },
        nodes,
        DESCRIPTORS,
      ),
    ).toBeUndefined();
  });

  it("defaultConfig merge: config wins, descriptor default fills the gap", () => {
    const descriptor = {
      fields: [
        { name: "temperature", default: 0.7, port_only: false } as unknown as FieldDescriptor,
        { name: "prompt", default: null, port_only: false } as unknown as FieldDescriptor,
        { name: "message", default: "hi", port_only: true } as unknown as FieldDescriptor,
      ],
    } as unknown as ComponentDescriptor;
    // null defaults and port-only fields never materialize into config
    expect(defaultConfig(descriptor)).toEqual({ temperature: 0.7 });
    // node card + inspector both resolve via {...defaults, ...config}
    const effective = { ...defaultConfig(descriptor), temperature: 0 };
    expect(effective.temperature).toBe(0); // 0 is a real value
  });

  it("round-trips sticky notes through ui.sticky_notes (§11.8)", () => {
    const withNote: FlowSpec = {
      ...FIXTURE,
      ui: {
        sticky_notes: [
          { id: "note_1", text: "remember the SSRF guard", position: { x: 10, y: 20 }, color: "sky" },
        ],
      },
    };
    const { nodes, edges } = specToCanvas(withNote);
    const note = nodes.find((n) => n.type === "note");
    expect(note?.data.notes).toBe("remember the SSRF guard");
    // notes are canvas-only: they never leak into spec.nodes
    const back = canvasToSpec(withNote, nodes, edges);
    expect(back.nodes.map((n) => n.id)).toEqual(FIXTURE.nodes.map((n) => n.id));
    expect(back.ui?.sticky_notes).toEqual(withNote.ui?.sticky_notes);
  });
});
