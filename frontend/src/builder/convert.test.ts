import { describe, expect, it } from "vitest";

import { canvasToDefinition, definitionToCanvas, metaOf } from "./convert";
import { definitionFixture } from "./fixtures";

describe("definition ↔ canvas", () => {
  it("round-trips a definition through the canvas", () => {
    const definition = definitionFixture();
    const { nodes, edges } = definitionToCanvas(definition);
    const back = canvasToDefinition(metaOf(definition), nodes, edges);
    expect(back.nodes).toEqual(definition.nodes);
    expect(back.edges).toEqual(definition.edges);
    expect(back.name).toBe(definition.name);
    expect(back.expose).toEqual(definition.expose);
  });

  it("reads positions from layout and writes them back rounded", () => {
    const definition = definitionFixture();
    const { nodes, edges } = definitionToCanvas(definition);
    const start = nodes.find((n) => n.id === "start_1")!;
    expect(start.position).toEqual({ x: 10, y: 20 });
    start.position = { x: 100.6, y: 200.4 };
    const back = canvasToDefinition(metaOf(definition), nodes, edges);
    expect(back.layout?.nodes.start_1).toEqual({ x: 101, y: 200 });
  });

  it("moving a node changes only the layout block", () => {
    const definition = definitionFixture();
    const a = definitionToCanvas(definition);
    const b = definitionToCanvas(definition);
    b.nodes[0] = { ...b.nodes[0], position: { x: 999, y: 999 } };
    const defA = canvasToDefinition(metaOf(definition), a.nodes, a.edges);
    const defB = canvasToDefinition(metaOf(definition), b.nodes, b.edges);
    expect({ ...defA, layout: null }).toEqual({ ...defB, layout: null });
    expect(defA.layout).not.toEqual(defB.layout);
  });

  it("start/end nodes are not deletable on the canvas", () => {
    const { nodes } = definitionToCanvas(definitionFixture());
    expect(nodes.find((n) => n.id === "start_1")?.deletable).toBe(false);
    expect(nodes.find((n) => n.id === "call_1")?.deletable).toBe(true);
  });

  it("maps edges to react-flow handles (node.port)", () => {
    const { edges } = definitionToCanvas(definitionFixture());
    const edge = edges.find((e) => e.id === "start_1.message->call_1.message")!;
    expect(edge.source).toBe("start_1");
    expect(edge.sourceHandle).toBe("message");
    expect(edge.target).toBe("call_1");
    expect(edge.targetHandle).toBe("message");
  });
});
