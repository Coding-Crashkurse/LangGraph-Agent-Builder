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
  OutputDescriptor,
  PortSpec,
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
        await raw.GET("/api/v1/flows/{flow_id}", { params: { path: { flow_id: id } } }),
      ),
    create: async (spec: FlowSpec) =>
      unwrap<FlowInfo>(await raw.POST("/api/v1/flows", { body: { spec } as never })),
    update: async (id: string, spec: FlowSpec) =>
      unwrap<FlowInfo>(
        await raw.PATCH("/api/v1/flows/{flow_id}", {
          params: { path: { flow_id: id } },
          body: { spec } as never,
        }),
      ),
    delete: async (id: string) =>
      unwrap<void>(
        await raw.DELETE("/api/v1/flows/{flow_id}", { params: { path: { flow_id: id } } }),
      ),
    validate: async (id: string, deep = false) =>
      unwrap<ValidateResponse>(
        await raw.POST("/api/v1/flows/{flow_id}/validate", {
          params: { path: { flow_id: id }, query: { deep } },
        }),
      ),
    publish: async (id: string, body: { version: string; changelog: string }) =>
      unwrap<{ published: boolean; version?: VersionInfo; diagnostics: Diagnostic[] }>(
        await raw.POST("/api/v1/flows/{flow_id}/publish", {
          params: { path: { flow_id: id } },
          body: body as never,
        }),
      ),
    versions: async (id: string) =>
      unwrap<VersionInfo[]>(
        await raw.GET("/api/v1/flows/{flow_id}/versions", {
          params: { path: { flow_id: id } },
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
        await raw.POST("/api/v1/flows/{flow_ref}/run", {
          params: { path: { flow_ref: id } },
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
    updateState: async (threadId: string, values: Record<string, unknown>) =>
      unwrap<Record<string, unknown>>(
        await raw.POST("/api/v1/threads/{thread_id}/state", {
          params: { path: { thread_id: threadId } },
          body: { values } as never,
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

  misc: {
    version: async () =>
      unwrap<Record<string, string>>(await raw.GET("/api/v1/version")),
    mcpConfig: async () =>
      unwrap<Record<string, unknown>>(await raw.GET("/api/v1/mcp/config")),
  },
};
