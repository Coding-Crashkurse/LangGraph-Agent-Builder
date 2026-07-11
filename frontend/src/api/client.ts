/** Typed client over the generated OpenAPI paths (SPEC §11.2: no hand-written
 * fetch paths — `openapi-fetch` derives them from `schema.gen.ts`). */

import createClient from "openapi-fetch";

import type { paths } from "./schema.gen";
import type {
  ApiKeyInfo,
  ComponentDescriptor,
  Diagnostic,
  FieldDescriptor,
  FlowInfo,
  FlowSpec,
  McpServerInfo,
  NodeRunInfo,
  OutputDescriptor,
  PortSpec,
  ResourceInfo,
  ResourceTestResult,
  RunInfo,
  RunResult,
  ThreadInfo,
  ValidateResponse,
  VariableInfo,
  VersionInfo,
} from "./types";

export const raw = createClient<paths>({ baseUrl: "" });

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
    public diagnostics?: Diagnostic[],
  ) {
    super(message);
  }
}

function unwrap<T>(result: { data?: unknown; error?: unknown; response: Response }): T {
  if (result.error !== undefined || !result.response.ok) {
    const err = result.error as { detail?: unknown } | undefined;
    let message = result.response.statusText;
    let diagnostics: Diagnostic[] | undefined;
    if (err && typeof err.detail === "string") message = err.detail;
    else if (err && typeof err.detail === "object" && err.detail !== null) {
      const detail = err.detail as { message?: string; diagnostics?: Diagnostic[] };
      message = detail.message ?? JSON.stringify(err.detail);
      diagnostics = detail.diagnostics;
    }
    throw new ApiError(result.response.status, message, diagnostics);
  }
  return result.data as T;
}

export const api = {
  components: {
    list: async () =>
      unwrap<ComponentDescriptor[]>(await raw.GET("/api/v1/components")),
    configChange: async (
      componentId: string,
      body: { config: Record<string, unknown>; changed_field: string; value: unknown },
    ) =>
      unwrap<{
        config: Record<string, unknown>;
        fields: FieldDescriptor[];
        outputs: OutputDescriptor[];
        input_ports: Record<string, PortSpec>;
      }>(
        await raw.POST("/api/v1/components/{component_id}/config", {
          params: { path: { component_id: componentId } },
          body: body as never,
        }),
      ),
  },

  flows: {
    list: async () => unwrap<FlowInfo[]>(await raw.GET("/api/v1/flows")),
    get: async (id: string) =>
      unwrap<FlowInfo>(
        await raw.GET("/api/v1/flows/{id_or_slug}", { params: { path: { id_or_slug: id } } }),
      ),
    create: async (spec: FlowSpec) =>
      unwrap<FlowInfo>(await raw.POST("/api/v1/flows", { body: { spec } as never })),
    update: async (id: string, spec: FlowSpec) =>
      unwrap<FlowInfo>(
        await raw.PATCH("/api/v1/flows/{id_or_slug}", {
          params: { path: { id_or_slug: id } },
          body: { spec } as never,
        }),
      ),
    delete: async (id: string) =>
      unwrap<void>(
        await raw.DELETE("/api/v1/flows/{id_or_slug}", { params: { path: { id_or_slug: id } } }),
      ),
    validate: async (id: string, deep = false) =>
      unwrap<ValidateResponse>(
        await raw.POST("/api/v1/flows/{id_or_slug}/validate", {
          params: { path: { id_or_slug: id }, query: { deep } },
        }),
      ),
    publish: async (id: string, body: { version: string; changelog: string }) =>
      unwrap<{ published: boolean; version?: VersionInfo; diagnostics: Diagnostic[] }>(
        await raw.POST("/api/v1/flows/{id_or_slug}/publish", {
          params: { path: { id_or_slug: id } },
          body: body as never,
        }),
      ),
    /** Export the stored draft as flow.json / standalone flow.py (§11.6). */
    export: async (id: string, format: "json" | "python") =>
      unwrap<string>(
        await raw.GET("/api/v1/flows/{id_or_slug}/export", {
          params: { path: { id_or_slug: id }, query: { format } },
          parseAs: "text",
        }),
      ),
    run: async (
      id: string,
      body: {
        input_text?: string;
        data?: Record<string, unknown> | null;
        session_id?: string | null;
        tweaks?: Record<string, Record<string, unknown>> | null;
        stream?: boolean;
        mode?: string;
      },
    ) =>
      unwrap<RunResult & { run_id: string; thread_id: string }>(
        await raw.POST("/api/v1/flows/{id_or_slug}/run", {
          params: { path: { id_or_slug: id } },
          body: body as never,
        }),
      ),
  },

  runs: {
    list: async (flowId?: string) =>
      unwrap<RunInfo[]>(
        await raw.GET("/api/v1/runs", {
          params: { query: flowId ? { flow_id: flowId } : {} },
        }),
      ),
    get: async (runId: string) =>
      unwrap<RunInfo>(
        await raw.GET("/api/v1/runs/{run_id}", { params: { path: { run_id: runId } } }),
      ),
    /** Per-node execution timeline for a past run (§7.3). Not yet in the
     * generated OpenAPI schema, so this uses the same thin-fetch helper as
     * api.resources (regen with `pnpm gen:api` and swap to `raw` once it ships). */
    nodes: async (runId: string): Promise<NodeRunInfo[]> =>
      resourceFetch<NodeRunInfo[]>(`/api/v1/runs/${encodeURIComponent(runId)}/nodes`),
    delete: async (runId: string) =>
      unwrap<unknown>(
        await raw.DELETE("/api/v1/runs/{run_id}", { params: { path: { run_id: runId } } }),
      ),
    clearFinished: async (flowId?: string) =>
      unwrap<{ deleted: number }>(
        await raw.DELETE("/api/v1/runs", {
          params: { query: flowId ? { flow_id: flowId } : {} },
        }),
      ),
    cancel: async (runId: string) =>
      unwrap<{ cancelled: boolean }>(
        await raw.POST("/api/v1/runs/{run_id}/cancel", {
          params: { path: { run_id: runId } },
        }),
      ),
    resume: async (runId: string, payload: unknown, debugAction?: "step" | "continue") =>
      unwrap<RunResult>(
        await raw.POST("/api/v1/runs/{run_id}/resume", {
          params: { path: { run_id: runId } },
          body: { payload, debug_action: debugAction ?? null } as never,
        }),
      ),
  },

  threads: {
    list: async (flowSlug?: string) =>
      unwrap<ThreadInfo[]>(
        await raw.GET("/api/v1/threads", {
          params: { query: flowSlug ? { flow_slug: flowSlug } : {} },
        }),
      ),
    state: async (threadId: string) =>
      unwrap<Record<string, unknown>>(
        await raw.GET("/api/v1/threads/{thread_id}/state", {
          params: { path: { thread_id: threadId } },
        }),
      ),
    delete: async (threadId: string) =>
      unwrap<void>(
        await raw.DELETE("/api/v1/threads/{thread_id}", {
          params: { path: { thread_id: threadId } },
        }),
      ),
  },

  variables: {
    list: async () => unwrap<VariableInfo[]>(await raw.GET("/api/v1/variables")),
    set: async (body: { name: string; value: string; kind: "generic" | "credential" }) =>
      unwrap<{ name: string }>(await raw.POST("/api/v1/variables", { body: body as never })),
    delete: async (name: string) =>
      unwrap<void>(
        await raw.DELETE("/api/v1/variables/{name}", { params: { path: { name } } }),
      ),
  },

  apikeys: {
    list: async () => unwrap<ApiKeyInfo[]>(await raw.GET("/api/v1/apikeys")),
    create: async (body: { name: string; scopes: string[] }) =>
      unwrap<ApiKeyInfo>(await raw.POST("/api/v1/apikeys", { body: body as never })),
    revoke: async (id: string) =>
      unwrap<void>(
        await raw.DELETE("/api/v1/apikeys/{key_id}", { params: { path: { key_id: id } } }),
      ),
  },

  mcpServers: {
    list: async () => unwrap<McpServerInfo[]>(await raw.GET("/api/v1/mcp-servers")),
    upsert: async (body: {
      name: string;
      transport: string;
      config: Record<string, unknown>;
    }) => unwrap<McpServerInfo>(await raw.POST("/api/v1/mcp-servers", { body: body as never })),
    delete: async (name: string) =>
      unwrap<void>(
        await raw.DELETE("/api/v1/mcp-servers/{name}", { params: { path: { name } } }),
      ),
  },

  // Resources layer — long-lived, flow-referenced config. Not yet in the
  // generated OpenAPI schema, so these use plain fetch (cf. api.variables once
  // the backend endpoints ship; regen with `pnpm gen:api` and swap to `raw`).
  resources: {
    list: async (type: string) =>
      resourceFetch<ResourceInfo[]>(`/api/v1/resources/${type}`),
    create: async (type: string, body: { name: string; config: Record<string, unknown> }) =>
      resourceFetch<ResourceInfo>(`/api/v1/resources/${type}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }),
    remove: async (type: string, name: string) =>
      resourceFetch<void>(`/api/v1/resources/${type}/${encodeURIComponent(name)}`, {
        method: "DELETE",
      }),
    test: async (type: string, name: string) =>
      resourceFetch<ResourceTestResult>(
        `/api/v1/resources/${type}/${encodeURIComponent(name)}/test`,
        { method: "POST" },
      ),
  },
};

/** Thin fetch wrapper for endpoints not yet in schema.gen.ts. Mirrors `unwrap`'s
 * error surface (throws ApiError with the server's detail) and tolerates empty
 * 204 bodies. */
async function resourceFetch<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const text = await response.text();
  if (!response.ok) {
    let message = response.statusText;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === "string") message = parsed.detail;
      else if (parsed.detail) message = JSON.stringify(parsed.detail);
      else if (text) message = text;
    } catch {
      if (text) message = text;
    }
    throw new ApiError(response.status, message);
  }
  return (text ? JSON.parse(text) : undefined) as T;
}
