/** Publish wizard (ShareDialog): the door picker writes serving.mode + the
 * derived a2a/mcp booleans, and the per-door forms surface publish guards live
 * (E060/E062), gate the gRPC transport on /config.a2a_grpc_available, and flag
 * human-in-the-loop flows on the A2A door (REFACTOR.md §5.3). */

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { FlowInfo, FlowMeta, FlowSpec } from "@/api/types";

import type { CanvasNode } from "./convert";
import { ShareDialog } from "./PublishDialog";
import { useBuilder } from "./store";

// useServerConfig drives the gRPC gate — mock it with a mutable holder so tests
// can flip a2a_grpc_available without a QueryClient.
const { serverConfig } = vi.hoisted(() => ({
  serverConfig: { auto_saving: false, auto_saving_interval_ms: 1000, a2a_grpc_available: false },
}));
vi.mock("./hooks/useServerConfig", () => ({ useServerConfig: () => serverConfig }));
// never resolves — keeps the async setCard out of the assertions (no act warning)
vi.mock("@/api/a2a", () => ({ fetchAgentCard: vi.fn(() => new Promise<null>(() => {})) }));
vi.mock("@/api/client", () => ({ api: { flows: { export: vi.fn(), publish: vi.fn() } } }));

function makeSpec(flowPatch: Partial<FlowMeta> = {}): FlowSpec {
  return {
    schema_version: "1.0.0",
    flow: {
      name: "My Flow",
      slug: "my-flow",
      description: "",
      a2a: { enabled: false },
      mcp: { enabled: false },
      serving: { mode: "api" },
      ...flowPatch,
    },
    nodes: [],
    edges: [],
  };
}

const flow: FlowInfo = {
  id: "f1",
  slug: "my-flow",
  name: "My Flow",
  description: "",
  spec: makeSpec(),
  serve_version: "latest_published",
  published_version: null,
  created_at: "2026-01-01",
  updated_at: "2026-01-01",
};

function interruptNode(id: string, componentId: string): CanvasNode {
  return {
    id,
    type: "lab",
    position: { x: 0, y: 0 },
    data: { componentId, componentVersion: "1.0.0", label: "", config: {}, notes: "" },
  };
}

const initialState = useBuilder.getState();

beforeEach(() => {
  useBuilder.setState(initialState, true);
  serverConfig.a2a_grpc_available = false;
});

const next = () => fireEvent.click(screen.getByRole("button", { name: /Next/ }));

describe("ShareDialog publish wizard", () => {
  it("picking a door writes serving.mode and the derived a2a/mcp booleans", () => {
    useBuilder.setState({ baseSpec: makeSpec({ serving: { mode: "api" } }) });
    render(<ShareDialog open onClose={() => {}} flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: /A2A Agent/ }));

    const meta = useBuilder.getState().baseSpec!.flow;
    expect(meta.serving?.mode).toBe("a2a");
    expect(meta.a2a?.enabled).toBe(true);
    expect(meta.mcp?.enabled).toBe(false);
  });

  it("switching doors turns the previously selected surface off", () => {
    useBuilder.setState({
      baseSpec: makeSpec({ serving: { mode: "a2a" }, a2a: { enabled: true } }),
    });
    render(<ShareDialog open onClose={() => {}} flow={flow} />);

    fireEvent.click(screen.getByRole("button", { name: /MCP Tool/ }));

    const meta = useBuilder.getState().baseSpec!.flow;
    expect(meta.serving?.mode).toBe("mcp");
    expect(meta.mcp?.enabled).toBe(true);
    expect(meta.a2a?.enabled).toBe(false);
  });

  it("surfaces the E060 guard live when the A2A description is empty, and clears it once filled", () => {
    // examples present so the E061 warning does not add noise
    useBuilder.setState({
      baseSpec: makeSpec({ serving: { mode: "a2a" }, a2a: { enabled: true, examples: ["ex"] } }),
    });
    render(<ShareDialog open onClose={() => {}} flow={flow} />);
    next();

    expect(screen.getByRole("dialog").textContent).toContain(
      "An A2A skill description is required",
    );

    fireEvent.change(screen.getByPlaceholderText("One sentence: what can this agent do?"), {
      target: { value: "Summarises support tickets" },
    });

    expect(screen.getByRole("dialog").textContent).not.toContain(
      "An A2A skill description is required",
    );
  });

  it("surfaces E062 on the MCP door when the tool description is empty", () => {
    useBuilder.setState({
      baseSpec: makeSpec({ serving: { mode: "mcp" }, mcp: { enabled: true } }),
    });
    render(<ShareDialog open onClose={() => {}} flow={flow} />);
    next();

    expect(screen.getByRole("dialog").textContent).toContain("An MCP tool description is required");
  });

  it("disables the gRPC transport option when a2a_grpc_available is false", () => {
    useBuilder.setState({
      baseSpec: makeSpec({
        serving: { mode: "a2a" },
        a2a: { enabled: true, description: "d", examples: ["ex"] },
      }),
    });
    render(<ShareDialog open onClose={() => {}} flow={flow} />);
    next();

    expect(screen.getByRole("radio", { name: /gRPC/ })).toBeDisabled();
    expect(screen.getByRole("dialog").textContent).toContain("requires the a2a-sdk[grpc] extra");
  });

  it("enables the gRPC option when the a2a-sdk[grpc] extra is available", () => {
    serverConfig.a2a_grpc_available = true;
    useBuilder.setState({
      baseSpec: makeSpec({
        serving: { mode: "a2a" },
        a2a: { enabled: true, description: "d", examples: ["ex"] },
      }),
    });
    render(<ShareDialog open onClose={() => {}} flow={flow} />);
    next();

    expect(screen.getByRole("radio", { name: /gRPC/ })).not.toBeDisabled();
    expect(screen.getByRole("dialog").textContent).toContain("high-throughput");
  });

  it("shows the human-in-the-loop note on the A2A door when the flow has interrupt nodes", () => {
    useBuilder.setState({
      baseSpec: makeSpec({
        serving: { mode: "a2a" },
        a2a: { enabled: true, description: "d", examples: ["ex"] },
      }),
      nodes: [interruptNode("appr_1", "lab.flow.human_approval")],
    });
    render(<ShareDialog open onClose={() => {}} flow={flow} />);
    next();

    const text = screen.getByRole("dialog").textContent ?? "";
    expect(text).toContain("1 human-in-the-loop step");
    expect(text).toContain("input-required");
  });
});
