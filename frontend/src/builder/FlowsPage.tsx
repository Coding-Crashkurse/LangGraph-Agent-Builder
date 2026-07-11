/** Flow list: create / import / open / delete + run history glance. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  Boxes,
  Plus,
  RotateCw,
  Settings as SettingsIcon,
  Trash2,
  Upload,
  Workflow,
} from "lucide-react";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";

import { emptyFlowSpec } from "./convert";

function slugify(name: string): string {
  return name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "flow";
}

function timeAgo(iso: string): string {
  const seconds = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

interface Template {
  id: string;
  name: string;
  description: string;
}

export function FlowsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");
  const [deleteTarget, setDeleteTarget] = useState<{ id: string; name: string } | null>(null);

  const flows = useQuery({ queryKey: ["flows"], queryFn: api.flows.list });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.runs.list() });
  const templates = useQuery({
    queryKey: ["templates"],
    queryFn: async (): Promise<Template[]> => {
      const r = await fetch("/api/v1/templates");
      return r.ok ? r.json() : [];
    },
  });

  const fromTemplate = useMutation({
    mutationFn: async (templateId: string) => {
      const r = await fetch(`/api/v1/flows/from-template/${templateId}`, { method: "POST" });
      if (!r.ok) throw new Error(await r.text());
      return r.json();
    },
    onSuccess: (flow: { id: string }) => {
      queryClient.invalidateQueries({ queryKey: ["flows"] });
      navigate(`/flows/${flow.id}`);
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const createFlow = useMutation({
    mutationFn: () => api.flows.create(emptyFlowSpec(name, slugify(name))),
    onSuccess: (flow) => {
      queryClient.invalidateQueries({ queryKey: ["flows"] });
      navigate(`/flows/${flow.id}`);
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const deleteFlow = useMutation({
    mutationFn: (id: string) => api.flows.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["flows"] }),
    onError: (error) => toast.error((error as Error).message),
  });

  const deleteRun = useMutation({
    mutationFn: (runId: string) => api.runs.delete(runId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["runs"] }),
    onError: (error) => toast.error((error as Error).message),
  });

  const clearRuns = useMutation({
    mutationFn: () => api.runs.clearFinished(),
    onSuccess: ({ deleted }) => {
      queryClient.invalidateQueries({ queryKey: ["runs"] });
      toast.success(`${deleted} trace(s) deleted`);
    },
    onError: (error) => toast.error((error as Error).message),
  });

  const importFlow = async (file: File) => {
    try {
      const spec = JSON.parse(await file.text());
      const flow = await api.flows.create(spec);
      queryClient.invalidateQueries({ queryKey: ["flows"] });
      navigate(`/flows/${flow.id}`);
    } catch (error) {
      toast.error(`import failed: ${(error as Error).message}`);
    }
  };

  const flowList = flows.data ?? [];
  const templateList = templates.data ?? [];

  return (
    <div className="min-h-screen bg-canvas px-8 py-6 text-text-1">
      <header className="mb-6 flex items-center gap-3">
        <h1 className="text-lg font-bold">LangGraph Agent Builder</h1>
        <span className="text-xs text-text-3">
          flows compile to LangGraph · publish = A2A agent + MCP tool
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Link
            to="/resources"
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-text-2 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
          >
            <Boxes size={14} strokeWidth={1.75} aria-hidden />
            Resources
          </Link>
          <Link
            to="/settings"
            className="inline-flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-text-2 hover:bg-surface-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
          >
            <SettingsIcon size={14} strokeWidth={1.75} aria-hidden />
            Settings
          </Link>
          <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-text-2 hover:bg-surface-2 hover:text-text-1 focus-within:outline-2 focus-within:outline-offset-1 focus-within:outline-accent">
            <Upload size={14} strokeWidth={1.75} aria-hidden />
            Import
            <input
              type="file"
              accept=".json"
              className="sr-only"
              onChange={(e) => e.target.files?.[0] && importFlow(e.target.files[0])}
            />
          </label>
          <Button onClick={() => setCreateOpen(true)}>
            <Plus size={14} strokeWidth={1.75} aria-hidden />
            New flow
          </Button>
        </div>
      </header>

      {flowList.length > 0 && templateList.length > 0 && (
        <div className="mb-6">
          <h2 className="mb-2 text-[11px] font-semibold uppercase tracking-widest text-text-3">
            Start from a template
          </h2>
          <div className="flex flex-wrap gap-2">
            {templateList.map((t) => (
              <TemplateCard
                key={t.id}
                template={t}
                disabled={fromTemplate.isPending}
                onPick={() => fromTemplate.mutate(t.id)}
              />
            ))}
          </div>
        </div>
      )}

      {flows.isLoading ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div key={i} className="rounded-xl border border-border bg-surface-1 p-4">
              <div className="h-4 w-2/5 animate-pulse rounded bg-surface-2" />
              <div className="mt-3 h-3 w-4/5 animate-pulse rounded bg-surface-2" />
              <div className="mt-3 h-3 w-1/3 animate-pulse rounded bg-surface-2" />
            </div>
          ))}
        </div>
      ) : flows.isError ? (
        <div className="max-w-xl rounded-lg border border-border border-l-2 border-l-danger bg-surface-1 p-4">
          <p className="flex items-center gap-2 text-sm text-danger">
            <AlertTriangle size={15} strokeWidth={1.75} aria-hidden />
            Could not load flows
          </p>
          <p className="mt-1 text-xs text-text-3">{(flows.error as Error).message}</p>
          <Button variant="secondary" size="sm" className="mt-3" onClick={() => flows.refetch()}>
            <RotateCw size={13} strokeWidth={1.75} aria-hidden />
            Retry
          </Button>
        </div>
      ) : flowList.length === 0 ? (
        <div className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-border px-6 py-16 text-center">
          <Workflow size={24} strokeWidth={1.75} className="text-text-3" aria-hidden />
          <p className="text-[13px] text-text-2">No flows yet</p>
          <p className="text-xs text-text-3">
            Build a graph on the canvas, then publish it as an A2A agent or MCP tool.
          </p>
          <Button className="mt-2" onClick={() => setCreateOpen(true)}>
            <Plus size={14} strokeWidth={1.75} aria-hidden />
            New flow
          </Button>
          {templateList.length > 0 && (
            <>
              <p className="mt-6 text-[11px] font-semibold uppercase tracking-widest text-text-3">
                or start from a template
              </p>
              <div className="mt-1 flex flex-wrap justify-center gap-2">
                {templateList.map((t) => (
                  <TemplateCard
                    key={t.id}
                    template={t}
                    disabled={fromTemplate.isPending}
                    onPick={() => fromTemplate.mutate(t.id)}
                  />
                ))}
              </div>
            </>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
          {flowList.map((flow) => (
            <div key={flow.id} className="gf-card group p-4">
              <div className="flex items-center gap-2">
                <Link
                  to={`/flows/${flow.id}`}
                  className="truncate rounded text-sm font-semibold text-text-1 hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
                >
                  {flow.name}
                </Link>
                {flow.spec.flow.a2a?.enabled && <Badge tone="accent">A2A</Badge>}
                {flow.spec.flow.mcp?.enabled && <Badge tone="toolset">MCP</Badge>}
                <button
                  type="button"
                  aria-label={`Delete flow ${flow.name}`}
                  className="ml-auto rounded p-1 text-text-3 opacity-0 hover:text-danger focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-accent group-focus-within:opacity-100 group-hover:opacity-100"
                  onClick={() => setDeleteTarget({ id: flow.id, name: flow.name })}
                >
                  <Trash2 size={14} strokeWidth={1.75} aria-hidden />
                </button>
              </div>
              <p className="mt-1 line-clamp-2 text-xs text-text-3">
                {flow.description || "no description"}
              </p>
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] text-text-3">/{flow.slug}</span>
                {flow.published_version ? (
                  <Badge tone="success">v{flow.published_version}</Badge>
                ) : (
                  <Badge tone="muted">draft</Badge>
                )}
                <span className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10.5px] tabular-nums text-text-3">
                  {flow.spec.nodes.length} nodes
                </span>
                <span
                  className="rounded-md bg-surface-2 px-1.5 py-0.5 text-[10.5px] tabular-nums text-text-3"
                  title={new Date(flow.updated_at).toLocaleString()}
                >
                  updated {timeAgo(flow.updated_at)}
                </span>
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="mb-2 mt-8 flex items-center">
        <h2 className="text-[11px] font-semibold uppercase tracking-widest text-text-3">
          Recent runs
        </h2>
        {(runs.data ?? []).length > 0 && (
          <button
            type="button"
            className="ml-auto rounded text-[11px] text-text-3 hover:text-danger focus-visible:outline-2 focus-visible:outline-accent"
            onClick={() => clearRuns.mutate()}
            title="Delete all finished traces (running ones stay)"
          >
            clear finished
          </button>
        )}
      </div>
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-1">
            <tr className="text-[11px] uppercase tracking-wide text-text-3">
              <th className="px-3 py-2 font-medium">run</th>
              <th className="px-3 py-2 font-medium">flow</th>
              <th className="px-3 py-2 font-medium">mode</th>
              <th className="px-3 py-2 font-medium">status</th>
              <th className="px-3 py-2 font-medium">result</th>
              <th className="px-3 py-2 font-medium">started</th>
              <th className="w-8 px-2 py-2" />
            </tr>
          </thead>
          <tbody>
            {runs.isLoading &&
              [0, 1, 2].map((i) => (
                <tr key={i} className="border-t border-border">
                  <td colSpan={7} className="px-3 py-2">
                    <div className="h-3.5 w-full animate-pulse rounded bg-surface-2" />
                  </td>
                </tr>
              ))}
            {!runs.isLoading && (runs.data ?? []).length === 0 && (
              <tr className="border-t border-border">
                <td colSpan={7} className="px-3 py-4 text-center text-xs text-text-3">
                  No runs yet — open a flow and try it in the playground.
                </td>
              </tr>
            )}
            {(runs.data ?? []).slice(0, 25).map((run) => (
              <tr
                key={run.run_id}
                className="group border-t border-border text-text-2 hover:bg-surface-2"
              >
                <td className="px-3 py-1.5 font-mono text-[10.5px]">
                  <Link
                    to={`/runs/${run.run_id}`}
                    title="Inspect this run node-by-node"
                    className="rounded text-text-2 hover:text-accent focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
                  >
                    {run.run_id.slice(0, 12)}…
                  </Link>
                </td>
                <td className="px-3 py-1.5">{run.flow_slug}</td>
                <td className="px-3 py-1.5">{run.mode}</td>
                <td className="px-3 py-1.5">
                  <StatusChip status={run.status} />
                </td>
                <td className="max-w-[280px] truncate px-3 py-1.5 text-text-3">
                  {run.error_message ?? run.result_preview}
                </td>
                <td className="px-3 py-1.5 tabular-nums text-text-3">
                  {new Date(run.started_at).toLocaleTimeString()}
                </td>
                <td className="px-2 py-1.5 text-right">
                  {run.status !== "running" && run.status !== "pending" && (
                    <button
                      type="button"
                      title="Delete this trace"
                      aria-label="Delete this trace"
                      className="rounded p-0.5 text-text-3 opacity-0 hover:text-danger focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-accent group-hover:opacity-100"
                      onClick={() => deleteRun.mutate(run.run_id)}
                    >
                      <Trash2 size={13} strokeWidth={1.75} aria-hidden />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog
        open={deleteTarget !== null}
        onClose={() => setDeleteTarget(null)}
        title="Delete flow"
      >
        <div className="space-y-4">
          <p className="text-sm text-text-2">
            Delete <span className="font-semibold text-text-1">{deleteTarget?.name}</span>?
          </p>
          <p className="text-xs text-text-3">
            This removes the draft, all published versions and unmounts its A2A/MCP
            endpoints. Runs and task history stay in the dashboard.
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setDeleteTarget(null)}>
              Cancel
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (deleteTarget) deleteFlow.mutate(deleteTarget.id);
                setDeleteTarget(null);
              }}
            >
              <Trash2 size={14} strokeWidth={1.75} aria-hidden />
              Delete flow
            </Button>
          </div>
        </div>
      </Dialog>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New flow">
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs font-medium text-text-2">Name</span>
            <Input
              autoFocus
              value={name}
              placeholder="e.g. Support triage"
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && name.trim() && createFlow.mutate()}
            />
          </label>
          <p className="text-[11px] text-text-3">
            slug: <span className="font-mono text-text-2">/{slugify(name || "flow")}</span> — the
            A2A/MCP mount path once published
          </p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => createFlow.mutate()}
              disabled={!name.trim() || createFlow.isPending}
            >
              {createFlow.isPending ? "Creating…" : "Create"}
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

function TemplateCard({
  template,
  disabled,
  onPick,
}: {
  template: Template;
  disabled: boolean;
  onPick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onPick}
      title={template.description}
      className="gf-card px-3 py-2 text-left hover:border-accent focus-visible:outline-2 focus-visible:outline-accent disabled:opacity-45"
    >
      <span className="block text-sm font-medium text-text-1">{template.name}</span>
      <span className="line-clamp-1 block max-w-[220px] text-[11px] text-text-3">
        {template.description}
      </span>
    </button>
  );
}

export function StatusChip({ status }: { status: string }) {
  const tones: Record<string, string> = {
    completed: "bg-success/15 text-success",
    running: "bg-port-toolset/15 text-port-toolset",
    pending: "bg-surface-2 text-text-2",
    input_required: "bg-warning/15 text-warning",
    failed: "bg-danger/15 text-danger",
    cancelled: "bg-surface-2 text-text-3",
  };
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10.5px] font-medium tabular-nums ${tones[status] ?? ""}`}
    >
      {status}
    </span>
  );
}
