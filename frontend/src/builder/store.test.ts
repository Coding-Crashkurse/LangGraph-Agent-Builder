/** Store unit tests: node actions (§11.2 kebab), autoLayout cycle safety,
 * run-state mapping (§11.2/§11.4) and edge family stamping (§11.3). */
import { beforeEach, describe, expect, it } from "vitest";

import type { ComponentDescriptor, RunEvent } from "@/api/types";

import type { CanvasEdge, CanvasNode } from "./convert";
import { useBuilder } from "./store";

function node(id: string, componentId = "lga.testing.fake_llm"): CanvasNode {
  return {
    id,
    type: "lga",
    deletable: id !== "start" && id !== "end",
    position: { x: 0, y: 0 },
    data: {
      componentId,
      componentVersion: "1.0.0",
      label: id,
      config: {},
      notes: "",
    },
  };
}

function edge(id: string, source: string, target: string, kind: "data" | "tool" | "router" = "data"): CanvasEdge {
  return {
    id,
    source,
    sourceHandle: "message",
    target,
    targetHandle: "input",
    data: { kind },
    type: "lga",
  };
}

function runEvent(event: string, data: Record<string, unknown> = {}): RunEvent {
  return { event, run_id: "r1", thread_id: "t1", seq: 0, ts: "", data };
}

const FAKE_LLM = {
  component_id: "lga.testing.fake_llm",
  version: "1.0.0",
  category: "testing",
  node_kind: "task",
  dynamic_outputs_from: null,
  fields: [
    { name: "api_key", type: "SecretInput", default: null, port_only: false },
    { name: "replies", type: "MultilineInput", default: null, port_only: false },
  ],
  outputs: [
    {
      name: "message",
      display_name: "Message",
      port: { schema_ref: "lga:Message", json_schema: {}, family: "MESSAGE", is_list: false },
      method: null,
      group: null,
    },
  ],
  input_ports: {},
} as unknown as ComponentDescriptor;

beforeEach(() => {
  useBuilder.setState({
    flow: null,
    baseSpec: null,
    nodes: [],
    edges: [],
    descriptors: new Map(),
    selectedNodeId: null,
    diagnostics: [],
    dirty: false,
    past: [],
    future: [],
    clipboard: null,
    dragging: false,
    runStates: {},
    runActive: false,
    partialTarget: null,
  });
});

describe("autoLayout (§11.8)", () => {
  it("terminates on a cyclic flow and still assigns columns", () => {
    useBuilder.setState({
      nodes: [node("start"), node("a"), node("b")],
      edges: [edge("e1", "start", "a"), edge("e2", "a", "b"), edge("e3", "b", "a")],
    });
    useBuilder.getState().autoLayout(); // pre-fix: unbounded BFS relaxation → hang
    const laid = useBuilder.getState().nodes;
    const x = (id: string) => laid.find((n) => n.id === id)!.position.x;
    expect(x("start")).toBeLessThan(x("a")); // a was relaxed from start before the cycle
    expect(new Set(laid.map((n) => `${n.position.x},${n.position.y}`)).size).toBe(3);
  });

  it("terminates on a pure 2-node cycle with no entry point", () => {
    useBuilder.setState({
      nodes: [node("a"), node("b")],
      edges: [edge("e1", "a", "b"), edge("e2", "b", "a")],
    });
    useBuilder.getState().autoLayout();
    expect(useBuilder.getState().nodes).toHaveLength(2);
  });

  it("layers a DAG left → right by longest path", () => {
    useBuilder.setState({
      nodes: [node("start"), node("a"), node("b"), node("end")],
      edges: [
        edge("e1", "start", "a"),
        edge("e2", "a", "b"),
        edge("e3", "start", "b"), // shortcut must not pull b left of a
        edge("e4", "b", "end"),
      ],
    });
    useBuilder.getState().autoLayout();
    const laid = useBuilder.getState().nodes;
    const x = (id: string) => laid.find((n) => n.id === id)!.position.x;
    expect(x("start")).toBeLessThan(x("a"));
    expect(x("a")).toBeLessThan(x("b"));
    expect(x("b")).toBeLessThan(x("end"));
  });
});

describe("node actions (§11.2 kebab menu)", () => {
  it("renameNode updates the label, dirties, and undo restores it", () => {
    useBuilder.setState({ nodes: [node("a")] });
    useBuilder.getState().renameNode("a", "My Agent");
    expect(useBuilder.getState().nodes[0].data.label).toBe("My Agent");
    expect(useBuilder.getState().dirty).toBe(true);
    useBuilder.getState().undo();
    expect(useBuilder.getState().nodes[0].data.label).toBe("a");
  });

  it("duplicateNode clones with a fresh id, offset position and stripped secrets (§11.8)", () => {
    const original = node("fake_llm_1");
    original.data.config = { api_key: "sk-secret", replies: "hi" };
    useBuilder.setState({
      nodes: [original],
      descriptors: new Map([["lga.testing.fake_llm", FAKE_LLM]]),
    });
    const id = useBuilder.getState().duplicateNode("fake_llm_1");
    expect(id).toBe("fake_llm_2");
    const copy = useBuilder.getState().nodes.find((n) => n.id === "fake_llm_2")!;
    expect(copy.data.config.api_key).toBeUndefined();
    expect(copy.data.config.replies).toBe("hi");
    expect(copy.position).toEqual({ x: 48, y: 48 });
    expect(useBuilder.getState().selectedNodeId).toBe("fake_llm_2");
  });

  it("duplicateNode refuses start/end", () => {
    useBuilder.setState({ nodes: [node("start")] });
    expect(useBuilder.getState().duplicateNode("start")).toBeNull();
    expect(useBuilder.getState().nodes).toHaveLength(1);
  });

  it("deleteNode removes the node plus its edges and clears selection", () => {
    useBuilder.setState({
      nodes: [node("start"), node("a"), node("end")],
      edges: [edge("e1", "start", "a"), edge("e2", "a", "end")],
      selectedNodeId: "a",
    });
    useBuilder.getState().deleteNode("a");
    expect(useBuilder.getState().nodes.map((n) => n.id)).toEqual(["start", "end"]);
    expect(useBuilder.getState().edges).toEqual([]);
    expect(useBuilder.getState().selectedNodeId).toBeNull();
    useBuilder.getState().undo();
    expect(useBuilder.getState().nodes).toHaveLength(3);
  });

  it("deleteNode refuses the reserved start/end nodes (E030)", () => {
    useBuilder.setState({ nodes: [node("start"), node("end")] });
    useBuilder.getState().deleteNode("start");
    expect(useBuilder.getState().nodes).toHaveLength(2);
  });

  it("toggleCollapsed flips canvas-only view state without dirtying the draft", () => {
    useBuilder.setState({ nodes: [node("a")] });
    useBuilder.getState().toggleCollapsed("a");
    expect(useBuilder.getState().nodes[0].data.collapsed).toBe(true);
    expect(useBuilder.getState().dirty).toBe(false);
    useBuilder.getState().toggleCollapsed("a");
    expect(useBuilder.getState().nodes[0].data.collapsed).toBe(false);
  });
});

describe("edge family stamping (§11.3)", () => {
  it("addEdge resolves the source port family from the descriptor", () => {
    useBuilder.setState({
      nodes: [node("fake_llm_1")],
      descriptors: new Map([["lga.testing.fake_llm", FAKE_LLM]]),
    });
    useBuilder.getState().addEdge(edge("e1", "fake_llm_1", "end"));
    expect(useBuilder.getState().edges[0].data?.family).toBe("MESSAGE");
  });

  it("setDescriptors backfills families on edges loaded before descriptors", () => {
    useBuilder.setState({
      nodes: [node("fake_llm_1")],
      edges: [edge("e1", "fake_llm_1", "end")],
    });
    expect(useBuilder.getState().edges[0].data?.family).toBeUndefined();
    useBuilder.getState().setDescriptors([FAKE_LLM]);
    expect(useBuilder.getState().edges[0].data?.family).toBe("MESSAGE");
  });
});

describe("run-state mapping (§11.2/§11.4)", () => {
  it("tracks the run lifecycle for the live-edge animation", () => {
    const apply = useBuilder.getState().applyRunEvent;
    apply(runEvent("run_started"));
    expect(useBuilder.getState().runActive).toBe(true);
    apply(runEvent("node_started", { node_id: "a" }));
    expect(useBuilder.getState().runStates.a).toEqual({ status: "running" });
    apply(runEvent("node_finished", { node_id: "a", duration_ms: 12 }));
    expect(useBuilder.getState().runStates.a).toEqual({ status: "finished", durationMs: 12 });
    apply(runEvent("run_finished"));
    expect(useBuilder.getState().runActive).toBe(false);
  });

  it("interrupt_raised marks the HITL node interrupted and parks the animation", () => {
    const apply = useBuilder.getState().applyRunEvent;
    apply(runEvent("run_started"));
    apply(runEvent("interrupt_raised", { node_id: "review", payload: { kind: "approval" } }));
    expect(useBuilder.getState().runStates.review).toEqual({ status: "interrupted" });
    expect(useBuilder.getState().runActive).toBe(false);
    // resume clears the amber ring
    apply(runEvent("run_resumed"));
    expect(useBuilder.getState().runStates.review).toBeUndefined();
    expect(useBuilder.getState().runActive).toBe(true);
  });

  it("resetRunStates clears node states and the active flag", () => {
    useBuilder.setState({ runStates: { a: { status: "running" } }, runActive: true });
    useBuilder.getState().resetRunStates();
    expect(useBuilder.getState().runStates).toEqual({});
    expect(useBuilder.getState().runActive).toBe(false);
  });
});
