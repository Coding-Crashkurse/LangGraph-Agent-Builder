/** Flow list: create / import / open / delete + run history glance. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
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

export function FlowsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");

  const flows = useQuery({ queryKey: ["flows"], queryFn: api.flows.list });
  const runs = useQuery({ queryKey: ["runs"], queryFn: () => api.runs.list() });

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

  return (
    <div className="min-h-screen bg-surface-950 px-8 py-6 text-zinc-100">
      <header className="mb-6 flex items-center gap-3">
        <h1 className="text-lg font-bold">lga</h1>
        <span className="text-xs text-zinc-500">
          flows compile to LangGraph · publish = A2A agent + MCP tool
        </span>
        <div className="ml-auto flex items-center gap-2">
          <Link to="/settings" className="text-sm text-zinc-400 hover:text-zinc-100">
            Settings
          </Link>
          <label className="cursor-pointer text-sm text-zinc-400 hover:text-zinc-100">
            Import
            <input
              type="file"
              accept=".json"
              className="hidden"
              onChange={(e) => e.target.files?.[0] && importFlow(e.target.files[0])}
            />
          </label>
          <Button onClick={() => setCreateOpen(true)}>New flow</Button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {(flows.data ?? []).map((flow) => (
          <div
            key={flow.id}
            className="group rounded-lg border border-surface-800 bg-surface-900 p-4 hover:border-accent-700"
          >
            <div className="flex items-center gap-2">
              <Link
                to={`/flows/${flow.id}`}
                className="text-sm font-semibold text-zinc-100 hover:text-accent-300"
              >
                {flow.name}
              </Link>
              {flow.published_version ? (
                <Badge tone="green">v{flow.published_version}</Badge>
              ) : (
                <Badge tone="muted">draft</Badge>
              )}
              {flow.spec.flow.a2a?.enabled && <Badge tone="violet">A2A</Badge>}
              {flow.spec.flow.mcp?.enabled && <Badge tone="sky">MCP</Badge>}
              <button
                className="ml-auto text-xs text-zinc-600 opacity-0 hover:text-red-400 group-hover:opacity-100"
                onClick={() => {
                  if (window.confirm(`Delete flow "${flow.name}"?`)) deleteFlow.mutate(flow.id);
                }}
              >
                delete
              </button>
            </div>
            <p className="mt-1 line-clamp-2 text-xs text-zinc-500">
              {flow.description || "no description"}
            </p>
            <p className="mt-2 font-mono text-[10px] text-zinc-600">
              /{flow.slug} · {flow.spec.nodes.length} nodes
            </p>
          </div>
        ))}
        {flows.data?.length === 0 && (
          <p className="text-sm text-zinc-500">No flows yet — create or import one.</p>
        )}
      </div>

      <h2 className="mb-2 mt-8 text-xs font-semibold uppercase tracking-widest text-zinc-500">
        Recent runs
      </h2>
      <div className="overflow-hidden rounded-lg border border-surface-800">
        <table className="w-full text-left text-xs">
          <thead className="bg-surface-900 text-zinc-500">
            <tr>
              <th className="px-3 py-2">run</th>
              <th className="px-3 py-2">flow</th>
              <th className="px-3 py-2">mode</th>
              <th className="px-3 py-2">status</th>
              <th className="px-3 py-2">result</th>
              <th className="px-3 py-2">started</th>
            </tr>
          </thead>
          <tbody>
            {(runs.data ?? []).slice(0, 25).map((run) => (
              <tr key={run.run_id} className="border-t border-surface-800 text-zinc-300">
                <td className="px-3 py-1.5 font-mono text-[10px]">{run.run_id.slice(0, 12)}…</td>
                <td className="px-3 py-1.5">{run.flow_slug}</td>
                <td className="px-3 py-1.5">{run.mode}</td>
                <td className="px-3 py-1.5">
                  <StatusChip status={run.status} />
                </td>
                <td className="max-w-[280px] truncate px-3 py-1.5 text-zinc-500">
                  {run.error_message ?? run.result_preview}
                </td>
                <td className="px-3 py-1.5 text-zinc-500">
                  {new Date(run.started_at).toLocaleTimeString()}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New flow">
        <div className="space-y-3">
          <Input
            value={name}
            placeholder="Flow name"
            onChange={(e) => setName(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && name.trim() && createFlow.mutate()}
          />
          <p className="text-xs text-zinc-500">slug: /{slugify(name || "flow")}</p>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setCreateOpen(false)}>
              Cancel
            </Button>
            <Button onClick={() => createFlow.mutate()} disabled={!name.trim()}>
              Create
            </Button>
          </div>
        </div>
      </Dialog>
    </div>
  );
}

export function StatusChip({ status }: { status: string }) {
  const tones: Record<string, string> = {
    completed: "bg-emerald-900/60 text-emerald-300",
    running: "bg-sky-900/60 text-sky-300",
    pending: "bg-zinc-800 text-zinc-400",
    input_required: "bg-amber-900/60 text-amber-300",
    failed: "bg-red-900/60 text-red-300",
    cancelled: "bg-zinc-800 text-zinc-500",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-[10px] font-medium ${tones[status] ?? ""}`}>
      {status}
    </span>
  );
}
