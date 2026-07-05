/** Schema-driven config form — the only way node configs are edited.
 * Adding a component must never require frontend changes (CLAUDE.md §6.2);
 * if a component seems to need custom UI, extend THIS renderer instead. */

import { Plus, X } from "lucide-react";
import { useState } from "react";

import type { JsonSchema } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Select, Switch } from "@/components/ui/controls";
import { prettyLabel, resolveSchema, widgetFor } from "./schema";

export interface SchemaFormProps {
  schema: JsonSchema;
  value: Record<string, unknown>;
  onChange: (value: Record<string, unknown>) => void;
  errors?: Record<string, string>;
}

export function SchemaForm({ schema, value, onChange, errors = {} }: SchemaFormProps) {
  const properties = schema.properties ?? {};
  const required = new Set(schema.required ?? []);

  const setField = (key: string, fieldValue: unknown) =>
    onChange({ ...value, [key]: fieldValue });

  return (
    <div className="space-y-4">
      {Object.entries(properties).map(([key, raw]) => {
        const field = resolveSchema(raw, schema);
        return (
          <div key={key}>
            <Label hint={required.has(key) ? "required" : undefined}>
              {prettyLabel(key, field)}
            </Label>
            <FieldWidget
              fieldKey={key}
              schema={field}
              value={value[key]}
              onChange={(v) => setField(key, v)}
            />
            {field.description ? (
              <p className="mt-1 text-[11px] leading-snug text-zinc-600">{field.description}</p>
            ) : null}
            {errors[key] ? <p className="mt-1 text-[11px] text-red-400">{errors[key]}</p> : null}
          </div>
        );
      })}
    </div>
  );
}

function FieldWidget({
  fieldKey,
  schema,
  value,
  onChange,
}: {
  fieldKey: string;
  schema: JsonSchema;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const widget = widgetFor(fieldKey, schema);

  switch (widget) {
    case "switch":
      return <Switch checked={Boolean(value)} onCheckedChange={onChange} label={fieldKey} />;
    case "select":
      return (
        <Select value={String(value ?? "")} onChange={(e) => onChange(e.target.value)}>
          {(schema.enum ?? []).map((option) => (
            <option key={String(option)} value={String(option)}>
              {String(option)}
            </option>
          ))}
        </Select>
      );
    case "integer":
    case "number":
      return (
        <Input
          type="number"
          value={value === undefined || value === null ? "" : String(value)}
          min={schema.minimum}
          max={schema.maximum}
          step={widget === "integer" ? 1 : "any"}
          onChange={(e) => {
            const raw = e.target.value;
            if (raw === "") return onChange(undefined);
            onChange(widget === "integer" ? parseInt(raw, 10) : parseFloat(raw));
          }}
        />
      );
    case "textarea":
      return (
        <Textarea
          value={String(value ?? "")}
          rows={4}
          onChange={(e) => onChange(e.target.value)}
        />
      );
    case "tags":
      return <TagListEditor value={asStringArray(value)} onChange={onChange} />;
    case "keyvalue":
      return <KeyValueEditor value={asStringRecord(value)} onChange={onChange} />;
    case "json":
      return <JsonEditor value={value} onChange={onChange} />;
    case "text":
    default:
      return (
        <Input
          value={String(value ?? "")}
          onChange={(e) => onChange(e.target.value)}
          placeholder={schema.default !== undefined ? String(schema.default) : undefined}
        />
      );
  }
}

function asStringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.map(String) : [];
}

function asStringRecord(value: unknown): Record<string, string> {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, String(v)]));
  }
  return {};
}

function TagListEditor({
  value,
  onChange,
}: {
  value: string[];
  onChange: (value: string[]) => void;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const trimmed = draft.trim();
    if (!trimmed || value.includes(trimmed)) return;
    onChange([...value, trimmed]);
    setDraft("");
  };
  return (
    <div>
      <div className="mb-1.5 flex flex-wrap gap-1.5">
        {value.map((tag) => (
          <span
            key={tag}
            className="inline-flex items-center gap-1 rounded-md border border-surface-700 bg-surface-800 px-2 py-0.5 text-xs text-zinc-300"
          >
            {tag}
            <button
              type="button"
              aria-label={`remove ${tag}`}
              className="text-zinc-500 hover:text-red-400"
              onClick={() => onChange(value.filter((t) => t !== tag))}
            >
              <X className="h-3 w-3" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-1.5">
        <Input
          value={draft}
          placeholder="add…"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
        />
        <Button variant="secondary" size="icon" onClick={add} aria-label="add tag">
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

function KeyValueEditor({
  value,
  onChange,
}: {
  value: Record<string, string>;
  onChange: (value: Record<string, string>) => void;
}) {
  const entries = Object.entries(value);
  const [draftKey, setDraftKey] = useState("");
  const [draftValue, setDraftValue] = useState("");

  return (
    <div className="space-y-1.5">
      {entries.map(([key, val]) => (
        <div key={key} className="flex items-center gap-1.5">
          <Input value={key} disabled className="w-2/5 font-mono text-xs" />
          <Input
            value={val}
            className="font-mono text-xs"
            onChange={(e) => onChange({ ...value, [key]: e.target.value })}
          />
          <Button
            variant="ghost"
            size="icon"
            aria-label={`remove ${key}`}
            onClick={() => {
              const next = { ...value };
              delete next[key];
              onChange(next);
            }}
          >
            <X className="h-3.5 w-3.5" />
          </Button>
        </div>
      ))}
      <div className="flex items-center gap-1.5">
        <Input
          value={draftKey}
          placeholder="key"
          className="w-2/5 font-mono text-xs"
          onChange={(e) => setDraftKey(e.target.value)}
        />
        <Input
          value={draftValue}
          placeholder="value"
          className="font-mono text-xs"
          onChange={(e) => setDraftValue(e.target.value)}
        />
        <Button
          variant="secondary"
          size="icon"
          aria-label="add entry"
          onClick={() => {
            if (!draftKey.trim()) return;
            onChange({ ...value, [draftKey.trim()]: draftValue });
            setDraftKey("");
            setDraftValue("");
          }}
        >
          <Plus className="h-3.5 w-3.5" />
        </Button>
      </div>
    </div>
  );
}

function JsonEditor({ value, onChange }: { value: unknown; onChange: (value: unknown) => void }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? null, null, 2));
  const [invalid, setInvalid] = useState(false);
  return (
    <div>
      <Textarea
        value={text}
        rows={5}
        onChange={(e) => {
          setText(e.target.value);
          try {
            onChange(JSON.parse(e.target.value));
            setInvalid(false);
          } catch {
            setInvalid(true);
          }
        }}
      />
      {invalid ? <p className="mt-1 text-[11px] text-amber-400">invalid JSON (not saved)</p> : null}
    </div>
  );
}
