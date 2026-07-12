/**
 * Flows list: builder-local drafts. New flows start as start+end
 * FlowDefinitions; import accepts canonical YAML/JSON files.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Loader2, Plus, Trash2, Workflow } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import type { FlowSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";

import { emptyDefinition } from "./convert";

const NAME_RE = /^[a-z0-9][a-z0-9-]{1,62}$/;

function NewFlowDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const valid = NAME_RE.test(name);
  const create = useMutation({
    mutationFn: () => api.flows.create(emptyDefinition(name)),
    onSuccess: async (flow) => {
      await queryClient.invalidateQueries({ queryKey: ["flows"] });
      navigate(`/flows/${flow.name}`);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "create failed"),
  });
  return (
    <Dialog open={open} onClose={onClose} title="New flow">
      <Label hint="^[a-z0-9][a-z0-9-]{1,62}$">Name</Label>
      <Input
        autoFocus
        value={name}
        placeholder="support-rag"
        className="font-mono"
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && valid) create.mutate();
        }}
      />
      <p className="mt-1 text-[11px] text-text-3">
        The name is the platform-wide identity of the flow (unique per owner).
      </p>
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button size="sm" disabled={!valid || create.isPending} onClick={() => create.mutate()}>
          {create.isPending && <Loader2 size={13} className="animate-spin" />} Create
        </Button>
      </div>
    </Dialog>
  );
}

function FlowCard({ flow, onDelete }: { flow: FlowSummary; onDelete: () => void }) {
  return (
    <div className="group flex items-center gap-3 rounded-xl border border-border bg-surface-1 p-3 transition-colors hover:border-border-strong">
      <Workflow size={16} className="shrink-0 text-accent" strokeWidth={1.75} />
      <Link to={`/flows/${flow.name}`} className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold text-text-1">
            {flow.display_name || flow.name}
          </span>
          <Badge tone={flow.expose_kind === "mcp" ? "toolset" : "accent"}>
            {flow.expose_kind}
          </Badge>
        </div>
        <p className="mt-0.5 truncate text-xs text-text-3">
          <span className="font-mono">{flow.name}</span>
          {flow.description ? ` — ${flow.description}` : ""}
        </p>
      </Link>
      <Button
        size="icon"
        variant="ghost"
        aria-label={`Delete ${flow.name}`}
        className="opacity-0 transition-opacity group-hover:opacity-100"
        onClick={onDelete}
      >
        <Trash2 size={14} />
      </Button>
    </div>
  );
}

export function FlowsPage() {
  const [creating, setCreating] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const flows = useQuery({ queryKey: ["flows"], queryFn: api.flows.list });
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.get });

  const importFile = async (file: File) => {
    try {
      const result = await api.flows.import(await file.text());
      await queryClient.invalidateQueries({ queryKey: ["flows"] });
      toast.success(`Imported ${result.name}`);
      navigate(`/flows/${result.name}`);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) {
        toast.error(`${err.message} — delete the existing flow first or rename in the file`);
      } else {
        toast.error(err instanceof Error ? err.message : "import failed");
      }
    }
  };

  const remove = async (name: string) => {
    try {
      await api.flows.delete(name);
      await queryClient.invalidateQueries({ queryKey: ["flows"] });
      toast.info(`Deleted ${name}`);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "delete failed");
    } finally {
      setPendingDelete(null);
    }
  };

  return (
    <div className="mx-auto flex h-screen max-w-3xl flex-col px-6 py-8">
      <header className="mb-6 flex items-center gap-3">
        <div>
          <h1 className="text-lg font-semibold text-text-1">Flows</h1>
          <p className="text-xs text-text-3">
            Design-time drafts — published flows are served by the agentplane runtime
            {config.data && !config.data.runtime_configured && " (no runtime configured)"}
          </p>
        </div>
        <span className="ml-auto flex items-center gap-2">
          <input
            ref={fileInput}
            type="file"
            accept=".yaml,.yml,.json"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void importFile(file);
              e.target.value = "";
            }}
          />
          <Button size="sm" variant="secondary" onClick={() => fileInput.current?.click()}>
            <FileUp size={13} /> Import
          </Button>
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus size={13} /> New flow
          </Button>
        </span>
      </header>

      {flows.isPending && (
        <div className="flex items-center gap-2 text-sm text-text-3">
          <Loader2 size={14} className="animate-spin" /> Loading…
        </div>
      )}
      {flows.isError && (
        <p className="text-sm text-danger">Could not load flows: {String(flows.error)}</p>
      )}
      <div className="flex flex-col gap-2 overflow-y-auto">
        {(flows.data ?? []).map((flow) => (
          <FlowCard key={flow.name} flow={flow} onDelete={() => setPendingDelete(flow.name)} />
        ))}
        {flows.data?.length === 0 && (
          <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-text-3">
            No flows yet — create one or import a <span className="font-mono">.flow.yaml</span>.
          </div>
        )}
      </div>

      <NewFlowDialog open={creating} onClose={() => setCreating(false)} />
      <Dialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title={`Delete ${pendingDelete}?`}
      >
        <p className="text-xs text-text-2">
          Deletes the builder-local draft only. Anything already published keeps running on the
          runtime.
        </p>
        <div className="mt-3 flex justify-end gap-2">
          <Button size="sm" variant="ghost" onClick={() => setPendingDelete(null)}>
            Cancel
          </Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => pendingDelete && void remove(pendingDelete)}
          >
            Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
