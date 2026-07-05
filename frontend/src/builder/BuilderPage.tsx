import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Background,
  BackgroundVariant,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import { Activity, ArrowLeft, CheckCircle2, Rocket, Save, ShieldCheck } from "lucide-react";
import { useCallback, useEffect, useState, type DragEvent } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/client";
import type { ComponentInfo } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";
import { ConfigPanel } from "./ConfigPanel";
import { canvasToSpec } from "./convert";
import { edgeTypes, nodeTypes } from "./nodes";
import { Palette } from "./Palette";
import { PublishDialog } from "./PublishDialog";
import { useBuilder } from "./store";

export function BuilderPage() {
  return (
    <ReactFlowProvider>
      <BuilderInner />
    </ReactFlowProvider>
  );
}

function BuilderInner() {
  const { flowId = "" } = useParams();
  const queryClient = useQueryClient();
  const { screenToFlowPosition } = useReactFlow();

  const flowQuery = useQuery({
    queryKey: ["flow", flowId],
    queryFn: () => api.flows.get(flowId),
  });
  const componentsQuery = useQuery({ queryKey: ["components"], queryFn: api.components });

  const builder = useBuilder();
  const [meta, setMeta] = useState({ name: "", description: "" });
  const [publishOpen, setPublishOpen] = useState(false);

  // initialize the canvas once per flow id (not on every refetch)
  useEffect(() => {
    if (flowQuery.data && componentsQuery.data && builder.flow?.id !== flowId) {
      builder.init(flowQuery.data, componentsQuery.data);
      setMeta({ name: flowQuery.data.name, description: flowQuery.data.description });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [flowQuery.data, componentsQuery.data, flowId]);

  const save = useMutation({
    mutationFn: async () => {
      const { nodes, edges } = canvasToSpec(builder.nodes, builder.edges);
      return api.flows.save(flowId, { ...meta, nodes, edges });
    },
    onSuccess: (saved) => {
      builder.markSaved(saved);
      builder.setIssues(saved.issues ?? []);
      queryClient.setQueryData(["flow", flowId], saved);
      toast.success(`Saved v${saved.version}`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const validate = useMutation({
    mutationFn: async () => {
      const { nodes, edges } = canvasToSpec(builder.nodes, builder.edges);
      return api.flows.validate(flowId, { nodes, edges });
    },
    onSuccess: (report) => {
      builder.setIssues(report.issues);
      if (report.valid) toast.success("Flow is valid");
      else toast.error(`${report.issues.filter((i) => i.severity === "error").length} error(s)`);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const addAtCenter = useCallback(
    (info: ComponentInfo) => {
      const position = screenToFlowPosition({
        x: window.innerWidth / 2,
        y: window.innerHeight / 2,
      });
      builder.addComponent(info, position);
    },
    [builder, screenToFlowPosition],
  );

  const onDrop = useCallback(
    (event: DragEvent) => {
      event.preventDefault();
      const name = event.dataTransfer.getData("application/graphforge-component");
      const info = componentsQuery.data?.find((c) => c.name === name);
      if (!info) return;
      builder.addComponent(
        info,
        screenToFlowPosition({ x: event.clientX, y: event.clientY }),
      );
    },
    [builder, componentsQuery.data, screenToFlowPosition],
  );

  if (flowQuery.isLoading || componentsQuery.isLoading) {
    return <div className="p-8 text-sm text-zinc-500">Loading builder…</div>;
  }
  if (flowQuery.isError || !flowQuery.data) {
    return <div className="p-8 text-sm text-red-400">Flow not found.</div>;
  }
  const flow = flowQuery.data;

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-surface-800 bg-surface-900 px-3">
        <Link to="/" className="text-zinc-500 hover:text-zinc-200" aria-label="back to flows">
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div className="flex items-baseline gap-2">
          <span className="text-sm font-semibold text-zinc-100">{meta.name || flow.name}</span>
          <span className="font-mono text-[10px] text-zinc-600">
            {flow.slug} · v{flow.version}
          </span>
          {builder.dirty && <span className="h-1.5 w-1.5 rounded-full bg-amber-400" title="unsaved changes" />}
        </div>
        <div className="ml-auto flex items-center gap-1.5">
          {flow.is_published && (
            <Badge color="emerald">
              <CheckCircle2 className="h-3 w-3" /> published
            </Badge>
          )}
          <Button variant="secondary" size="sm" onClick={() => validate.mutate()} disabled={validate.isPending}>
            <ShieldCheck className="h-3.5 w-3.5" /> Validate
          </Button>
          <Button variant="secondary" size="sm" onClick={() => save.mutate()} disabled={save.isPending}>
            <Save className="h-3.5 w-3.5" /> Save
          </Button>
          <Button size="sm" onClick={() => setPublishOpen(true)}>
            <Rocket className="h-3.5 w-3.5" /> Publish
          </Button>
          <Link to={`/debug/${flow.id}`}>
            <Button variant="secondary" size="sm">
              <Activity className="h-3.5 w-3.5" /> Debug
            </Button>
          </Link>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <Palette components={componentsQuery.data ?? []} onAdd={addAtCenter} />
        <div className="min-w-0 flex-1">
          <ReactFlow
            nodes={builder.nodes}
            edges={builder.edges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            onNodesChange={builder.onNodesChange}
            onEdgesChange={builder.onEdgesChange}
            onConnect={builder.onConnect}
            onNodeClick={(_, node) => builder.select(node.id)}
            onPaneClick={() => builder.select(null)}
            onDrop={onDrop}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "move";
            }}
            fitView
            deleteKeyCode={["Backspace", "Delete"]}
            proOptions={{ hideAttribution: false }}
          >
            <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#26263a" />
            <Controls position="bottom-left" />
            <MiniMap pannable zoomable className="!h-28 !w-44" />
          </ReactFlow>
        </div>
        <ConfigPanel
          flowName={meta.name}
          flowDescription={meta.description}
          onMetaChange={setMeta}
        />
      </div>

      {publishOpen && (
        <PublishDialog
          flow={flow}
          open={publishOpen}
          onClose={() => setPublishOpen(false)}
          onBeforePublish={async () => {
            await save.mutateAsync();
          }}
          onPublished={() => {
            queryClient.invalidateQueries({ queryKey: ["flow", flowId] });
            queryClient.invalidateQueries({ queryKey: ["flows"] });
          }}
        />
      )}
    </div>
  );
}
