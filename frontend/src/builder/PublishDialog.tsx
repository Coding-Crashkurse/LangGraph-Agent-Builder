/** Publish (semver bump + changelog + blocking diagnostics), and the two-step
 * publish wizard (REFACTOR.md §5.3 — "one contract, three doors; a wizard,
 * never raw JSON"):
 *   step 1  pick the serving door (MCP Tool / A2A Agent / HTTP API) as explicit
 *           cards — the pick writes serving.mode + the derived a2a/mcp booleans;
 *   step 2  the per-door form — ONLY named fields with live publish-guard
 *           validation (E060–E065). The A2A card / MCP tool schema is generated
 *           server-side; AgentCardPreview is display-only.
 */

import { useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ArrowRight,
  Bot,
  ChevronDown,
  ChevronRight,
  Download,
  Globe,
  TriangleAlert,
  Users,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { fetchAgentCard } from "@/api/a2a";
import { api } from "@/api/client";
import type {
  A2ASettings,
  Diagnostic,
  FlowInfo,
  FlowMeta,
  McpSettings,
} from "@/api/types";
import { Button } from "@/components/ui/button";
import { Checkbox, Select, Switch, Tabs } from "@/components/ui/controls";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import { useServerConfig } from "./hooks/useServerConfig";
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

// ---------------------------------------------------------------- publish wizard
type Door = "mcp" | "a2a" | "api";

interface DoorDef {
  value: Door;
  label: string;
  icon: LucideIcon;
  blurb: string;
}

/** Order is intentional: MCP · A2A · HTTP (REFACTOR.md §5.3). */
const DOORS: DoorDef[] = [
  {
    value: "mcp",
    label: "MCP Tool",
    icon: Wrench,
    blurb: "Expose this flow as a callable tool for MCP clients like Claude Code or Cursor.",
  },
  {
    value: "a2a",
    label: "A2A Agent",
    icon: Bot,
    blurb: "Publish as an A2A agent that other agents can discover and delegate tasks to.",
  },
  {
    value: "api",
    label: "HTTP API",
    icon: Globe,
    blurb: "Call the flow directly over HTTP/JSON, or export it to run headless.",
  },
];

const DOOR_LABEL: Record<Door, string> = {
  mcp: "MCP Tool",
  a2a: "A2A Agent",
  api: "HTTP API",
};

/** Interrupt (human-in-the-loop) components — power E063 + the HITL A2A note. */
const INTERRUPT_IDS = new Set(["lab.flow.human_approval", "lab.flow.human_input"]);
/** Prefilled A2A input/output modes — mirror the FlowSpec contract defaults. */
const DEFAULT_MODES = ["text/plain", "application/json"];
const MODE_OPTIONS = ["text/plain", "application/json", "text/markdown"];
/** Publish-guard codes surfaced by the wizard (SPEC §7.4/§8.1). */
const GUARD_CODES = new Set(["E060", "E061", "E062", "E063", "E064", "E065"]);
/** Guards that map to a visible named field (rendered inline, not in the summary). */
const NAMED_GUARD_FIELDS = new Set([
  "a2a.description",
  "a2a.examples",
  "mcp.description",
  "mcp.auto_resolve_interrupts",
]);

interface PublishGuard {
  code: string;
  severity: Diagnostic["severity"];
  message: string;
  field?: string;
  node_id?: string;
}

/** Client-side mirror of the backend `publish_guards` for the door-scoped,
 * named-field checks (E060–E063). The /validate endpoint only runs these at
 * publish time (server-side), so deriving them here is what makes them *live*
 * as the user types. E064/E065 (end-node output_schema) come from the store's
 * validation and are merged in by the caller. */
function deriveGuards(
  flow: FlowMeta | undefined,
  a2a: A2ASettings,
  mcp: McpSettings,
  mode: Door,
  interruptCount: number,
): PublishGuard[] {
  const guards: PublishGuard[] = [];
  const flowDesc = (flow?.description ?? "").trim();
  if (mode === "a2a") {
    if (!(a2a.description ?? "").trim() && !flowDesc) {
      guards.push({
        code: "E060",
        severity: "error",
        field: "a2a.description",
        message: "An A2A skill description is required before publishing.",
      });
    }
    if (!(a2a.examples?.length ?? 0)) {
      guards.push({
        code: "E061",
        severity: "warning",
        field: "a2a.examples",
        message: "Skill examples are recommended — agents route better with examples.",
      });
    }
  } else if (mode === "mcp") {
    if (!(mcp.description ?? "").trim() && !flowDesc) {
      guards.push({
        code: "E062",
        severity: "error",
        field: "mcp.description",
        message: "An MCP tool description is required before publishing.",
      });
    }
    if (interruptCount > 0 && (mcp.auto_resolve_interrupts ?? null) === null) {
      guards.push({
        code: "E063",
        severity: "error",
        field: "mcp.auto_resolve_interrupts",
        message:
          "This flow has interrupt nodes; MCP has no input-required concept — set an interrupt policy.",
      });
    }
  }
  return guards;
}

const splitList = (value: string) =>
  value
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean);

/**
 * Comma-separated list editor. Holds the raw text locally so the user can type
 * commas (and trailing spaces) freely — the parent only ever sees the parsed
 * array. Re-syncs from `value` only when the external list genuinely diverges
 * from what our text would produce (e.g. switching flows), never on a keystroke.
 */
function CommaListInput({
  value,
  placeholder,
  onChange,
}: {
  value: string[];
  placeholder?: string;
  onChange: (v: string[]) => void;
}) {
  const [raw, setRaw] = useState(() => value.join(", "));
  useEffect(() => {
    if (splitList(raw).join(" ") !== value.join(" ")) setRaw(value.join(", "));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Input
      value={raw}
      placeholder={placeholder}
      onChange={(e) => {
        setRaw(e.target.value);
        onChange(splitList(e.target.value));
      }}
    />
  );
}

export function ShareDialog({
  open,
  onClose,
  flow,
  onProceedToPublish,
}: {
  open: boolean;
  onClose: () => void;
  flow: FlowInfo;
  onProceedToPublish: () => void;
}) {
  const baseSpec = useBuilder((s) => s.baseSpec);
  const nodes = useBuilder((s) => s.nodes);
  const descriptors = useBuilder((s) => s.descriptors);
  const storeDiagnostics = useBuilder((s) => s.diagnostics);
  const updateFlowMeta = useBuilder((s) => s.updateFlowMeta);
  const grpcAvailable = useServerConfig().a2a_grpc_available;

  const [step, setStep] = useState<1 | 2>(1);
  const [card, setCard] = useState<Record<string, unknown> | null>(null);

  const origin = window.location.origin;
  const flowMeta = baseSpec?.flow;
  // Memoised so the guard useMemo below has stable deps (not fresh objects each render).
  const a2a: A2ASettings = useMemo(() => flowMeta?.a2a ?? { enabled: false }, [flowMeta]);
  const mcp: McpSettings = useMemo(() => flowMeta?.mcp ?? { enabled: false }, [flowMeta]);
  // The door choice IS the serving surface, and surfaces are mutually exclusive
  // (SPEC §7.1): picking a door serves the flow that way and turns the others
  // off. serving.mode is authoritative (SPEC §5.2) — persisted specs carry it,
  // so it MUST be written here alongside the legacy enabled booleans.
  const mode: Door =
    flowMeta?.serving?.mode ?? (a2a.enabled ? "a2a" : mcp.enabled ? "mcp" : "api");
  const setMode = (next: Door) =>
    updateFlowMeta({
      serving: { mode: next },
      a2a: { ...a2a, enabled: next === "a2a" },
      mcp: { ...mcp, enabled: next === "mcp" },
    });

  // Reset to the door picker each time the wizard opens.
  useEffect(() => {
    if (open) setStep(1);
  }, [open]);

  // Interrupt nodes drive the E063 guard and the HITL marketing note (§5.3).
  const interruptCount = useMemo(
    () =>
      nodes.filter((node) => {
        if (INTERRUPT_IDS.has(node.data.componentId)) return true;
        return descriptors.get(node.data.componentId)?.node_kind === "interrupt";
      }).length,
    [nodes, descriptors],
  );

  const guards = useMemo<PublishGuard[]>(() => {
    const derived = deriveGuards(flowMeta, a2a, mcp, mode, interruptCount);
    const seen = new Set(derived.map((g) => `${g.code}:${g.field ?? ""}`));
    // Merge any E06x the builder's validation has already surfaced (E064/E065
    // on the end node) without duplicating the client-derived ones.
    for (const d of storeDiagnostics) {
      if (!GUARD_CODES.has(d.code)) continue;
      const key = `${d.code}:${d.field ?? ""}`;
      if (seen.has(key)) continue;
      seen.add(key);
      derived.push({
        code: d.code,
        severity: d.severity,
        message: d.message,
        field: d.field ?? undefined,
        node_id: d.node_id ?? undefined,
      });
    }
    return derived;
  }, [flowMeta, a2a, mcp, mode, interruptCount, storeDiagnostics]);

  const guardFor = (field: string) => guards.find((g) => g.field === field);
  const errorGuards = guards.filter((g) => g.severity === "error");
  const summaryGuards = errorGuards.filter(
    (g) => !g.field || !NAMED_GUARD_FIELDS.has(g.field),
  );

  const endpoint = `${origin}/a2a/${flow.slug}/`;
  const runUrl = `${origin}/api/v1/flows/${flow.slug}/run`;

  useEffect(() => {
    if (!open || !a2a.enabled) return;
    fetchAgentCard(flow.slug).then(setCard);
  }, [open, flow.slug, a2a.enabled]);

  const curl = useMemo(
    () =>
      `curl -X POST ${endpoint} \\\n  -H 'Content-Type: application/json' \\\n  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"role":"user","messageId":"m1","parts":[{"kind":"text","text":"hello"}]}}}'`,
    [endpoint],
  );
  const apiCurl = useMemo(
    () =>
      `curl -X POST ${runUrl} \\\n  -H 'Content-Type: application/json' \\\n  -d '{"input_text": "hello", "tweaks": {"<node_id>": {"<field>": "value"}}}'`,
    [runUrl],
  );
  const headlessSnippet = useMemo(
    () =>
      `import json\n\nfrom langgraph_agent_builder.compiler import compile_flow   # json -> LangGraph\nfrom langgraph_agent_builder.runtime import arun_flow\n\nspec = json.load(open("${flow.slug}.flow.json"))\ngraph = compile_flow(spec).graph        # vanilla StateGraph, no server needed\nresult = await arun_flow(spec, input_text="hello")\nprint(result.result_text)`,
    [flow.slug],
  );
  const mcpClientConfig = useMemo(
    () =>
      JSON.stringify(
        { mcpServers: { "langgraph-agent-builder": { type: "http", url: `${origin}/mcp` } } },
        null,
        2,
      ),
    [origin],
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
    <Dialog open={open} onClose={onClose} title={`Publish · ${flow.name}`} className="w-[760px]">
      <div className="space-y-4">
        <p className="text-[11px] uppercase tracking-widest text-text-3">
          Step {step} of 3 · {step === 1 ? "Choose the door" : DOOR_LABEL[mode]}
        </p>

        {step === 1 && (
          <div className="space-y-4">
            <p className="text-xs text-text-2">
              Choose how this flow is served. Surfaces are exclusive (SPEC §7.1) — picking one
              turns the others off.
            </p>
            <div className="grid grid-cols-3 gap-2.5">
              {DOORS.map((door) => (
                <DoorCard
                  key={door.value}
                  door={door}
                  selected={mode === door.value}
                  onSelect={() => setMode(door.value)}
                />
              ))}
            </div>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={onClose}>
                Cancel
              </Button>
              <Button onClick={() => setStep(2)}>
                Next
                <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.75} />
              </Button>
            </div>
          </div>
        )}

        {step === 2 && (
          <div className="space-y-3">
            {summaryGuards.length > 0 && (
              <div
                role="alert"
                className="space-y-1.5 rounded-lg border-l-2 border-danger bg-danger/10 p-2.5"
              >
                <p className="flex items-center gap-1.5 text-xs font-semibold text-danger">
                  <TriangleAlert className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
                  {summaryGuards.length} publish guard{summaryGuards.length === 1 ? "" : "s"} to
                  resolve
                </p>
                {summaryGuards.map((g, i) => (
                  <p key={i} className="text-[11px] text-danger">
                    <span className="font-mono">{g.code}</span>
                    {g.node_id ? ` · ${g.node_id}` : ""} · {g.message}
                  </p>
                ))}
              </div>
            )}

            {mode === "a2a" && (
              <div className="space-y-3">
                <Field label="Agent name">
                  <Input
                    value={a2a.agent_name ?? ""}
                    placeholder={flow.name}
                    onChange={(e) => updateFlowMeta({ a2a: { ...a2a, agent_name: e.target.value } })}
                  />
                </Field>
                <Field label="Description" hint="required (E060)" guard={guardFor("a2a.description")}>
                  <Input
                    value={a2a.description ?? ""}
                    placeholder="One sentence: what can this agent do?"
                    onChange={(e) => updateFlowMeta({ a2a: { ...a2a, description: e.target.value } })}
                  />
                </Field>
                <Field label="Skill examples" hint="comma-separated" guard={guardFor("a2a.examples")}>
                  <CommaListInput
                    value={a2a.examples ?? []}
                    placeholder="Summarise this ticket, Draft a reply…"
                    onChange={(v) => updateFlowMeta({ a2a: { ...a2a, examples: v } })}
                  />
                </Field>
                <Field label="Tags" hint="comma-separated">
                  <CommaListInput
                    value={a2a.tags ?? []}
                    placeholder="support, summarisation"
                    onChange={(v) => updateFlowMeta({ a2a: { ...a2a, tags: v } })}
                  />
                </Field>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Input modes">
                    <ModeMultiSelect
                      name="a2a-in"
                      selected={a2a.input_modes ?? DEFAULT_MODES}
                      onChange={(v) => updateFlowMeta({ a2a: { ...a2a, input_modes: v } })}
                    />
                  </Field>
                  <Field label="Output modes">
                    <ModeMultiSelect
                      name="a2a-out"
                      selected={a2a.output_modes ?? DEFAULT_MODES}
                      onChange={(v) => updateFlowMeta({ a2a: { ...a2a, output_modes: v } })}
                    />
                  </Field>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <Field label="Auth">
                    <Select
                      value={a2a.auth ?? "public"}
                      onChange={(e) =>
                        updateFlowMeta({
                          a2a: { ...a2a, auth: e.target.value as "public" | "api-key" },
                        })
                      }
                    >
                      <option value="public">public (session-namespaced)</option>
                      <option value="api-key">api-key (X-API-Key · a2a:invoke)</option>
                    </Select>
                  </Field>
                  <Field label="Push notifications" hint="client supplies the webhook per task">
                    <div className="flex h-8.5 items-center gap-2">
                      <Switch
                        checked={false}
                        disabled
                        onCheckedChange={() => {}}
                        label="Push notifications"
                      />
                      <span className="text-xs text-text-2">not configured here</span>
                    </div>
                  </Field>
                </div>
                <Field label="Transport">
                  <div role="radiogroup" aria-label="A2A transport" className="space-y-1.5">
                    <TransportOption
                      name="a2a-transport"
                      checked={(a2a.transport ?? "http_json") === "http_json"}
                      onSelect={() => updateFlowMeta({ a2a: { ...a2a, transport: "http_json" } })}
                      label="HTTP + JSON"
                      hint="REST / JSON-RPC — always served"
                    />
                    <TransportOption
                      name="a2a-transport"
                      checked={(a2a.transport ?? "http_json") === "grpc"}
                      disabled={!grpcAvailable}
                      onSelect={() => updateFlowMeta({ a2a: { ...a2a, transport: "grpc" } })}
                      label="gRPC"
                      hint={
                        grpcAvailable
                          ? "high-throughput binary transport"
                          : "requires the a2a-sdk[grpc] extra"
                      }
                    />
                  </div>
                </Field>
                {interruptCount > 0 && (
                  <div className="flex items-start gap-2 rounded-lg border border-border bg-surface-2 p-2.5">
                    <Users className="mt-px h-4 w-4 shrink-0 text-accent" strokeWidth={1.75} />
                    <p className="text-[11px] leading-relaxed text-text-2">
                      This flow has {interruptCount} human-in-the-loop step
                      {interruptCount === 1 ? "" : "s"}; as an A2A agent the task pauses natively in{" "}
                      <code className="font-mono text-text-1">input-required</code>.
                    </p>
                  </div>
                )}
                <div>
                  <p className="mb-1 text-xs font-medium text-text-2">
                    Live Agent Card (generated server-side)
                  </p>
                  <AgentCardPreview card={card} />
                </div>
                <Snippet label={`Endpoint · ${endpoint}`} text={curl} />
              </div>
            )}

            {mode === "mcp" && (
              <div className="space-y-3">
                <Field label="Tool name" hint="default: flow slug">
                  <Input
                    value={mcp.tool_name ?? ""}
                    placeholder={flow.slug.replace(/-/g, "_")}
                    onChange={(e) => updateFlowMeta({ mcp: { ...mcp, tool_name: e.target.value } })}
                  />
                </Field>
                <Field
                  label="Tool description"
                  hint="required (E062)"
                  guard={guardFor("mcp.description")}
                >
                  <Input
                    value={mcp.description ?? ""}
                    placeholder="One sentence the calling model sees."
                    onChange={(e) => updateFlowMeta({ mcp: { ...mcp, description: e.target.value } })}
                  />
                </Field>
                <Field
                  label="Interrupt policy"
                  hint="how HITL steps resolve (E063)"
                  guard={guardFor("mcp.auto_resolve_interrupts")}
                >
                  <Select
                    value={mcp.auto_resolve_interrupts ?? ""}
                    onChange={(e) =>
                      updateFlowMeta({
                        mcp: {
                          ...mcp,
                          auto_resolve_interrupts: (e.target.value ||
                            null) as McpSettings["auto_resolve_interrupts"],
                        },
                      })
                    }
                  >
                    <option value="">none — reject flows with interrupts</option>
                    <option value="approve">auto-approve interrupts</option>
                    <option value="reject">auto-reject interrupts</option>
                  </Select>
                </Field>
                <Field label="Timeout" hint="seconds — blank = server default">
                  <Input
                    type="number"
                    min={1}
                    value={mcp.timeout_s ?? ""}
                    placeholder="e.g. 120"
                    onChange={(e) => {
                      const n = Number(e.target.value);
                      updateFlowMeta({
                        mcp: {
                          ...mcp,
                          timeout_s: e.target.value !== "" && Number.isFinite(n) ? n : undefined,
                        },
                      });
                    }}
                  />
                </Field>
                <div className="flex items-start gap-2 rounded-lg border border-border bg-surface-2 p-2.5">
                  <Wrench className="mt-px h-4 w-4 shrink-0 text-text-3" strokeWidth={1.75} />
                  <p className="text-[11px] leading-relaxed text-text-2">
                    Served over streamable HTTP only — MCP has no transport choice. Add it to a
                    client at <code className="font-mono text-text-1">{origin}/mcp</code>.
                  </p>
                </div>
                <Snippet label="Client config (Claude Code / Cursor)" text={mcpClientConfig} />
              </div>
            )}

            {mode === "api" && (
              <div className="space-y-3">
                <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-2 px-2.5 py-1.5">
                  <span className="text-[11px] uppercase tracking-widest text-text-3">base url</span>
                  <code className="truncate font-mono text-xs text-text-1">{runUrl}</code>
                  <CopyButton text={runUrl} label="Copy base url" className="ml-auto" />
                </div>
                <div className="grid gap-2 rounded-lg border border-border bg-surface-2 p-2.5 text-[11px] leading-relaxed text-text-2">
                  <p>
                    <span className="font-medium text-text-1">Auth.</span> Public unless your gateway
                    requires a key; protected routes check{" "}
                    <code className="font-mono">X-API-Key</code> with scope{" "}
                    <code className="font-mono">flow:run</code>.
                  </p>
                  <p>
                    <span className="font-medium text-text-1">Sync / async.</span>{" "}
                    <code className="font-mono">POST …/run</code> blocks until the flow finishes;
                    pass <code className="font-mono">{`"stream": true`}</code> for incremental SSE,
                    or use the webhook door for fire-and-forget.
                  </p>
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
                <div className="flex flex-wrap items-center gap-2">
                  <span className="text-xs font-medium text-text-2">Export:</span>
                  <Button variant="ghost" className="!h-7 !text-xs" onClick={() => download("json")}>
                    <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
                    flow.json
                  </Button>
                  <Button
                    variant="ghost"
                    className="!h-7 !text-xs"
                    onClick={() => download("python")}
                  >
                    <Download className="h-3.5 w-3.5" strokeWidth={1.75} />
                    standalone flow.py
                  </Button>
                  <span className="text-[11px] text-text-3">flow.py runs under vanilla LangGraph</span>
                </div>
              </div>
            )}

            <div className="flex items-center justify-between gap-2 border-t border-border pt-3">
              <Button variant="ghost" onClick={() => setStep(1)}>
                <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.75} />
                Back
              </Button>
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-text-3">
                  These settings save into the flow on publish.
                </span>
                <Button onClick={onProceedToPublish}>Publish →</Button>
              </div>
            </div>
          </div>
        )}
      </div>
    </Dialog>
  );
}

/** Explicit serving-surface card (step 1) — not a tab with a side effect. */
function DoorCard({
  door,
  selected,
  onSelect,
}: {
  door: DoorDef;
  selected: boolean;
  onSelect: () => void;
}) {
  const Icon = door.icon;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cn(
        "flex flex-col items-start gap-2 rounded-[10px] border p-3 text-left transition-colors duration-150",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        selected
          ? "border-accent bg-accent/10"
          : "border-border bg-surface-2 hover:border-border-strong hover:bg-surface-3",
      )}
    >
      <span
        className={cn(
          "flex h-8 w-8 items-center justify-center rounded-lg",
          selected ? "bg-accent/15 text-accent" : "bg-surface-3 text-text-2",
        )}
      >
        <Icon className="h-4 w-4" strokeWidth={1.75} />
      </span>
      <span className="text-sm font-semibold text-text-1">{door.label}</span>
      <span className="text-[11px] leading-relaxed text-text-3">{door.blurb}</span>
    </button>
  );
}

/** Labelled form field with an optional hint and an inline publish-guard error. */
function Field({
  label,
  hint,
  guard,
  children,
}: {
  label: string;
  hint?: string;
  guard?: PublishGuard;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-xs font-medium text-text-2">{label}</span>
        {hint ? <span className="text-[11px] text-text-3">{hint}</span> : null}
      </div>
      {children}
      {guard ? (
        <p
          role="alert"
          className={cn(
            "mt-1 flex items-start gap-1 text-[11px]",
            guard.severity === "error" ? "text-danger" : "text-warning",
          )}
        >
          <TriangleAlert className="mt-px h-3 w-3 shrink-0" strokeWidth={1.75} />
          <span>
            <span className="font-mono">{guard.code}</span> · {guard.message}
          </span>
        </p>
      ) : null}
    </div>
  );
}

/** Multiselect of A2A content modes as a small checkbox list. */
function ModeMultiSelect({
  name,
  selected,
  onChange,
}: {
  name: string;
  selected: string[];
  onChange: (value: string[]) => void;
}) {
  const toggle = (mode: string) => {
    const set = new Set(selected);
    if (set.has(mode)) set.delete(mode);
    else set.add(mode);
    onChange(MODE_OPTIONS.filter((m) => set.has(m)));
  };
  return (
    <div className="space-y-1.5 rounded-lg border border-border-strong bg-surface-2 p-2">
      {MODE_OPTIONS.map((mode) => (
        <label key={mode} className="flex cursor-pointer items-center gap-2">
          <Checkbox
            checked={selected.includes(mode)}
            onCheckedChange={() => toggle(mode)}
            label={`${name} ${mode}`}
          />
          <span className="font-mono text-[11px] text-text-2">{mode}</span>
        </label>
      ))}
    </div>
  );
}

/** One transport radio; the row shows selection state and disables gRPC when
 * the a2a-sdk[grpc] extra is missing. */
function TransportOption({
  name,
  checked,
  onSelect,
  disabled,
  label,
  hint,
}: {
  name: string;
  checked: boolean;
  onSelect: () => void;
  disabled?: boolean;
  label: string;
  hint: string;
}) {
  return (
    <label
      className={cn(
        "flex items-start gap-2 rounded-lg border p-2 transition-colors duration-150",
        disabled
          ? "cursor-not-allowed border-border bg-surface-2 opacity-45"
          : checked
            ? "cursor-pointer border-accent bg-accent/10"
            : "cursor-pointer border-border-strong bg-surface-2 hover:border-accent/60",
      )}
    >
      <input
        type="radio"
        name={name}
        checked={checked}
        disabled={disabled}
        onChange={onSelect}
        style={{ accentColor: "var(--color-accent)" }}
        className="mt-0.5"
      />
      <span className="min-w-0">
        <span className="block text-xs font-medium text-text-1">{label}</span>
        <span className="block text-[11px] text-text-3">{hint}</span>
      </span>
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
