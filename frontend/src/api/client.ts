/**
 * Typed client for the builder backend (SPEC §3). Plain fetch — the API is
 * small and stable; issues arriving on 422 bodies are surfaced on ApiError so
 * the validation panel can render local and runtime failures identically.
 */

import { authHeaders, authMode, onUnauthorized } from "./auth";
import type {
  FlowDefinition,
  FlowDetail,
  FlowSummary,
  FrontendConfig,
  ImportResponse,
  NodeCatalog,
  PlaygroundResponse,
  PublishResponse,
  ResourceGroup,
  ResourceSummary,
  RuntimeHealth,
  SourcedIssue,
  ValidationResponse,
} from "./types";

export class ApiError extends Error {
  status: number;
  issues: SourcedIssue[];

  constructor(status: number, message: string, issues: SourcedIssue[] = []) {
    super(message);
    this.status = status;
    this.issues = issues;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const response = await fetch(`/api/v1${path}`, {
    ...init,
    headers: { ...(init.headers ?? {}), ...authHeaders() },
  });
  if (response.status === 401 && authMode() === "oidc") {
    await onUnauthorized(); // navigates away; the throw below is a fallback
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    let issues: SourcedIssue[] = [];
    try {
      const body = (await response.json()) as { detail?: string; issues?: SourcedIssue[] };
      detail = body.detail ?? detail;
      issues = body.issues ?? [];
    } catch {
      // non-JSON error body — keep the status text
    }
    throw new ApiError(response.status, detail, issues);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

function jsonBody(payload: unknown): RequestInit {
  return {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  };
}

export const api = {
  config: {
    get: () => request<FrontendConfig>("/config"),
  },
  runtime: {
    health: () => request<RuntimeHealth>("/runtime/health"),
  },
  catalog: {
    get: () => request<NodeCatalog>("/node-types"),
  },
  flows: {
    list: () => request<FlowSummary[]>("/flows"),
    get: (name: string) => request<FlowDetail>(`/flows/${name}`),
    create: (definition: FlowDefinition) => request<FlowDetail>("/flows", jsonBody(definition)),
    save: (name: string, definition: FlowDefinition) =>
      request<FlowDetail>(`/flows/${name}`, { ...jsonBody(definition), method: "PUT" }),
    delete: (name: string, opts?: { undeploy?: boolean }) =>
      request<void>(`/flows/${name}${opts?.undeploy ? "?undeploy=true" : ""}`, {
        method: "DELETE",
      }),
    validate: (definition: FlowDefinition, opts?: { runtime?: boolean }) =>
      request<ValidationResponse>(
        `/flows/validate${opts?.runtime === false ? "?runtime=false" : ""}`,
        jsonBody(definition),
      ),
    publish: (name: string, opts?: { version_label?: string | null }) =>
      request<PublishResponse>(
        `/flows/${name}/publish`,
        opts?.version_label ? jsonBody({ version_label: opts.version_label }) : { method: "POST" },
      ),
    playground: (name: string) =>
      request<PlaygroundResponse>(`/flows/${name}/playground`, { method: "POST" }),
    exportUrl: (name: string, format: "yaml" | "json" = "yaml") =>
      `/api/v1/flows/${name}/export?format=${format}`,
    exportText: async (name: string, format: "yaml" | "json" = "yaml") => {
      const response = await fetch(`/api/v1/flows/${name}/export?format=${format}`, {
        headers: authHeaders(),
      });
      if (!response.ok) throw new ApiError(response.status, `export failed`);
      return response.text();
    },
    import: (text: string, overwrite = false) =>
      request<ImportResponse>(`/flows/import?overwrite=${overwrite}`, {
        method: "POST",
        headers: { "Content-Type": "application/yaml" },
        body: text,
      }),
  },
  resources: {
    list: (kind?: ResourceGroup) =>
      request<ResourceSummary[]>(`/resources${kind ? `?kind=${kind}` : ""}`),
    /** Thin proxy to the runtime — credentials pass through write-only. */
    create: (payload: Record<string, unknown>) =>
      request<ResourceSummary>("/resources", jsonBody(payload)),
    delete: (name: string) => request<void>(`/resources/${name}`, { method: "DELETE" }),
  },
};
