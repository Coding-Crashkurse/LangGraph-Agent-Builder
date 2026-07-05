import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  Boxes,
  GitCommitHorizontal,
  Hammer,
  Plus,
  Trash2,
  Workflow,
} from "lucide-react";
import { useState, type MouseEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import type { Flow } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";

export function FlowsPage() {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const [createOpen, setCreateOpen] = useState(false);
  const [name, setName] = useState("");

  const flows = useQuery({ queryKey: ["flows"], queryFn: api.flows.list });

  const create = useMutation({
    mutationFn: () => api.flows.create({ name }),
    onSuccess: (flow) => {
      queryClient.invalidateQueries({ queryKey: ["flows"] });
      navigate(`/flows/${flow.id}`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.flows.delete(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["flows"] }),
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <div className="mx-auto max-w-6xl px-6 py-14">
      <header className="gf-animate-in mb-10 flex items-end justify-between">
        <div className="flex items-center gap-3.5">
          <div className="flex h-12 w-12 items-center justify-center rounded-2xl border border-accent-500/25 bg-gradient-to-br from-accent-500/25 via-accent-600/10 to-sky-500/15 shadow-lg shadow-accent-600/15">
            <Workflow className="h-5.5 w-5.5 text-accent-300" />
          </div>
          <div>
            <h1 className="bg-gradient-to-r from-white via-zinc-200 to-zinc-500 bg-clip-text text-2xl font-bold tracking-tight text-transparent">
              GraphForge
            </h1>
            <p className="mt-0.5 text-[13px] text-zinc-500">
              Visual LangGraph flows, published as A2A & MCP servers.
            </p>
          </div>
        </div>
        <Button onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" /> New flow
        </Button>
      </header>

      {flows.isLoading ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-44 animate-pulse rounded-xl border border-surface-800 bg-surface-900"
            />
          ))}
        </div>
      ) : flows.data?.length ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {flows.data.map((flow, index) => (
            <FlowCard
              key={flow.id}
              flow={flow}
              index={index}
              onOpen={() => navigate(`/flows/${flow.id}`)}
              onDebug={() => navigate(`/debug/${flow.id}`)}
              onDelete={() => {
                if (window.confirm(`Delete flow "${flow.name}"? This unpublishes it too.`)) {
                  remove.mutate(flow.id);
                }
              }}
            />
          ))}
        </div>
      ) : (
        <div className="gf-animate-in flex flex-col items-center rounded-2xl border border-dashed border-surface-700 bg-surface-900/40 py-20">
          <div className="flex h-14 w-14 items-center justify-center rounded-2xl border border-surface-700 bg-surface-850">
            <Workflow className="h-6 w-6 text-zinc-600" />
          </div>
          <p className="mt-4 text-sm text-zinc-400">No flows yet.</p>
          <p className="mt-1 text-xs text-zinc-600">
            Compose a graph, publish it, watch it run.
          </p>
          <Button className="mt-5" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" /> Create your first flow
          </Button>
        </div>
      )}

      <Dialog open={createOpen} onClose={() => setCreateOpen(false)} title="New flow">
        <Label>Flow name</Label>
        <Input
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Library RAG Agent"
          onKeyDown={(e) => {
            if (e.key === "Enter" && name.trim()) create.mutate();
          }}
        />
        <div className="mt-4 flex justify-end">
          <Button disabled={!name.trim() || create.isPending} onClick={() => create.mutate()}>
            Create
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

function FlowCard({
  flow,
  index,
  onOpen,
  onDebug,
  onDelete,
}: {
  flow: Flow;
  index: number;
  onOpen: () => void;
  onDebug: () => void;
  onDelete: () => void;
}) {
  const stop = (event: MouseEvent, action: () => void) => {
    event.stopPropagation();
    action();
  };

  return (
    <div
      onClick={onOpen}
      className="gf-card gf-animate-in group cursor-pointer p-5"
      style={{ animationDelay: `${Math.min(index, 8) * 45}ms` }}
    >
      <div className="flex items-start gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-accent-500/20 bg-gradient-to-br from-accent-500/20 to-sky-500/10 text-accent-300 transition-all duration-200 group-hover:border-accent-500/45 group-hover:text-accent-200 group-hover:shadow-md group-hover:shadow-accent-600/20">
          <Workflow className="h-4 w-4" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1.5">
            <span className="truncate text-sm font-semibold text-zinc-100 transition-colors group-hover:text-white">
              {flow.name}
            </span>
            <ArrowUpRight className="h-3.5 w-3.5 shrink-0 -translate-x-1 text-accent-300 opacity-0 transition-all duration-200 group-hover:translate-x-0 group-hover:opacity-100" />
          </div>
          <div className="mt-0.5 truncate font-mono text-[10px] text-zinc-600">{flow.slug}</div>
        </div>
        {flow.is_published ? <LiveBadge /> : <Badge color="zinc">draft</Badge>}
      </div>

      <p className="mt-3 line-clamp-2 min-h-8 text-xs leading-relaxed text-zinc-500">
        {flow.description || "No description yet."}
      </p>

      <div className="mt-4 flex items-center gap-3 border-t border-surface-800/80 pt-3.5">
        <span className="inline-flex items-center gap-1 font-mono text-[10px] text-zinc-500">
          <Boxes className="h-3 w-3" /> {flow.nodes.length} nodes
        </span>
        <span className="inline-flex items-center gap-1 font-mono text-[10px] text-zinc-500">
          <GitCommitHorizontal className="h-3 w-3" /> v{flow.version}
        </span>
        <div className="ml-auto flex items-center gap-1 opacity-70 transition-opacity duration-200 group-hover:opacity-100">
          <Button variant="secondary" size="sm" onClick={(e) => stop(e, onOpen)}>
            <Hammer className="h-3 w-3" /> Builder
          </Button>
          <Button variant="secondary" size="sm" onClick={(e) => stop(e, onDebug)}>
            <Activity className="h-3 w-3" /> Debug
          </Button>
          <Button
            variant="ghost"
            size="icon"
            aria-label={`delete ${flow.name}`}
            className="text-zinc-600 opacity-0 transition-all duration-200 hover:text-red-400 group-hover:opacity-100"
            onClick={(e) => stop(e, onDelete)}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>
    </div>
  );
}

function LiveBadge() {
  return (
    <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-800/50 bg-emerald-950/60 px-2 py-0.5 text-[11px] font-medium text-emerald-300">
      <span className="relative flex h-1.5 w-1.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
        <span className="relative inline-flex h-1.5 w-1.5 rounded-full bg-emerald-400" />
      </span>
      live
    </span>
  );
}
