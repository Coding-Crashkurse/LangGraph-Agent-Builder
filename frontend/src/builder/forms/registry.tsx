/** FieldWidgetRegistry (SPEC §11.2): one widget per §4.2 field type; node
 * forms render EXCLUSIVELY from component descriptors. Unknown type → JSON
 * fallback + console warn (forward compat). */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Eye,
  EyeOff,
  Globe,
  KeyRound,
  Plus,
  RefreshCw,
  X,
} from "lucide-react";
import { useState, type CSSProperties, type FC } from "react";

import { api } from "@/api/client";
import type { FieldDescriptor } from "@/api/types";
import { Input, Textarea } from "@/components/ui/input";
import { Select, Slider, Switch, Tabs } from "@/components/ui/controls";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

export interface WidgetProps {
  field: FieldDescriptor;
  value: unknown;
  onChange: (value: unknown) => void;
  onRefresh?: () => void; // refresh_button / options_source round-trip
}

// ------------------------------------------------------------------ $var/$secret refs (§10.3)
type RefKind = "$secret" | "$var";

function refOf(value: unknown): { kind: RefKind; name: string } | null {
  if (typeof value === "object" && value !== null) {
    const record = value as Record<string, string>;
    if ("$secret" in record) return { kind: "$secret", name: record.$secret };
    if ("$var" in record) return { kind: "$var", name: record.$var };
  }
  return null;
}

const RefIcon: FC<{ kind: RefKind; size?: number }> = ({ kind, size = 12 }) =>
  kind === "$secret" ? (
    <KeyRound size={size} strokeWidth={1.75} aria-hidden />
  ) : (
    <Globe size={size} strokeWidth={1.75} aria-hidden />
  );

/** Chip + dropdown that binds a field to a stored global variable/credential.
 * Values never touch the FlowSpec — only the reference does (SPEC §10.3). */
const VarPicker: FC<{
  kind: RefKind;
  value: unknown;
  onChange: (value: unknown) => void;
}> = ({ kind, value, onChange }) => {
  const queryClient = useQueryClient();
  const variables = useQuery({ queryKey: ["variables"], queryFn: api.variables.list });
  const [open, setOpen] = useState(false);
  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newValue, setNewValue] = useState("");
  const wantKind = kind === "$secret" ? "credential" : "generic";
  const candidates = (variables.data ?? []).filter((v) => v.kind === wantKind);
  const current = refOf(value);

  if (current) {
    return (
      <span className="inline-flex items-center gap-1 rounded border border-success/50 bg-success/10 px-1.5 py-0.5 text-[11px] text-success">
        <RefIcon kind={kind} /> {current.kind}: {current.name}
        <button
          type="button"
          className="ml-1 rounded text-success hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
          title="Remove reference"
          aria-label="Remove reference"
          onClick={() => onChange(null)}
        >
          <X size={12} strokeWidth={1.75} aria-hidden />
        </button>
      </span>
    );
  }

  return (
    <span className="relative">
      <button
        type="button"
        title={
          kind === "$secret"
            ? "Use a stored credential (never saved into the flow)"
            : "Use a global variable"
        }
        onClick={() => setOpen((o) => !o)}
        className="inline-flex items-center gap-1 whitespace-nowrap rounded border border-border px-1.5 py-1 text-[11px] text-text-2 hover:border-success/60 hover:text-success focus-visible:outline-2 focus-visible:outline-accent"
      >
        <RefIcon kind={kind} /> {kind === "$secret" ? "use credential" : "$var"}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 w-56 rounded-md border border-border bg-canvas p-1.5 shadow-xl">
          {candidates.length === 0 && !creating && (
            <p className="px-1 py-0.5 text-[11px] text-text-3">
              no {wantKind}s stored yet
            </p>
          )}
          {candidates.map((variable) => (
            <button
              key={variable.name}
              type="button"
              className="flex w-full items-center gap-1.5 rounded px-1.5 py-1 text-left text-[11px] text-text-1 hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
              onClick={() => {
                onChange({ [kind]: variable.name });
                setOpen(false);
              }}
            >
              <RefIcon kind={kind} /> {variable.name}
            </button>
          ))}
          <div className="mt-1 border-t border-border pt-1">
            {creating ? (
              <div className="space-y-1 p-0.5">
                <Input
                  autoFocus
                  className="bg-surface-2 placeholder:text-text-3"
                  placeholder="NAME (e.g. OPENAI_API_KEY)"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <Input
                  type={kind === "$secret" ? "password" : "text"}
                  className="bg-surface-2 placeholder:text-text-3"
                  placeholder="value (stored server-side)"
                  value={newValue}
                  onChange={(e) => setNewValue(e.target.value)}
                />
                <button
                  type="button"
                  className="w-full rounded bg-accent px-1.5 py-1 text-[11px] font-medium text-white hover:brightness-110 focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-40"
                  disabled={!newName || !newValue}
                  onClick={async () => {
                    try {
                      await api.variables.set({ name: newName, value: newValue, kind: wantKind });
                      queryClient.invalidateQueries({ queryKey: ["variables"] });
                      onChange({ [kind]: newName });
                      setOpen(false);
                      setCreating(false);
                      setNewName("");
                      setNewValue("");
                      toast.success(
                        wantKind === "credential"
                          ? "credential stored (encrypted, write-only)"
                          : "variable stored",
                      );
                    } catch (error) {
                      toast.error(`failed: ${(error as Error).message}`);
                    }
                  }}
                >
                  save & use
                </button>
              </div>
            ) : (
              <button
                type="button"
                className="flex w-full items-center gap-1 rounded px-1.5 py-1 text-left text-[11px] text-accent hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
                onClick={() => setCreating(true)}
              >
                <Plus size={12} strokeWidth={1.75} aria-hidden /> new {wantKind}…
              </button>
            )}
          </div>
        </div>
      )}
    </span>
  );
};

function optionValues(field: FieldDescriptor): { value: string; label: string }[] {
  const options = (field.options as (string | { value: string; label?: string })[]) ?? [];
  return options.map((o) =>
    typeof o === "string" ? { value: o, label: o } : { value: o.value, label: o.label ?? o.value },
  );
}

const Str: FC<WidgetProps> = ({ field, value, onChange }) => {
  const ref = refOf(value);
  return (
    <div className="flex items-center gap-1.5">
      {!ref && (
        <Input
          value={String(value ?? "")}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {field.accepts_global_variable && (
        <VarPicker kind="$var" value={value} onChange={onChange} />
      )}
    </div>
  );
};

const Multiline: FC<WidgetProps> = ({ field, value, onChange }) => {
  const ref = refOf(value);
  return (
    <div className="space-y-1">
      {!ref && (
        <Textarea
          className="min-h-[72px]"
          value={String(value ?? "")}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
        />
      )}
      {/* Match Str: offer the picker so a $var binding can be CREATED from a
          plain textarea (not just displayed once one already exists). */}
      {field.accepts_global_variable && (
        <VarPicker kind="$var" value={value} onChange={onChange} />
      )}
    </div>
  );
};

const NumberWidget: FC<WidgetProps & { integer?: boolean }> = ({
  field,
  value,
  onChange,
  integer,
}) => (
  <Input
    type="number"
    className="tabular-nums"
    value={value === null || value === undefined ? "" : String(value)}
    min={field.min as number | undefined}
    max={field.max as number | undefined}
    step={(field.step as number | undefined) ?? (integer ? 1 : 0.1)}
    onChange={(e) => {
      const raw = e.target.value;
      if (raw === "") return onChange(null);
      onChange(integer ? parseInt(raw, 10) : parseFloat(raw));
    }}
  />
);

const Bool: FC<WidgetProps> = ({ value, onChange }) => (
  <Switch checked={Boolean(value)} onCheckedChange={onChange} />
);

const SliderWidget: FC<WidgetProps> = ({ field, value, onChange }) => {
  const minLabel = field.min_label as string | undefined;
  const maxLabel = field.max_label as string | undefined;
  return (
    <div className="space-y-0.5">
      {/* Slider primitive renders its own tabular value readout */}
      <Slider
        aria-label={field.display_name || field.name}
        min={(field.min as number | null | undefined) ?? 0}
        max={(field.max as number | null | undefined) ?? 100}
        step={(field.step as number | null | undefined) ?? 1}
        value={Number(value ?? field.min ?? 0)}
        onChange={onChange}
      />
      {minLabel || maxLabel ? (
        <div className="flex justify-between text-[11px] text-text-3">
          <span>{minLabel}</span>
          <span>{maxLabel}</span>
        </div>
      ) : null}
    </div>
  );
};

const Dropdown: FC<WidgetProps> = ({ field, value, onChange, onRefresh }) => {
  const options = optionValues(field);
  if (field.combobox || options.length === 0) {
    return (
      <div className="flex gap-1">
        <Input
          list={`opts-${field.name}`}
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
        />
        <datalist id={`opts-${field.name}`}>
          {options.map((o) => (
            <option key={o.value} value={o.value} />
          ))}
        </datalist>
        {field.options_source ? <RefreshButton onRefresh={onRefresh} /> : null}
      </div>
    );
  }
  return (
    <div className="flex gap-1">
      <Select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
        <option value="">—</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>
      {field.options_source ? <RefreshButton onRefresh={onRefresh} /> : null}
    </div>
  );
};

const Multiselect: FC<WidgetProps> = ({ field, value, onChange, onRefresh }) => {
  const selected = Array.isArray(value) ? (value as string[]) : [];
  const options = optionValues(field);
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const item = raw.trim();
    if (item && !selected.includes(item)) onChange([...selected, item]);
    setDraft("");
  };
  return (
    <div className="space-y-1">
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {selected.map((item) => (
            <span
              key={item}
              className="inline-flex items-center gap-1 rounded bg-surface-3 px-1.5 py-0.5 text-xs text-text-1"
            >
              {item}
              <button
                type="button"
                aria-label={`Remove ${item}`}
                className="rounded text-text-3 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
                onClick={() => onChange(selected.filter((x) => x !== item))}
              >
                <X size={11} strokeWidth={1.75} aria-hidden />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-1">
        <Input
          list={`ms-${field.name}`}
          value={draft}
          placeholder={selected.length ? "add another…" : "type a value, then Enter or +"}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add(draft);
            }
          }}
          onBlur={() => add(draft)} // commit on click-away so a typed value isn't lost
        />
        <datalist id={`ms-${field.name}`}>
          {options
            .filter((o) => !selected.includes(o.value))
            .map((o) => (
              <option key={o.value} value={o.value} />
            ))}
        </datalist>
        <button
          type="button"
          title="Add value"
          aria-label="Add value"
          className="rounded border border-border px-2 text-text-2 hover:border-accent hover:text-accent focus-visible:outline-2 focus-visible:outline-accent"
          onMouseDown={(e) => e.preventDefault()} // keep focus so onBlur doesn't double-fire
          onClick={() => add(draft)}
        >
          <Plus size={13} strokeWidth={1.75} aria-hidden />
        </button>
        {field.options_source ? <RefreshButton onRefresh={onRefresh} /> : null}
      </div>
      <p className="text-[11px] text-text-3">
        {selected.length === 0
          ? "Accepts multiple values — add one per label."
          : `${selected.length} value${selected.length === 1 ? "" : "s"}`}
      </p>
    </div>
  );
};

const TabWidget: FC<WidgetProps> = ({ field, value, onChange }) => (
  <Tabs
    value={String(value ?? optionValues(field)[0]?.value ?? "")}
    onChange={onChange}
    items={optionValues(field).map((o) => ({ value: o.value, label: o.label }))}
  />
);

/** Icon-only reveal toggle shared by the secret widgets (lucide Eye/EyeOff). */
const RevealToggle: FC<{ reveal: boolean; onToggle: () => void; className?: string }> = ({
  reveal,
  onToggle,
  className,
}) => (
  <button
    type="button"
    aria-label={reveal ? "Hide value" : "Reveal value"}
    aria-pressed={reveal}
    title={reveal ? "Hide value" : "Reveal value"}
    className={cn(
      "rounded p-0.5 text-text-3 hover:text-text-1",
      "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
      className,
    )}
    onClick={onToggle}
  >
    {reveal ? (
      <EyeOff size={14} strokeWidth={1.75} aria-hidden />
    ) : (
      <Eye size={14} strokeWidth={1.75} aria-hidden />
    )}
  </button>
);

const Secret: FC<WidgetProps> = ({ value, onChange }) => {
  const ref = refOf(value);
  const [reveal, setReveal] = useState(false);
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        {!ref && (
          <div className="relative min-w-0 flex-1">
            <Input
              type={reveal ? "text" : "password"}
              className="pr-8"
              value={String(value ?? "")}
              placeholder="secret value (better: use a stored credential →)"
              onChange={(e) => onChange(e.target.value)}
            />
            <RevealToggle
              reveal={reveal}
              onToggle={() => setReveal((r) => !r)}
              className="absolute right-1.5 top-1/2 -translate-y-1/2"
            />
          </div>
        )}
        <VarPicker kind="$secret" value={value} onChange={onChange} />
      </div>
      {!ref && (
        <p className="text-[11px] text-text-3">
          Pasted values land in the FlowSpec — stored credentials stay encrypted
          on the server and only the reference is saved.
        </p>
      )}
    </div>
  );
};

// MultilineSecretInput: a *masked, multi-line* secret (PEM keys, JSON creds).
// A textarea has no native password masking, so mask via -webkit-text-security
// with a reveal toggle. Prefer a stored credential ($secret) as with Secret.
const MASK: CSSProperties = { WebkitTextSecurity: "disc" } as CSSProperties;

const MultilineSecret: FC<WidgetProps> = ({ field, value, onChange }) => {
  const ref = refOf(value);
  const [reveal, setReveal] = useState(false);
  return (
    <div className="space-y-1">
      {!ref && (
        <div className="relative">
          <Textarea
            className="min-h-[72px] pr-8"
            style={reveal ? undefined : MASK}
            value={String(value ?? "")}
            placeholder={field.placeholder || "multi-line secret — better: use a stored credential →"}
            onChange={(e) => onChange(e.target.value)}
          />
          <RevealToggle
            reveal={reveal}
            onToggle={() => setReveal((r) => !r)}
            className="absolute right-1.5 top-1.5"
          />
        </div>
      )}
      <VarPicker kind="$secret" value={value} onChange={onChange} />
      {!ref && (
        <p className="text-[11px] text-text-3">
          Pasted values land in the FlowSpec — stored credentials stay encrypted
          server-side and only the reference is saved.
        </p>
      )}
    </div>
  );
};

const JsonWidget: FC<WidgetProps> = ({ value, onChange }) => {
  const [text, setText] = useState(() =>
    value === undefined || value === null ? "" : JSON.stringify(value, null, 2),
  );
  const [bad, setBad] = useState(false);
  return (
    <div>
      <Textarea
        className={cn("min-h-[80px]", bad && "border-danger")}
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          if (!e.target.value.trim()) {
            setBad(false);
            onChange(null);
            return;
          }
          try {
            onChange(JSON.parse(e.target.value));
            setBad(false);
          } catch {
            setBad(true);
          }
        }}
      />
      {bad && <p className="text-[11px] text-danger">invalid JSON (not applied)</p>}
    </div>
  );
};

const DictWidget: FC<WidgetProps> = ({ value, onChange }) => {
  const entries = Object.entries((value as Record<string, unknown>) ?? {});
  const set = (index: number, key: string, val: string) => {
    const next = entries.map(([k, v], i) => (i === index ? [key, val] : [k, v]));
    onChange(Object.fromEntries(next));
  };
  return (
    <div className="space-y-1">
      {entries.map(([k, v], index) => (
        <div key={index} className="flex items-center gap-1">
          <Input value={k} onChange={(e) => set(index, e.target.value, String(v))} />
          <Input value={String(v ?? "")} onChange={(e) => set(index, k, e.target.value)} />
          <button
            type="button"
            aria-label="Remove entry"
            className="rounded px-1 text-text-3 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
            onClick={() => onChange(Object.fromEntries(entries.filter((_, i) => i !== index)))}
          >
            <X size={13} strokeWidth={1.75} aria-hidden />
          </button>
        </div>
      ))}
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded text-xs text-accent hover:brightness-125 focus-visible:outline-2 focus-visible:outline-accent"
        onClick={() => onChange({ ...(value as object), "": "" })}
      >
        <Plus size={12} strokeWidth={1.75} aria-hidden /> entry
      </button>
    </div>
  );
};

const TableWidget: FC<WidgetProps> = ({ field, value, onChange }) => {
  const columns = (field.columns as { name: string; display_name: string }[]) ?? [];
  const rows = Array.isArray(value) ? (value as Record<string, unknown>[]) : [];
  return (
    <div className="space-y-1">
      <div
        className="grid gap-1 text-[11px] uppercase tracking-wide text-text-3"
        style={{ gridTemplateColumns: `repeat(${columns.length}, 1fr) 20px` }}
      >
        {columns.map((c) => (
          <span key={c.name}>{c.display_name || c.name}</span>
        ))}
        <span />
      </div>
      {rows.map((row, rowIndex) => (
        <div
          key={rowIndex}
          className="grid items-center gap-1"
          style={{ gridTemplateColumns: `repeat(${columns.length}, 1fr) 20px` }}
        >
          {columns.map((c) => (
            <Input
              key={c.name}
              value={String(row[c.name] ?? "")}
              onChange={(e) =>
                onChange(
                  rows.map((r, i) =>
                    i === rowIndex ? { ...r, [c.name]: e.target.value } : r,
                  ),
                )
              }
            />
          ))}
          <button
            type="button"
            aria-label="Remove row"
            className="rounded text-text-3 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
            onClick={() => onChange(rows.filter((_, i) => i !== rowIndex))}
          >
            <X size={13} strokeWidth={1.75} aria-hidden />
          </button>
        </div>
      ))}
      <button
        type="button"
        className="inline-flex items-center gap-1 rounded text-xs text-accent hover:brightness-125 focus-visible:outline-2 focus-visible:outline-accent"
        onClick={() => onChange([...rows, Object.fromEntries(columns.map((c) => [c.name, ""]))])}
      >
        <Plus size={12} strokeWidth={1.75} aria-hidden /> row
      </button>
    </div>
  );
};

const PromptWidget: FC<WidgetProps> = (props) => (
  <div className="space-y-1">
    <Multiline {...props} />
    <p className="text-[11px] text-text-3">
      {"{variables}"} become input ports on the node.
    </p>
  </div>
);

// Nobody memorizes model ids — surface a concrete example per provider as the
// placeholder + tooltip for the free-text "model id" field.
const MODEL_ID_EXAMPLES: Record<string, string> = {
  openai: "gpt-4o-mini",
  anthropic: "claude-3-5-sonnet-latest",
  ollama: "llama3.1",
  fake: "any (uses scripted replies)",
  echo: "optional prefix",
};

const ModelWidget: FC<WidgetProps> = ({ field, value, onChange }) => {
  const model = (value as { provider?: string; model?: string; temperature?: number }) ?? {};
  const providers = (field.providers as string[] | null) ?? [
    "openai",
    "anthropic",
    "ollama",
    "fake",
  ];
  const example = MODEL_ID_EXAMPLES[model.provider ?? ""];
  return (
    <div className="flex gap-1">
      <Select
        className="w-28"
        value={model.provider ?? ""}
        onChange={(e) => onChange({ ...model, provider: e.target.value })}
      >
        <option value="">provider</option>
        {providers.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </Select>
      <Input
        value={model.model ?? ""}
        placeholder={example ? `e.g. ${example}` : "model id"}
        title={
          model.provider
            ? `Model name for ${model.provider}` +
              (example ? ` — e.g. ${example}` : "") +
              ". See the provider's model list."
            : "Pick a provider, then enter its model name (e.g. gpt-4o-mini)."
        }
        onChange={(e) => onChange({ ...model, model: e.target.value })}
      />
      {/* ModelInput's value carries temperature (§4.2); expose it so a model
          configured inline (LLM Call/Agent/Router) isn't forced through a
          separate Language Model node just to set it. Blank = provider default. */}
      <Input
        type="number"
        className="w-16 tabular-nums"
        min={0}
        max={2}
        step={0.1}
        title="temperature (blank = provider default)"
        placeholder="temp"
        value={model.temperature === undefined || model.temperature === null ? "" : String(model.temperature)}
        onChange={(e) => {
          const raw = e.target.value;
          const next = { ...model } as { provider?: string; model?: string; temperature?: number };
          if (raw === "") delete next.temperature;
          else next.temperature = parseFloat(raw);
          onChange(next);
        }}
      />
    </div>
  );
};

const EmbeddingModelWidget: FC<WidgetProps> = ({ field, value, onChange }) => {
  const model = (value as { provider?: string; model?: string }) ?? {};
  const providers = (field.providers as string[] | null) ?? ["openai", "ollama", "fake"];
  return (
    <div className="flex gap-1">
      <Select
        className="w-28"
        value={model.provider ?? ""}
        onChange={(e) => onChange({ ...model, provider: e.target.value })}
      >
        <option value="">provider</option>
        {providers.map((p) => (
          <option key={p} value={p}>
            {p}
          </option>
        ))}
      </Select>
      <Input
        value={model.model ?? ""}
        placeholder="embedding model"
        onChange={(e) => onChange({ ...model, model: e.target.value })}
      />
    </div>
  );
};

interface VectorConnection {
  name: string;
  backend: string;
  collections?: { name: string }[];
}

// Value shape: {"$vectorstore": connectionName, collection: string} (SPEC §4.2).
const VectorStoreWidget: FC<WidgetProps> = ({ field, value, onChange }) => {
  const current = (value as { $vectorstore?: string; collection?: string }) ?? {};
  const connections = useQuery({
    queryKey: ["vectorstores"],
    queryFn: async (): Promise<VectorConnection[]> => {
      const response = await fetch("/api/v1/vectorstores");
      return response.ok ? response.json() : [];
    },
  });
  const conns = connections.data ?? [];
  const selected = conns.find((c) => c.name === current.$vectorstore);
  const collections = selected?.collections ?? [];
  return (
    <div className="space-y-1">
      <Select
        value={current.$vectorstore ?? ""}
        onChange={(e) => onChange({ ...current, $vectorstore: e.target.value })}
      >
        <option value="">connection…</option>
        {conns.map((c) => (
          <option key={c.name} value={c.name}>
            {c.name} ({c.backend})
          </option>
        ))}
      </Select>
      <Input
        list={`vs-cols-${field.name}`}
        placeholder="collection"
        value={current.collection ?? ""}
        onChange={(e) => onChange({ ...current, collection: e.target.value })}
      />
      <datalist id={`vs-cols-${field.name}`}>
        {collections.map((c) => (
          <option key={c.name} value={c.name} />
        ))}
      </datalist>
    </div>
  );
};

/** McpInput (§8.4): value {server: string, tools?: string[]} — picks from the
 * globally managed MCP servers (Settings → MCP Servers). Raw connection JSON
 * remains available behind an "advanced" toggle and is the automatic fallback
 * while no managed servers exist. */
const McpWidget: FC<WidgetProps> = ({ field, value, onChange }) => {
  const servers = useQuery({ queryKey: ["mcp-servers"], queryFn: api.mcpServers.list });
  const [rawJson, setRawJson] = useState(false);
  const current =
    typeof value === "object" && value !== null
      ? (value as { server?: string; tools?: string[] })
      : {};

  if (servers.isLoading) {
    return <div className="h-8.5 w-full animate-pulse rounded-md bg-surface-2" aria-hidden />;
  }

  const list = servers.data ?? [];
  const noServers = list.length === 0;
  const showJson = rawJson || noServers;

  return (
    <div className="space-y-1">
      {showJson ? (
        <JsonWidget field={field} value={value} onChange={onChange} />
      ) : (
        <Select
          aria-label="Managed MCP server"
          value={current.server ?? ""}
          onChange={(e) =>
            onChange(e.target.value ? { ...current, server: e.target.value } : null)
          }
        >
          <option value="">managed server…</option>
          {list.map((s) => (
            <option key={s.id} value={s.name}>
              {s.name} ({s.transport})
            </option>
          ))}
        </Select>
      )}
      {noServers ? (
        <p className="text-[11px] text-text-3">
          No managed servers yet —{" "}
          <a
            href="/settings"
            className="rounded text-accent underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-accent"
          >
            add one in Settings → MCP Servers
          </a>
          , or paste connection JSON above.
        </p>
      ) : (
        <button
          type="button"
          aria-pressed={rawJson}
          className="rounded text-[11px] text-text-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent"
          onClick={() => setRawJson((r) => !r)}
        >
          {showJson ? "← pick a managed server" : "advanced: raw connection JSON"}
        </button>
      )}
    </div>
  );
};

const LinkWidget: FC<WidgetProps> = ({ value }) => (
  <a
    href={String(value ?? "#")}
    target="_blank"
    rel="noreferrer"
    className="rounded text-xs text-accent underline underline-offset-2 focus-visible:outline-2 focus-visible:outline-accent"
  >
    {String(value ?? "")}
  </a>
);

const FileWidget: FC<WidgetProps> = ({ field, value, onChange }) => (
  <div className="space-y-1">
    <input
      type="file"
      multiple={Boolean(field.multiple)}
      accept={(field.file_types as string[] | undefined)?.join(",") || undefined}
      className="rounded text-xs text-text-2 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
      onChange={async (e) => {
        const files = [...(e.target.files ?? [])];
        const ids: string[] = [];
        for (const file of files) {
          const form = new FormData();
          form.append("file", file);
          const response = await fetch("/api/v1/files", { method: "POST", body: form });
          if (response.ok) ids.push((await response.json()).file_id);
          else toast.error(`upload failed: ${file.name}`);
        }
        onChange(field.multiple ? ids : ids[0]);
      }}
    />
    {value ? <p className="break-all text-[11px] text-text-3">{JSON.stringify(value)}</p> : null}
  </div>
);

function RefreshButton({ onRefresh }: { onRefresh?: () => void }) {
  return (
    <button
      type="button"
      title="refresh options from server"
      aria-label="Refresh options from server"
      className="rounded border border-border px-2 text-text-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent"
      onClick={onRefresh}
    >
      <RefreshCw size={13} strokeWidth={1.75} aria-hidden />
    </button>
  );
}

const JsonFallback: FC<WidgetProps> = (props) => {
  console.warn(`FieldWidgetRegistry: unknown field type ${props.field?.type}; JSON fallback`);
  return (
    <div className="space-y-1">
      <JsonWidget {...props} />
      <p className="text-[11px] text-text-3">
        unknown field type <span className="font-mono">{props.field?.type}</span> — editing
        raw JSON
      </p>
    </div>
  );
};

export const FieldWidgetRegistry: Record<string, FC<WidgetProps>> = {
  StrInput: Str,
  MultilineInput: Multiline,
  IntInput: (p) => <NumberWidget {...p} integer />,
  FloatInput: (p) => <NumberWidget {...p} />,
  BoolInput: Bool,
  SliderInput: SliderWidget,
  DropdownInput: Dropdown,
  MultiselectInput: Multiselect,
  TabInput: TabWidget,
  SecretInput: Secret,
  MultilineSecretInput: MultilineSecret,
  DictInput: DictWidget,
  NestedDictInput: JsonWidget,
  TableInput: TableWidget,
  FileInput: FileWidget,
  CodeInput: Multiline,
  PromptInput: PromptWidget,
  ModelInput: ModelWidget,
  EmbeddingModelInput: EmbeddingModelWidget,
  VectorStoreInput: VectorStoreWidget,
  QueryInput: Str,
  LinkInput: LinkWidget,
  McpInput: McpWidget,
  // HandleField / ToolsInput are port-only: no widget (handled by the panel)
};

export function widgetFor(field: FieldDescriptor): FC<WidgetProps> {
  return FieldWidgetRegistry[field.type] ?? JsonFallback;
}
