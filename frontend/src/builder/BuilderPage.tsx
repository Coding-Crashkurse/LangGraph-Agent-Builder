/** Builder: canvas + palette + inspector + validation + toolbar (SPEC §11.1). */

import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useQuery } from "@tanstack/react-query";
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";

import { ConfigPanel } from "./ConfigPanel";
import type { CanvasEdge } from "./convert";
import { defaultConfig, newEdgeId, newNodeId, ROUTER_TARGET_HANDLE } from "./convert";
import { indexPorts, judgeConnection } from "./guards";
import { edgeTypes, nodeTypes } from "./nodes";
import { Palette } from "./Palette";
import { Playground } from "./Playground";
import { PublishDialog, ShareDialog } from "./PublishDialog";
import { useBuilder } from "./store";
import { ValidationPanel } from "./ValidationPanel";

function Canvas() {
  const store = useBuilder();
  const { screenToFlowPosition, fitView, setCenter, getNode } = useReactFlow();

  const judge = useCallback(
    (connection: Connection | { source: string; target: string;
      sourceHandle?: string | null; targetHandle?: string | null }) => {
      const sourceNode = store.nodes.find((n) => n.id === connection.source);
      const targetNode = store.nodes.find((n) => n.id === connection.target);
      const sourceDesc = sourceNode && store.descriptors.get(sourceNode.data.componentId);
      const targetDesc = targetNode && store.descriptors.get(targetNode.data.componentId);
      if (!sourceNode || !targetNode || !sourceDesc || !targetDesc) {
        return { ok: false as const, reason: "unknown node" };
      }
      const sourcePorts = indexPorts(sourceDesc, sourceNode.data.config);
      const targetPorts = indexPorts(targetDesc, targetNode.data.config);
      const sourcePort = sourcePorts.outputs.get(connection.sourceHandle ?? "");
      const targetPort =
        connection.targetHandle === ROUTER_TARGET_HANDLE
          ? undefined
          : targetPorts.inputs.get(connection.targetHandle ?? "");
      return judgeConnection(
        sourcePort,
        targetPort,
        connection.targetHandle === ROUTER_TARGET_HANDLE,
      );
    },
    [store],
  );

  const onConnect = useCallback(
    (connection: Connection) => {
      const verdict = judge(connection);
      if (!verdict.ok) {
        toast.error(verdict.reason);
        return;
      }
      const edge: CanvasEdge = {
        id: newEdgeId(),
        source: connection.source,
        sourceHandle: connection.sourceHandle,
        target: connection.target,
        targetHandle: verdict.kind === "router" ? ROUTER_TARGET_HANDLE : connection.targetHandle,
        data: { kind: verdict.kind },
        type: "lga",
      };
      store.addEdge(edge);
    },
    [store, judge],
  );

  const isValidConnection = useCallback(
    (connection: Connection | CanvasEdge) => judge(connection).ok,
    [judge],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const componentId = event.dataTransfer.getData("application/lga-component");
      const descriptor = store.descriptors.get(componentId);
      if (!descriptor) return;
      const taken = new Set(store.nodes.map((n) => n.id));
      const id = newNodeId(descriptor, taken);
      if (taken.has(id)) {
        toast.error(`node ${id} already exists`);
        return;
      }
      const position = screenToFlowPosition({ x: event.clientX, y: event.clientY });
      store.addNode({
        id,
        type: "lga",
        deletable: id !== "start" && id !== "end",
        position,
        data: {
          componentId,
          componentVersion: descriptor.version,
          label: descriptor.display_name,
          config: defaultConfig(descriptor),
          notes: "",
        },
      });
      store.select(id);
    },
    [store, screenToFlowPosition],
  );

  const focusNode = useCallback(
    (nodeId: string) => {
      const node = getNode(nodeId);
      if (node) {
        setCenter(node.position.x + 100, node.position.y + 40, { zoom: 1.2, duration: 350 });
        store.select(nodeId);
      }
    },
    [getNode, setCenter, store],
  );

  useEffect(() => {
    const t = window.setTimeout(() => fitView({ padding: 0.2 }), 60);
    return () => window.clearTimeout(t);
  }, [store.flow?.id, fitView]);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="min-w-0 flex-1" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
        <ReactFlow
          nodes={store.nodes}
          edges={store.edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={store.onNodesChange}
          onEdgesChange={store.onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onNodeClick={(_, node) => store.select(node.id)}
          onPaneClick={() => store.select(null)}
          deleteKeyCode={["Delete", "Backspace"]}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
          fitView
        >
          <Background gap={18} size={1} />
          <MiniMap pannable zoomable className="!bg-surface-900" />
          <Controls showInteractive={false} />
        </ReactFlow>
      </div>
      <div className="flex w-80 flex-col border-l border-surface-800 bg-surface-950">
        <div className="min-h-0 flex-1 overflow-hidden">
          <ConfigPanel />
        </div>
        <ValidationPanel onFocusNode={focusNode} />
      </div>
    </div>
  );
}

export function BuilderPage() {
  const { flowId } = useParams<{ flowId: string }>();
  const store = useBuilder();
  const [publishOpen, setPublishOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [playgroundOpen, setPlaygroundOpen] = useState(false);

  const componentsQuery = useQuery({ queryKey: ["components"], queryFn: api.components.list });
  const flowQuery = useQuery({
    queryKey: ["flow", flowId],
    queryFn: () => api.flows.get(flowId!),
    enabled: Boolean(flowId),
  });

  useEffect(() => {
    if (componentsQuery.data) store.setDescriptors(componentsQuery.data);
  }, [componentsQuery.data]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (flowQuery.data) store.loadFlow(flowQuery.data);
  }, [flowQuery.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = async () => {
    if (!store.flow) return;
    try {
      const updated = await api.flows.update(store.flow.id, store.currentSpec());
      store.loadFlow(updated);
      toast.success("saved");
    } catch (error) {
      toast.error(`save failed: ${(error as Error).message}`);
    }
  };

  // autosave (SPEC §18.1: LGA_AUTO_SAVING / LGA_AUTO_SAVING_INTERVAL_MS)
  const [autosave, setAutosave] = useState<{ on: boolean; ms: number }>({ on: false, ms: 1000 });
  useEffect(() => {
    fetch("/api/v1/config")
      .then((r) => (r.ok ? r.json() : null))
      .then((cfg) => {
        if (cfg) {
          setAutosave({
            on: Boolean(cfg.auto_saving),
            ms: Number(cfg.auto_saving_interval_ms) || 1000,
          });
        }
      })
      .catch(() => {});
  }, []);
  useEffect(() => {
    if (!autosave.on || !store.dirty || !store.flow) return;
    const timer = window.setTimeout(async () => {
      try {
        await api.flows.update(store.flow!.id, store.currentSpec());
        store.markSaved(); // no loadFlow: keep canvas state (no rebuild mid-edit)
      } catch {
        // silent — the amber "unsaved" badge stays until a manual save succeeds
      }
    }, autosave.ms);
    return () => window.clearTimeout(timer);
  }, [autosave, store.dirty, store.nodes, store.edges]); // eslint-disable-line react-hooks/exhaustive-deps

  const validate = async (deep = false) => {
    if (!store.flow) return;
    try {
      if (store.dirty) await api.flows.update(store.flow.id, store.currentSpec());
      const result = await api.flows.validate(store.flow.id, deep);
      store.setDiagnostics(result.diagnostics);
      const errors = result.diagnostics.filter((d) => d.severity === "error").length;
      if (errors === 0) toast.success(`valid — ${result.diagnostics.length} diagnostics`);
      else toast.error(`${errors} error(s)`);
    } catch (error) {
      toast.error(`validate failed: ${(error as Error).message}`);
    }
  };

  const hasErrors = store.diagnostics.some((d) => d.severity === "error");

  if (!flowQuery.data || !componentsQuery.data) {
    return <div className="p-8 text-sm text-zinc-500">loading…</div>;
  }

  return (
    <ReactFlowProvider>
      <div className="flex h-screen flex-col bg-surface-950 text-zinc-100">
        <header className="flex items-center gap-3 border-b border-surface-800 px-4 py-2">
          <Link to="/" className="text-sm text-zinc-500 hover:text-zinc-200">
            ← Flows
          </Link>
          <h1 className="text-sm font-semibold">{store.flow?.name}</h1>
          <Badge tone="muted">
            {store.flow?.published_version
              ? `v${store.flow.published_version} · published`
              : "draft"}
          </Badge>
          {store.dirty && <Badge tone="amber">unsaved</Badge>}
          <div className="ml-auto flex items-center gap-2">
            <Button variant="ghost" onClick={() => validate(false)}>
              Validate
            </Button>
            <Button variant="ghost" onClick={save}>
              Save
            </Button>
            <Button
              variant="ghost"
              onClick={() => setShareOpen(true)}
              title="A2A / MCP / API access"
            >
              Share
            </Button>
            <Button
              onClick={() => setPublishOpen(true)}
              disabled={hasErrors}
              title={hasErrors ? "fix validation errors first" : "publish a version"}
            >
              Publish
            </Button>
            <Button variant="ghost" onClick={() => setPlaygroundOpen((v) => !v)}>
              Playground
            </Button>
          </div>
        </header>
        <div className="flex min-h-0 flex-1">
          <Palette components={componentsQuery.data} />
          <Canvas />
          {playgroundOpen && store.flow && (
            <Playground flow={store.flow} onClose={() => setPlaygroundOpen(false)} />
          )}
        </div>
        {store.flow && (
          <>
            <PublishDialog
              open={publishOpen}
              onClose={() => setPublishOpen(false)}
              flow={store.flow}
              beforePublish={save}
            />
            <ShareDialog open={shareOpen} onClose={() => setShareOpen(false)} flow={store.flow} />
          </>
        )}
      </div>
    </ReactFlowProvider>
  );
}
