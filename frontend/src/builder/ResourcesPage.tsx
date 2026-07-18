/**
 * Resource manager — one page per resource group (Models, Knowledge Bases,
 * Tools). Resources live on the platform runtime; this lists them and proxies
 * create/delete. Reachable standalone now, not only from inside a node config.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Boxes, Database, Loader2, type LucideIcon, Plug, Plus, Trash2 } from "lucide-react";
import { useState } from "react";

import { api, ApiError } from "@/api/client";
import type { ResourceGroup, ResourceSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";

import { ResourceDialog } from "./ResourceDialog";

interface GroupMeta {
  title: string;
  subtitle: string;
  newLabel: string;
  icon: LucideIcon;
  empty: string;
}

const META: Record<ResourceGroup, GroupMeta> = {
  model_provider: {
    title: "Models",
    subtitle: "OpenAI-compatible model providers used by LLM and embedding nodes.",
    newLabel: "New model",
    icon: Boxes,
    empty: "No model providers yet.",
  },
  vector_db: {
    title: "Knowledge Bases",
    subtitle: "Vector DBs (Qdrant / pgvector) consumed read-only by retrieval nodes.",
    newLabel: "New knowledge base",
    icon: Database,
    empty: "No knowledge bases yet.",
  },
  mcp_server: {
    title: "Tools",
    subtitle: "MCP servers whose tools flows can call.",
    newLabel: "New tool",
    icon: Plug,
    empty: "No MCP servers yet.",
  },
};

function ResourceCard({
  resource,
  onDelete,
}: {
  resource: ResourceSummary;
  onDelete: () => void;
}) {
  return (
    <div className="group flex items-center gap-3 rounded-xl border border-border bg-surface-1 p-3 transition-colors hover:border-border-strong">
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold text-text-1">
            {resource.display_name || resource.name}
          </span>
          <Badge tone="muted">{resource.kind}</Badge>
        </div>
        <p className="mt-0.5 truncate font-mono text-xs text-text-3">{resource.name}</p>
      </div>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Delete ${resource.name}`}
        className="opacity-0 transition-opacity group-hover:opacity-100"
        onClick={onDelete}
      >
        <Trash2 size={14} />
      </Button>
    </div>
  );
}

export function ResourcesPage({ group }: { group: ResourceGroup }) {
  const meta = META[group];
  const Icon = meta.icon;
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const queryClient = useQueryClient();

  const resources = useQuery({
    queryKey: ["resources", group],
    queryFn: () => api.resources.list(group),
    retry: false,
  });

  const invalidate = () =>
    queryClient.invalidateQueries({
      predicate: (q) => q.queryKey[0] === "resources",
    });

  const remove = useMutation({
    mutationFn: (name: string) => api.resources.delete(name),
    onSuccess: async (_data, name) => {
      await invalidate();
      toast.info(`Deleted ${name}`);
      setPendingDelete(null);
    },
    onError: (err) => {
      toast.error(err instanceof Error ? err.message : "delete failed");
      setPendingDelete(null);
    },
  });

  const unreachable = resources.error instanceof ApiError && resources.error.status === 503;

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <header className="mb-6 flex items-center gap-3">
        <Icon size={20} strokeWidth={1.75} className="shrink-0 text-accent" />
        <div className="min-w-0">
          <h1 className="text-lg font-semibold text-text-1">{meta.title}</h1>
          <p className="text-xs text-text-3">{meta.subtitle}</p>
        </div>
        <Button size="sm" className="ml-auto" onClick={() => setCreating(true)}>
          <Plus size={13} /> {meta.newLabel}
        </Button>
      </header>

      {resources.isPending && (
        <div className="flex items-center gap-2 text-sm text-text-3">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      )}

      {resources.isError && (
        <div className="rounded-xl border border-border border-l-2 border-l-warning bg-surface-1 p-4 text-sm text-text-2">
          {unreachable
            ? "The platform runtime is unreachable — resources live there and cannot be listed right now."
            : `Could not load resources: ${String(resources.error)}`}
        </div>
      )}

      {resources.data && (
        <div className="flex flex-col gap-2">
          {resources.data.map((resource) => (
            <ResourceCard
              key={resource.name}
              resource={resource}
              onDelete={() => setPendingDelete(resource.name)}
            />
          ))}
          {resources.data.length === 0 && (
            <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-text-3">
              {meta.empty}
            </div>
          )}
        </div>
      )}

      <ResourceDialog
        open={creating}
        group={group}
        onClose={() => setCreating(false)}
        onCreated={() => {
          void invalidate();
          setCreating(false);
        }}
      />
      <Dialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title={`Delete ${pendingDelete}?`}
      >
        <p className="text-xs text-text-2">
          Deletes the resource on the runtime. The runtime refuses deletion while a flow still
          references it.
        </p>
        <div className="mt-3 flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setPendingDelete(null)}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="danger"
            disabled={remove.isPending}
            onClick={() => pendingDelete && remove.mutate(pendingDelete)}
          >
            {remove.isPending && <Loader2 size={13} className="animate-spin" />} Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
