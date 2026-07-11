/** Publish (semver bump + changelog + blocking diagnostics) and Share dialog
 * with A2A / MCP / API tabs incl. live card preview + snippets (SPEC §11.6). */

import { useQueryClient } from "@tanstack/react-query";
import { Bot, ChevronDown, ChevronRight, Download, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchAgentCard } from "@/api/a2a";
import { api } from "@/api/client";
import type { Diagnostic, FlowInfo } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, Tabs } from "@/components/ui/controls";
import { toast } from "@/components/ui/toast";

import { CopyButton } from "./playground/CopyButton";
import { useBuilder } from "./store";

type Bump = "patch" | "minor" | "major";

const BUMP_HINTS: Record<Bump, string> = {
  patch: "fixes, no contract change",
  minor: "new capability, backwards compatible",
  major: "breaking change to inputs/outputs",
};

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
  const [bump, setBump] = useState<Bump>("patch");
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
        <div>
          <p className="mb-1 text-xs font-medium text-text-2">Version bump</p>
          <Tabs
            value={bump}
            onChange={setBump}
            items={[
              { value: "patch", label: "patch" },
              { value: "minor", label: "minor" },
              { value: "major", label: "major" },
            ]}
          />
          <p className="mt-1 text-[11px] text-text-3">{BUMP_HINTS[bump]}</p>
        </div>
        <label className="block text-xs text-text-2">
          Changelog
          <textarea
            className="mt-1 min-h-[64px] w-full rounded-lg border border-border bg-surface-1 px-2 py-1.5 text-sm text-text-1 focus:border-accent focus:outline-none focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
            value={changelog}
            onChange={(e) => setChangelog(e.target.value)}
            placeholder="What changed?"
          />
        </label>
        {blocking.length > 0 && (
          <div role="alert" className="space-y-1.5 rounded-lg border-l-2 border-danger bg-danger/10 p-2.5">
            <p className="flex items-center gap-1.5 text-xs font-semibold text-danger">
              <TriangleAlert className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
              Publishing blocked — {blocking.length} diagnostic{blocking.length === 1 ? "" : "s"}
            </p>
            {blocking.map((d, i) => (
              <p key={i} className="text-xs text-danger">
                <span className="rounded bg-danger/15 px-1 py-px font-mono text-[11px]">
                  {d.code}
                </span>{" "}
                {d.message}
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
    fetchAgentCard(flow.slug).then(setCard);
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
    try {
      let content = await api.flows.export(flow.id, format);
      if (format === "json") {
        try {
          content = JSON.stringify(JSON.parse(content), null, 2);
        } catch {
          /* already text */
        }
      }
      const blob = new Blob([content], { type: "text/plain" });
      const anchor = document.createElement("a");
      anchor.href = URL.createObjectURL(blob);
      anchor.download = format === "json" ? `${flow.slug}.flow.json` : `${flow.slug}_flow.py`;
      anchor.click();
      URL.revokeObjectURL(anchor.href);
    } catch (error) {
      toast.error(`export failed: ${(error as Error).message}`);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} title={`Share · ${flow.name}`} className="w-[760px]">
      <div className="space-y-3">
        <Tabs
          value={mode}
          onChange={(m) => setMode(m)}
          items={[
            { value: "a2a", label: "A2A" },
            { value: "mcp", label: "MCP" },
            { value: "api", label: "API" },
          ]}
        />
        <p className="text-[11px] text-text-3">
          Serving surfaces are exclusive — this flow is served as{" "}
          <span className="text-text-2">{mode.toUpperCase()}</span> and the others are off.
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
              <p className="mb-1 text-xs font-medium text-text-2">Live Agent Card</p>
              <AgentCardPreview card={card} />
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
            <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-2 px-2.5 py-1.5">
              <span className="text-[11px] uppercase tracking-widest text-text-3">
                base url
              </span>
              <code className="truncate font-mono text-xs text-text-1">{runUrl}</code>
              <CopyButton text={runUrl} label="Copy base url" className="ml-auto" />
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
              <span className="text-xs font-medium text-text-2">Export:</span>
              <Button variant="ghost" className="!h-7 !text-xs" onClick={() => download("json")}>
                <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
                flow.json
              </Button>
              <Button variant="ghost" className="!h-7 !text-xs" onClick={() => download("python")}>
                <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
                standalone flow.py
              </Button>
              <span className="text-[11px] text-text-3">
                flow.py runs under vanilla LangGraph
              </span>
            </div>
          </div>
        )}
        <p className="text-[11px] text-text-3">
          Settings live in the FlowSpec — hit Save, then Publish to serve the new version.
        </p>
      </div>
    </Dialog>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-text-2">{label}</span>
      {children}
    </label>
  );
}

/** Mono snippet block with an icon copy button + copied feedback (§11.6). */
function Snippet({ label, text }: { label: string; text: string }) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <p className="text-xs font-medium text-text-2">{label}</p>
        <CopyButton text={text} label={`Copy: ${label}`} />
      </div>
      <pre className="overflow-x-auto rounded-lg border border-border bg-surface-2 p-2.5 font-mono text-[11px] leading-relaxed text-text-2">
        {text}
      </pre>
    </div>
  );
}

/** The live agent card rendered as a card (name, skills, capabilities) with a
 * collapsible raw-JSON view — not a bare JSON dump. */
function AgentCardPreview({ card }: { card: Record<string, unknown> | null }) {
  const [showRaw, setShowRaw] = useState(false);
  if (!card) {
    return (
      <p className="rounded-lg border border-border bg-surface-2 p-2.5 text-xs text-text-3">
        Publish with A2A enabled to see the live card.
      </p>
    );
  }
  const capabilities = (card.capabilities ?? {}) as Record<string, unknown>;
  const skills = Array.isArray(card.skills)
    ? (card.skills as Record<string, unknown>[])
    : [];
  const Chevron = showRaw ? ChevronDown : ChevronRight;

  return (
    <div className="space-y-2 rounded-[10px] border border-border bg-surface-2 p-3">
      <div className="flex items-center gap-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-accent/15">
          <Bot className="h-4 w-4 text-accent" strokeWidth={1.75} />
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-text-1">
            {String(card.name ?? "agent")}
          </p>
          <p className="truncate font-mono text-[10.5px] text-text-3">{String(card.url ?? "")}</p>
        </div>
        {typeof card.version === "string" && (
          <span className="ml-auto shrink-0 rounded-[6px] bg-surface-3 px-1.5 py-0.5 font-mono text-[10.5px] text-text-2">
            v{card.version}
          </span>
        )}
      </div>
      {typeof card.description === "string" && card.description && (
        <p className="text-xs leading-relaxed text-text-2">{card.description}</p>
      )}
      <div className="flex flex-wrap gap-1">
        {Boolean(capabilities.streaming) && <CapabilityChip label="streaming" />}
        {Boolean(capabilities.pushNotifications) && <CapabilityChip label="push notifications" />}
        {Boolean(capabilities.stateTransitionHistory) && <CapabilityChip label="history" />}
      </div>
      {skills.length > 0 && (
        <div className="space-y-1.5">
          <p className="text-[11px] uppercase tracking-widest text-text-3">skills</p>
          {skills.map((skill, index) => (
            <div key={index} className="rounded-lg border border-border bg-surface-1 px-2.5 py-1.5">
              <p className="font-mono text-xs text-text-1">{String(skill.name ?? skill.id ?? "")}</p>
              {typeof skill.description === "string" && skill.description && (
                <p className="text-[11px] text-text-2">{skill.description}</p>
              )}
              {Array.isArray(skill.tags) && skill.tags.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {(skill.tags as unknown[]).map((tag, tagIndex) => (
                    <span
                      key={tagIndex}
                      className="rounded-[6px] bg-surface-3 px-1.5 py-px text-[10.5px] text-text-3"
                    >
                      {String(tag)}
                    </span>
                  ))}
                </div>
              )}
            </div>
          ))}
        </div>
      )}
      <button
        type="button"
        aria-expanded={showRaw}
        onClick={() => setShowRaw((v) => !v)}
        className="flex items-center gap-1 rounded text-[11px] text-text-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
      >
        <Chevron className="h-3 w-3" strokeWidth={1.75} />
        raw card JSON
      </button>
      {showRaw && (
        <pre className="max-h-52 overflow-auto rounded-lg border border-border bg-surface-1 p-2 font-mono text-[10.5px] leading-relaxed text-text-2">
          {JSON.stringify(card, null, 2)}
        </pre>
      )}
    </div>
  );
}

function CapabilityChip({ label }: { label: string }) {
  return (
    <span className="rounded-[6px] bg-success/15 px-1.5 py-px text-[10.5px] text-success">
      {label}
    </span>
  );
}
