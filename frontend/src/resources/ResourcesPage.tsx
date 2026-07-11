/** Resources (REFACTOR.md Resources layer): long-lived configuration that flows
 * reference by name via {"$resource": name}. Four types — model providers,
 * knowledge bases, A2A agents and MCP servers — each a list + add form + delete
 * + Test. MCP reuses the Settings CRUD (api.mcpServers) rather than duplicating
 * it. Design brief: theme tokens only, shared Settings chrome, visible focus. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Bot,
  Cpu,
  FlaskConical,
  Library,
  Plug,
  Settings as SettingsIcon,
  type LucideIcon,
} from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import type { ResourceInfo, ResourceTestResult } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select } from "@/components/ui/controls";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import { McpServersSection } from "@/settings/SettingsPage";
import {
  ConfirmDelete,
  CopyButton,
  EmptyState,
  RowDeleteButton,
  SectionHeader,
  SkeletonRows,
} from "@/settings/ui";

type ResourceSectionId = "model_provider" | "knowledge_base" | "a2a_agent" | "mcp_server";

const SECTIONS: { id: ResourceSectionId; label: string; icon: LucideIcon }[] = [
  { id: "model_provider", label: "Model Providers", icon: Cpu },
  { id: "knowledge_base", label: "Knowledge Bases", icon: Library },
  { id: "a2a_agent", label: "A2A Agents", icon: Bot },
  { id: "mcp_server", label: "MCP Servers", icon: Plug },
];

export function ResourcesPage() {
  const [section, setSection] = useState<ResourceSectionId>("model_provider");
  return (
    <div className="min-h-screen bg-canvas px-8 py-6 text-text-1">
      <header className="mb-6 flex items-center gap-3">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-text-3 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        >
          <ArrowLeft size={14} strokeWidth={1.75} aria-hidden />
          Flows
        </Link>
        <h1 className="text-lg font-bold">Resources</h1>
        <span className="text-xs text-text-3">
          shared config nodes bind to via <code className="font-mono">{'{"$resource": …}'}</code>
        </span>
        <Link
          to="/settings"
          className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-text-2 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        >
          <SettingsIcon size={14} strokeWidth={1.75} aria-hidden />
          Settings
        </Link>
      </header>

      <div className="flex max-w-5xl gap-8">
        <nav aria-label="Resource types" className="w-48 shrink-0 space-y-0.5">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              type="button"
              aria-current={section === id ? "page" : undefined}
              onClick={() => setSection(id)}
              className={cn(
                "flex w-full items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors",
                "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
                section === id
                  ? "bg-accent/15 text-text-1"
                  : "text-text-2 hover:bg-surface-2 hover:text-text-1",
              )}
            >
              <Icon size={14} strokeWidth={1.75} aria-hidden />
              {label}
            </button>
          ))}
        </nav>

        <main className="min-w-0 flex-1">
          {section === "model_provider" && <ModelProvidersSection />}
          {section === "knowledge_base" && <KnowledgeBasesSection />}
          {section === "a2a_agent" && <A2AAgentsSection />}
          {section === "mcp_server" && <McpServersSection />}
        </main>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ shared bits

function parseList(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Neutral (untested) · green (ok) · red (failed) status dot. */
function HealthDot({ ok }: { ok?: boolean }) {
  return (
    <span
      className={cn(
        "h-2 w-2 shrink-0 rounded-full",
        ok === undefined ? "bg-text-3" : ok ? "bg-success" : "bg-danger",
      )}
      title={ok === undefined ? "not tested" : ok ? "healthy" : "unreachable"}
      aria-hidden
    />
  );
}

/** Picks a stored credential (Settings → Variables) → {"$secret": name}. The
 * secret value never enters the resource config, only the reference. */
function SecretRefSelect({
  value,
  onChange,
  label,
}: {
  value: { $secret?: string } | null;
  onChange: (value: { $secret: string } | null) => void;
  label: string;
}) {
  const variables = useQuery({ queryKey: ["variables"], queryFn: api.variables.list });
  const creds = (variables.data ?? []).filter((v) => v.kind === "credential");
  return (
    <div className="space-y-0.5">
      <Select
        className="w-44"
        aria-label={label}
        value={value?.$secret ?? ""}
        onChange={(e) => onChange(e.target.value ? { $secret: e.target.value } : null)}
      >
        <option value="">none</option>
        {creds.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name}
          </option>
        ))}
      </Select>
      {creds.length === 0 && (
        <p className="text-[11px] text-text-3">
          No credentials —{" "}
          <Link
            to="/settings"
            className="rounded text-accent underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-accent"
          >
            add in Settings → Variables
          </Link>
        </p>
      )}
    </div>
  );
}

/** Per-name Test state for a resource type (health / auth / card-fetch probe). */
function useResourceTest(type: string) {
  const [results, setResults] = useState<Record<string, ResourceTestResult>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const run = async (name: string) => {
    setBusy(name);
    try {
      const res = await api.resources.test(type, name);
      setResults((prev) => ({ ...prev, [name]: res }));
      if (res.ok) toast.success(`${name}: ok`);
      else toast.error(`${name}: ${res.error ?? "test failed"}`);
    } catch (e) {
      setResults((prev) => ({ ...prev, [name]: { ok: false, error: (e as Error).message } }));
      toast.error(`${name}: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };
  return { results, busy, run };
}

function TestButton({
  name,
  busy,
  onRun,
}: {
  name: string;
  busy: string | null;
  onRun: (name: string) => void;
}) {
  return (
    <Button
      variant="secondary"
      size="sm"
      disabled={busy === name}
      onClick={() => onRun(name)}
    >
      <FlaskConical size={13} strokeWidth={1.75} aria-hidden />
      {busy === name ? "Testing…" : "Test"}
    </Button>
  );
}

function labelBox(label: string, control: ReactNode) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-text-2">{label}</span>
      {control}
    </label>
  );
}

// ------------------------------------------------------------------ Model Providers
function ModelProvidersSection() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["resources", "model_provider"],
    queryFn: () => api.resources.list("model_provider"),
  });
  const test = useResourceTest("model_provider");
  const [name, setName] = useState("");
  const [provider, setProvider] = useState("openai");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState<{ $secret: string } | null>(null);
  const [modelsText, setModelsText] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = { provider };
      if (baseUrl) config.base_url = baseUrl;
      if (apiKey) config.api_key = apiKey;
      const models = parseList(modelsText);
      if (models.length) config.models = models;
      return api.resources.create("model_provider", { name, config });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resources", "model_provider"] });
      setName("");
      setBaseUrl("");
      setApiKey(null);
      setModelsText("");
      toast.success("model provider saved");
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: (n: string) => api.resources.remove("model_provider", n),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["resources", "model_provider"] }),
    onError: (e) => toast.error((e as Error).message),
  });

  const rows = list.data ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      <SectionHeader
        title="Model Providers"
        description="Named LLM providers (openai / anthropic / ollama / custom). Bind a node's model field to one via {&quot;$resource&quot;: name} — pick a model from its list when configured."
      />
      <div className="flex flex-wrap items-end gap-2">
        {labelBox(
          "Name",
          <Input
            className="w-40"
            value={name}
            placeholder="prod-openai"
            onChange={(e) => setName(e.target.value)}
          />,
        )}
        {labelBox(
          "Provider",
          <Select className="w-36" value={provider} onChange={(e) => setProvider(e.target.value)}>
            <option value="openai">openai</option>
            <option value="anthropic">anthropic</option>
            <option value="ollama">ollama</option>
            <option value="custom">custom</option>
          </Select>,
        )}
        {labelBox(
          "Base URL",
          <Input
            className="w-52"
            value={baseUrl}
            placeholder="optional (e.g. proxy)"
            onChange={(e) => setBaseUrl(e.target.value)}
          />,
        )}
        {labelBox("API key", <SecretRefSelect value={apiKey} onChange={setApiKey} label="API key credential" />)}
        {labelBox(
          "Models",
          <Input
            className="w-56"
            value={modelsText}
            placeholder="gpt-4o, gpt-4o-mini"
            onChange={(e) => setModelsText(e.target.value)}
          />,
        )}
        <Button disabled={!name || create.isPending} onClick={() => create.mutate()}>
          Save
        </Button>
      </div>

      {list.isLoading ? (
        <SkeletonRows />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Cpu}
          headline="No model providers yet"
          hint="Register a provider once, then every model field can reference it by name."
        />
      ) : (
        <div className="space-y-2">
          {rows.map((row) => {
            const models = Array.isArray(row.config?.models)
              ? (row.config.models as string[])
              : [];
            const status = test.results[row.name]?.ok ?? row.ok;
            const result = test.results[row.name];
            return (
              <div key={row.name} className="gf-card p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <HealthDot ok={status} />
                  <span className="font-mono text-sm text-text-1">{row.name}</span>
                  <Badge tone="accent">{String(row.config?.provider ?? "—")}</Badge>
                  {row.config?.api_key ? <Badge tone="warning">api key</Badge> : null}
                  {models.length > 0 && (
                    <span className="text-[11px] text-text-3">{models.join(", ")}</span>
                  )}
                  <span className="ml-auto flex items-center gap-1.5">
                    <TestButton name={row.name} busy={test.busy} onRun={test.run} />
                    <RowDeleteButton
                      label={`Delete provider ${row.name}`}
                      onClick={() => setDeleteTarget(row.name)}
                    />
                  </span>
                </div>
                {result && !result.ok && (
                  <p className="mt-1 text-[11px] text-danger">{result.error ?? "test failed"}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDelete
        target={deleteTarget}
        title="Delete model provider"
        description="Flows that reference it will fail to resolve the binding at run time until it is recreated."
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && remove.mutate(deleteTarget)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ Knowledge Bases
interface VectorConn {
  name: string;
  backend: string;
}

function KnowledgeBasesSection() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["resources", "knowledge_base"],
    queryFn: () => api.resources.list("knowledge_base"),
  });
  const stores = useQuery({
    queryKey: ["vectorstores"],
    queryFn: async (): Promise<VectorConn[]> => {
      const r = await fetch("/api/v1/vectorstores");
      return r.ok ? r.json() : [];
    },
  });
  const test = useResourceTest("knowledge_base");
  const [name, setName] = useState("");
  const [vectorstore, setVectorstore] = useState("");
  const [collection, setCollection] = useState("");
  const [embProvider, setEmbProvider] = useState("openai");
  const [embModel, setEmbModel] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = {};
      if (vectorstore) config.vectorstore = vectorstore;
      if (collection) config.collection = collection;
      if (embProvider || embModel) config.embedding = { provider: embProvider, model: embModel };
      return api.resources.create("knowledge_base", { name, config });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resources", "knowledge_base"] });
      setName("");
      setCollection("");
      setEmbModel("");
      toast.success("knowledge base saved");
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: (n: string) => api.resources.remove("knowledge_base", n),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: ["resources", "knowledge_base"] }),
    onError: (e) => toast.error((e as Error).message),
  });

  const rows = list.data ?? [];
  const storeList = stores.data ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      <SectionHeader
        title="Knowledge Bases"
        description="A vector-store connection + embedding model + collection, bound as one named resource. Retrieval nodes reference it by name."
      />
      <div className="flex flex-wrap items-end gap-2">
        {labelBox(
          "Name",
          <Input
            className="w-40"
            value={name}
            placeholder="handbook"
            onChange={(e) => setName(e.target.value)}
          />,
        )}
        {labelBox(
          "Vector store",
          <Select
            className="w-40"
            value={vectorstore}
            onChange={(e) => setVectorstore(e.target.value)}
          >
            <option value="">connection…</option>
            {storeList.map((s) => (
              <option key={s.name} value={s.name}>
                {s.name} ({s.backend})
              </option>
            ))}
          </Select>,
        )}
        {labelBox(
          "Collection",
          <Input
            className="w-36"
            value={collection}
            placeholder="docs"
            onChange={(e) => setCollection(e.target.value)}
          />,
        )}
        {labelBox(
          "Embedding",
          <div className="flex gap-1">
            <Select className="w-28" value={embProvider} onChange={(e) => setEmbProvider(e.target.value)}>
              <option value="openai">openai</option>
              <option value="ollama">ollama</option>
              <option value="fake">fake</option>
            </Select>
            <Input
              className="w-40"
              value={embModel}
              placeholder="text-embedding-3-small"
              onChange={(e) => setEmbModel(e.target.value)}
            />
          </div>,
        )}
        <Button disabled={!name || create.isPending} onClick={() => create.mutate()}>
          Save
        </Button>
      </div>

      {list.isLoading ? (
        <SkeletonRows />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Library}
          headline="No knowledge bases yet"
          hint="Add one, then reference it from a Vector Retriever node."
        />
      ) : (
        <div className="space-y-2">
          {rows.map((row) => {
            const status = test.results[row.name]?.ok ?? row.ok;
            const result = test.results[row.name];
            const emb = row.config?.embedding as { provider?: string; model?: string } | undefined;
            return (
              <div key={row.name} className="gf-card p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <HealthDot ok={status} />
                  <span className="font-mono text-sm text-text-1">{row.name}</span>
                  {row.config?.vectorstore ? (
                    <Badge tone="accent">{String(row.config.vectorstore)}</Badge>
                  ) : null}
                  {row.config?.collection ? (
                    <span className="text-[11px] text-text-3">/{String(row.config.collection)}</span>
                  ) : null}
                  {emb?.model ? (
                    <span className="text-[11px] text-text-3">emb: {emb.model}</span>
                  ) : null}
                  <span className="ml-auto flex items-center gap-1.5">
                    <TestButton name={row.name} busy={test.busy} onRun={test.run} />
                    <RowDeleteButton
                      label={`Delete knowledge base ${row.name}`}
                      onClick={() => setDeleteTarget(row.name)}
                    />
                  </span>
                </div>
                {result && !result.ok && (
                  <p className="mt-1 text-[11px] text-danger">{result.error ?? "test failed"}</p>
                )}
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDelete
        target={deleteTarget}
        title="Delete knowledge base"
        description="Retrieval nodes bound to it will fail health checks until it is re-added. Documents on the vector store itself are not touched."
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && remove.mutate(deleteTarget)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ A2A Agents
function AgentCardPreview({ card }: { card: unknown }) {
  if (!card || typeof card !== "object") return null;
  const c = card as Record<string, unknown>;
  const skills = Array.isArray(c.skills) ? (c.skills as unknown[]) : [];
  return (
    <div className="mt-2 rounded-md border border-border bg-surface-1 p-2.5 text-xs">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="font-semibold text-text-1">{String(c.name ?? "Agent Card")}</span>
        {c.version ? <Badge tone="muted">v{String(c.version)}</Badge> : null}
      </div>
      {c.description ? <p className="mt-1 text-text-3">{String(c.description)}</p> : null}
      {c.url ? (
        <p className="mt-1 break-all font-mono text-[10.5px] text-text-3">{String(c.url)}</p>
      ) : null}
      {skills.length > 0 && (
        <div className="mt-1.5 flex flex-wrap gap-1">
          {skills.map((s, i) => {
            const sk = (s ?? {}) as Record<string, unknown>;
            return (
              <Badge key={i} tone="toolset">
                {String(sk.name ?? sk.id ?? "skill")}
              </Badge>
            );
          })}
        </div>
      )}
    </div>
  );
}

function A2AAgentsSection() {
  const queryClient = useQueryClient();
  const list = useQuery({
    queryKey: ["resources", "a2a_agent"],
    queryFn: () => api.resources.list("a2a_agent"),
  });
  const test = useResourceTest("a2a_agent");
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [auth, setAuth] = useState<{ $secret: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => {
      const config: Record<string, unknown> = { url };
      if (auth) config.auth = auth;
      return api.resources.create("a2a_agent", { name, config });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["resources", "a2a_agent"] });
      setName("");
      setUrl("");
      setAuth(null);
      toast.success("A2A agent saved");
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: (n: string) => api.resources.remove("a2a_agent", n),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["resources", "a2a_agent"] }),
    onError: (e) => toast.error((e as Error).message),
  });

  const rows = list.data ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      <SectionHeader
        title="A2A Agents"
        description="Remote A2A agents referenced as tools/sub-agents. Test fetches and caches the Agent Card (a read-only preview shown below each entry)."
      />
      <div className="flex flex-wrap items-end gap-2">
        {labelBox(
          "Name",
          <Input
            className="w-40"
            value={name}
            placeholder="triage-bot"
            onChange={(e) => setName(e.target.value)}
          />,
        )}
        {labelBox(
          "URL",
          <Input
            className="w-64"
            value={url}
            placeholder="https://host/a2a/agent"
            onChange={(e) => setUrl(e.target.value)}
          />,
        )}
        {labelBox("Auth", <SecretRefSelect value={auth} onChange={setAuth} label="Auth credential" />)}
        <Button disabled={!name || !url || create.isPending} onClick={() => create.mutate()}>
          Save
        </Button>
      </div>

      {list.isLoading ? (
        <SkeletonRows />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Bot}
          headline="No A2A agents yet"
          hint="Register a remote agent's URL, then Test to fetch its Agent Card."
        />
      ) : (
        <div className="space-y-2">
          {rows.map((row) => {
            const status = test.results[row.name]?.ok ?? row.ok;
            const result = test.results[row.name];
            const rowUrl = String(row.config?.url ?? "");
            const card = result?.detail ?? row.config?.card ?? (row as ResourceInfo).card;
            return (
              <div key={row.name} className="gf-card p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <HealthDot ok={status} />
                  <span className="font-mono text-sm text-text-1">{row.name}</span>
                  {row.config?.auth ? <Badge tone="warning">auth</Badge> : null}
                  {rowUrl && (
                    <span className="inline-flex max-w-[280px] items-center gap-1">
                      <span className="truncate font-mono text-[10.5px] text-text-3">{rowUrl}</span>
                      <CopyButton text={rowUrl} label={`Copy URL of ${row.name}`} />
                    </span>
                  )}
                  <span className="ml-auto flex items-center gap-1.5">
                    <TestButton name={row.name} busy={test.busy} onRun={test.run} />
                    <RowDeleteButton
                      label={`Delete agent ${row.name}`}
                      onClick={() => setDeleteTarget(row.name)}
                    />
                  </span>
                </div>
                {result && !result.ok && (
                  <p className="mt-1 text-[11px] text-danger">{result.error ?? "card fetch failed"}</p>
                )}
                {card ? <AgentCardPreview card={card} /> : null}
              </div>
            );
          })}
        </div>
      )}

      <ConfirmDelete
        target={deleteTarget}
        title="Delete A2A agent"
        description="Flows that call this agent will fail to resolve it until it is re-added."
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && remove.mutate(deleteTarget)}
      />
    </div>
  );
}
