/** FieldWidgetRegistry (SPEC §11.2): one widget per §4.2 field type; node
 * forms render EXCLUSIVELY from component descriptors. Unknown type → JSON
 * fallback + console warn (forward compat). */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, type CSSProperties, type FC } from "react";

import { api } from "@/api/client";
import type { FieldDescriptor } from "@/api/types";
import { Input } from "@/components/ui/input";
import { Select, Switch, Tabs } from "@/components/ui/controls";
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
      <span className="inline-flex items-center gap-1 rounded border border-emerald-800 bg-emerald-950/60 px-1.5 py-0.5 text-[10px] text-emerald-300">
        {kind === "$secret" ? "🔑" : "🌐"} {current.kind}: {current.name}
        <button
          type="button"
          className="ml-1 text-emerald-500 hover:text-red-400"
          title="Remove reference"
          onClick={() => onChange(null)}
        >
          ✕
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
        className="rounded border border-surface-700 px-1.5 py-0.5 text-[10px] text-zinc-400 hover:border-emerald-700 hover:text-emerald-300"
      >
        {kind === "$secret" ? "🔑 use credential" : "🌐 $var"}
      </button>
      {open && (
        <div className="absolute right-0 z-50 mt-1 w-56 rounded-md border border-surface-700 bg-surface-950 p-1.5 shadow-xl">
          {candidates.length === 0 && !creating && (
            <p className="px-1 py-0.5 text-[10px] text-zinc-500">
              no {wantKind}s stored yet
            </p>
          )}
          {candidates.map((variable) => (
            <button
              key={variable.name}
              type="button"
              className="block w-full rounded px-1.5 py-1 text-left text-[11px] text-zinc-200 hover:bg-surface-800"
              onClick={() => {
                onChange({ [kind]: variable.name });
                setOpen(false);
              }}
            >
              {kind === "$secret" ? "🔑" : "🌐"} {variable.name}
            </button>
          ))}
          <div className="mt-1 border-t border-surface-800 pt-1">
            {creating ? (
              <div className="space-y-1 p-0.5">
                <Input
                  autoFocus
                  className="bg-surface-800 placeholder:text-zinc-500"
                  placeholder="NAME (e.g. OPENAI_API_KEY)"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                />
                <Input
                  type={kind === "$secret" ? "password" : "text"}
                  className="bg-surface-800 placeholder:text-zinc-500"
                  placeholder="value (stored server-side)"
                  value={newValue}
                  onChange={(e) => setNewValue(e.target.value)}
                />
                <button
                  type="button"
                  className="w-full rounded bg-accent-600 px-1.5 py-1 text-[11px] font-medium text-white hover:bg-accent-500 disabled:opacity-40"
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
                className="block w-full rounded px-1.5 py-1 text-left text-[11px] text-accent-400 hover:bg-surface-800"
                onClick={() => setCreating(true)}
              >
                ＋ new {wantKind}…
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
        <textarea
          className="min-h-[72px] w-full rounded-md border border-surface-700 bg-surface-900 px-2 py-1.5 font-mono text-xs text-zinc-100 focus:border-accent-500 focus:outline-none"
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

const Slider: FC<WidgetProps> = ({ field, value, onChange }) => {
  const minLabel = field.min_label as string | undefined;
  const maxLabel = field.max_label as string | undefined;
  return (
    <div className="space-y-0.5">
      <div className="flex items-center gap-2">
        <input
          type="range"
          className="w-full accent-accent-500"
          min={field.min as number}
          max={field.max as number}
          step={field.step as number}
          value={Number(value ?? field.min ?? 0)}
          onChange={(e) => onChange(parseFloat(e.target.value))}
        />
        <span className="w-10 text-right font-mono text-xs tabular-nums text-text-2">
          {String(value ?? "")}
        </span>
      </div>
      {minLabel || maxLabel ? (
        <div className="flex justify-between text-[10px] text-text-3">
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
              className="inline-flex items-center gap-1 rounded bg-surface-700 px-1.5 py-0.5 text-xs text-zinc-200"
            >
              {item}
              <button
                type="button"
                className="text-zinc-500 hover:text-red-400"
                onClick={() => onChange(selected.filter((x) => x !== item))}
              >
                ×
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
          className="rounded border border-surface-700 px-2 text-sm text-zinc-400 hover:border-accent-600 hover:text-accent-300"
          onMouseDown={(e) => e.preventDefault()} // keep focus so onBlur doesn't double-fire
          onClick={() => add(draft)}
        >
          ＋
        </button>
        {field.options_source ? <RefreshButton onRefresh={onRefresh} /> : null}
      </div>
      <p className="text-[10px] text-zinc-500">
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

const Secret: FC<WidgetProps> = ({ value, onChange }) => {
  const ref = refOf(value);
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1.5">
        {!ref && (
          <Input
            type="password"
            value={String(value ?? "")}
            placeholder="secret value (better: use a stored credential →)"
            onChange={(e) => onChange(e.target.value)}
          />
        )}
        <VarPicker kind="$secret" value={value} onChange={onChange} />
      </div>
      {!ref && (
        <p className="text-[10px] text-zinc-500">
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
          <textarea
            className="min-h-[72px] w-full rounded-md border border-surface-700 bg-surface-900 px-2 py-1.5 font-mono text-xs text-zinc-100 focus:border-accent-500 focus:outline-none"
            style={reveal ? undefined : MASK}
            value={String(value ?? "")}
            placeholder={field.placeholder || "multi-line secret — better: use a stored credential →"}
            onChange={(e) => onChange(e.target.value)}
          />
          <button
            type="button"
            className="absolute right-1.5 top-1.5 text-[10px] text-zinc-500 hover:text-zinc-200"
            onClick={() => setReveal((r) => !r)}
          >
            {reveal ? "hide" : "show"}
          </button>
        </div>
      )}
      <VarPicker kind="$secret" value={value} onChange={onChange} />
      {!ref && (
        <p className="text-[10px] text-zinc-500">
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
      <textarea
        className={cn(
          "min-h-[80px] w-full rounded-md border bg-surface-900 px-2 py-1.5 font-mono text-xs text-zinc-100 focus:outline-none",
          bad ? "border-red-600" : "border-surface-700 focus:border-accent-500",
        )}
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
      {bad && <p className="text-[10px] text-red-400">invalid JSON (not applied)</p>}
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
        <div key={index} className="flex gap-1">
          <Input value={k} onChange={(e) => set(index, e.target.value, String(v))} />
          <Input value={String(v ?? "")} onChange={(e) => set(index, k, e.target.value)} />
          <button
            type="button"
            className="px-1 text-zinc-500 hover:text-red-400"
            onClick={() => onChange(Object.fromEntries(entries.filter((_, i) => i !== index)))}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="text-xs text-accent-400 hover:text-accent-300"
        onClick={() => onChange({ ...(value as object), "": "" })}
      >
        + entry
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
        className="grid gap-1 text-[10px] uppercase tracking-wide text-zinc-500"
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
          className="grid gap-1"
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
            className="text-zinc-500 hover:text-red-400"
            onClick={() => onChange(rows.filter((_, i) => i !== rowIndex))}
          >
            ×
          </button>
        </div>
      ))}
      <button
        type="button"
        className="text-xs text-accent-400 hover:text-accent-300"
        onClick={() => onChange([...rows, Object.fromEntries(columns.map((c) => [c.name, ""]))])}
      >
        + row
      </button>
    </div>
  );
};

const PromptWidget: FC<WidgetProps> = (props) => (
  <div className="space-y-1">
    <Multiline {...props} />
    <p className="text-[10px] text-zinc-500">
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
        className="w-16"
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

const McpWidget: FC<WidgetProps> = ({ value, onChange }) => (
  <JsonWidget
    field={undefined as never}
    value={value}
    onChange={onChange}
  />
);

const LinkWidget: FC<WidgetProps> = ({ value }) => (
  <a
    href={String(value ?? "#")}
    target="_blank"
    rel="noreferrer"
    className="text-xs text-accent-400 underline"
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
      className="text-xs text-zinc-400"
      onChange={async (e) => {
        const files = [...(e.target.files ?? [])];
        const ids: string[] = [];
        for (const file of files) {
          const form = new FormData();
          form.append("file", file);
          const response = await fetch("/api/v1/files", { method: "POST", body: form });
          if (response.ok) ids.push((await response.json()).file_id);
        }
        onChange(field.multiple ? ids : ids[0]);
      }}
    />
    {value ? <p className="break-all text-[10px] text-zinc-500">{JSON.stringify(value)}</p> : null}
  </div>
);

function RefreshButton({ onRefresh }: { onRefresh?: () => void }) {
  return (
    <button
      type="button"
      title="refresh options from server"
      className="rounded border border-surface-700 px-2 text-xs text-zinc-400 hover:text-zinc-100"
      onClick={onRefresh}
    >
      ↻
    </button>
  );
}

const JsonFallback: FC<WidgetProps> = (props) => {
  console.warn(`FieldWidgetRegistry: unknown field type ${props.field?.type}; JSON fallback`);
  return <JsonWidget {...props} />;
};

export const FieldWidgetRegistry: Record<string, FC<WidgetProps>> = {
  StrInput: Str,
  MultilineInput: Multiline,
  IntInput: (p) => <NumberWidget {...p} integer />,
  FloatInput: (p) => <NumberWidget {...p} />,
  BoolInput: Bool,
  SliderInput: Slider,
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
