import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  api: {
    variables: { list: vi.fn(), set: vi.fn() },
    mcpServers: { list: vi.fn() },
  },
}));

import { api } from "@/api/client";
import type { FieldDescriptor } from "@/api/types";

import { FieldWidgetRegistry, widgetFor } from "./registry";

/** SPEC §11.2: every §4.2 field type maps to a widget (port-only types render
 * as handles, not widgets). */
const SPEC_FIELD_TYPES = [
  "StrInput",
  "MultilineInput",
  "IntInput",
  "FloatInput",
  "BoolInput",
  "SliderInput",
  "DropdownInput",
  "MultiselectInput",
  "TabInput",
  "SecretInput",
  "MultilineSecretInput",
  "DictInput",
  "NestedDictInput",
  "TableInput",
  "FileInput",
  "CodeInput",
  "PromptInput",
  "ModelInput",
  "QueryInput",
  "LinkInput",
  "McpInput",
];

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

/** VarPicker/McpWidget use react-query — give each render a fresh cache. */
function renderWidget(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(api.variables.list).mockResolvedValue([]);
  vi.mocked(api.mcpServers.list).mockResolvedValue([]);
});

describe("FieldWidgetRegistry", () => {
  it("covers every widget-capable field type from SPEC §4.2", () => {
    for (const type of SPEC_FIELD_TYPES) {
      expect(FieldWidgetRegistry[type], `missing widget for ${type}`).toBeDefined();
    }
  });

  it("port-only field types intentionally have no widget", () => {
    expect(FieldWidgetRegistry.HandleField).toBeUndefined();
    expect(FieldWidgetRegistry.ToolsInput).toBeUndefined();
  });

  it("falls back to the JSON widget for unknown types and warns", () => {
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const field = makeField({ name: "mystery", type: "FrobInput" });
    const Widget = widgetFor(field);
    const { container } = renderWidget(
      <Widget field={field} value={{ a: 1 }} onChange={() => {}} />,
    );
    expect(container.querySelector("textarea")).toBeTruthy();
    expect(warn).toHaveBeenCalledWith(expect.stringContaining("FrobInput"));
    warn.mockRestore();
  });
});

describe("SecretInput", () => {
  it("masks by default and reveals via the eye toggle", () => {
    const Secret = FieldWidgetRegistry.SecretInput;
    const field = makeField({ name: "api_key", type: "SecretInput" });
    const { container } = renderWidget(
      <Secret field={field} value="hunter2" onChange={() => {}} />,
    );
    const input = container.querySelector("input:not([type=hidden])") as HTMLInputElement;
    expect(input.type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Reveal value" }));
    expect(input.type).toBe("text");
    fireEvent.click(screen.getByRole("button", { name: "Hide value" }));
    expect(input.type).toBe("password");
  });
});

describe("$var / $secret references", () => {
  it("renders an existing $var binding as a chip and clears it on remove", () => {
    const Str = FieldWidgetRegistry.StrInput;
    const field = makeField({ name: "base_url", accepts_global_variable: true });
    const onChange = vi.fn();
    renderWidget(<Str field={field} value={{ $var: "API_BASE" }} onChange={onChange} />);
    expect(screen.getByText(/\$var: API_BASE/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Remove reference" }));
    expect(onChange).toHaveBeenCalledWith(null);
  });

  it("offers the $var picker on plain string fields", () => {
    const Str = FieldWidgetRegistry.StrInput;
    const field = makeField({ name: "base_url", accepts_global_variable: true });
    renderWidget(<Str field={field} value="" onChange={() => {}} />);
    expect(screen.getByRole("button", { name: /\$var/ })).toBeInTheDocument();
  });
});

describe("McpInput", () => {
  const mcpField = makeField({ name: "server", type: "McpInput" });

  it("picks from globally managed MCP servers", async () => {
    vi.mocked(api.mcpServers.list).mockResolvedValue([
      {
        id: "1",
        name: "docs",
        transport: "streamable_http",
        config: { url: "http://localhost:9000/mcp" },
        created_at: "",
      },
    ]);
    const McpWidget = FieldWidgetRegistry.McpInput;
    const onChange = vi.fn();
    renderWidget(<McpWidget field={mcpField} value={null} onChange={onChange} />);
    const select = await screen.findByRole("combobox", { name: "Managed MCP server" });
    expect(screen.getByText("docs (streamable_http)")).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "docs" } });
    expect(onChange).toHaveBeenCalledWith({ server: "docs" });
    // raw JSON stays reachable as an advanced escape hatch
    fireEvent.click(screen.getByRole("button", { name: /advanced: raw connection JSON/ }));
    expect(document.querySelector("textarea")).toBeTruthy();
  });

  it("falls back to the JSON editor with a Settings hint when no servers exist", async () => {
    const McpWidget = FieldWidgetRegistry.McpInput;
    const { container } = renderWidget(
      <McpWidget field={mcpField} value={null} onChange={() => {}} />,
    );
    expect(await screen.findByText(/add one in Settings/)).toBeInTheDocument();
    expect(container.querySelector("textarea")).toBeTruthy();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });
});
