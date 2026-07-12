import { beforeEach, describe, expect, it } from "vitest";

import { catalogFixture, definitionFixture } from "./fixtures";
import { useBuilder } from "./store";

function fresh() {
  useBuilder.getState().load(definitionFixture(), catalogFixture);
  return useBuilder.getState();
}

describe("builder store", () => {
  beforeEach(fresh);

  it("load → currentDefinition round-trips the definition", () => {
    const current = useBuilder.getState().currentDefinition();
    const original = definitionFixture();
    expect(current.nodes).toEqual(original.nodes);
    expect(current.edges).toEqual(original.edges);
    expect(current.name).toBe(original.name);
  });

  it("addNode assigns catalog-conform ids and empty config", () => {
    useBuilder.getState().addNode("llm_call", { x: 5, y: 5 });
    useBuilder.getState().addNode("llm_call", { x: 6, y: 6 });
    const ids = useBuilder.getState().nodes.map((n) => n.id);
    expect(ids).toContain("call_2"); // call_1 exists in the fixture
    expect(ids).toContain("call_3");
    const added = useBuilder.getState().nodes.find((n) => n.id === "call_2")!;
    expect(added.data.def).toEqual({ id: "call_2", type: "llm_call", version: 1, config: {} });
    expect(useBuilder.getState().dirty).toBe(true);
  });

  it("onConnect refuses incompatible ports", () => {
    const state = useBuilder.getState();
    state.addNode("retrieval", { x: 0, y: 0 });
    const before = useBuilder.getState().edges.length;
    // retrieval.documents (documents) → start has no inputs; use end.input (text): allowed
    useBuilder.getState().onConnect({
      source: "retrieve_1",
      sourceHandle: "documents",
      target: "end_1",
      targetHandle: "input",
    });
    expect(useBuilder.getState().edges.length).toBe(before + 1);
    // text → documents direction is NOT connectable
    useBuilder.getState().onConnect({
      source: "call_1",
      sourceHandle: "text",
      target: "retrieve_1",
      targetHandle: "documents",
    });
    expect(useBuilder.getState().edges.length).toBe(before + 1);
  });

  it("updateNodeConfig prunes edges whose ports vanished", () => {
    expect(useBuilder.getState().edges.map((e) => e.id)).toContain(
      "start_1.message->call_1.message",
    );
    useBuilder.getState().updateNodeConfig("call_1", { prompt: "{renamed}" });
    expect(useBuilder.getState().edges.map((e) => e.id)).not.toContain(
      "start_1.message->call_1.message",
    );
  });

  it("validation state resets on semantic change", () => {
    useBuilder.getState().setValidation({ valid: true, runtime_checked: false, issues: [] });
    expect(useBuilder.getState().validated).toBe(true);
    useBuilder.getState().updateNodeConfig("call_1", { prompt: "{x}" });
    expect(useBuilder.getState().validated).toBe(false);
  });
});
