/**
 * Config panels render from the JSON Schemas served by GET /node-types (the
 * generated fixture), never from hardcoded field lists. Backend API via MSW.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it } from "vitest";

import { ConfigPanel } from "./ConfigPanel";
import { catalogFixture, definitionFixture } from "./fixtures";
import { useBuilder } from "./store";

const server = setupServer(
  http.get("/api/v1/config", () =>
    HttpResponse.json({
      version: "0.1.0",
      auth_mode: "none",
      oidc_issuer: "",
      oidc_client_id: "",
      runtime_configured: true,
      resources_ui_url: "http://platform.test/resources",
      registry_ui_url: "",
    }),
  ),
  http.get("/api/v1/resources", () =>
    HttpResponse.json([
      { name: "default-llm", kind: "model_provider", group: "model_provider", display_name: "" },
      { name: "backup-llm", kind: "model_provider", group: "model_provider", display_name: "" },
    ]),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel(selected: string | null) {
  useBuilder.getState().load(definitionFixture(), catalogFixture);
  useBuilder.getState().select(selected);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ConfigPanel />
    </QueryClientProvider>,
  );
}

describe("ConfigPanel", () => {
  it("renders every llm_call field from the served config schema", async () => {
    renderPanel("call_1");
    const schema = catalogFixture.node_types.find((t) => t.type === "llm_call")!;
    const properties = Object.keys(schema.config_schema.properties as object);
    expect(properties).toContain("prompt");
    for (const name of properties) {
      const label = schema.ui[name]?.label || name;
      await waitFor(() => expect(screen.getByText(label)).toBeInTheDocument());
    }
  });

  it("writes field edits into the node config", async () => {
    renderPanel("call_1");
    const prompt = screen.getByText("Prompt").closest("div")!.parentElement!;
    const textarea = prompt.querySelector("textarea")!;
    await userEvent.clear(textarea);
    await userEvent.type(textarea, "Say {{hi}"); // {{ escapes to a literal {

    const def = useBuilder.getState().nodes.find((n) => n.id === "call_1")!.data.def;
    expect(def.config.prompt).toBe("Say {hi}");
  });

  it("resource fields render a dropdown fed by GET /resources", async () => {
    renderPanel("call_1");
    await waitFor(() => expect(screen.getByLabelText("resource")).toBeInTheDocument());
    const select = screen.getByLabelText("resource");
    await waitFor(() => expect(select).toHaveTextContent("backup-llm"));
    expect(screen.getByText(/Manage in Resources/)).toBeInTheDocument();
  });

  it("structured output is a toggle: on shows the schema editor, off stores null", async () => {
    renderPanel("call_1");
    const toggle = screen.getByRole("switch", { name: "Output Schema" });
    expect(toggle).toHaveAttribute("aria-checked", "false");
    await userEvent.click(toggle);
    const def = () => useBuilder.getState().nodes.find((n) => n.id === "call_1")!.data.def;
    expect(def().config.structured_output).toEqual({ type: "object", properties: {} });
    await waitFor(() =>
      expect(screen.getAllByRole("textbox").length).toBeGreaterThan(2),
    );
    await userEvent.click(screen.getByRole("switch", { name: "Output Schema" }));
    expect(def().config.structured_output).toBeNull();
  });

  it("shows flow settings incl. MCP tool fields when nothing is selected", async () => {
    renderPanel(null);
    expect(screen.getByText("Flow settings")).toBeInTheDocument();
    await userEvent.click(screen.getByText("MCP tool"));
    expect(screen.getByText("Tool name")).toBeInTheDocument();
    expect(useBuilder.getState().meta.expose.kind).toBe("mcp");
  });
});
