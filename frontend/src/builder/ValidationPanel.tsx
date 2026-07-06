/** VALIDATION panel (SPEC §11.4): diagnostics grouped by severity; click
 * focuses the offending node. Publish is disabled while ERRORs exist. */

import type { Diagnostic } from "@/api/types";
import { cn } from "@/lib/utils";

import { useBuilder } from "./store";

const TONE: Record<string, string> = {
  error: "text-red-400 border-red-900/60",
  warning: "text-amber-400 border-amber-900/60",
  info: "text-sky-400 border-sky-900/60",
};

export function ValidationPanel({ onFocusNode }: { onFocusNode: (nodeId: string) => void }) {
  const diagnostics = useBuilder((s) => s.diagnostics);
  const groups: [string, Diagnostic[]][] = ["error", "warning", "info"]
    .map((sev) => [sev, diagnostics.filter((d) => d.severity === sev)] as [string, Diagnostic[]])
    .filter(([, list]) => list.length > 0);

  return (
    <div className="border-t border-surface-800">
      <h3 className="flex items-center gap-2 px-4 pt-3 text-[10px] font-semibold uppercase tracking-widest text-zinc-500">
        Validation
        {diagnostics.length > 0 && (
          <span className="text-zinc-600">({diagnostics.length})</span>
        )}
      </h3>
      <div className="max-h-56 space-y-1.5 overflow-y-auto px-4 py-2">
        {diagnostics.length === 0 && (
          <p className="text-xs text-zinc-600">No diagnostics — run Validate.</p>
        )}
        {groups.map(([severity, list]) => (
          <div key={severity} className="space-y-1">
            {list.map((d, index) => (
              <button
                key={`${severity}-${index}`}
                type="button"
                onClick={() => d.node_id && onFocusNode(d.node_id)}
                className={cn(
                  "block w-full rounded border-l-2 bg-surface-900 px-2 py-1 text-left text-xs",
                  TONE[severity],
                  d.node_id && "hover:bg-surface-800",
                )}
              >
                <span className="font-mono font-semibold">{d.code}</span>{" "}
                {d.node_id && <span className="text-zinc-500">[{d.node_id}]</span>}{" "}
                <span className="text-zinc-300">{d.message}</span>
                {d.fix_hint && <span className="block text-[10px] text-zinc-500">{d.fix_hint}</span>}
              </button>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}
