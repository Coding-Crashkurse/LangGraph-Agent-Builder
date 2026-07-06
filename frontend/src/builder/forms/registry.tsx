/** FieldWidgetRegistry (SPEC §11.2): one widget per §4.2 field type; node
 * forms render EXCLUSIVELY from component descriptors. Unknown type → JSON
 * fallback + console warn (forward compat). */

import { useState, type FC } from "react";

import type { FieldDescriptor } from "@/api/types";
import { Input } from "@/components/ui/input";
import { Select, Switch, Tabs } from "@/components/ui/controls";
import { cn } from "@/lib/utils";

export interface WidgetProps {
  field: FieldDescriptor;
  value: unknown;
  onChange: (value: unknown) => void;
  onRefresh?: () => void; // refresh_button / options_source round-trip
}

function optionValues(field: FieldDescriptor): { value: string; label: string }[] {
  const options = (field.options as (string | { value: string; label?: string })[]) ?? [];
  return options.map((o) =>
    typeof o === "string" ? { value: o, label: o } : { value: o.value, label: o.label ?? o.value },
  );
}

const Str: FC<WidgetProps> = ({ field, value, onChange }) => (
  <Input
    value={String(value ?? "")}
    placeholder={field.placeholder}
    onChange={(e) => onChange(e.target.value)}
  />
);

const Multiline: FC<WidgetProps> = ({ field, value, onChange }) => (
  <textarea
    className="min-h-[72px] w-full rounded-md border border-surface-700 bg-surface-900 px-2 py-1.5 font-mono text-xs text-zinc-100 focus:border-accent-500 focus:outline-none"
    value={String(value ?? "")}
    placeholder={field.placeholder}
    onChange={(e) => onChange(e.target.value)}
  />
);

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

const Slider: FC<WidgetProps> = ({ field, value, onChange }) => (
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
    <span className="w-10 text-right text-xs text-zinc-400">{String(value ?? "")}</span>
  </div>
);

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
  return (
    <div className="space-y-1">
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
      <div className="flex gap-1">
        <Input
          list={`ms-${field.name}`}
          value={draft}
          placeholder="add…"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && draft.trim()) {
              e.preventDefault();
              if (!selected.includes(draft.trim())) onChange([...selected, draft.trim()]);
              setDraft("");
            }
          }}
        />
        <datalist id={`ms-${field.name}`}>
          {options
            .filter((o) => !selected.includes(o.value))
            .map((o) => (
              <option key={o.value} value={o.value} />
            ))}
        </datalist>
        {field.options_source ? <RefreshButton onRefresh={onRefresh} /> : null}
      </div>
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
  const isRef = typeof value === "object" && value !== null && "$secret" in (value as object);
  return (
    <div className="space-y-1">
      <Input
        type="password"
        value={isRef ? "" : String(value ?? "")}
        placeholder={
          isRef ? `$secret: ${(value as Record<string, string>).$secret}` : "secret value"
        }
        onChange={(e) => onChange(e.target.value)}
      />
      <p className="text-[10px] text-zinc-500">
        Tip: reference a stored credential as {"{\"$secret\": \"name\"}"} instead of pasting it.
      </p>
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

const ModelWidget: FC<WidgetProps> = ({ field, value, onChange }) => {
  const model = (value as { provider?: string; model?: string; temperature?: number }) ?? {};
  const providers = (field.providers as string[] | null) ?? [
    "openai",
    "anthropic",
    "ollama",
    "fake",
  ];
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
        placeholder="model id"
        onChange={(e) => onChange({ ...model, model: e.target.value })}
      />
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
  MultilineSecretInput: Secret,
  DictInput: DictWidget,
  NestedDictInput: JsonWidget,
  TableInput: TableWidget,
  FileInput: FileWidget,
  CodeInput: Multiline,
  PromptInput: PromptWidget,
  ModelInput: ModelWidget,
  QueryInput: Str,
  LinkInput: LinkWidget,
  McpInput: McpWidget,
  // HandleField / ToolsInput are port-only: no widget (handled by the panel)
};

export function widgetFor(field: FieldDescriptor): FC<WidgetProps> {
  return FieldWidgetRegistry[field.type] ?? JsonFallback;
}
