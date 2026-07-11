/** ResourceRefInput widget: binds a node field to a Resource by name. Value
 * contract {"$resource": name} (+ optional `model` for model_provider). Fetches
 * ["resources", type] from /api/v1/resources/{type}. */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { FieldDescriptor } from "@/api/types";

import { FieldWidgetRegistry } from "./registry";

function makeField(overrides: Partial<FieldDescriptor> & { name: string }): FieldDescriptor {
  return {
    type: "ResourceRefInput",
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

function renderWidget(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function stubFetch(data: unknown) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => ({ ok: true, json: async () => data }) as unknown as Response),
  );
}

beforeEach(() => vi.restoreAllMocks());
afterEach(() => vi.unstubAllGlobals());

describe("ResourceRefInput", () => {
  it("lists resources and writes a {$resource} binding on select", async () => {
    stubFetch([
      { name: "kb-a", config: {} },
      { name: "kb-b", config: {} },
    ]);
    const Widget = FieldWidgetRegistry.ResourceRefInput;
    const field = makeField({ name: "kb", resource_type: "knowledge_base" });
    const onChange = vi.fn();
    renderWidget(<Widget field={field} value={null} onChange={onChange} />);

    const select = await screen.findByRole("combobox", { name: "kb" });
    expect(await screen.findByText("kb-a")).toBeInTheDocument();
    fireEvent.change(select, { target: { value: "kb-b" } });
    expect(onChange).toHaveBeenCalledWith({ $resource: "kb-b" });
  });

  it("adds a model picker for model_provider from config.models", async () => {
    stubFetch([{ name: "openai-main", config: { models: ["gpt-4o", "gpt-4o-mini"] } }]);
    const Widget = FieldWidgetRegistry.ResourceRefInput;
    const field = makeField({ name: "model", resource_type: "model_provider" });
    const onChange = vi.fn();
    // provider already chosen → the model dropdown is shown
    renderWidget(<Widget field={field} value={{ $resource: "openai-main" }} onChange={onChange} />);

    const modelSelect = await screen.findByRole("combobox", { name: "Model" });
    fireEvent.change(modelSelect, { target: { value: "gpt-4o" } });
    expect(onChange).toHaveBeenCalledWith({ $resource: "openai-main", model: "gpt-4o" });
  });

  it("shows a 'Manage in Resources' hint when none exist", async () => {
    stubFetch([]);
    const Widget = FieldWidgetRegistry.ResourceRefInput;
    const field = makeField({ name: "kb", resource_type: "knowledge_base" });
    renderWidget(<Widget field={field} value={null} onChange={() => {}} />);

    expect(await screen.findByText(/Manage in Resources/)).toBeInTheDocument();
  });
});
