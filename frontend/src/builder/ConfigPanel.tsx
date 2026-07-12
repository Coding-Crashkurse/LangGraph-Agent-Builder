/**
 * Inspector panel. Node config forms render from the JSON Schema served by
 * GET /node-types plus its UI metadata — no hardcoded per-node forms
 * (SPEC §3, UI rules). With no node selected it shows the flow settings
 * (display name, expose config incl. flow-level MCP tool fields).
 */

import { useQuery } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { useEffect, useState } from "react";

import { api } from "@/api/client";
import type {
  FieldUI,
  NodeTypeInfo,
  ResourceGroup,
  SourcedIssue,
  WidgetKind,
} from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Select, Switch } from "@/components/ui/controls";
import { Input, Label, Textarea } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import type { FlowMeta } from "./convert";
import { issueNodeId, useBuilder } from "./store";

// ------------------------------------------------------------------ widgets

function JsonEditor({
  value,
  onCommit,
  placeholder,
  rows = 6,
}: {
  value: unknown;
  onCommit: (parsed: unknown) => void;
  placeholder?: string;
  rows?: number;
}) {
  const [text, setText] = useState(() =>
    value == null ? "" : JSON.stringify(value, null, 2),
  );
  const [invalid, setInvalid] = useState(false);
  useEffect(() => {
    setText(value == null ? "" : JSON.stringify(value, null, 2));
    setInvalid(false);
  }, [value]);
  return (
    <div>
      <Textarea
        rows={rows}
        value={text}
        placeholder={placeholder ?? "{ }"}
        className={cn(invalid && "border-danger focus-visible:outline-danger")}
        onChange={(e) => setText(e.target.value)}
        onBlur={() => {
          const trimmed = text.trim();
          if (!trimmed) {
            setInvalid(false);
            onCommit(null);
            return;
          }
          try {
            onCommit(JSON.parse(trimmed));
            setInvalid(false);
          } catch {
            setInvalid(true);
          }
        }}
      />
      {invalid && <p className="mt-1 text-[11px] text-danger">Not valid JSON — not saved.</p>}
    </div>
  );
}

function DictEditor({
  value,
  onCommit,
}: {
  value: unknown;
  onCommit: (next: Record<string, string>) => void;
}) {
  const entries = Object.entries(
    typeof value === "object" && value !== null ? (value as Record<string, unknown>) : {},
  ).map(([k, v]) => [k, String(v)] as [string, string]);
  const commit = (next: [string, string][]) => onCommit(Object.fromEntries(next));
  return (
    <div className="flex flex-col gap-1.5">
      {entries.map(([key, val], index) => (
        <div key={index} className="flex items-center gap-1.5">
          <Input
            value={key}
            aria-label="port name"
            placeholder="port"
            className="h-7 font-mono text-xs"
            onChange={(e) => {
              const next = [...entries];
              next[index] = [e.target.value, val];
              commit(next);
            }}
          />
          <span className="text-text-3">→</span>
          <Input
            value={val}
            aria-label="argument name"
            placeholder="argument"
            className="h-7 font-mono text-xs"
            onChange={(e) => {
              const next = [...entries];
              next[index] = [key, e.target.value];
              commit(next);
            }}
          />
          <button
            type="button"
            aria-label="remove entry"
            className="text-text-3 hover:text-danger"
            onClick={() => commit(entries.filter((_, i) => i !== index))}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="self-start text-[11px] text-accent hover:underline"
        onClick={() => commit([...entries, ["", ""]])}
      >
        + add mapping
      </button>
    </div>
  );
}

function ResourcePicker({
  value,
  kind,
  onChange,
}: {
  value: string;
  kind: ResourceGroup | null;
  onChange: (name: string | null) => void;
}) {
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.get });
  const resources = useQuery({
    queryKey: ["resources", kind],
    queryFn: () => api.resources.list(kind ?? undefined),
    retry: false,
  });
  const options = resources.data ?? [];
  return (
    <div>
      <Select
        value={value}
        aria-label="resource"
        onChange={(e) => onChange(e.target.value || null)}
      >
        <option value="">— select resource —</option>
        {value && !options.some((r) => r.name === value) && (
          <option value={value}>{value}</option>
        )}
        {options.map((r) => (
          <option key={r.name} value={r.name}>
            {r.display_name || r.name} ({r.kind})
          </option>
        ))}
      </Select>
      {resources.isError &&
        (config.data?.runtime_configured ? (
          <p className="mt-1 text-[11px] text-warning">
            Platform runtime unreachable — enter the name manually below.
          </p>
        ) : (
          <p className="mt-1 text-[11px] text-text-3">
            No platform runtime connected — type the resource name; it resolves at
            publish time.
          </p>
        ))}
      {resources.isSuccess && options.length === 0 && (
        <p className="mt-1 text-[11px] text-text-3">
          The platform has no {kind ? kind.replace("_", " ") : "matching"} resources yet
          — type the name it will get; publish resolves it (E020 until it exists).
        </p>
      )}
      {(resources.isError || (resources.isSuccess && options.length === 0)) && (
        <Input
          className="mt-1 h-7 font-mono text-xs"
          value={value}
          placeholder="resource-name"
          onChange={(e) => onChange(e.target.value || null)}
        />
      )}
      {config.data?.resources_ui_url && (
        <a
          href={config.data.resources_ui_url}
          target="_blank"
          rel="noreferrer"
          className="mt-1 inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
        >
          Manage in Resources <ExternalLink size={11} />
        </a>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ field

interface SchemaProperty {
  type?: string;
  description?: string;
  default?: unknown;
  minimum?: number;
  maximum?: number;
}

function widgetFor(ui: FieldUI | undefined, prop: SchemaProperty): WidgetKind {
  if (ui) return ui.widget;
  if (prop.type === "boolean") return "switch";
  if (prop.type === "integer" || prop.type === "number") return "number";
  if (prop.type === "object") return "json";
  return "text";
}

function FieldRow({
  name,
  prop,
  ui,
  value,
  onChange,
  issues,
}: {
  name: string;
  prop: SchemaProperty;
  ui: FieldUI | undefined;
  value: unknown;
  onChange: (value: unknown) => void;
  issues: SourcedIssue[];
}) {
  const widget = widgetFor(ui, prop);
  const label = ui?.label || name;
  const help = ui?.help || prop.description || "";
  const fieldIssues = issues.filter((i) => i.path.endsWith(`/${name}`));
  return (
    <div>
      <Label hint={help}>{label}</Label>
      {widget === "switch" && (
        <Switch checked={value === true} onCheckedChange={onChange} label={label} />
      )}
      {widget === "number" && (
        <Input
          type="number"
          value={value == null ? "" : String(value)}
          min={prop.minimum}
          max={prop.maximum}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
      )}
      {(widget === "text" || widget === "prompt" || widget === "textarea") &&
        (widget === "text" ? (
          <Input
            value={typeof value === "string" ? value : ""}
            placeholder={ui?.placeholder}
            onChange={(e) => onChange(e.target.value)}
          />
        ) : (
          <Textarea
            rows={widget === "prompt" ? 6 : 3}
            value={typeof value === "string" ? value : ""}
            placeholder={ui?.placeholder}
            onChange={(e) => onChange(e.target.value)}
          />
        ))}
      {(widget === "schema" || widget === "json") &&
        (ui?.toggleable ? (
          <div className="flex flex-col gap-1.5">
            <Switch
              checked={value != null}
              onCheckedChange={(on) =>
                onChange(on ? { type: "object", properties: {} } : null)
              }
              label={label}
            />
            {value != null && <JsonEditor value={value} onCommit={onChange} />}
          </div>
        ) : (
          <JsonEditor value={value} onCommit={onChange} />
        ))}
      {widget === "dict" && (
        <DictEditor value={value} onCommit={(next) => onChange(next)} />
      )}
      {widget === "resource" && (
        <ResourcePicker
          value={typeof value === "string" ? value : ""}
          kind={ui?.resource_kind ?? null}
          onChange={onChange}
        />
      )}
      {fieldIssues.map((issue) => (
        <p
          key={`${issue.code}-${issue.path}`}
          className={cn(
            "mt-1 text-[11px]",
            issue.severity === "error" ? "text-danger" : "text-warning",
          )}
        >
          <span className="font-mono">{issue.code}</span> {issue.message}
        </p>
      ))}
    </div>
  );
}

// ------------------------------------------------------------------ panels

function NodeConfigForm({ nodeId, info }: { nodeId: string; info: NodeTypeInfo }) {
  const node = useBuilder((s) => s.nodes.find((n) => n.id === nodeId));
  const issues = useBuilder((s) => s.issues);
  const updateNodeConfig = useBuilder((s) => s.updateNodeConfig);
  if (!node) return null;
  const nodeIssues = issues.filter((i) => issueNodeId(i.path) === nodeId);
  const properties = (info.config_schema.properties ?? {}) as Record<string, SchemaProperty>;
  const fields = Object.entries(properties);
  const visible = fields.filter(([name]) => !(info.ui[name]?.advanced ?? false));
  const advanced = fields.filter(([name]) => info.ui[name]?.advanced ?? false);
  const render = ([name, prop]: [string, SchemaProperty]) => (
    <FieldRow
      key={name}
      name={name}
      prop={prop}
      ui={info.ui[name]}
      value={node.data.def.config[name] ?? prop.default ?? null}
      onChange={(value) => updateNodeConfig(nodeId, { [name]: value })}
      issues={nodeIssues}
    />
  );
  return (
    <div className="flex flex-col gap-3">
      <div>
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-text-1">{info.label}</span>
          <Badge>v{info.version}</Badge>
          <span className="ml-auto font-mono text-[11px] text-text-3">{nodeId}</span>
        </div>
        <p className="mt-1 text-[11px] leading-relaxed text-text-3">{info.description}</p>
      </div>
      {visible.map(render)}
      {advanced.length > 0 && (
        <details>
          <summary className="cursor-pointer text-[11px] font-medium uppercase tracking-wide text-text-3">
            Advanced
          </summary>
          <div className="mt-2 flex flex-col gap-3">{advanced.map(render)}</div>
        </details>
      )}
    </div>
  );
}

function FlowSettingsForm() {
  const meta = useBuilder((s) => s.meta);
  const updateMeta = useBuilder((s) => s.updateMeta);
  const expose = meta.expose;
  return (
    <div className="flex flex-col gap-3">
      <div>
        <span className="text-sm font-semibold text-text-1">Flow settings</span>
        <p className="mt-1 text-[11px] text-text-3">
          Name <span className="font-mono">{meta.name}</span> · rename via export → import
        </p>
      </div>
      <div>
        <Label>Display name</Label>
        <Input
          value={meta.display_name}
          onChange={(e) => updateMeta({ display_name: e.target.value })}
        />
      </div>
      <div>
        <Label>Description</Label>
        <Textarea
          rows={3}
          value={meta.description}
          onChange={(e) => updateMeta({ description: e.target.value })}
        />
      </div>
      <div>
        <Label hint="comma separated">Tags</Label>
        <Input
          value={meta.tags.join(", ")}
          onChange={(e) =>
            updateMeta({
              tags: e.target.value
                .split(",")
                .map((t) => t.trim())
                .filter(Boolean),
            })
          }
        />
      </div>
      <p className="text-[11px] text-text-3">
        Currently exposed as{" "}
        <span className="font-medium text-text-2">
          {expose.kind === "mcp" ? "MCP tool" : "A2A agent"}
        </span>{" "}
        — the door (and its fields) is chosen in the Publish dialog.
      </p>
    </div>
  );
}

export function ConfigPanel() {
  const selectedNodeId = useBuilder((s) => s.selectedNodeId);
  const infoByType = useBuilder((s) => s.infoByType);
  const node = useBuilder((s) => s.nodes.find((n) => n.id === s.selectedNodeId));
  const info = node ? infoByType().get(node.data.def.type) : undefined;
  return (
    <aside className="flex w-80 shrink-0 flex-col overflow-y-auto border-l border-border bg-surface-1 p-3">
      {selectedNodeId && info ? (
        <NodeConfigForm nodeId={selectedNodeId} info={info} />
      ) : (
        <FlowSettingsForm />
      )}
    </aside>
  );
}

export { FieldRow, JsonEditor };
export type { FlowMeta };
