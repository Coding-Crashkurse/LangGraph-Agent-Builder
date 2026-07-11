/** Output-preview primitives (§11.6): Message → chat bubble, dict →
 * collapsible JSON tree, list → simple table, long text truncated with an
 * "open full" toggle. Previews arrive as repr strings from the backend, so the
 * dispatcher parses JSON-looking strings before falling back to plain text. */

import { ChevronDown, ChevronRight } from "lucide-react";
import { useState } from "react";

import { cn } from "@/lib/utils";

const MAX_TREE_CHILDREN = 50;
const MAX_TABLE_ROWS = 20;
const MAX_TABLE_COLS = 6;
const TEXT_FOLD = 280;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function scalarLabel(value: unknown): string {
  if (value === null) return "null";
  if (value === undefined) return "undefined";
  if (typeof value === "string") return JSON.stringify(value);
  return String(value);
}

// ------------------------------------------------------------------ JSON tree
export function JsonTree({
  value,
  name,
  depth = 0,
}: {
  value: unknown;
  name?: string;
  depth?: number;
}) {
  const [open, setOpen] = useState(depth < 1);
  const container = isRecord(value) || Array.isArray(value);

  if (!container) {
    return (
      <p className="font-mono text-[11px] leading-relaxed">
        {name !== undefined && <span className="text-text-3">{name}: </span>}
        <span className={cn(value == null ? "italic text-text-3" : "text-text-2")}>
          {scalarLabel(value)}
        </span>
      </p>
    );
  }

  const entries = Array.isArray(value)
    ? value.map((item, index): [string, unknown] => [String(index), item])
    : Object.entries(value);
  const summary = Array.isArray(value)
    ? `[${entries.length} item${entries.length === 1 ? "" : "s"}]`
    : `{${entries.length} key${entries.length === 1 ? "" : "s"}}`;
  const Chevron = open ? ChevronDown : ChevronRight;

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex items-center gap-1 rounded font-mono text-[11px] leading-relaxed",
          "text-text-2 hover:text-text-1",
          "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        )}
      >
        <Chevron className="h-3 w-3 shrink-0 text-text-3" strokeWidth={1.75} />
        {name !== undefined && <span className="text-text-3">{name}:</span>}
        <span>{summary}</span>
      </button>
      {open && (
        <div className="ml-1.5 border-l border-border pl-3">
          {entries.slice(0, MAX_TREE_CHILDREN).map(([key, child]) => (
            <JsonTree key={key} name={key} value={child} depth={depth + 1} />
          ))}
          {entries.length > MAX_TREE_CHILDREN && (
            <p className="font-mono text-[11px] italic text-text-3">
              … {entries.length - MAX_TREE_CHILDREN} more
            </p>
          )}
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ list table
export function ListTable({ items }: { items: unknown[] }) {
  const [full, setFull] = useState(false);
  const objects = items.every(isRecord);
  const columns = objects
    ? [...new Set(items.slice(0, MAX_TABLE_ROWS).flatMap((row) => Object.keys(row as object)))]
        .slice(0, MAX_TABLE_COLS)
    : ["value"];
  const rows = full ? items : items.slice(0, MAX_TABLE_ROWS);

  return (
    <div className="space-y-1">
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full border-collapse font-mono text-[11px]">
          <thead>
            <tr>
              {columns.map((column) => (
                <th
                  key={column}
                  className="border-b border-border bg-surface-2 px-1.5 py-1 text-left font-medium text-text-2"
                >
                  {column}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr key={index} className="odd:bg-surface-1/50">
                {columns.map((column) => {
                  const cell = objects ? (row as Record<string, unknown>)[column] : row;
                  const text = isRecord(cell) || Array.isArray(cell)
                    ? JSON.stringify(cell)
                    : scalarLabel(cell);
                  return (
                    <td key={column} className="px-1.5 py-0.5 align-top text-text-2">
                      {text.length > 80 ? `${text.slice(0, 80)}…` : text}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {items.length > MAX_TABLE_ROWS && (
        <button
          type="button"
          className="text-[11px] text-accent hover:brightness-125 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
          onClick={() => setFull((v) => !v)}
        >
          {full ? "collapse" : `open full (${items.length} rows)`}
        </button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ long text
function TruncatedText({ text }: { text: string }) {
  const [full, setFull] = useState(false);
  const long = text.length > TEXT_FOLD;
  return (
    <div>
      <pre className="max-h-64 overflow-auto whitespace-pre-wrap font-mono text-[11px] leading-relaxed text-text-2">
        {full || !long ? text : `${text.slice(0, TEXT_FOLD)}…`}
      </pre>
      {long && (
        <button
          type="button"
          className="text-[11px] text-accent hover:brightness-125 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
          onClick={() => setFull((v) => !v)}
        >
          {full ? "collapse" : "open full"}
        </button>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ dispatcher
/** True for Message-shaped payloads ({role, content} or bare {text}). */
function messageText(value: Record<string, unknown>): string | null {
  if (typeof value.content === "string" && typeof value.role === "string") {
    return value.content;
  }
  if (typeof value.text === "string" && Object.keys(value).length <= 2) {
    return value.text;
  }
  return null;
}

/** Render one output-port value with the §11.6 type-appropriate preview. */
export function OutputValue({ value }: { value: unknown }) {
  let resolved = value;
  if (typeof resolved === "string") {
    const trimmed = resolved.trim();
    if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
      try {
        resolved = JSON.parse(trimmed);
      } catch {
        /* repr string, not JSON — fall through to text */
      }
    }
  }

  if (isRecord(resolved)) {
    const text = messageText(resolved);
    if (text !== null) {
      return (
        <div className="max-w-full rounded-lg border border-border bg-surface-1 px-2.5 py-1.5">
          {typeof resolved.role === "string" && (
            <p className="text-[11px] uppercase tracking-wider text-text-3">
              {resolved.role}
            </p>
          )}
          <p className="whitespace-pre-wrap text-[13px] leading-[1.45] text-text-1">{text}</p>
        </div>
      );
    }
    return <JsonTree value={resolved} />;
  }
  if (Array.isArray(resolved)) return <ListTable items={resolved} />;
  if (typeof resolved === "string") return <TruncatedText text={resolved} />;
  return (
    <span className="font-mono text-[11px] text-text-2">{scalarLabel(resolved)}</span>
  );
}
