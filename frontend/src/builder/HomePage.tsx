/**
 * Home dashboard: the builder's landing. Counts, quick actions, recent flows,
 * and an at-a-glance runtime status — so it is clear before publishing whether
 * the platform runtime is reachable.
 */

import { useQuery } from "@tanstack/react-query";
import {
  ArrowRight,
  Boxes,
  Database,
  Loader2,
  type LucideIcon,
  Plus,
  Plug,
  Workflow,
} from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api } from "@/api/client";
import type { ResourceGroup } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

import { NewFlowDialog } from "./NewFlowDialog";
import { ResourceDialog } from "./ResourceDialog";

function StatCard({
  to,
  icon: Icon,
  label,
  value,
}: {
  to: string;
  icon: LucideIcon;
  label: string;
  value: number | string;
}) {
  return (
    <Link
      to={to}
      className="group flex flex-col gap-3 rounded-xl border border-border bg-surface-1 p-4 transition-colors hover:border-border-strong"
    >
      <div className="flex items-center justify-between">
        <Icon size={17} strokeWidth={1.75} className="text-accent" />
        <ArrowRight
          size={14}
          className="text-text-3 opacity-0 transition-opacity group-hover:opacity-100"
        />
      </div>
      <div>
        <div className="text-2xl font-semibold tabular-nums text-text-1">{value}</div>
        <div className="text-xs text-text-3">{label}</div>
      </div>
    </Link>
  );
}

export function HomePage() {
  const [creatingFlow, setCreatingFlow] = useState(false);
  const [resourceGroup, setResourceGroup] = useState<ResourceGroup | null>(null);

  const flows = useQuery({ queryKey: ["flows"], queryFn: api.flows.list });
  const resources = useQuery({
    queryKey: ["resources"],
    queryFn: () => api.resources.list(),
    retry: false,
  });
  const health = useQuery({
    queryKey: ["runtime-health"],
    queryFn: api.runtime.health,
    retry: false,
  });

  const countOf = (group: ResourceGroup): number | string =>
    resources.data ? resources.data.filter((r) => r.group === group).length : "—";

  const recent = (flows.data ?? []).slice(0, 5);
  const runtimeDown = health.data && health.data.configured && !health.data.reachable;
  const noRuntime = health.data && !health.data.configured;

  return (
    <div className="mx-auto max-w-4xl px-8 py-8">
      <header className="mb-6">
        <h1 className="text-xl font-semibold text-text-1">Agent Builder</h1>
        <p className="mt-0.5 text-sm text-text-3">
          Design flows, manage models and knowledge bases, publish to the agentplane runtime.
        </p>
      </header>

      {(runtimeDown || noRuntime) && (
        <div className="mb-6 rounded-lg border border-border border-l-2 border-l-warning bg-surface-1 px-4 py-3 text-xs text-text-2">
          {noRuntime
            ? "No runtime configured — set BUILDER_RUNTIME_URL to publish flows and manage resources."
            : "The configured runtime is unreachable — publishing and resource management are unavailable until it responds."}
        </div>
      )}

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <StatCard to="/flows" icon={Workflow} label="Flows" value={flows.data?.length ?? "—"} />
        <StatCard to="/models" icon={Boxes} label="Models" value={countOf("model_provider")} />
        <StatCard
          to="/knowledge-bases"
          icon={Database}
          label="Knowledge Bases"
          value={countOf("vector_db")}
        />
      </div>

      <section className="mt-8">
        <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-text-3">
          Quick actions
        </h2>
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={() => setCreatingFlow(true)}>
            <Plus size={13} /> New flow
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setResourceGroup("model_provider")}>
            <Boxes size={13} /> New model
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setResourceGroup("vector_db")}>
            <Database size={13} /> New knowledge base
          </Button>
          <Button size="sm" variant="secondary" onClick={() => setResourceGroup("mcp_server")}>
            <Plug size={13} /> New tool
          </Button>
        </div>
      </section>

      <section className="mt-8">
        <div className="mb-2 flex items-center justify-between">
          <h2 className="text-xs font-semibold uppercase tracking-wide text-text-3">
            Recent flows
          </h2>
          <Link to="/flows" className="text-xs text-accent hover:underline">
            All flows
          </Link>
        </div>
        {flows.isPending && (
          <div className="flex items-center gap-2 text-sm text-text-3">
            <Loader2 size={14} className="animate-spin" /> Loading…
          </div>
        )}
        <div className="flex flex-col gap-2">
          {recent.map((flow) => (
            <Link
              key={flow.name}
              to={`/flows/${flow.name}`}
              className="group flex items-center gap-3 rounded-xl border border-border bg-surface-1 p-3 transition-colors hover:border-border-strong"
            >
              <Workflow size={16} className="shrink-0 text-accent" strokeWidth={1.75} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="truncate text-sm font-semibold text-text-1">
                    {flow.display_name || flow.name}
                  </span>
                  <Badge tone={flow.expose_kind === "mcp" ? "accent" : "muted"}>
                    {flow.expose_kind}
                  </Badge>
                </div>
                <p className="mt-0.5 truncate text-xs text-text-3">
                  <span className="font-mono">{flow.name}</span>
                  {flow.description ? ` — ${flow.description}` : ""}
                </p>
              </div>
              <ArrowRight
                size={14}
                className="shrink-0 text-text-3 opacity-0 transition-opacity group-hover:opacity-100"
              />
            </Link>
          ))}
          {flows.data?.length === 0 && (
            <div className="rounded-xl border border-dashed border-border p-8 text-center text-sm text-text-3">
              No flows yet — create your first one.
            </div>
          )}
        </div>
      </section>

      <NewFlowDialog open={creatingFlow} onClose={() => setCreatingFlow(false)} />
      <ResourceDialog
        open={resourceGroup !== null}
        group={resourceGroup}
        onClose={() => setResourceGroup(null)}
        onCreated={() => {
          void resources.refetch();
          setResourceGroup(null);
        }}
      />
    </div>
  );
}
