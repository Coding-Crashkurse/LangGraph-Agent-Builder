/** Interrupt surface rendered from the normative §5.5 payloads — identical for
 * playground runs and the A2A input-required state. ApprovalRequest → buttons
 * from `options`; InputRequest with `schema` → a generated form
 * (string/number/boolean/enum) with a raw-JSON "advanced" fallback. */

import { Braces, Pause } from "lucide-react";
import { useMemo, useState } from "react";

import type { InterruptPayload } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, Switch } from "@/components/ui/controls";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

interface SchemaProperty {
  type?: string;
  enum?: unknown[];
  title?: string;
  description?: string;
  default?: unknown;
}

function SchemaForm({
  schema,
  onAnswer,
}: {
  schema: Record<string, unknown>;
  onAnswer: (answer: unknown) => void;
}) {
  const properties = useMemo(
    () => (schema.properties ?? {}) as Record<string, SchemaProperty>,
    [schema],
  );
  const required = useMemo(
    () => new Set(Array.isArray(schema.required) ? (schema.required as string[]) : []),
    [schema],
  );
  const [values, setValues] = useState<Record<string, unknown>>(() => {
    const initial: Record<string, unknown> = {};
    for (const [name, prop] of Object.entries(properties)) {
      if (prop.default !== undefined) initial[name] = prop.default;
      else if (prop.type === "boolean") initial[name] = false;
    }
    return initial;
  });
  const [advanced, setAdvanced] = useState(false);
  const [rawJson, setRawJson] = useState("");

  const setValue = (name: string, value: unknown) =>
    setValues((prev) => ({ ...prev, [name]: value }));

  const coerced = (): Record<string, unknown> => {
    const answer: Record<string, unknown> = {};
    for (const [name, prop] of Object.entries(properties)) {
      const value = values[name];
      if (value === undefined || value === "") continue;
      if (prop.type === "number" || prop.type === "integer") {
        const num = Number(value);
        answer[name] = Number.isNaN(num) ? value : num;
      } else {
        answer[name] = value;
      }
    }
    return answer;
  };

  const missingRequired = [...required].some(
    (name) => values[name] === undefined || values[name] === "",
  );

  const submit = () => {
    if (advanced) {
      try {
        onAnswer(JSON.parse(rawJson));
      } catch {
        toast.error("invalid JSON for the requested schema");
      }
      return;
    }
    onAnswer(coerced());
  };

  const toggleAdvanced = () => {
    if (!advanced) setRawJson(JSON.stringify(coerced(), null, 2));
    setAdvanced((v) => !v);
  };

  return (
    <div className="mt-2 space-y-2">
      {advanced ? (
        <textarea
          className={cn(
            "min-h-[88px] w-full rounded-lg border border-border bg-surface-1 px-2 py-1.5",
            "font-mono text-xs text-text-1 focus:border-accent focus:outline-none",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
          )}
          aria-label="Raw JSON answer"
          value={rawJson}
          onChange={(e) => setRawJson(e.target.value)}
          spellCheck={false}
        />
      ) : (
        Object.entries(properties).map(([name, prop]) => {
          const label = prop.title ?? name;
          const requiredMark = required.has(name) ? " *" : "";
          if (Array.isArray(prop.enum)) {
            return (
              <label key={name} className="block text-xs text-text-2">
                {label}
                {requiredMark}
                <Select
                  className="mt-0.5 !h-7 text-xs"
                  value={String(values[name] ?? "")}
                  onChange={(e) => setValue(name, e.target.value)}
                >
                  <option value="">— select —</option>
                  {prop.enum.map((option) => (
                    <option key={String(option)} value={String(option)}>
                      {String(option)}
                    </option>
                  ))}
                </Select>
              </label>
            );
          }
          if (prop.type === "boolean") {
            return (
              <span key={name} className="flex items-center gap-2 text-xs text-text-2">
                <Switch
                  checked={Boolean(values[name])}
                  onCheckedChange={(checked) => setValue(name, checked)}
                  label={label}
                />
                {label}
                {requiredMark}
              </span>
            );
          }
          const isNumber = prop.type === "number" || prop.type === "integer";
          return (
            <label key={name} className="block text-xs text-text-2">
              {label}
              {requiredMark}
              <Input
                className="mt-0.5 !h-7 text-xs"
                type={isNumber ? "number" : "text"}
                value={String(values[name] ?? "")}
                placeholder={prop.description ?? ""}
                onChange={(e) => setValue(name, e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submit()}
              />
            </label>
          );
        })
      )}
      <div className="flex items-center gap-2">
        <Button className="!h-7 !text-xs" onClick={submit} disabled={!advanced && missingRequired}>
          Answer
        </Button>
        <button
          type="button"
          aria-pressed={advanced}
          onClick={toggleAdvanced}
          className={cn(
            "inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 text-[11px]",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
            advanced ? "bg-surface-3 text-text-1" : "text-text-3 hover:text-text-1",
          )}
        >
          <Braces className="h-3 w-3" strokeWidth={1.75} />
          raw JSON
        </button>
      </div>
    </div>
  );
}

export function InterruptModal({
  payload,
  onAnswer,
}: {
  payload: InterruptPayload;
  onAnswer: (answer: unknown) => void;
}) {
  const [text, setText] = useState("");
  const [comment, setComment] = useState("");
  const isApproval = payload.kind === "approval";
  const schema =
    payload.schema && typeof payload.schema === "object" ? payload.schema : null;

  return (
    <div
      role="region"
      aria-label="Run paused — input required"
      className="border-t-2 border-warning/60 bg-warning/10 px-3 py-2"
    >
      <p className="flex items-center gap-1.5 text-xs font-semibold text-warning">
        <Pause className="h-3.5 w-3.5 shrink-0" strokeWidth={1.75} />
        {payload.prompt ?? "input required"}
      </p>

      {isApproval ? (
        <div className="mt-2 space-y-2">
          <Input
            className="!h-7 text-xs"
            value={comment}
            placeholder="optional comment"
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex gap-2">
            {(payload.options ?? ["approve", "reject"]).map((option) => (
              <Button
                key={option}
                variant={
                  option === "approve" ? "primary" : option === "reject" ? "danger" : "secondary"
                }
                className="!h-7 !text-xs"
                onClick={() => onAnswer({ decision: option, comment: comment || null })}
              >
                {option}
              </Button>
            ))}
          </div>
        </div>
      ) : schema ? (
        <SchemaForm schema={schema} onAnswer={onAnswer} />
      ) : (
        <div className="mt-2 flex gap-2">
          <Input
            className="!h-7 text-xs"
            value={text}
            placeholder="your answer"
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && onAnswer({ text })}
          />
          <Button className="!h-7 !text-xs" onClick={() => onAnswer({ text })}>
            Answer
          </Button>
        </div>
      )}
    </div>
  );
}
