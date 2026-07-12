/**
 * Validation panel: local (advisory) AND runtime (authoritative) issues
 * render identically; click focuses the offending node/field via
 * `ValidationIssue.path` (SPEC §2.3).
 */

import { AlertTriangle, CheckCircle2, CloudOff, XCircle } from "lucide-react";

import type { SourcedIssue } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

import { issueNodeId, useBuilder } from "./store";

function IssueRow({
  issue,
  onFocus,
}: {
  issue: SourcedIssue;
  onFocus: (nodeId: string | null, path: string) => void;
}) {
  const nodeId = issueNodeId(issue.path);
  const isError = issue.severity === "error";
  return (
    <button
      type="button"
      onClick={() => onFocus(nodeId, issue.path)}
      className={cn(
        "flex w-full items-start gap-2 rounded-lg border border-transparent px-2 py-1.5 text-left",
        "transition-colors hover:border-border hover:bg-surface-2",
      )}
    >
      {isError ? (
        <XCircle size={13} className="mt-0.5 shrink-0 text-danger" />
      ) : (
        <AlertTriangle size={13} className="mt-0.5 shrink-0 text-warning" />
      )}
      <span className="min-w-0 flex-1 text-xs leading-relaxed text-text-1">
        <span className={cn("font-mono", isError ? "text-danger" : "text-warning")}>
          {issue.code}
        </span>{" "}
        {issue.message}
        <span className="mt-0.5 block truncate font-mono text-[10px] text-text-3">
          {issue.path}
        </span>
      </span>
      <Badge tone={issue.source === "runtime" ? "accent" : "muted"} className="shrink-0">
        {issue.source}
      </Badge>
    </button>
  );
}

export function ValidationPanel({
  onFocusIssue,
}: {
  onFocusIssue: (nodeId: string | null, path: string) => void;
}) {
  const issues = useBuilder((s) => s.issues);
  const validated = useBuilder((s) => s.validated);
  const runtimeChecked = useBuilder((s) => s.runtimeChecked);
  const errors = issues.filter((i) => i.severity === "error");
  const warnings = issues.filter((i) => i.severity === "warning");

  return (
    <section
      aria-label="Validation issues"
      className="flex max-h-56 flex-col border-t border-border bg-surface-1"
    >
      <header className="flex items-center gap-2 border-b border-border px-3 py-1.5">
        <span className="text-[11px] font-semibold uppercase tracking-wide text-text-3">
          Validation
        </span>
        {errors.length > 0 && (
          <span className="font-mono text-[11px] text-danger">{errors.length} errors</span>
        )}
        {warnings.length > 0 && (
          <span className="font-mono text-[11px] text-warning">{warnings.length} warnings</span>
        )}
        <span className="ml-auto inline-flex items-center gap-1 text-[11px] text-text-3">
          {validated && !runtimeChecked && (
            <>
              <CloudOff size={12} /> local only — runtime not checked
            </>
          )}
          {validated && runtimeChecked && "local + runtime"}
        </span>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-1.5">
        {!validated && (
          <p className="px-2 py-3 text-xs text-text-3">
            Not validated yet — run Validate (local check is instant; the runtime answer is
            authoritative).
          </p>
        )}
        {validated && issues.length === 0 && (
          <p className="inline-flex items-center gap-1.5 px-2 py-3 text-xs text-success">
            <CheckCircle2 size={13} /> No issues found.
          </p>
        )}
        {issues.map((issue) => (
          <IssueRow key={`${issue.source}-${issue.code}-${issue.path}`} issue={issue} onFocus={onFocusIssue} />
        ))}
      </div>
    </section>
  );
}
