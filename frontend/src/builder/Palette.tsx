/** Component sidebar: collapsible category groups, search, drag to canvas
 * (Enter adds at canvas center — §11.4 keyboard path), hover card showing
 * description + typed ports (SPEC §11.1/§11.3). */

import { ChevronDown, ChevronRight, GripVertical, Search } from "lucide-react";
import { useMemo, useState } from "react";

import { PORT_FAMILY_COLORS, type ComponentDescriptor } from "@/api/types";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

import { useAddComponent } from "./hooks/useAddComponent";

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
  llm: "bg-port-embedding",
  rag: "bg-port-documents",
  flow_control: "bg-port-route",
  tools: "bg-port-toolset",
  io: "bg-port-file",
  data: "bg-port-data",
  testing: "bg-port-vectorstore",
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
  const color =
    PORT_FAMILY_COLORS[family as keyof typeof PORT_FAMILY_COLORS] ?? "var(--color-port-any)";
  return (
    <span
      className="inline-flex items-center gap-1 rounded border border-border px-1 py-0.5 text-[10.5px] text-text-2"
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
  const addComponent = useAddComponent();

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
    <div className="relative flex h-full w-60 flex-col border-r border-border bg-canvas">
      <div className="p-3">
        <div className="relative">
          <Search
            size={14}
            strokeWidth={1.75}
            className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-text-3"
            aria-hidden
          />
          <Input
            id="palette-search"
            value={query}
            placeholder="Search components…"
            aria-label="Search components"
            onChange={(e) => setQuery(e.target.value)}
            className="pl-8 pr-8"
          />
          <kbd
            className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 rounded border border-border bg-surface-2 px-1 py-px font-mono text-[10.5px] text-text-3"
            aria-hidden
          >
            /
          </kbd>
        </div>
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
                aria-expanded={!isCollapsed}
                className="mb-1.5 flex w-full items-center gap-1.5 rounded text-[11px] font-semibold uppercase tracking-widest text-text-3 hover:text-text-2 focus-visible:outline-2 focus-visible:outline-accent"
              >
                <span className={cn("h-1.5 w-1.5 rounded-full", CATEGORY_DOTS[category])} />
                {CATEGORY_LABELS[category] ?? category}
                <span className="text-text-3">({items.length})</span>
                <span className="ml-auto text-text-3">
                  {isCollapsed ? (
                    <ChevronRight size={13} strokeWidth={1.75} aria-hidden />
                  ) : (
                    <ChevronDown size={13} strokeWidth={1.75} aria-hidden />
                  )}
                </span>
              </button>
              {!isCollapsed && (
                <div className="space-y-1">
                  {items.map((component) => (
                    <div
                      key={component.component_id}
                      role="button"
                      tabIndex={0}
                      aria-label={`Add ${component.display_name} to the canvas`}
                      draggable
                      onDragStart={(event) => {
                        setHover(null);
                        event.dataTransfer.setData(
                          "application/lga-component",
                          component.component_id,
                        );
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          addComponent(component.component_id);
                        }
                      }}
                      onMouseEnter={(event) =>
                        setHover({
                          component,
                          top: event.currentTarget.getBoundingClientRect().top,
                        })
                      }
                      onMouseLeave={() => setHover(null)}
                      onFocus={(event) =>
                        setHover({
                          component,
                          top: event.currentTarget.getBoundingClientRect().top,
                        })
                      }
                      onBlur={() => setHover(null)}
                      className={cn(
                        "flex cursor-grab items-center gap-1.5 rounded-md border border-border bg-surface-1",
                        "px-2 py-1.5 text-xs text-text-1 hover:border-border-strong hover:bg-surface-2",
                        "active:cursor-grabbing focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
                      )}
                    >
                      <GripVertical
                        size={13}
                        strokeWidth={1.75}
                        className="shrink-0 text-text-3"
                        aria-hidden
                      />
                      <span className="flex min-w-0 flex-1 items-center gap-1">
                        <span className="truncate">{component.display_name}</span>
                        {component.beta && (
                          <span className="rounded bg-accent/15 px-1 text-[10.5px] font-bold text-accent">
                            BETA
                          </span>
                        )}
                        {component.node_kind === "interrupt" && (
                          <span className="rounded bg-warning/15 px-1 text-[10.5px] font-bold text-warning">
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
          className="pointer-events-none fixed z-50 w-72 rounded-lg border border-border bg-canvas/95 p-3 shadow-2xl"
          style={{ left: 248, top: Math.min(hover.top, window.innerHeight - 220) }}
        >
          <p className="text-xs font-semibold text-text-1">
            {hover.component.display_name}
            <span className="ml-2 font-mono text-[10.5px] font-normal text-text-3">
              {hover.component.component_id}
            </span>
          </p>
          <p className="mt-1 text-[11px] leading-snug text-text-2">
            {hover.component.description}
          </p>
          {(() => {
            const { inputs, outputs } = portChips(hover.component);
            return (
              <div className="mt-2 space-y-1.5">
                {inputs.length > 0 && (
                  <div>
                    <p className="text-[10.5px] uppercase tracking-widest text-text-3">inputs</p>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {inputs.map((p) => (
                        <Chip key={p.name} name={p.name} family={p.family} />
                      ))}
                    </div>
                  </div>
                )}
                {outputs.length > 0 && (
                  <div>
                    <p className="text-[10.5px] uppercase tracking-widest text-text-3">outputs</p>
                    <div className="mt-0.5 flex flex-wrap gap-1">
                      {outputs.map((p) => (
                        <Chip key={p.name} name={p.name} family={p.family} />
                      ))}
                    </div>
                  </div>
                )}
                <p className="text-[10.5px] text-text-3">
                  Drag onto the canvas · Enter adds at the center
                </p>
              </div>
            );
          })()}
        </div>
      )}
    </div>
  );
}
