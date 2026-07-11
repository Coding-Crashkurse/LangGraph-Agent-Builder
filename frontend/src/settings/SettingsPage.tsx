/** Settings (SPEC §11.7): Global Variables, API Keys, MCP Servers, Vector
 * Stores — left section nav, descriptor-style tables, guarded deletes. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  Boxes,
  Database,
  KeyRound,
  Plug,
  Variable,
  type LucideIcon,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Checkbox, Select } from "@/components/ui/controls";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import {
  ConfirmDelete,
  CopyButton,
  EmptyState,
  RowDeleteButton,
  SectionHeader,
  SkeletonRows,
  Th,
} from "./ui";

type SectionId = "variables" | "apikeys" | "mcp" | "vectorstores";

const SECTIONS: { id: SectionId; label: string; icon: LucideIcon }[] = [
  { id: "variables", label: "Variables", icon: Variable },
  { id: "apikeys", label: "API Keys", icon: KeyRound },
  { id: "mcp", label: "MCP Servers", icon: Plug },
  { id: "vectorstores", label: "Vector Stores", icon: Database },
];

interface VectorConn {
  name: string;
  backend: string;
  managed: boolean;
  ok?: boolean;
  error?: string | null;
  collections?: { name: string; dim: number; metric: string; count: number }[];
}

export function SettingsPage() {
  const [section, setSection] = useState<SectionId>("variables");
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
        <h1 className="text-lg font-bold">Settings</h1>
        <Link
          to="/resources"
          className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-text-2 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        >
          <Boxes size={14} strokeWidth={1.75} aria-hidden />
          Resources
        </Link>
      </header>

      <div className="flex max-w-5xl gap-8">
        <nav aria-label="Settings sections" className="w-48 shrink-0 space-y-0.5">
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
          {section === "variables" && <VariablesSection />}
          {section === "apikeys" && <ApiKeysSection />}
          {section === "mcp" && <McpServersSection />}
          {section === "vectorstores" && <VectorStoresSection />}
        </main>
      </div>
    </div>
  );
}

// ------------------------------------------------------------------ Variables (§10.3)
function VariablesSection() {
  const queryClient = useQueryClient();
  const variables = useQuery({ queryKey: ["variables"], queryFn: api.variables.list });
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [kind, setKind] = useState<"generic" | "credential">("generic");
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () => api.variables.set({ name, value, kind }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["variables"] });
      setName("");
      setValue("");
      toast.success("saved (credentials are write-only)");
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const remove = useMutation({
    mutationFn: (n: string) => api.variables.delete(n),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["variables"] }),
    onError: (error) => toast.error((error as Error).message),
  });

  const list = variables.data ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      <SectionHeader
        title="Global Variables"
        description={
          <>
            Reference in node configs as{" "}
            <code className="font-mono text-text-2">{'{"$var": "name"}'}</code> /{" "}
            <code className="font-mono text-text-2">{'{"$secret": "name"}'}</code>. Credentials
            are Fernet-encrypted and never readable through the API. Env promotion: LAB_VAR_* /
            LAB_CRED_*.
          </>
        }
      />
      <div className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-text-2">Name</span>
          <Input
            className="w-44"
            value={name}
            placeholder="OPENAI_API_KEY"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-text-2">Value</span>
          <Input
            className="w-56"
            value={value}
            placeholder="value"
            type={kind === "credential" ? "password" : "text"}
            onChange={(e) => setValue(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-text-2">Kind</span>
          <Select
            className="w-32"
            value={kind}
            onChange={(e) => setKind(e.target.value as "generic" | "credential")}
          >
            <option value="generic">generic</option>
            <option value="credential">credential</option>
          </Select>
        </label>
        <Button onClick={() => save.mutate()} disabled={!name || !value || save.isPending}>
          Save
        </Button>
      </div>

      {variables.isLoading ? (
        <SkeletonRows />
      ) : list.length === 0 ? (
        <EmptyState
          icon={Variable}
          headline="No variables yet"
          hint="Store shared values and credentials once — bind them from any secret or string field."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-1">
              <tr>
                <Th>name</Th>
                <Th>kind</Th>
                <Th>value</Th>
                <Th>reference</Th>
                <Th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {list.map((variable) => {
                const ref =
                  variable.kind === "credential"
                    ? `{"$secret": "${variable.name}"}`
                    : `{"$var": "${variable.name}"}`;
                return (
                  <tr
                    key={variable.name}
                    className="border-t border-border text-text-2 hover:bg-surface-2"
                  >
                    <td className="px-3 py-1.5 font-mono text-text-1">{variable.name}</td>
                    <td className="px-3 py-1.5">
                      <Badge tone={variable.kind === "credential" ? "warning" : "muted"}>
                        {variable.kind}
                      </Badge>
                    </td>
                    <td className="px-3 py-1.5 text-text-3">
                      {variable.kind === "credential" ? "••••••" : "stored"}
                    </td>
                    <td className="px-3 py-1.5">
                      <span className="inline-flex items-center gap-1">
                        <code className="font-mono text-[10.5px] text-text-3">{ref}</code>
                        <CopyButton text={ref} label={`Copy reference for ${variable.name}`} />
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <RowDeleteButton
                        label={`Delete variable ${variable.name}`}
                        onClick={() => setDeleteTarget(variable.name)}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDelete
        target={deleteTarget}
        title="Delete variable"
        description="Flows that reference it will fail to resolve the binding at run time until it is recreated."
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && remove.mutate(deleteTarget)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ API Keys (§9)
function ApiKeysSection() {
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: ["apikeys"], queryFn: api.apikeys.list });
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["a2a:invoke"]);
  const [freshKey, setFreshKey] = useState<string | null>(null);
  const [revokeTarget, setRevokeTarget] = useState<{ id: string; name: string } | null>(null);

  const create = useMutation({
    mutationFn: () => api.apikeys.create({ name, scopes }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["apikeys"] });
      setFreshKey(result.key ?? null);
      setName("");
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const revoke = useMutation({
    mutationFn: (id: string) => api.apikeys.revoke(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["apikeys"] }),
    onError: (error) => toast.error((error as Error).message),
  });

  const allScopes = ["studio:*", "a2a:invoke", "mcp:invoke", "webhook:invoke"];
  const list = keys.data ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      <SectionHeader
        title="API Keys"
        description="Scoped keys for the published surfaces — A2A agents, MCP tools and webhooks. The key value is shown exactly once, on creation."
      />
      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="w-48"
          value={name}
          placeholder="key name"
          aria-label="Key name"
          onChange={(e) => setName(e.target.value)}
        />
        {allScopes.map((scope) => (
          <label key={scope} className="flex items-center gap-1 text-xs text-text-2">
            <Checkbox
              label={`Scope ${scope}`}
              checked={scopes.includes(scope)}
              onCheckedChange={(checked) =>
                setScopes(checked ? [...scopes, scope] : scopes.filter((s) => s !== scope))
              }
            />
            {scope}
          </label>
        ))}
        <Button
          onClick={() => create.mutate()}
          disabled={scopes.length === 0 || create.isPending}
        >
          Create
        </Button>
      </div>

      {freshKey && (
        <div className="rounded-lg border border-success/50 bg-success/10 p-3">
          <p className="text-xs font-medium text-success">Copy now — shown exactly once:</p>
          <div className="mt-1 flex items-center gap-1.5">
            <code className="break-all font-mono text-xs text-success">{freshKey}</code>
            <CopyButton text={freshKey} label="Copy API key" />
          </div>
        </div>
      )}

      {keys.isLoading ? (
        <SkeletonRows />
      ) : list.length === 0 ? (
        <EmptyState
          icon={KeyRound}
          headline="No API keys yet"
          hint="Create a scoped key to call published flows from outside the Studio."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-1">
              <tr>
                <Th>key</Th>
                <Th>name</Th>
                <Th>scopes</Th>
                <Th className="text-right">uses</Th>
                <Th className="w-20" />
              </tr>
            </thead>
            <tbody>
              {list.map((key) => (
                <tr
                  key={key.id}
                  className="border-t border-border text-text-2 hover:bg-surface-2"
                >
                  <td className="px-3 py-1.5 font-mono text-[10.5px]">{key.prefix}…</td>
                  <td className="px-3 py-1.5 text-text-1">{key.name}</td>
                  <td className="px-3 py-1.5 text-[10.5px] text-text-3">
                    {key.scopes.join(", ")}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums text-text-3">
                    {key.total_uses}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {key.revoked ? (
                      <Badge tone="muted">revoked</Badge>
                    ) : (
                      <button
                        type="button"
                        className="rounded px-1 text-xs text-text-3 hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
                        onClick={() => setRevokeTarget({ id: key.id, name: key.name })}
                      >
                        revoke
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDelete
        target={revokeTarget?.name ?? null}
        title="Revoke API key"
        verb="Revoke"
        confirmLabel="Revoke key"
        description="Requests using this key are rejected immediately. Revocation cannot be undone."
        onClose={() => setRevokeTarget(null)}
        onConfirm={() => revokeTarget && revoke.mutate(revokeTarget.id)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ MCP Servers (§8.3)
// Exported so the Resources page can reuse the exact same CRUD (shared
// api.mcpServers storage) instead of duplicating it.
export function McpServersSection() {
  const queryClient = useQueryClient();
  const servers = useQuery({ queryKey: ["mcp-servers"], queryFn: api.mcpServers.list });
  const [name, setName] = useState("");
  const [transport, setTransport] = useState("streamable_http");
  const [url, setUrl] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const save = useMutation({
    mutationFn: () =>
      api.mcpServers.upsert({
        name,
        transport,
        config: transport === "stdio" ? { command: url } : { url },
      }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["mcp-servers"] });
      setName("");
      setUrl("");
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const remove = useMutation({
    mutationFn: (n: string) => api.mcpServers.delete(n),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["mcp-servers"] }),
    onError: (error) => toast.error((error as Error).message),
  });

  const list = servers.data ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      <SectionHeader
        title="MCP Servers"
        description="Globally managed MCP servers — the MCP Toolset component picks from this list. stdio transports are unavailable on Windows (selector loop)."
      />
      <div className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-text-2">Name</span>
          <Input
            className="w-40"
            value={name}
            placeholder="name"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-text-2">Transport</span>
          <Select
            className="w-44"
            value={transport}
            onChange={(e) => setTransport(e.target.value)}
          >
            <option value="streamable_http">streamable_http</option>
            <option value="sse">sse</option>
            <option value="stdio">stdio</option>
          </Select>
        </label>
        <label className="block min-w-0 flex-1">
          <span className="mb-1 block text-xs font-medium text-text-2">
            {transport === "stdio" ? "Command" : "URL"}
          </span>
          <Input
            value={url}
            placeholder={transport === "stdio" ? "command" : "http://host:port/mcp"}
            onChange={(e) => setUrl(e.target.value)}
          />
        </label>
        <Button onClick={() => save.mutate()} disabled={!name || !url || save.isPending}>
          Save
        </Button>
      </div>

      {servers.isLoading ? (
        <SkeletonRows />
      ) : list.length === 0 ? (
        <EmptyState
          icon={Plug}
          headline="No MCP servers yet"
          hint="Register a server here and every MCP Toolset node can attach its tools."
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-border">
          <table className="w-full text-left text-xs">
            <thead className="bg-surface-1">
              <tr>
                <Th>name</Th>
                <Th>transport</Th>
                <Th>endpoint</Th>
                <Th className="w-8" />
              </tr>
            </thead>
            <tbody>
              {list.map((server) => {
                const endpoint = String(server.config.url ?? server.config.command ?? "");
                return (
                  <tr
                    key={server.id}
                    className="border-t border-border text-text-2 hover:bg-surface-2"
                  >
                    <td className="px-3 py-1.5 font-mono text-text-1">{server.name}</td>
                    <td className="px-3 py-1.5">
                      <Badge tone="toolset">{server.transport}</Badge>
                    </td>
                    <td className="max-w-[260px] px-3 py-1.5">
                      <span className="inline-flex max-w-full items-center gap-1">
                        <span className="truncate font-mono text-[10.5px] text-text-3">
                          {endpoint}
                        </span>
                        {endpoint && (
                          <CopyButton
                            text={endpoint}
                            label={`Copy endpoint of ${server.name}`}
                          />
                        )}
                      </span>
                    </td>
                    <td className="px-2 py-1.5 text-right">
                      <RowDeleteButton
                        label={`Delete server ${server.name}`}
                        onClick={() => setDeleteTarget(server.name)}
                      />
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}

      <ConfirmDelete
        target={deleteTarget}
        title="Delete MCP server"
        description="MCP Toolset nodes that pick this server will stop resolving tools until it is re-added."
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && remove.mutate(deleteTarget)}
      />
    </div>
  );
}

// ------------------------------------------------------------------ Vector Stores (§8b.3/§11.8)
function VectorStoresSection() {
  const queryClient = useQueryClient();
  const conns = useQuery({
    queryKey: ["vectorstores"],
    queryFn: async (): Promise<VectorConn[]> => {
      const r = await fetch("/api/v1/vectorstores");
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
  });
  const backends = useQuery({
    queryKey: ["vs-backends"],
    queryFn: async (): Promise<{ installed: string[]; all: string[] }> => {
      const r = await fetch("/api/v1/vectorstores/backends");
      return r.ok ? r.json() : { installed: [], all: [] };
    },
  });
  const [name, setName] = useState("");
  const [backend, setBackend] = useState("local");
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: async () => {
      const r = await fetch("/api/v1/vectorstores", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ name, backend, config: {} }),
      });
      if (!r.ok) throw new Error(await r.text());
    },
    onSuccess: () => {
      setName("");
      queryClient.invalidateQueries({ queryKey: ["vectorstores"] });
      toast.success("connection created");
    },
    onError: (e) => toast.error((e as Error).message),
  });
  const remove = useMutation({
    mutationFn: async (n: string) => {
      await fetch(`/api/v1/vectorstores/${n}`, { method: "DELETE" });
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["vectorstores"] }),
  });

  const list = conns.data ?? [];

  return (
    <div className="max-w-3xl space-y-4">
      <SectionHeader
        title="Vector Stores"
        description={
          <>
            Named connections the Vector Store components bind to via{" "}
            <code className="font-mono text-text-2">{'{"$vectorstore": "name"}'}</code>. Installed
            backends:{" "}
            <span className="font-mono text-text-2">
              {(backends.data?.installed ?? ["local"]).join(", ")}
            </span>
          </>
        }
      />
      <div className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-text-2">Name</span>
          <Input
            className="w-44"
            value={name}
            placeholder="prod-qdrant"
            onChange={(e) => setName(e.target.value)}
          />
        </label>
        <label className="block">
          <span className="mb-1 block text-xs font-medium text-text-2">Backend</span>
          <Select className="w-40" value={backend} onChange={(e) => setBackend(e.target.value)}>
            {(backends.data?.all ?? ["local"]).map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </Select>
        </label>
        <Button disabled={!name || create.isPending} onClick={() => create.mutate()}>
          Add connection
        </Button>
      </div>

      {conns.isLoading ? (
        <SkeletonRows />
      ) : conns.isError ? (
        <div className="rounded-lg border border-border border-l-2 border-l-danger bg-surface-1 p-3">
          <p className="text-xs text-danger">
            Could not load connections: {(conns.error as Error).message}
          </p>
          <Button variant="secondary" size="sm" className="mt-2" onClick={() => conns.refetch()}>
            Retry
          </Button>
        </div>
      ) : list.length === 0 ? (
        <EmptyState
          icon={Database}
          headline="No connections yet"
          hint="Add a connection to index and search documents from RAG components."
        />
      ) : (
        <div className="space-y-2">
          {list.map((c) => (
            <div key={c.name} className="gf-card p-3">
              <div className="flex items-center gap-2">
                <span
                  className={cn("h-2 w-2 rounded-full", c.ok ? "bg-success" : "bg-danger")}
                  title={c.ok ? "healthy" : c.error ?? "unreachable"}
                  aria-hidden
                />
                <span className="sr-only">{c.ok ? "healthy" : "unreachable"}</span>
                <span className="font-mono text-sm text-text-1">{c.name}</span>
                <Badge>{c.backend}</Badge>
                {c.managed && <Badge>managed</Badge>}
                {c.name !== "local" && (
                  <span className="ml-auto">
                    <RowDeleteButton
                      label={`Delete connection ${c.name}`}
                      onClick={() => setDeleteTarget(c.name)}
                    />
                  </span>
                )}
              </div>
              {c.error && <p className="mt-1 text-[11px] text-danger">{c.error}</p>}
              {c.collections && c.collections.length > 0 && (
                <table className="mt-2 w-full text-left text-[11px] text-text-2">
                  <thead>
                    <tr className="text-[11px] uppercase tracking-wide text-text-3">
                      <th className="py-0.5 font-medium">collection</th>
                      <th className="font-medium">dim</th>
                      <th className="font-medium">metric</th>
                      <th className="font-medium">count</th>
                    </tr>
                  </thead>
                  <tbody className="font-mono tabular-nums">
                    {c.collections.map((col) => (
                      <tr key={col.name} className="hover:bg-surface-2">
                        <td className="py-0.5">{col.name}</td>
                        <td>{col.dim}</td>
                        <td>{col.metric}</td>
                        <td>{col.count}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDelete
        target={deleteTarget}
        title="Delete connection"
        description="Flows bound to this connection will fail health checks until it is re-added. Collections on the backend itself are not touched."
        onClose={() => setDeleteTarget(null)}
        onConfirm={() => deleteTarget && remove.mutate(deleteTarget)}
      />
    </div>
  );
}
