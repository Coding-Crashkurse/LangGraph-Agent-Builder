import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { PublishResponse } from "@/api/types";

import { PublishDialog } from "./PublishDialog";
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
      resources_ui_url: "",
      registry_ui_url: "http://registry.test/entries",
    }),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

const published: PublishResponse = {
  name: "hello-agent",
  version: 3,
  endpoint_url: "http://gateway.test/a2a/hello-agent",
  registry_id: "abc-123",
};

function renderDialog(onPublish = vi.fn().mockResolvedValue(published)) {
  useBuilder.getState().load(definitionFixture(), catalogFixture);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <PublishDialog flowName="hello-agent" open onClose={() => {}} onPublish={onPublish} />
    </QueryClientProvider>,
  );
  return onPublish;
}

describe("PublishDialog", () => {
  it("offers both doors and switches expose.kind", async () => {
    renderDialog();
    expect(screen.getByText("A2A agent")).toBeInTheDocument();
    await userEvent.click(screen.getByText("MCP tool"));
    expect(useBuilder.getState().meta.expose.kind).toBe("mcp");
    expect(screen.getByText("Tool name")).toBeInTheDocument();
  });

  it("blocks MCP publish until the tool name is valid", async () => {
    const onPublish = renderDialog();
    await userEvent.click(screen.getByText("MCP tool"));
    const publish = screen.getByRole("button", { name: /Publish/ });
    expect(publish).toBeDisabled();
    expect(screen.getByText(/Required for MCP \(E050\)/)).toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText("search_support_kb"), "do_things");
    expect(publish).toBeEnabled();
    await userEvent.click(publish);
    expect(onPublish).toHaveBeenCalled();
  });

  it("publishes and shows endpoint, card link and registry link", async () => {
    renderDialog();
    await userEvent.click(screen.getByRole("button", { name: /Publish/ }));
    await waitFor(() =>
      expect(screen.getByText(/Version 3 is live/)).toBeInTheDocument(),
    );
    expect(screen.getByText("http://gateway.test/a2a/hello-agent")).toBeInTheDocument();
    const cardLink = screen.getByRole("link", { name: /agent card/ });
    expect(cardLink).toHaveAttribute(
      "href",
      "http://gateway.test/a2a/hello-agent/.well-known/agent-card.json",
    );
    expect(screen.getByRole("link", { name: /registry/ })).toHaveAttribute(
      "href",
      "http://registry.test/entries/abc-123",
    );
  });

  it("tags input accepts commas while typing", async () => {
    renderDialog();
    const tags = screen.getByPlaceholderText("support, rag");
    await userEvent.clear(tags);
    await userEvent.type(tags, "demo, rag,");
    expect(tags).toHaveValue("demo, rag,"); // raw text survives the round-trip
    expect(useBuilder.getState().meta.tags).toEqual(["demo", "rag"]);
  });

  it("nudges toward a description for the agent card", () => {
    useBuilder.getState().load(definitionFixture(), catalogFixture);
    useBuilder.getState().updateMeta({ description: "", display_name: "" });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <PublishDialog flowName="hello-agent" open onClose={() => {}} onPublish={vi.fn()} />
      </QueryClientProvider>,
    );
    expect(screen.getByText(/sparse agent card/)).toBeInTheDocument();
  });
});
