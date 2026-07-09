/** Settings (SPEC §11.7): Global Variables, API Keys, MCP Servers. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, Tabs } from "@/components/ui/controls";
import { toast } from "@/components/ui/toast";

type Tab = "variables" | "apikeys" | "mcp" | "vectorstores";

interface VectorConn {
  name: string;
  backend: string;
  managed: boolean;
  ok?: boolean;
  error?: string | null;
  collections?: { name: string; dim: number; metric: string; count: number }[];
}

export function SettingsPage() {
  const [tab, setTab] = useState<Tab>("variables");
  return (
    <div className="min-h-screen bg-surface-950 px-8 py-6 text-zinc-100">
      <header className="mb-6 flex items-center gap-3">
        <Link to="/" className="text-sm text-zinc-500 hover:text-zinc-200">
          ← Flows
        </Link>
        <h1 className="text-lg font-bold">Settings</h1>
        <div className="ml-6">
          <Tabs
            value={tab}
            onChange={setTab}
            items={[
              { value: "variables", label: "Global Variables" },
              { value: "apikeys", label: "API Keys" },
              { value: "mcp", label: "MCP Servers" },
              { value: "vectorstores", label: "Vector Stores" },
            ]}
          />
        </div>
      </header>
      {tab === "variables" && <VariablesTab />}
      {tab === "apikeys" && <ApiKeysTab />}
      {tab === "mcp" && <McpServersTab />}
      {tab === "vectorstores" && <VectorStoresTab />}
    </div>
  );
}

// ------------------------------------------------------------------ Vector Stores (§8b.3/§11.8)
function VectorStoresTab() {
  const queryClient = useQueryClient();
  const conns = useQuery({
    queryKey: ["vectorstores"],
    queryFn: async (): Promise<VectorConn[]> => {
      const r = await fetch("/api/v1/vectorstores");
      return r.ok ? r.json() : [];
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

  return (
    <div className="max-w-3xl space-y-4">
      <p className="text-xs text-text-3">
        Installed backends:{" "}
        <span className="font-mono text-text-2">
          {(backends.data?.installed ?? ["local"]).join(", ")}
        </span>
      </p>
      <div className="flex items-end gap-2">
        <div>
          <label className="mb-1 block text-xs text-text-2">Name</label>
          <Input value={name} placeholder="prod-qdrant" onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="mb-1 block text-xs text-text-2">Backend</label>
          <Select value={backend} onChange={(e) => setBackend(e.target.value)}>
            {(backends.data?.all ?? ["local"]).map((b) => (
              <option key={b} value={b}>
                {b}
              </option>
            ))}
          </Select>
        </div>
        <Button disabled={!name || create.isPending} onClick={() => create.mutate()}>
          Add connection
        </Button>
      </div>
      <div className="space-y-2">
        {(conns.data ?? []).map((c) => (
          <div key={c.name} className="gf-card p-3">
            <div className="flex items-center gap-2">
              <span
                className="h-2 w-2 rounded-full"
                style={{ background: c.ok ? "var(--color-success)" : "var(--color-danger)" }}
                title={c.ok ? "healthy" : c.error ?? "unreachable"}
              />
              <span className="font-mono text-sm text-text-1">{c.name}</span>
              <Badge>{c.backend}</Badge>
              {c.managed && <Badge>managed</Badge>}
              {c.name !== "local" && (
                <button
                  className="ml-auto text-xs text-text-3 hover:text-danger"
                  onClick={() => remove.mutate(c.name)}
                >
                  delete
                </button>
              )}
            </div>
            {c.error && <p className="mt-1 text-[11px] text-danger">{c.error}</p>}
            {c.collections && c.collections.length > 0 && (
              <table className="mt-2 w-full text-left text-[11px] text-text-2">
                <thead className="text-text-3">
                  <tr>
                    <th className="py-0.5">collection</th>
                    <th>dim</th>
                    <th>metric</th>
                    <th>count</th>
                  </tr>
                </thead>
                <tbody className="font-mono tabular-nums">
                  {c.collections.map((col) => (
                    <tr key={col.name}>
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
    </div>
  );
}

function VariablesTab() {
  const queryClient = useQueryClient();
  const variables = useQuery({ queryKey: ["variables"], queryFn: api.variables.list });
  const [name, setName] = useState("");
  const [value, setValue] = useState("");
  const [kind, setKind] = useState<"generic" | "credential">("generic");

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

  return (
    <div className="max-w-2xl space-y-4">
      <p className="text-xs text-zinc-500">
        Reference in node configs as {"{\"$var\": \"name\"}"} /{" "}
        {"{\"$secret\": \"name\"}"}. Credentials are Fernet-encrypted and never
        readable through the API. Env promotion: LGA_VAR_* / LGA_CRED_*.
      </p>
      <div className="flex gap-2">
        <Input value={name} placeholder="name" onChange={(e) => setName(e.target.value)} />
        <Input
          value={value}
          placeholder="value"
          type={kind === "credential" ? "password" : "text"}
          onChange={(e) => setValue(e.target.value)}
        />
        <Select
          className="w-32"
          value={kind}
          onChange={(e) => setKind(e.target.value as never)}
        >
          <option value="generic">generic</option>
          <option value="credential">credential</option>
        </Select>
        <Button onClick={() => save.mutate()} disabled={!name || !value}>
          Save
        </Button>
      </div>
      <div className="space-y-1">
        {(variables.data ?? []).map((variable) => (
          <div
            key={variable.name}
            className="flex items-center gap-2 rounded border border-surface-800 bg-surface-900 px-3 py-1.5 text-sm"
          >
            <span className="font-mono">{variable.name}</span>
            <Badge tone={variable.kind === "credential" ? "amber" : "muted"}>
              {variable.kind}
            </Badge>
            <span className="ml-auto text-xs text-zinc-600">
              {variable.kind === "credential" ? "••••••" : ""}
            </span>
            <button
              className="text-xs text-zinc-600 hover:text-red-400"
              onClick={() =>
                api.variables
                  .delete(variable.name)
                  .then(() => queryClient.invalidateQueries({ queryKey: ["variables"] }))
              }
            >
              delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}

function ApiKeysTab() {
  const queryClient = useQueryClient();
  const keys = useQuery({ queryKey: ["apikeys"], queryFn: api.apikeys.list });
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<string[]>(["a2a:invoke"]);
  const [freshKey, setFreshKey] = useState<string | null>(null);

  const create = useMutation({
    mutationFn: () => api.apikeys.create({ name, scopes }),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ["apikeys"] });
      setFreshKey(result.key ?? null);
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const allScopes = ["studio:*", "a2a:invoke", "mcp:invoke", "webhook:invoke"];

  return (
    <div className="max-w-2xl space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Input
          className="w-48"
          value={name}
          placeholder="key name"
          onChange={(e) => setName(e.target.value)}
        />
        {allScopes.map((scope) => (
          <label key={scope} className="flex items-center gap-1 text-xs text-zinc-400">
            <input
              type="checkbox"
              checked={scopes.includes(scope)}
              onChange={(e) =>
                setScopes(
                  e.target.checked ? [...scopes, scope] : scopes.filter((s) => s !== scope),
                )
              }
            />
            {scope}
          </label>
        ))}
        <Button onClick={() => create.mutate()} disabled={scopes.length === 0}>
          Create
        </Button>
      </div>
      {freshKey && (
        <div className="rounded border border-emerald-800 bg-emerald-950/40 p-3">
          <p className="text-xs text-emerald-300">Copy now — shown exactly once:</p>
          <code className="break-all text-xs text-emerald-200">{freshKey}</code>
        </div>
      )}
      <div className="space-y-1">
        {(keys.data ?? []).map((key) => (
          <div
            key={key.id}
            className="flex items-center gap-2 rounded border border-surface-800 bg-surface-900 px-3 py-1.5 text-sm"
          >
            <span className="font-mono text-xs">{key.prefix}…</span>
            <span className="text-zinc-400">{key.name}</span>
            <span className="text-[10px] text-zinc-600">{key.scopes.join(", ")}</span>
            {key.revoked && <Badge tone="muted">revoked</Badge>}
            <span className="ml-auto text-[10px] text-zinc-600">{key.total_uses} uses</span>
            {!key.revoked && (
              <button
                className="text-xs text-zinc-600 hover:text-red-400"
                onClick={() =>
                  api.apikeys
                    .revoke(key.id)
                    .then(() => queryClient.invalidateQueries({ queryKey: ["apikeys"] }))
                }
              >
                revoke
              </button>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

function McpServersTab() {
  const queryClient = useQueryClient();
  const servers = useQuery({ queryKey: ["mcp-servers"], queryFn: api.mcpServers.list });
  const [name, setName] = useState("");
  const [transport, setTransport] = useState("streamable_http");
  const [url, setUrl] = useState("");

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

  return (
    <div className="max-w-2xl space-y-4">
      <p className="text-xs text-zinc-500">
        Globally managed MCP servers — the MCP Toolset component picks from this
        list. stdio transports are unavailable on Windows (selector loop).
      </p>
      <div className="flex gap-2">
        <Input
          className="w-40"
          value={name}
          placeholder="name"
          onChange={(e) => setName(e.target.value)}
        />
        <Select
          className="w-44"
          value={transport}
          onChange={(e) => setTransport(e.target.value)}
        >
          <option value="streamable_http">streamable_http</option>
          <option value="sse">sse</option>
          <option value="stdio">stdio</option>
        </Select>
        <Input
          value={url}
          placeholder={transport === "stdio" ? "command" : "http://host:port/mcp"}
          onChange={(e) => setUrl(e.target.value)}
        />
        <Button onClick={() => save.mutate()} disabled={!name || !url}>
          Save
        </Button>
      </div>
      <div className="space-y-1">
        {(servers.data ?? []).map((server) => (
          <div
            key={server.id}
            className="flex items-center gap-2 rounded border border-surface-800 bg-surface-900 px-3 py-1.5 text-sm"
          >
            <span className="font-mono">{server.name}</span>
            <Badge tone="sky">{server.transport}</Badge>
            <span className="truncate text-xs text-zinc-500">
              {String(server.config.url ?? server.config.command ?? "")}
            </span>
            <button
              className="ml-auto text-xs text-zinc-600 hover:text-red-400"
              onClick={() =>
                api.mcpServers
                  .delete(server.name)
                  .then(() => queryClient.invalidateQueries({ queryKey: ["mcp-servers"] }))
              }
            >
              delete
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
