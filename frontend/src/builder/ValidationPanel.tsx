/** VALIDATION panel (SPEC §11.4/§11.6): diagnostics grouped by severity with
 * counts; click focuses the offending node. Publish is disabled while ERRORs
 * exist. Empty copy is honest: "validated clean" vs "not validated yet". */

import {
  AlertTriangle,
  CheckCircle2,
  Info,
  OctagonAlert,
  type LucideIcon,
} from "lucide-react";

import type { Diagnostic, Severity } from "@/api/types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

import { useBuilder } from "./store";

const GROUPS: { severity: Severity; label: string; icon: LucideIcon }[] = [
  { severity: "error", label: "Errors", icon: OctagonAlert },
  { severity: "warning", label: "Warnings", icon: AlertTriangle },
  { severity: "info", label: "Info", icon: Info },
];

const ROW_TONE: Record<Severity, string> = {
  error: "border-danger/50",
  warning: "border-warning/50",
  info: "border-port-toolset/50",
};

const HEAD_TONE: Record<Severity, string> = {
  error: "text-danger",
  warning: "text-warning",
  info: "text-port-toolset",
};

const CHIP_TONE: Record<Severity, string> = {
  error: "bg-danger/10 text-danger",
  warning: "bg-warning/10 text-warning",
  info: "bg-port-toolset/10 text-port-toolset",
};

export function ValidationPanel({
  onFocusNode,
  needsValidation,
}: {
  onFocusNode: (nodeId: string) => void;
  needsValidation: boolean;
}) {
  const diagnostics = useBuilder((s) => s.diagnostics);
  // §4.11: nodes whose pinned component_version is behind the installed one
  // (same predicate as the per-node "update" badge in nodes.tsx)
  const outdatedCount = useBuilder((s) =>
    s.nodes.reduce((count, node) => {
      const descriptor = s.descriptors.get(node.data.componentId);
      const stale =
        descriptor &&
        !descriptor.legacy &&
        node.data.componentVersion &&
        node.data.componentVersion !== descriptor.version;
      return count + (stale ? 1 : 0);
    }, 0),
  );

  const groups = GROUPS.map((group) => ({
    ...group,
    items: diagnostics.filter((d) => d.severity === group.severity),
  })).filter((group) => group.items.length > 0);

  return (
    <div className="border-t border-border">
      <div className="flex items-center gap-2 px-4 pt-3">
        <h3 className="text-[11px] font-semibold uppercase tracking-widest text-text-3">
          Validation
        </h3>
        {groups.map(({ severity, items }) => (
          <span
            key={severity}
            className={cn(
              "rounded-md px-1.5 py-0.5 text-[10.5px] font-semibold tabular-nums",
              CHIP_TONE[severity],
            )}
          >
            {items.length} {severity}
            {items.length === 1 ? "" : "s"}
          </span>
        ))}
        {outdatedCount > 0 && (
          // Bulk component update has no store/API action yet — surfaced
          // disabled so the version drift is visible (per-node badge updates).
          <span
            className="ml-auto"
            title="Bulk update is not wired yet — update nodes individually via their update badge"
          >
            <Button
              size="sm"
              variant="outline"
              disabled
              className="h-6 px-2 text-[11px]"
              aria-label={`Update all ${outdatedCount} outdated components (not available yet)`}
            >
              Update all ({outdatedCount})
            </Button>
          </span>
        )}
      </div>
      <div className="max-h-56 space-y-2 overflow-y-auto px-4 py-2">
        {diagnostics.length === 0 &&
          (needsValidation ? (
            <p className="flex items-center gap-1.5 text-xs text-text-3">
              <Info size={13} strokeWidth={1.75} aria-hidden />
              No diagnostics — validate to refresh.
            </p>
          ) : (
            <p className="flex items-center gap-1.5 text-xs text-success">
              <CheckCircle2 size={13} strokeWidth={1.75} aria-hidden />
              No issues
              <span className="font-normal text-text-3">— current graph validated clean</span>
            </p>
          ))}
        {groups.map(({ severity, label, icon: Icon, items }) => (
          <div key={severity}>
            <p
              className={cn(
                "mb-1 flex items-center gap-1 text-[10.5px] font-semibold uppercase tracking-widest",
                HEAD_TONE[severity],
              )}
            >
              <Icon size={12} strokeWidth={1.75} aria-hidden />
              {label}
              <span className="font-normal tabular-nums text-text-3">({items.length})</span>
            </p>
            <div className="space-y-1">
              {items.map((d: Diagnostic, index) => (
                <button
                  key={`${severity}-${index}`}
                  type="button"
                  onClick={() => d.node_id && onFocusNode(d.node_id)}
                  className={cn(
                    "block w-full rounded border-l-2 bg-surface-1 px-2 py-1 text-left text-xs",
                    "focus-visible:outline-2 focus-visible:outline-accent",
                    ROW_TONE[severity],
                    HEAD_TONE[severity],
                    d.node_id ? "hover:bg-surface-2" : "cursor-default",
                  )}
                >
                  <span className="font-mono font-semibold">{d.code}</span>{" "}
                  {d.node_id && <span className="text-text-3">[{d.node_id}]</span>}{" "}
                  <span className="text-text-2">{d.message}</span>
                  {d.fix_hint && (
                    <span className="block text-[11px] text-text-3">{d.fix_hint}</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
