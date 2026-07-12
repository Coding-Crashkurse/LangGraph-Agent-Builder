/**
 * Node palette — rendered 1:1 from GET /node-types. Node types are a
 * platform concern; nothing here is builder-local.
 */

import { Sparkles } from "lucide-react";

import type { NodeCatalog, NodeTypeInfo } from "@/api/types";
import { cn } from "@/lib/utils";

import { NODE_ICONS } from "./nodes";

const CATEGORY_ORDER = ["io", "llm", "rag", "tools"];
const CATEGORY_LABEL: Record<string, string> = {
  io: "Input / Output",
  llm: "LLM",
  rag: "Knowledge",
  tools: "Tools",
};

export const DRAG_MIME = "application/x-agentplane-node-type";

function PaletteEntry({ info }: { info: NodeTypeInfo }) {
  const Icon = NODE_ICONS[info.icon] ?? Sparkles;
  return (
    <div
      draggable
      role="button"
      tabIndex={0}
      aria-label={`Add ${info.label}`}
      title={info.description}
      onDragStart={(event) => {
        event.dataTransfer.setData(DRAG_MIME, info.type);
        event.dataTransfer.effectAllowed = "move";
      }}
      className={cn(
        "flex cursor-grab items-center gap-2 rounded-lg border border-border bg-surface-2 px-2.5 py-2",
        "text-xs text-text-1 transition-colors hover:border-border-strong hover:bg-surface-3",
      )}
    >
      <Icon size={14} strokeWidth={1.75} className="shrink-0 text-accent" />
      <div className="min-w-0">
        <div className="truncate font-medium">{info.label}</div>
        <div className="truncate text-[11px] text-text-3">
          {info.type} · v{info.version}
        </div>
      </div>
    </div>
  );
}

export function Palette({ catalog }: { catalog: NodeCatalog }) {
  const groups = new Map<string, NodeTypeInfo[]>();
  for (const info of catalog.node_types) {
    const list = groups.get(info.category) ?? [];
    list.push(info);
    groups.set(info.category, list);
  }
  const orderedCategories = [
    ...CATEGORY_ORDER.filter((c) => groups.has(c)),
    ...[...groups.keys()].filter((c) => !CATEGORY_ORDER.includes(c)),
  ];
  return (
    <aside className="flex w-56 shrink-0 flex-col gap-4 overflow-y-auto border-r border-border bg-surface-1 p-3">
      {orderedCategories.map((category) => (
        <section key={category}>
          <h3 className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-wide text-text-3">
            {CATEGORY_LABEL[category] ?? category}
          </h3>
          <div className="flex flex-col gap-1.5">
            {(groups.get(category) ?? []).map((info) => (
              <PaletteEntry key={`${info.type}@${info.version}`} info={info} />
            ))}
          </div>
        </section>
      ))}
    </aside>
  );
}
