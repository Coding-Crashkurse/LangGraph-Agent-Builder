/** Publish (semver bump + changelog + blocking diagnostics) and Share dialog
 * with A2A / MCP / API tabs incl. live card preview + snippets (SPEC §11.6). */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import type { Diagnostic, FlowInfo } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, Switch, Tabs } from "@/components/ui/controls";
import { toast } from "@/components/ui/toast";

import { useBuilder } from "./store";

export function PublishDialog({
  open,
  onClose,
  flow,
  beforePublish,
}: {
  open: boolean;
  onClose: () => void;
  flow: FlowInfo;
  beforePublish: () => Promise<void>;
}) {
  const [bump, setBump] = useState("patch");
  const [changelog, setChangelog] = useState("");
  const [blocking, setBlocking] = useState<Diagnostic[]>([]);
  const [busy, setBusy] = useState(false);
  const queryClient = useQueryClient();

  const publish = async () => {
    setBusy(true);
    try {
      await beforePublish();
      const result = await api.flows.publish(flow.id, { version: bump, changelog });
      if (result.published) {
        toast.success(`published v${result.version?.semver}`);
        queryClient.invalidateQueries({ queryKey: ["flow", flow.id] });
        onClose();
      } else {
        setBlocking(result.diagnostics.filter((d) => d.severity !== "info"));
      }
    } catch (error) {
      toast.error((error as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title="Publish version">
      <div className="space-y-3">
        <label className="block text-xs text-zinc-400">
          Version bump
          <Select value={bump} onChange={(e) => setBump(e.target.value)} className="mt-1">
            <option value="patch">patch</option>
            <option value="minor">minor</option>
            <option value="major">major</option>
          </Select>
        </label>
        <label className="block text-xs text-zinc-400">
          Changelog
          <textarea
            className="mt-1 min-h-[64px] w-full rounded-md border border-surface-700 bg-surface-900 px-2 py-1.5 text-sm text-zinc-100 focus:border-accent-500 focus:outline-none"
            value={changelog}
            onChange={(e) => setChangelog(e.target.value)}
            placeholder="What changed?"
          />
        </label>
        {blocking.length > 0 && (
          <div className="space-y-1 rounded border border-red-900/60 bg-red-950/30 p-2">
            {blocking.map((d, i) => (
              <p key={i} className="text-xs text-red-300">
                <span className="font-mono">{d.code}</span> {d.message}
              </p>
            ))}
          </div>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={publish} disabled={busy}>
            {busy ? "publishing…" : "Publish"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

type ShareTab = "a2a" | "mcp" | "api";

export function ShareDialog({
  open,
  onClose,
  flow,
}: {
  open: boolean;
  onClose: () => void;
  flow: FlowInfo;
}) {
  const [tab, setTab] = useState<ShareTab>("a2a");
  const baseSpec = useBuilder((s) => s.baseSpec);
  const updateFlowMeta = useBuilder((s) => s.updateFlowMeta);
  const [card, setCard] = useState<Record<string, unknown> | null>(null);

  const origin = window.location.origin;
  const a2a = baseSpec?.flow.a2a ?? { enabled: false };
  const mcp = baseSpec?.flow.mcp ?? { enabled: false };
  const endpoint = `${origin}/a2a/${flow.slug}/`;

  useEffect(() => {
    if (!open || !a2a.enabled) return;
    fetch(`/a2a/${flow.slug}/.well-known/agent-card.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setCard)
      .catch(() => setCard(null));
  }, [open, flow.slug, a2a.enabled]);

  const curl = useMemo(
    () =>
      `curl -X POST ${endpoint} \\\n  -H 'Content-Type: application/json' \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","messageId":"m1","parts":[{"kind":"text","text":"hello"}]}}}'`,
    [endpoint],
  );
  const python = useMemo(
    () =>
      `import httpx\n\nresp = httpx.post("${endpoint}", json={\n    "jsonrpc": "2.0", "id": 1, "method": "message/send",\n    "params": {"message": {"role": "user", "messageId": "m1",\n               "parts": [{"kind": "text", "text": "hello"}]}},\n})\nprint(resp.json()["result"]["status"]["state"])`,
    [endpoint],
  );
  const apiCurl = useMemo(
    () =>
      `curl -X POST ${origin}/api/v1/flows/${flow.id}/run \\\n  -H 'Content-Type: application/json' \\\n  -d '{"input_text": "hello", "tweaks": {"<node_id>": {"<field>": "value"}}}'`,
    [origin, flow.id],
  );

  return (
    <Dialog open={open} onClose={onClose} title={`Share · ${flow.name}`} className="w-[760px]">
      <div className="space-y-3">
        <Tabs
          value={tab}
          onChange={setTab}
          items={[
            { value: "a2a", label: "A2A" },
            { value: "mcp", label: "MCP" },
            { value: "api", label: "API" },
          ]}
        />
        {tab === "a2a" && (
          <div className="space-y-3">
            <Row label="Serve as A2A agent">
              <Switch
                checked={Boolean(a2a.enabled)}
                onCheckedChange={(v) => updateFlowMeta({ a2a: { ...a2a, enabled: v } })}
              />
            </Row>
            <Row label="Agent name">
              <Input
                value={a2a.agent_name ?? ""}
                placeholder={flow.name}
                onChange={(e) => updateFlowMeta({ a2a: { ...a2a, agent_name: e.target.value } })}
              />
            </Row>
            <Row label="Skill description (E060: required)">
              <Input
                value={a2a.description ?? ""}
                onChange={(e) => updateFlowMeta({ a2a: { ...a2a, description: e.target.value } })}
              />
            </Row>
            <Row label="Examples (comma-separated)">
              <Input
                value={(a2a.examples ?? []).join(", ")}
                onChange={(e) =>
                  updateFlowMeta({
                    a2a: {
                      ...a2a,
                      examples: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                    },
                  })
                }
              />
            </Row>
            <Row label="Auth">
              <Select
                value={a2a.auth ?? "public"}
                onChange={(e) =>
                  updateFlowMeta({ a2a: { ...a2a, auth: e.target.value as "public" | "api-key" } })
                }
              >
                <option value="public">public (session-namespaced)</option>
                <option value="api-key">api-key (X-API-Key, scope a2a:invoke)</option>
              </Select>
            </Row>
            <Snippet label={`Endpoint · ${endpoint}`} text={curl} />
            <Snippet label="Python (JSON-RPC)" text={python} />
            <div>
              <p className="mb-1 text-xs font-medium text-zinc-400">Live Agent Card</p>
              <pre className="max-h-52 overflow-auto rounded bg-surface-900 p-2 text-[10px] text-emerald-300">
                {card ? JSON.stringify(card, null, 2) : "publish with A2A enabled to see the card"}
              </pre>
            </div>
          </div>
        )}
        {tab === "mcp" && (
          <div className="space-y-3">
            <Row label="Serve as MCP tool">
              <Switch
                checked={Boolean(mcp.enabled)}
                onCheckedChange={(v) => updateFlowMeta({ mcp: { ...mcp, enabled: v } })}
              />
            </Row>
            <Row label="Tool name">
              <Input
                value={mcp.tool_name ?? ""}
                placeholder={flow.slug.replace(/-/g, "_")}
                onChange={(e) => updateFlowMeta({ mcp: { ...mcp, tool_name: e.target.value } })}
              />
            </Row>
            <Row label="Tool description (E062: required)">
              <Input
                value={mcp.description ?? ""}
                onChange={(e) => updateFlowMeta({ mcp: { ...mcp, description: e.target.value } })}
              />
            </Row>
            <Row label="Interrupt policy (E063)">
              <Select
                value={mcp.auto_resolve_interrupts ?? ""}
                onChange={(e) =>
                  updateFlowMeta({
                    mcp: {
                      ...mcp,
                      auto_resolve_interrupts: (e.target.value || null) as never,
                    },
                  })
                }
              >
                <option value="">reject flows with interrupts</option>
                <option value="approve">auto-approve interrupts</option>
                <option value="reject">auto-reject interrupts</option>
              </Select>
            </Row>
            <Snippet
              label="Client config (Claude Code / Cursor)"
              text={JSON.stringify(
                { mcpServers: { lga: { type: "http", url: `${origin}/mcp` } } },
                null,
                2,
              )}
            />
          </div>
        )}
        {tab === "api" && (
          <div className="space-y-3">
            <Snippet label="Run (blocking; tweaks are one-time overrides)" text={apiCurl} />
            <Snippet
              label="Webhook (fire-and-forget; body → data.webhook_payload)"
              text={`curl -X POST ${origin}/api/v1/webhook/${flow.slug} \\\n  -H 'X-API-Key: <key with webhook:invoke>' \\\n  -d '{"event": "ticket.created"}'`}
            />
          </div>
        )}
        <p className="text-[10px] text-zinc-600">
          Settings live in the FlowSpec — hit Save, then Publish to serve the new version.
        </p>
      </div>
    </Dialog>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-zinc-400">{label}</span>
      {children}
    </label>
  );
}

function Snippet({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-medium text-zinc-400">{label}</p>
        <button
          type="button"
          className="text-[10px] text-accent-400 hover:text-accent-300"
          onClick={() => {
            navigator.clipboard.writeText(text);
            toast.success("copied");
          }}
        >
          copy
        </button>
      </div>
      <pre className="overflow-x-auto rounded bg-surface-900 p-2 text-[10px] text-zinc-300">
        {text}
      </pre>
    </div>
  );
}
