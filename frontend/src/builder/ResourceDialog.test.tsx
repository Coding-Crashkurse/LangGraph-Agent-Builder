/** Create-resource dialog: write-only proxy to the runtime (MSW-mocked). */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { ResourceDialog } from "./ResourceDialog";

let lastCreateBody: Record<string, unknown> | null = null;

const server = setupServer(
  http.get("/api/v1/resources", ({ request }) =>
    HttpResponse.json(
      new URL(request.url).searchParams.get("kind") === "model_provider"
        ? [{ name: "default-llm", kind: "model_provider", group: "model_provider", display_name: "" }]
        : [],
    ),
  ),
  http.post("/api/v1/resources", async ({ request }) => {
    lastCreateBody = (await request.json()) as Record<string, unknown>;
    return HttpResponse.json(
      { name: lastCreateBody.name, kind: lastCreateBody.kind, group: "vector_db", display_name: "" },
      { status: 201 },
    );
  }),
);

beforeAll(() => server.listen({ onUnhandledRequest: "error" }));
afterEach(() => {
  server.resetHandlers();
  lastCreateBody = null;
});
afterAll(() => server.close());

function renderDialog(onCreated = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ResourceDialog open group="vector_db" onClose={() => {}} onCreated={onCreated} />
    </QueryClientProvider>,
  );
  return onCreated;
}

describe("ResourceDialog", () => {
  it("defaults to the picker's group and renders secret fields as passwords", () => {
    renderDialog();
    expect(screen.getByLabelText("resource type")).toHaveValue("qdrant");
    const secret = screen.getByText("API key").closest("div")!.parentElement!;
    expect(secret.querySelector("input")!.type).toBe("password");
  });

  it("creates a qdrant resource with embedding config and reports the name", async () => {
    const onCreated = renderDialog();
    await userEvent.type(screen.getByPlaceholderText("my-kb"), "team-kb");
    await userEvent.type(screen.getByPlaceholderText("http://127.0.0.1:6333"), "http://q:6333");
    await waitFor(() => expect(screen.getByLabelText("embedding provider")).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText("embedding provider"), "default-llm");
    await userEvent.type(screen.getByPlaceholderText("nomic-embed-text"), "nomic-embed-text");
    await userEvent.click(screen.getByRole("button", { name: /Create/ }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith("team-kb"));
    expect(lastCreateBody).toMatchObject({
      kind: "qdrant",
      name: "team-kb",
      url: "http://q:6333",
      embedding: { resource: "default-llm", model: "nomic-embed-text", dimension: 768 },
    });
  });

  it("surfaces runtime rejections (E022) inline", async () => {
    server.use(
      http.post("/api/v1/resources", () =>
        HttpResponse.json(
          {
            detail: "runtime rejected the resource",
            issues: [
              {
                code: "E022",
                severity: "error",
                path: "embedding/dimension",
                message: "collection has 384 dims",
                source: "runtime",
              },
            ],
          },
          { status: 422 },
        ),
      ),
    );
    renderDialog();
    await userEvent.type(screen.getByPlaceholderText("my-kb"), "bad-kb");
    await waitFor(() => expect(screen.getByLabelText("embedding provider")).toBeInTheDocument());
    await userEvent.selectOptions(screen.getByLabelText("embedding provider"), "default-llm");
    await userEvent.type(screen.getByPlaceholderText("nomic-embed-text"), "m");
    await userEvent.click(screen.getByRole("button", { name: /Create/ }));
    await waitFor(() =>
      expect(screen.getByText(/E022 collection has 384 dims/)).toBeInTheDocument(),
    );
  });
});
