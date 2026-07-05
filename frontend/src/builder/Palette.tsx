import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import type { ComponentInfo } from "@/api/types";
import { CategoryDot } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const CATEGORY_ORDER = ["llm", "rag", "flow", "tools", "io"] as const;
const CATEGORY_LABELS: Record<string, string> = {
  llm: "LLM",
  rag: "RAG",
  flow: "Flow control",
  tools: "Tools",
  io: "I/O & glue",
};

export function Palette({
  components,
  onAdd,
}: {
  components: ComponentInfo[];
  onAdd: (info: ComponentInfo) => void;
}) {
  const [query, setQuery] = useState("");

  const grouped = useMemo(() => {
    const filtered = components.filter((c) => {
      const haystack = `${c.name} ${c.display_name} ${c.description}`.toLowerCase();
      return haystack.includes(query.toLowerCase());
    });
    return CATEGORY_ORDER.map((category) => ({
      category,
      items: filtered.filter((c) => c.category === category),
    })).filter((group) => group.items.length);
  }, [components, query]);

  return (
    <aside className="flex w-60 shrink-0 flex-col border-r border-surface-800 bg-surface-900">
      <div className="border-b border-surface-800 p-2.5">
        <div className="relative">
          <Search className="pointer-events-none absolute left-2 top-2 h-4 w-4 text-zinc-600" />
          <Input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search components…"
            className="pl-7.5"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2.5">
        {grouped.map(({ category, items }) => (
          <div key={category} className="mb-4">
            <div className="mb-1.5 px-1 text-[10px] font-semibold uppercase tracking-widest text-zinc-600">
              {CATEGORY_LABELS[category]}
            </div>
            <div className="space-y-1">
              {items.map((info) => (
                <div
                  key={info.name}
                  draggable
                  title={info.description}
                  onDragStart={(event) => {
                    event.dataTransfer.setData("application/graphforge-component", info.name);
                    event.dataTransfer.effectAllowed = "move";
                  }}
                  onDoubleClick={() => onAdd(info)}
                  className="group cursor-grab rounded-md border border-transparent bg-surface-850 px-2.5 py-2 transition-all duration-150 hover:translate-x-0.5 hover:border-surface-600 hover:bg-surface-800 hover:shadow-md hover:shadow-black/40 active:cursor-grabbing active:scale-[0.99]"
                >
                  <div className="flex items-center gap-2">
                    <CategoryDot category={info.category} />
                    <span className="text-xs font-medium text-zinc-200">{info.display_name}</span>
                    {info.kind !== "node" && (
                      <span className="ml-auto rounded bg-surface-700 px-1 py-px font-mono text-[9px] uppercase text-zinc-400">
                        {info.kind === "tool_provider" ? "tools" : "router"}
                      </span>
                    )}
                  </div>
                  <p className="mt-0.5 line-clamp-2 text-[10px] leading-snug text-zinc-500">
                    {info.description}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
        <p className="px-1 pb-2 text-[10px] leading-relaxed text-zinc-700">
          Drag onto the canvas (or double-click). Dashed sky edges attach tool providers to
          agents; amber handles are router outputs.
        </p>
      </div>
    </aside>
  );
}
