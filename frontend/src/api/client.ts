import type {
  CollectionInfo,
  ComponentInfo,
  EdgeSpec,
  Flow,
  NodeSpec,
  PublishResult,
  PublishSpec,
  Run,
  SendMessageResult,
  TaskDetail,
  ValidationReport,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body);
    } catch {
      /* keep statusText */
    }
    throw new ApiError(response.status, detail);
  }
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  components: () => request<ComponentInfo[]>("/api/components"),

  flows: {
    list: () => request<Flow[]>("/api/flows"),
    get: (id: string) => request<Flow>(`/api/flows/${id}`),
    create: (body: { name: string; slug?: string; description?: string }) =>
      request<Flow>("/api/flows", { method: "POST", body: JSON.stringify(body) }),
    save: (
      id: string,
      body: { name?: string; description?: string; nodes?: NodeSpec[]; edges?: EdgeSpec[] },
    ) =>
      request<Flow & { issues: ValidationReport["issues"] }>(`/api/flows/${id}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    delete: (id: string) => request<void>(`/api/flows/${id}`, { method: "DELETE" }),
    validate: (id: string, body?: { nodes?: NodeSpec[]; edges?: EdgeSpec[] }) =>
      request<ValidationReport>(`/api/flows/${id}/validate`, {
        method: "POST",
        body: JSON.stringify(body ?? {}),
      }),
    publish: (id: string, body: Partial<PublishSpec>) =>
      request<PublishResult>(`/api/flows/${id}/publish`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    unpublish: (id: string) =>
      request<{ published: boolean }>(`/api/flows/${id}/unpublish`, { method: "POST" }),
  },

  debug: {
    tasks: (flowId: string, filters?: { state?: string; source?: string }) => {
      const params = new URLSearchParams();
      if (filters?.state) params.set("state", filters.state);
      if (filters?.source) params.set("source", filters.source);
      const qs = params.toString();
      return request<Run[]>(`/api/debug/flows/${flowId}/tasks${qs ? `?${qs}` : ""}`);
    },
    task: (taskId: string) => request<TaskDetail>(`/api/debug/tasks/${taskId}`),
    sendMessage: (flowId: string, body: { message: string; context_id?: string; stream: boolean }) =>
      request<SendMessageResult>(`/api/debug/flows/${flowId}/messages`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    sendInput: (taskId: string, body: { text?: string; data?: Record<string, unknown> }) =>
      request<SendMessageResult>(`/api/debug/tasks/${taskId}/input`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
    cancel: (taskId: string) =>
      request<{ state: string }>(`/api/debug/tasks/${taskId}/cancel`, { method: "POST" }),
  },

  collections: {
    list: () => request<CollectionInfo[]>("/api/collections"),
    ingestText: (name: string, body: { text: string; source?: string }) =>
      request<{ collection: string; chunks: number }>(`/api/collections/${name}/documents`, {
        method: "POST",
        body: JSON.stringify(body),
      }),
  },
};
