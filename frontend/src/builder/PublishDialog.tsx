/** Publish (semver bump + changelog + blocking diagnostics) and Share dialog
 * with A2A / MCP / API tabs incl. live card preview + snippets (SPEC §11.6). */

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { api } from "@/api/client";
import type { Diagnostic, FlowInfo } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, Tabs } from "@/components/ui/controls";
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
  const baseSpec = useBuilder((s) => s.baseSpec);
  const updateFlowMeta = useBuilder((s) => s.updateFlowMeta);
  const [card, setCard] = useState<Record<string, unknown> | null>(null);

  const origin = window.location.origin;
  const a2a = baseSpec?.flow.a2a ?? { enabled: false };
  const mcp = baseSpec?.flow.mcp ?? { enabled: false };
  // The tabs ARE the serving surface, and surfaces are mutually exclusive
  // (SPEC §7.1): choosing a tab serves the flow that way and turns the others
  // off. A2A is the default for a new flow.
  const mode: ShareTab = a2a.enabled ? "a2a" : mcp.enabled ? "mcp" : "api";
  const setMode = (next: ShareTab) =>
    updateFlowMeta({
      a2a: { ...a2a, enabled: next === "a2a" },
      mcp: { ...mcp, enabled: next === "mcp" },
    });
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
  const runUrl = `${origin}/api/v1/flows/${flow.slug}/run`;
  const apiCurl = useMemo(
    () =>
      `curl -X POST ${runUrl} \\\n  -H 'Content-Type: application/json' \\\n  -d '{"input_text": "hello", "tweaks": {"<node_id>": {"<field>": "value"}}}'`,
    [runUrl],
  );
  const headlessSnippet = useMemo(
    () =>
      `import json\n\nfrom lga.compiler import compile_flow   # json -> LangGraph\nfrom lga.runtime import arun_flow\n\nspec = json.load(open("${flow.slug}.flow.json"))\ngraph = compile_flow(spec).graph        # vanilla StateGraph, no server needed\nresult = await arun_flow(spec, input_text="hello")\nprint(result.result_text)`,
    [flow.slug],
  );

  const download = async (format: "json" | "python") => {
    const response = await fetch(`/api/v1/flows/${flow.id}/export?format=${format}`);
    if (!response.ok) {
      toast.error(`export failed: ${response.status}`);
      return;
    }
    const content = format === "json"
      ? JSON.stringify(await response.json(), null, 2)
      : await response.text();
    const blob = new Blob([content], { type: "text/plain" });
    const anchor = document.createElement("a");
    anchor.href = URL.createObjectURL(blob);
    anchor.download = format === "json" ? `${flow.slug}.flow.json` : `${flow.slug}_flow.py`;
    anchor.click();
    URL.revokeObjectURL(anchor.href);
  };

  return (
    <Dialog open={open} onClose={onClose} title={`Share · ${flow.name}`} className="w-[760px]">
      <div className="space-y-3">
        <Tabs
          value={mode}
          onChange={(m) => setMode(m as ShareTab)}
          items={[
            { value: "a2a", label: "A2A" },
            { value: "mcp", label: "MCP" },
            { value: "api", label: "API" },
          ]}
        />
        <p className="text-[10px] text-zinc-500">
          Serving surfaces are exclusive — this flow is served as{" "}
          <span className="text-zinc-300">{mode.toUpperCase()}</span> and the others are off.
        </p>
        {mode === "a2a" && (
          <div className="space-y-3">
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
        {mode === "mcp" && (
          <div className="space-y-3">
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
        {mode === "api" && (
          <div className="space-y-3">
            <div className="flex items-center gap-2 rounded border border-surface-800 bg-surface-900 px-2.5 py-1.5">
              <span className="text-[10px] uppercase tracking-widest text-zinc-500">
                base url
              </span>
              <code className="text-xs text-emerald-300">{runUrl}</code>
              <button
                type="button"
                className="ml-auto text-[10px] text-accent-400 hover:text-accent-300"
                onClick={() => {
                  navigator.clipboard.writeText(runUrl);
                  toast.success("copied");
                }}
              >
                copy
              </button>
            </div>
            <Snippet label="Run (blocking; tweaks are one-time overrides)" text={apiCurl} />
            <Snippet
              label="Webhook (fire-and-forget; body → data.webhook_payload)"
              text={`curl -X POST ${origin}/api/v1/webhook/${flow.slug} \\\n  -H 'X-API-Key: <key with webhook:invoke>' \\\n  -d '{"event": "ticket.created"}'`}
            />
            <Snippet
              label="Headless Python (compile_flow = json → LangGraph)"
              text={headlessSnippet}
            />
            <div className="flex items-center gap-2">
              <span className="text-xs font-medium text-zinc-400">Export:</span>
              <Button variant="ghost" className="!h-7 !text-xs" onClick={() => download("json")}>
                ⬇ flow.json
              </Button>
              <Button variant="ghost" className="!h-7 !text-xs" onClick={() => download("python")}>
                ⬇ standalone flow.py
              </Button>
              <span className="text-[10px] text-zinc-600">
                flow.py runs under vanilla LangGraph
              </span>
            </div>
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
