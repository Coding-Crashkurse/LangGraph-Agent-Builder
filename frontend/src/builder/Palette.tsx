/** Component sidebar: grouped by category, searchable, drag to canvas. */

import { useMemo, useState } from "react";

import type { ComponentDescriptor } from "@/api/types";
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

export function Palette({ components }: { components: ComponentDescriptor[] }) {
  const [query, setQuery] = useState("");
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
    return [...map.entries()].sort(
      (a, b) => CATEGORY_ORDER.indexOf(a[0]) - CATEGORY_ORDER.indexOf(b[0]),
    );
  }, [components, query]);

  return (
    <div className="flex h-full w-60 flex-col border-r border-surface-800 bg-surface-950">
      <div className="p-3">
        <Input
          value={query}
          placeholder="Search components…"
          onChange={(e) => setQuery(e.target.value)}
        />
      </div>
      <div className="flex-1 overflow-y-auto px-3 pb-4">
        {groups.map(([category, items]) => (
          <div key={category} className="mb-4">
            <h3 className="mb-1.5 flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
              <span className={cn("h-1.5 w-1.5 rounded-full", CATEGORY_DOTS[category])} />
              {CATEGORY_LABELS[category] ?? category}
            </h3>
            <div className="space-y-1">
              {items.map((component) => (
                <div
                  key={component.component_id}
                  draggable
                  title={component.description}
                  onDragStart={(event) => {
                    event.dataTransfer.setData("application/lga-component",
                                               component.component_id);
                    event.dataTransfer.effectAllowed = "move";
                  }}
                  className="cursor-grab rounded-md border border-surface-800 bg-surface-900 px-2.5 py-1.5 text-xs text-zinc-200 hover:border-accent-600 hover:bg-surface-800 active:cursor-grabbing"
                >
                  <span className="flex items-center gap-1">
                    {component.display_name}
                    {component.beta && (
                      <span className="rounded bg-violet-900/60 px-1 text-[8px] font-bold text-violet-300">
                        BETA
                      </span>
                    )}
                  </span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
