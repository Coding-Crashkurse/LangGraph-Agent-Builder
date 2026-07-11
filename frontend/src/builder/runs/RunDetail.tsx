/** Run Detail (§7.3 "every run is fully inspectable"): a node-by-node timeline
 * for ANY past run_id, not just the live event stream. Fetches the recorded
 * NodeRunInfo[] and renders one expandable row per node execution — loops show
 * one row per iteration — each opening an input/output inspector (JsonTree /
 * OutputValue). A parked `interrupted` node / `input_required` run surfaces a
 * prominent banner. The live Playground Timeline is unchanged; this is additive.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  ChevronDown,
  ChevronRight,
  ListTree,
  RotateCw,
  Trash2,
} from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "@/api/client";
import type { NodeRunInfo, RunStatus } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import { StatusChip } from "../FlowsPage";
import { OutputValue } from "../playground/JsonTree";
import { shortId } from "../playground/format";

type NodeStatus = NodeRunInfo["status"];

export interface NodeRow extends NodeRunInfo {
  /** node_id executes more than once in this run (a loop) → show the iteration. */
  repeated: boolean;
}

/** Annotate each recorded execution with whether its node_id repeats (pure,
 * testable). One row per execution, order preserved; a looping node yields one
 * row per iteration rather than being folded together. */
export function buildNodeRows(nodes: NodeRunInfo[]): NodeRow[] {
  const counts = new Map<string, number>();
  for (const node of nodes) counts.set(node.node_id, (counts.get(node.node_id) ?? 0) + 1);
  return nodes.map((node) => ({ ...node, repeated: (counts.get(node.node_id) ?? 0) > 1 }));
}

const STATUS_TONES: Record<NodeStatus, string> = {
  running: "bg-accent/15 text-accent",
  ok: "bg-success/15 text-success",
  error: "bg-danger/15 text-danger",
  interrupted: "bg-warning/15 text-warning",
};

function formatDuration(ms: number | null): string {
  if (ms == null) return "";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
}

function formatCost(cost: number | null): string {
  if (cost == null) return "";
  return `$${cost < 0.01 ? cost.toFixed(4) : cost.toFixed(2)}`;
}

function NodeRowView({ row }: { row: NodeRow }) {
  const [open, setOpen] = useState(false);
  const hasInput = row.input_snapshot != null;
  const hasOutput = row.output_snapshot != null;
  const expandable = hasInput || hasOutput || row.error_code !== null;
  const Chevron = open ? ChevronDown : ChevronRight;
  const duration = formatDuration(row.duration_ms);
  const cost = formatCost(row.cost);

  return (
    <div
      className={cn(
        "rounded-lg border border-border bg-surface-1/60",
        row.status === "interrupted" && "border-l-2 border-l-warning",
      )}
    >
      <button
        type="button"
        aria-expanded={expandable ? open : undefined}
        disabled={!expandable}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          "flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left",
          expandable && "hover:bg-surface-2",
          "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
        )}
      >
        <span
          className={cn(
            "shrink-0 rounded-[6px] px-1.5 py-px text-[10.5px] font-medium uppercase tracking-wider",
            STATUS_TONES[row.status],
          )}
        >
          {row.status}
        </span>
        <span className="truncate font-mono text-[11px] text-text-1">
          {row.node_id || "(run)"}
        </span>
        {row.repeated && (
          <Badge tone="muted" className="shrink-0 px-1 py-0 text-[10px]">
            iteration {row.iteration}
          </Badge>
        )}
        <span className="ml-auto flex shrink-0 items-center gap-2 font-mono text-[11px] tabular-nums text-text-3">
          {row.tokens != null && <span>{row.tokens} tok</span>}
          {cost && <span>{cost}</span>}
          {duration && <span>{duration}</span>}
        </span>
        {expandable && (
          <Chevron className="h-3.5 w-3.5 shrink-0 text-text-3" strokeWidth={1.75} />
        )}
      </button>
      {open && expandable && (
        <div className="space-y-2 border-t border-border px-2.5 py-2">
          {row.error_code && (
            <p className="rounded border-l-2 border-danger bg-danger/10 px-2 py-1 font-mono text-[11px] text-danger">
              {row.error_code}
            </p>
          )}
          {hasInput && (
            <section className="space-y-0.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">
                input
              </p>
              <OutputValue value={row.input_snapshot} />
            </section>
          )}
          {hasOutput && (
            <section className="space-y-0.5">
              <p className="text-[11px] font-semibold uppercase tracking-wider text-text-3">
                output
              </p>
              <OutputValue value={row.output_snapshot} />
            </section>
          )}
        </div>
      )}
    </div>
  );
}

/** Pure presentational timeline — data comes in as NodeRunInfo[] (tested in
 * isolation, no query/router). `runStatus` lets an `input_required` run raise
 * the banner even if the parked node isn't in the recorded slice yet. */
export function RunDetailView({
  nodes,
  runStatus,
}: {
  nodes: NodeRunInfo[];
  runStatus?: RunStatus;
}) {
  const rows = useMemo(() => buildNodeRows(nodes), [nodes]);
  const awaitingInput =
    runStatus === "input_required" || nodes.some((node) => node.status === "interrupted");

  if (nodes.length === 0) {
    return (
      <div className="flex flex-col items-center gap-1.5 rounded-lg border border-dashed border-border px-6 py-12 text-center">
        <ListTree className="h-5 w-5 text-text-3" strokeWidth={1.75} aria-hidden />
        <p className="text-[13px] text-text-2">No node executions recorded</p>
        <p className="text-xs text-text-3">
          This run has no per-node timeline — it may not have reached the graph.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-2">
      {awaitingInput && (
        <div
          role="status"
          className="flex items-start gap-2 rounded-lg border border-warning/40 bg-warning/10 px-3 py-2"
        >
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-warning" strokeWidth={1.75} aria-hidden />
          <div className="min-w-0">
            <p className="text-[13px] font-semibold text-warning">Waiting for input</p>
            <p className="text-xs text-text-3">
              This run paused on a human-input interrupt. Resume it from the flow playground to
              continue.
            </p>
          </div>
        </div>
      )}
      <div className="space-y-1">
        {rows.map((row, index) => (
          <NodeRowView key={`${row.node_id}-${row.iteration}-${index}`} row={row} />
        ))}
      </div>
    </div>
  );
}

/** Route container for /runs/:runId — fetches the run row (header chrome) and
 * its node timeline, with skeleton / error / empty handling. */
export function RunDetailPage() {
  const { runId = "" } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();

  const run = useQuery({
    queryKey: ["run", runId],
    queryFn: () => api.runs.get(runId),
    enabled: runId !== "",
  });
  const nodes = useQuery({
    queryKey: ["run-nodes", runId],
    queryFn: () => api.runs.nodes(runId),
    enabled: runId !== "",
  });

  const deleteRun = useMutation({
    mutationFn: () => api.runs.delete(runId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      toast.info("trace deleted");
      navigate("/");
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const finished = run.data && run.data.status !== "running" && run.data.status !== "pending";

  return (
    <div className="min-h-screen bg-canvas px-8 py-6 text-text-1">
      <header className="mb-6 flex flex-wrap items-center gap-x-3 gap-y-2">
        <Link
          to="/"
          className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-text-3 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
        >
          <ArrowLeft size={14} strokeWidth={1.75} aria-hidden />
          Flows
        </Link>
        <h1 className="text-lg font-bold">Run</h1>
        <span className="font-mono text-xs text-text-3" title={runId}>
          {shortId(runId, 14)}
        </span>
        {run.data && <StatusChip status={run.data.status} />}
        {run.data && (
          <span className="text-xs text-text-3">
            {run.data.flow_slug && (
              <Link
                to={run.data.flow_id ? `/flows/${run.data.flow_id}` : "/"}
                className="rounded font-mono text-text-2 hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
              >
                /{run.data.flow_slug}
              </Link>
            )}
            {" · "}
            {run.data.mode} · started {new Date(run.data.started_at).toLocaleString()}
          </span>
        )}
        {finished && (
          <button
            type="button"
            title="Delete this trace"
            aria-label="Delete this trace"
            className="ml-auto inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-xs text-text-3 hover:bg-surface-2 hover:text-danger focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
            onClick={() => deleteRun.mutate()}
          >
            <Trash2 size={13} strokeWidth={1.75} aria-hidden />
            Delete
          </button>
        )}
      </header>

      <div className="max-w-3xl">
        {run.data?.error_message && (
          <p className="mb-3 rounded-lg border border-border border-l-2 border-l-danger bg-danger/10 px-3 py-2 font-mono text-xs text-danger">
            {run.data.error_code ? `${run.data.error_code}: ` : ""}
            {run.data.error_message}
          </p>
        )}

        {nodes.isLoading ? (
          <div className="space-y-1" aria-busy="true" aria-label="Loading node timeline">
            {[0, 1, 2, 3].map((i) => (
              <div key={i} className="rounded-lg border border-border bg-surface-1/60 px-2 py-2.5">
                <div className="h-3.5 w-full animate-pulse rounded bg-surface-2" />
              </div>
            ))}
          </div>
        ) : nodes.isError ? (
          <div className="rounded-lg border border-border border-l-2 border-l-danger bg-surface-1 p-4">
            <p className="flex items-center gap-2 text-sm text-danger">
              <AlertTriangle size={15} strokeWidth={1.75} aria-hidden />
              Could not load node timeline
            </p>
            <p className="mt-1 text-xs text-text-3">{(nodes.error as Error).message}</p>
            <Button variant="secondary" size="sm" className="mt-3" onClick={() => nodes.refetch()}>
              <RotateCw size={13} strokeWidth={1.75} aria-hidden />
              Retry
            </Button>
          </div>
        ) : (
          <RunDetailView nodes={nodes.data ?? []} runStatus={run.data?.status} />
        )}
      </div>
    </div>
  );
}
