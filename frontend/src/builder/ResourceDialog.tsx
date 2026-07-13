/**
 * Create-resource dialog (SPEC §2.6): a thin proxy to the runtime's
 * `POST /resources`. Credentials entered here go straight to the runtime
 * (stored encrypted there) — the builder never persists or re-displays them.
 * The runtime validates on create (e.g. E022 embedding dimension vs. the
 * actual collection) and its answer is authoritative.
 */

import { useQuery } from "@tanstack/react-query";
import { Loader2, Plus } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import type { ResourceGroup } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/controls";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";

type ConcreteKind = "model_provider" | "qdrant" | "pgvector" | "mcp_server";

const KIND_LABEL: Record<ConcreteKind, string> = {
  model_provider: "Model Provider (OpenAI-compatible)",
  qdrant: "Vector DB — Qdrant",
  pgvector: "Vector DB — pgvector (Postgres)",
  mcp_server: "MCP Server",
};

const DEFAULT_KIND: Record<ResourceGroup, ConcreteKind> = {
  model_provider: "model_provider",
  vector_db: "qdrant",
  mcp_server: "mcp_server",
};

const NAME_RE = /^[a-z0-9][a-z0-9-]{1,62}$/;

interface Values {
  name: string;
  display_name: string;
  base_url: string;
  url: string;
  api_key_secret: string;
  dsn_secret: string;
  auth_secret: string;
  default_model: string;
  embedding_resource: string;
  embedding_model: string;
  embedding_dimension: string;
}

const EMPTY: Values = {
  name: "",
  display_name: "",
  base_url: "",
  url: "",
  api_key_secret: "",
  dsn_secret: "",
  auth_secret: "",
  default_model: "",
  embedding_resource: "",
  embedding_model: "",
  embedding_dimension: "768",
};

function buildPayload(kind: ConcreteKind, v: Values): Record<string, unknown> {
  const base: Record<string, unknown> = { kind, name: v.name, display_name: v.display_name };
  if (kind === "model_provider") {
    return {
      ...base,
      base_url: v.base_url,
      api_key_secret: v.api_key_secret || null,
      default_model: v.default_model,
    };
  }
  if (kind === "mcp_server") {
    return { ...base, url: v.url, auth_secret: v.auth_secret || null };
  }
  const embedding = {
    resource: v.embedding_resource,
    model: v.embedding_model,
    dimension: Number(v.embedding_dimension) || 0,
  };
  if (kind === "qdrant") {
    return { ...base, url: v.url, api_key_secret: v.api_key_secret || null, embedding };
  }
  return { ...base, dsn_secret: v.dsn_secret || null, embedding };
}

export function ResourceDialog({
  open,
  group,
  onClose,
  onCreated,
}: {
  open: boolean;
  group: ResourceGroup | null;
  onClose: () => void;
  onCreated: (name: string) => void;
}) {
  const [kind, setKind] = useState<ConcreteKind>(DEFAULT_KIND[group ?? "model_provider"]);
  const [values, setValues] = useState<Values>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const providers = useQuery({
    queryKey: ["resources", "model_provider"],
    queryFn: () => api.resources.list("model_provider"),
    enabled: open && (kind === "qdrant" || kind === "pgvector"),
    retry: false,
  });

  const set = (patch: Partial<Values>) => setValues((prev) => ({ ...prev, ...patch }));
  const isVectorDb = kind === "qdrant" || kind === "pgvector";
  const nameOk = NAME_RE.test(values.name);
  const embeddingOk =
    !isVectorDb ||
    (values.embedding_resource !== "" &&
      values.embedding_model !== "" &&
      Number(values.embedding_dimension) > 0);
  const canSubmit = nameOk && embeddingOk && !busy;

  const close = () => {
    setValues(EMPTY);
    setError(null);
    onClose();
  };

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const created = await api.resources.create(buildPayload(kind, values));
      toast.success(`Resource ${created.name} created on the runtime`);
      onCreated(created.name);
      close();
    } catch (err) {
      if (err instanceof ApiError && err.issues.length > 0) {
        setError(err.issues.map((i) => `${i.code} ${i.message}`).join(" · "));
      } else {
        setError(err instanceof Error ? err.message : "create failed");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title="New resource" className="max-w-md">
      <p className="text-[11px] leading-relaxed text-text-3">
        Created on the platform runtime — credentials are stored encrypted there and never
        kept in the builder. Flows reference the resource by name only.
      </p>
      <div className="mt-3 flex flex-col gap-3">
        <div>
          <Label>Type</Label>
          <Select
            value={kind}
            aria-label="resource type"
            onChange={(e) => setKind(e.target.value as ConcreteKind)}
          >
            {(Object.keys(KIND_LABEL) as ConcreteKind[]).map((k) => (
              <option key={k} value={k}>
                {KIND_LABEL[k]}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label hint="^[a-z0-9][a-z0-9-]{1,62}$">Name</Label>
          <Input
            className="font-mono"
            value={values.name}
            placeholder="my-kb"
            onChange={(e) => set({ name: e.target.value })}
          />
        </div>
        <div>
          <Label>Display name</Label>
          <Input
            value={values.display_name}
            onChange={(e) => set({ display_name: e.target.value })}
          />
        </div>

        {kind === "model_provider" && (
          <>
            <div>
              <Label hint="empty = gateway default">Base URL</Label>
              <Input
                className="font-mono"
                value={values.base_url}
                placeholder="http://127.0.0.1:11434/v1"
                onChange={(e) => set({ base_url: e.target.value })}
              />
            </div>
            <div>
              <Label hint="write-only">API key</Label>
              <Input
                type="password"
                value={values.api_key_secret}
                onChange={(e) => set({ api_key_secret: e.target.value })}
              />
            </div>
            <div>
              <Label>Default model</Label>
              <Input
                className="font-mono"
                value={values.default_model}
                placeholder="llama3.2:latest"
                onChange={(e) => set({ default_model: e.target.value })}
              />
            </div>
          </>
        )}

        {kind === "qdrant" && (
          <>
            <div>
              <Label>Qdrant URL</Label>
              <Input
                className="font-mono"
                value={values.url}
                placeholder="http://127.0.0.1:6333"
                onChange={(e) => set({ url: e.target.value })}
              />
            </div>
            <div>
              <Label hint="write-only, optional">API key</Label>
              <Input
                type="password"
                value={values.api_key_secret}
                onChange={(e) => set({ api_key_secret: e.target.value })}
              />
            </div>
          </>
        )}

        {kind === "pgvector" && (
          <div>
            <Label hint="write-only">Postgres DSN</Label>
            <Input
              type="password"
              className="font-mono"
              value={values.dsn_secret}
              placeholder="postgresql://user:pass@host:5432/db"
              onChange={(e) => set({ dsn_secret: e.target.value })}
            />
          </div>
        )}

        {isVectorDb && (
          <div className="rounded-lg border border-border bg-canvas p-2.5">
            <p className="mb-2 text-[11px] uppercase tracking-wide text-text-3">
              Embedding (must match the existing collection)
            </p>
            <div className="flex flex-col gap-2">
              <div>
                <Label>Model provider</Label>
                <Select
                  value={values.embedding_resource}
                  aria-label="embedding provider"
                  onChange={(e) => set({ embedding_resource: e.target.value })}
                >
                  <option value="">— select —</option>
                  {(providers.data ?? []).map((r) => (
                    <option key={r.name} value={r.name}>
                      {r.display_name || r.name}
                    </option>
                  ))}
                </Select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label>Model</Label>
                  <Input
                    className="font-mono"
                    value={values.embedding_model}
                    placeholder="nomic-embed-text"
                    onChange={(e) => set({ embedding_model: e.target.value })}
                  />
                </div>
                <div>
                  <Label hint="checked on create (E022)">Dimension</Label>
                  <Input
                    type="number"
                    value={values.embedding_dimension}
                    onChange={(e) => set({ embedding_dimension: e.target.value })}
                  />
                </div>
              </div>
            </div>
          </div>
        )}

        {kind === "mcp_server" && (
          <>
            <div>
              <Label>Server URL</Label>
              <Input
                className="font-mono"
                value={values.url}
                placeholder="http://127.0.0.1:8300/mcp"
                onChange={(e) => set({ url: e.target.value })}
              />
            </div>
            <div>
              <Label hint="write-only, optional bearer">Auth token</Label>
              <Input
                type="password"
                value={values.auth_secret}
                onChange={(e) => set({ auth_secret: e.target.value })}
              />
            </div>
          </>
        )}

        {error && <p className="text-[11px] text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={close}>
            Cancel
          </Button>
          <Button size="sm" disabled={!canSubmit} onClick={() => void submit()}>
            {busy ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
            Create
          </Button>
        </div>
      </div>
    </Dialog>
  );
}
