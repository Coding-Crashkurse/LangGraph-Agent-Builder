/** Regression: dynamically-refreshed fields (liveFields from
 * POST /components/{cid}/config) must never leak from one node's inspector
 * into another — the inner Inspector is keyed by node id. Also pins that the
 * inspector resolves defaults through convert.ts's defaultConfig. */

import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  api: { components: { configChange: vi.fn() } },
}));
vi.mock("@/api/sse", () => ({ streamRun: vi.fn() }));

import { api } from "@/api/client";
import type { ComponentDescriptor, FieldDescriptor } from "@/api/types";

import { ConfigPanel } from "../ConfigPanel";
import type { CanvasNode } from "../convert";
import { useBuilder } from "../store";

function makeField(overrides: Partial<FieldDescriptor> & { name: string }): FieldDescriptor {
  return {
    type: "StrInput",
    display_name: overrides.name,
    info: "",
    required: false,
    default: null,
    advanced: false,
    show: true,
    dynamic: false,
    real_time_refresh: false,
    refresh_button: false,
    placeholder: "",
    tool_mode: false,
    accepts_global_variable: false,
    deprecated: false,
    as_port: null,
    port_only: false,
    ...overrides,
  };
}

function makeDescriptor(
  componentId: string,
  fields: FieldDescriptor[],
): ComponentDescriptor {
  return {
    component_id: componentId,
    version: "1.0.0",
    display_name: componentId,
    description: "",
    icon: "",
    category: "data",
    tags: [],
    beta: false,
    legacy: false,
    node_kind: "task",
    tool_mode_supported: false,
    dynamic_outputs_from: null,
    fields,
    outputs: [],
    input_ports: {},
    config_schema: {},
  };
}

function makeNode(id: string, componentId: string): CanvasNode {
  return {
    id,
    type: "lga",
    position: { x: 0, y: 0 },
    data: { componentId, componentVersion: "1.0.0", label: "", config: {}, notes: "" },
  };
}

const descriptorA = makeDescriptor("test.a", [
  makeField({
    name: "mode",
    display_name: "Mode",
    type: "DropdownInput",
    options: [],
    options_source: "modes",
    refresh_button: true,
  }),
]);
const descriptorB = makeDescriptor("test.b", [
  makeField({ name: "text", display_name: "Text", default: "hello" }),
]);

beforeEach(() => {
  vi.clearAllMocks();
  useBuilder.setState({
    nodes: [makeNode("a", "test.a"), makeNode("b", "test.b")],
    edges: [],
    descriptors: new Map([
      ["test.a", descriptorA],
      ["test.b", descriptorB],
    ]),
    selectedNodeId: null,
    diagnostics: [],
  });
});

describe("ConfigPanel dynamic fields", () => {
  it("shows an empty state when nothing is selected", () => {
    render(<ConfigPanel />);
    expect(screen.getByText("Select a node to configure")).toBeInTheDocument();
  });

  it("does not leak dynamically-refreshed fields into another node", async () => {
    vi.mocked(api.components.configChange).mockResolvedValue({
      config: { mode: "x" },
      fields: [
        descriptorA.fields[0],
        makeField({ name: "dynamic_extra", display_name: "Dynamic Extra" }),
      ],
      outputs: [],
      input_ports: {},
    });

    act(() => useBuilder.getState().select("a"));
    render(<ConfigPanel />);

    // trigger a dynamic refresh on node A → liveFields now include Dynamic Extra
    fireEvent.click(screen.getByRole("button", { name: "Refresh options from server" }));
    expect(await screen.findByText("Dynamic Extra")).toBeInTheDocument();
    expect(api.components.configChange).toHaveBeenCalledTimes(1);

    // selecting node B must render B's descriptor fields, NOT A's live list
    act(() => useBuilder.getState().select("b"));
    expect(screen.queryByText("Dynamic Extra")).not.toBeInTheDocument();
    expect(screen.getByText("Text")).toBeInTheDocument();

    // …and back on A the stale live list is gone too (state was remounted)
    act(() => useBuilder.getState().select("a"));
    expect(screen.queryByText("Dynamic Extra")).not.toBeInTheDocument();
    expect(screen.getByText("Mode")).toBeInTheDocument();
  });

  it("resolves unset values through convert.ts defaultConfig", () => {
    act(() => useBuilder.getState().select("b"));
    render(<ConfigPanel />);
    // node B's config is empty; the descriptor default must show in the widget
    expect(screen.getByDisplayValue("hello")).toBeInTheDocument();
  });
});
