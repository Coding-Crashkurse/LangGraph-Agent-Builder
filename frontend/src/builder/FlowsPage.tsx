/**
 * Flows list: builder-local drafts. New flows start as start+end
 * FlowDefinitions; import accepts canonical YAML/JSON files. Rendered inside
 * the app shell — the flow canvas itself lives at /flows/:name, full-screen.
 */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FileUp, Loader2, Plus, Trash2, Workflow } from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import type { FlowSummary } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { toast } from "@/components/ui/toast";

import { NewFlowDialog } from "./NewFlowDialog";

function FlowCard({ flow, onDelete }: { flow: FlowSummary; onDelete: () => void }) {
  return (
    <div className="group flex items-center gap-3 rounded-xl border border-border bg-surface-1 p-3 transition-colors hover:border-border-strong">
      <Workflow size={16} className="shrink-0 text-accent" strokeWidth={1.75} />
      <Link to={`/flows/${flow.name}`} className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-semibold text-text-1">
            {flow.display_name || flow.name}
          </span>
          <Badge tone={flow.expose_kind === "mcp" ? "accent" : "muted"}>{flow.expose_kind}</Badge>
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
  const [alsoUndeploy, setAlsoUndeploy] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const flows = useQuery({ queryKey: ["flows"], queryFn: api.flows.list });

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
      await api.flows.delete(name, { undeploy: alsoUndeploy });
      await queryClient.invalidateQueries({ queryKey: ["flows"] });
      toast.info(
        alsoUndeploy ? `Deleted ${name} and removed it from the platform` : `Deleted ${name}`,
      );
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "delete failed");
    } finally {
      setPendingDelete(null);
      setAlsoUndeploy(false);
    }
  };

  return (
    <div className="mx-auto max-w-3xl px-8 py-8">
      <header className="mb-6 flex items-center gap-3">
        <div>
          <h1 className="text-lg font-semibold text-text-1">Flows</h1>
          <p className="text-xs text-text-3">
            Design-time drafts — published flows are served by the agentplane runtime
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
      <div className="flex flex-col gap-2">
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
        onClose={() => {
          setPendingDelete(null);
          setAlsoUndeploy(false);
        }}
        title={`Delete ${pendingDelete}?`}
      >
        <p className="rounded border border-border border-l-2 border-l-warning bg-surface-1 px-2 py-1.5 text-xs text-text-1">
          This deletes the <strong>builder draft only</strong>. If the flow was published, the
          agent keeps running on the platform and stays listed in the registry.
        </p>
        <label className="mt-3 flex items-start gap-2 text-xs text-text-2">
          <input
            type="checkbox"
            className="mt-0.5"
            checked={alsoUndeploy}
            onChange={(event) => setAlsoUndeploy(event.target.checked)}
          />
          <span>
            Also remove it from the platform: undeploy the agent (drops the registry entry) and
            delete the runtime definition.
          </span>
        </label>
        <div className="mt-3 flex justify-end gap-2">
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              setPendingDelete(null);
              setAlsoUndeploy(false);
            }}
          >
            Cancel
          </Button>
          <Button
            size="sm"
            variant="danger"
            onClick={() => pendingDelete && void remove(pendingDelete)}
          >
            {alsoUndeploy ? "Delete draft + undeploy" : "Delete draft"}
          </Button>
        </div>
      </Dialog>
    </div>
  );
}
