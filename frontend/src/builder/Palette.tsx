/** Component sidebar: collapsible category groups, search, drag to canvas,
 * hover card showing description + typed ports (SPEC §11.1/§11.3). */

import { useMemo, useState } from "react";

import { PORT_FAMILY_COLORS, type ComponentDescriptor } from "@/api/types";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

const CATEGORY_ORDER = ["llm", "rag", "flow_control", "tools", "io", "data", "testing"];
const CATEGORY_LABELS: Record<string, string> = {
  llm: "LLM",
  rag: "RAG",
  flow_control: "Flow Control",
  tools: "Tools",
  io: "IO & Glue",
  data: "Data",
  testing: "Testing",
};
const CATEGORY_DOTS: Record<string, string> = {
  llm: "bg-violet-500",
  rag: "bg-emerald-500",
  flow_control: "bg-amber-500",
  tools: "bg-sky-500",
  io: "bg-zinc-400",
  data: "bg-slate-400",
  testing: "bg-pink-500",
};
const CATEGORY_HINTS: Record<string, string> = {
  llm: "Models: single completions and tool-loop agents.",
  rag: "Retrieval: pgvector search, embeddings, splitting, loading.",
  flow_control: "Branching, loops and human-in-the-loop interrupts.",
  tools: "Toolsets for agents: MCP servers, remote A2A agents, utilities.",
  io: "Flow entry/exit and glue for the shared data dict.",
  data: "Templates, converters, extractors.",
  testing: "Deterministic components — CI without API keys.",
};

interface HoverCard {
  component: ComponentDescriptor;
  top: number;
}

function portChips(component: ComponentDescriptor) {
  const inputs = Object.entries(component.input_ports).map(([name, port]) => ({
    name,
    family: port.family,
    ref: port.schema_ref,
  }));
  const outputs = component.outputs.map((output) => ({
    name: output.name,
    family: output.port.family,
    ref: output.port.schema_ref,
  }));
  return { inputs, outputs };
}

function Chip({ name, family }: { name: string; family: string }) {
  const color = PORT_FAMILY_COLORS[family as keyof typeof PORT_FAMILY_COLORS] ?? "#9ca3af";
  return (
    <span
      className="inline-flex items-center gap-1 rounded border border-surface-700 px-1 py-0.5 text-[9px] text-zinc-300"
      title={family}
    >
      <span className="h-1.5 w-1.5 rounded-full" style={{ background: color }} />
      {name}
    </span>
  );
}

export function Palette({ components }: { components: ComponentDescriptor[] }) {
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [hover, setHover] = useState<HoverCard | null>(null);

  const groups = useMemo(() => {
    const filtered = components.filter(
      (c) =>
        !c.legacy &&
        (query === "" ||
          c.display_name.toLowerCase().includes(query.toLowerCase()) ||
          c.component_id.includes(query.toLowerCase())),
    );
    const map = new Map<string, ComponentDescriptor[]>();
    for (const c of filtered) {
      map.set(c.category, [...(map.get(c.category) ?? []), c]);
    }
    for (const items of map.values()) {
      // SPEC §18.2: priority sorts within a category (lower first), ties by name
      items.sort(
        (a, b) =>
          (a.priority ?? 1000) - (b.priority ?? 1000) ||
          a.display_name.localeCompare(b.display_name),
      );
    }
    return [...map.entries()].sort(
      (a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]),
    );
  }, [components, query]);

  const toggle = (category: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(category)) next.delete(category);
      else next.add(category);
      return next;
    });

  return (
    <div className="relative flex h-full w-60 flex-col border-r border-surface-800 bg-surface-950">
      <div className="p-3">
        <Input
          id="palette-search"
          value={query}
          placeholder="Search components…  ( / )"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="flex-1 overflow-y-auto px-3 pb-4">
        {groups.map(([category, items]) => {
          const isCollapsed = collapsed.has(category) && query === "";
          return (
            <div key={category} className="mb-3">
              <button
                type="button"
                onClick={() => toggle(category)}
                title={CATEGORY_HINTS[category]}
                className="mb-1.5 flex w-full items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-500 hover:text-zinc-300"
              >
                <span className={cn("h-1.5 w-1.5 rounded-full", CATEGORY_DOTS[category])} />
                {CATEGORY_LABELS[category] ?? category}
                <span className="text-zinc-700">({items.length})</span>
                <span className="ml-auto text-zinc-600">{isCollapsed ? "▸" : "▾"}</span>
              </button>
              {!isCollapsed && (
                <div className="space-y-1">
                  {items.map((component) => (
                    <div
                      key={component.component_id}
                      draggable
                      onDragStart={(event) => {
                        setHover(null);
                        event.dataTransfer.setData(
                          "application/lga-component",
                          component.component_id,
                        );
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onMouseEnter={(event) =>
                        setHover({
                          component,
                          top: event.currentTarget.getBoundingClientRect().top,
                        })
                      }
                      onMouseLeave={() => setHover(null)}
                      className="cursor-grab rounded-md border border-surface-800 bg-surface-900 px-2.5 py-1.5 text-xs text-zinc-200 hover:border-accent-600 hover:bg-surface-800 active:cursor-grabbing"
                    >
                      <span className="flex items-center gap-1">
                        {component.display_name}
                        {component.beta && (
                          <span className="rounded bg-violet-900/60 px-1 text-[8px] font-bold text-violet-300">
                            BETA
                          </span>
                        )}
                        {component.node_kind === "interrupt" && (
                          <span className="rounded bg-amber-900/60 px-1 text-[8px] font-bold text-amber-300">
                            HITL
                          </span>
                        )}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {hover && (
        <div
          className="pointer-events-none fixed z-50 w-72 rounded-lg border border-surface-700 bg-surface-950/95 p-3 shadow-2xl"
          style={{ left: 248, top: Math.min(hover.top, window.innerHeight - 220) }}
        >
          <p className="text-xs font-semibold text-zinc-100">
            {hover.component.display_name}
            <span className="ml-2 font-mono text-[9px] font-normal text-zinc-600">
              {hover.component.component_id}
            </span>
          </p>
          <p className="mt-1 text-[11px] leading-snug text-zinc-400">
            {hover.component.description}
          </p>
          {(() => {
            const { inputs, outputs } = portChips(hover.component);
            return (
              <div className="mt-2 space-y-1.5">
                {inputs.length > 0 && (
                  <div>
                    <p className="text-[9px] uppercase tracking-widest text-zinc-600">inputs</p>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {inputs.map((p) => (
                        <Chip key={p.name} name={p.name} family={p.family} />
                      ))}
                    </div>
                  </div>
                )}
                {outputs.length > 0 && (
                  <div>
                    <p className="text-[9px] uppercase tracking-widest text-zinc-600">outputs</p>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {outputs.map((p) => (
                        <Chip key={p.name} name={p.name} family={p.family} />
                      ))}
                    </div>
                  </div>
                )}
                <p className="text-[9px] text-zinc-600">
                  Drag onto the canvas · ports connect by matching colors
                </p>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
