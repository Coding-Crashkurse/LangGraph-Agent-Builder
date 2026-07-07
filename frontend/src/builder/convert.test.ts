import { describe, expect, it } from "vitest";

import type { FlowSpec } from "@/api/types";

import { canvasToSpec, specToCanvas } from "./convert";

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
      component_id: "lga.io.start",
      component_version: "1.0.0",
      config: {},
      position: { x: 0, y: 0 },
    },
    {
      id: "fake_llm_1",
      component_id: "lga.testing.fake_llm",
      component_version: "1.0.0",
      config: { replies: ["Hello from LGA!"] },
      position: { x: 300, y: 0 },
    },
    {
      id: "review",
      component_id: "lga.flow.human_approval",
      component_version: "1.0.0",
      config: {},
      position: { x: 450, y: 0 },
    },
    {
      id: "end",
      component_id: "lga.io.end",
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
