/**
 * The canvas page. Button semantics (SPEC §5): Save = local draft,
 * Validate = local instantly + runtime when reachable, Publish = runtime
 * draft + deploy (endpoint URL in the success dialog), Playground =
 * ephemeral deploy + chat, Share = canonical YAML export.
 */

import { useQuery } from "@tanstack/react-query";
import {
  Background,
  Controls,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
} from "@xyflow/react";
import {
  ArrowLeft,
  Check,
  Loader2,
  MessageSquare,
  Redo2,
  Rocket,
  Save,
  Share2,
  Undo2,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, ApiError } from "@/api/client";
import type { PublishResponse } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";

import { ConfigPanel } from "./ConfigPanel";
import { DRAG_MIME, Palette } from "./Palette";
import { Playground } from "./Playground";
import { PublishDialog } from "./PublishDialog";
import { ShareDialog } from "./ShareDialog";
import { ValidationPanel } from "./ValidationPanel";
import { edgeTypes, nodeTypes } from "./nodes";
import { hasErrors, useBuilder } from "./store";

function Canvas({ flowName }: { flowName: string }) {
  const reactFlow = useReactFlow();
  const nodes = useBuilder((s) => s.nodes);
  const edges = useBuilder((s) => s.edges);
  const onNodesChange = useBuilder((s) => s.onNodesChange);
  const onEdgesChange = useBuilder((s) => s.onEdgesChange);
  const onConnect = useBuilder((s) => s.onConnect);
  const isValidConnection = useBuilder((s) => s.isValidConnection);
  const addNode = useBuilder((s) => s.addNode);
  const select = useBuilder((s) => s.select);

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      const type = event.dataTransfer.getData(DRAG_MIME);
      if (!type) return;
      event.preventDefault();
      addNode(type, reactFlow.screenToFlowPosition({ x: event.clientX, y: event.clientY }));
    },
    [addNode, reactFlow],
  );

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges}
      nodeTypes={nodeTypes}
      edgeTypes={edgeTypes}
      onNodesChange={onNodesChange}
      onEdgesChange={onEdgesChange}
      onConnect={onConnect}
      isValidConnection={isValidConnection}
      deleteKeyCode={["Backspace", "Delete"]}
      onDrop={onDrop}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = "move";
      }}
      onSelectionChange={({ nodes: selected }) => select(selected[0]?.id ?? null)}
      fitView
      proOptions={{ hideAttribution: true }}
      className="bg-canvas"
      aria-label={`Flow canvas for ${flowName}`}
    >
      <Background gap={20} size={1} color="var(--color-border)" />
      <Controls showInteractive={false} />
    </ReactFlow>
  );
}

function BuilderInner({ flowName }: { flowName: string }) {
  const reactFlow = useReactFlow();
  const loaded = useBuilder((s) => s.loaded);
  const dirty = useBuilder((s) => s.dirty);
  const validated = useBuilder((s) => s.validated);
  const issues = useBuilder((s) => s.issues);
  const catalog = useBuilder((s) => s.catalog);
  const load = useBuilder((s) => s.load);
  const currentDefinition = useBuilder((s) => s.currentDefinition);
  const setValidation = useBuilder((s) => s.setValidation);
  const setIssues = useBuilder((s) => s.setIssues);
  const markSaved = useBuilder((s) => s.markSaved);
  const select = useBuilder((s) => s.select);
  const undo = useBuilder((s) => s.undo);
  const redo = useBuilder((s) => s.redo);
  const canUndo = useBuilder((s) => s.past.length > 0);
  const canRedo = useBuilder((s) => s.future.length > 0);
  const nodes = useBuilder((s) => s.nodes);
  const edges = useBuilder((s) => s.edges);
  const meta = useBuilder((s) => s.meta);

  const [busy, setBusy] = useState<"save" | "validate" | "publish" | "playground" | null>(null);
  const [publishOpen, setPublishOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [playgroundEndpoint, setPlaygroundEndpoint] = useState<string | null>(null);

  const flowQuery = useQuery({
    queryKey: ["flow", flowName],
    queryFn: () => api.flows.get(flowName),
  });
  const catalogQuery = useQuery({ queryKey: ["node-types"], queryFn: api.catalog.get });
  const configQuery = useQuery({ queryKey: ["config"], queryFn: api.config.get });

  const loadedFor = useRef<string | null>(null);
  useEffect(() => {
    if (flowQuery.data && catalogQuery.data && loadedFor.current !== flowName) {
      loadedFor.current = flowName;
      load(flowQuery.data.definition, catalogQuery.data);
    }
  }, [flowQuery.data, catalogQuery.data, flowName, load]);

  // Undo/redo keyboard shortcuts; form fields keep their native text undo.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey)) return;
      const target = event.target as HTMLElement | null;
      if (
        target &&
        (target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.tagName === "SELECT" ||
          target.isContentEditable)
      ) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "z" && !event.shiftKey) {
        event.preventDefault();
        undo();
      } else if (key === "y" || (key === "z" && event.shiftKey)) {
        event.preventDefault();
        redo();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [undo, redo]);

  // Silent local re-validate after semantic changes: keeps issues fresh while
  // editing (no stale field errors); the Validate button adds the
  // authoritative runtime answer on top.
  useEffect(() => {
    if (!loaded || useBuilder.getState().validated) return;
    const timer = setTimeout(() => {
      api.flows
        .validate(currentDefinition(), { runtime: false })
        .then(setValidation)
        .catch(() => undefined); // silent — manual Validate surfaces errors
    }, 700);
    return () => clearTimeout(timer);
  }, [nodes, edges, meta, loaded, currentDefinition, setValidation]);

  const save = useCallback(async (): Promise<boolean> => {
    setBusy("save");
    try {
      await api.flows.save(flowName, currentDefinition());
      markSaved();
      return true;
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "save failed");
      return false;
    } finally {
      setBusy(null);
    }
  }, [flowName, currentDefinition, markSaved]);

  const validate = useCallback(async () => {
    setBusy("validate");
    try {
      setValidation(await api.flows.validate(currentDefinition()));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "validate failed");
    } finally {
      setBusy(null);
    }
  }, [currentDefinition, setValidation]);

  const runPublish = useCallback(
    async (versionLabel: string | null): Promise<PublishResponse | null> => {
    if (!(await save())) return null;
    setBusy("publish");
    try {
      const published = await api.flows.publish(flowName, { version_label: versionLabel });
      toast.success("Deployed to the runtime");
      return published;
    } catch (err) {
      if (err instanceof ApiError && err.issues.length > 0) {
        setIssues(err.issues);
        toast.error("Publish rejected — see validation panel");
      } else {
        toast.error(err instanceof Error ? err.message : "publish failed");
      }
      return null;
    } finally {
      setBusy(null);
    }
  }, [flowName, save, setIssues]);

  const playground = useCallback(async () => {
    if (!(await save())) return;
    setBusy("playground");
    try {
      const result = await api.flows.playground(flowName);
      setPlaygroundEndpoint(result.endpoint_url);
    } catch (err) {
      if (err instanceof ApiError && err.issues.length > 0) {
        setIssues(err.issues);
        toast.error("Draft rejected — see validation panel");
      } else {
        toast.error(err instanceof Error ? err.message : "playground deploy failed");
      }
    } finally {
      setBusy(null);
    }
  }, [flowName, save, setIssues]);

  const focusIssue = useCallback(
    (nodeId: string | null) => {
      if (!nodeId) return;
      const node = useBuilder.getState().nodes.find((n) => n.id === nodeId);
      if (!node) return;
      select(nodeId);
      reactFlow.setCenter(node.position.x + 90, node.position.y + 40, {
        zoom: 1.1,
        duration: 300,
      });
    },
    [reactFlow, select],
  );

  if (flowQuery.isError) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-2">
        Flow not found. <Link className="ml-1 text-accent hover:underline" to="/flows">Back</Link>
      </div>
    );
  }
  if (!loaded || !catalog) {
    return (
      <div className="flex h-full items-center justify-center text-sm text-text-3">
        <Loader2 className="mr-2 animate-spin" size={15} /> Loading flow…
      </div>
    );
  }

  const blocked = hasErrors(issues);
  return (
    <div className="flex h-screen flex-col bg-canvas">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border bg-surface-1 px-3">
        <Link to="/flows" aria-label="Back to flows" className="text-text-2 hover:text-text-1">
          <ArrowLeft size={16} />
        </Link>
        <span className="text-sm font-semibold text-text-1">{flowName}</span>
        {dirty && <Badge tone="warning">unsaved</Badge>}
        {validated && !blocked && <Badge tone="success">valid</Badge>}
        {validated && blocked && <Badge tone="danger">errors</Badge>}
        <span className="ml-auto flex items-center gap-1.5">
          <Button
            size="icon"
            variant="ghost"
            onClick={undo}
            disabled={!canUndo}
            title="Undo (Ctrl+Z)"
            aria-label="Undo"
          >
            <Undo2 size={14} />
          </Button>
          <Button
            size="icon"
            variant="ghost"
            onClick={redo}
            disabled={!canRedo}
            title="Redo (Ctrl+Y)"
            aria-label="Redo"
          >
            <Redo2 size={14} />
          </Button>
          <Button size="sm" variant="secondary" onClick={() => void save()} disabled={busy !== null}>
            {busy === "save" ? <Loader2 size={13} className="animate-spin" /> : <Save size={13} />}
            Save
          </Button>
          <Button size="sm" variant="secondary" onClick={() => void validate()} disabled={busy !== null}>
            {busy === "validate" ? <Loader2 size={13} className="animate-spin" /> : <Check size={13} />}
            Validate
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void playground()}
            disabled={busy !== null || !configQuery.data?.runtime_configured || blocked}
            title={
              blocked
                ? "Fix the validation errors first"
                : configQuery.data?.runtime_configured
                  ? "Ephemeral deploy + chat"
                  : "No runtime configured"
            }
          >
            {busy === "playground" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <MessageSquare size={13} />
            )}
            Playground
          </Button>
          <Button
            size="sm"
            variant="secondary"
            onClick={() => setShareOpen(true)}
            disabled={blocked}
            title={blocked ? "Fix the validation errors first" : "Export canonical YAML"}
          >
            <Share2 size={13} /> Share
          </Button>
          <Button
            size="sm"
            onClick={() => setPublishOpen(true)}
            disabled={busy !== null || !configQuery.data?.runtime_configured || blocked}
            title={
              blocked
                ? "Fix the validation errors first"
                : configQuery.data?.runtime_configured
                  ? "Choose the door, then update runtime draft + deploy"
                  : "No runtime configured"
            }
          >
            {busy === "publish" ? <Loader2 size={13} className="animate-spin" /> : <Rocket size={13} />}
            Publish
          </Button>
        </span>
      </header>
      <div className="flex min-h-0 flex-1">
        <Palette catalog={catalog} />
        <main className="flex min-w-0 flex-1 flex-col">
          <div className="min-h-0 flex-1">
            <Canvas flowName={flowName} />
          </div>
          <ValidationPanel onFocusIssue={focusIssue} />
        </main>
        {playgroundEndpoint ? (
          <Playground
            endpoint={playgroundEndpoint}
            onClose={() => setPlaygroundEndpoint(null)}
            onRedeploy={() => void playground()}
          />
        ) : (
          <ConfigPanel />
        )}
      </div>
      <PublishDialog
        flowName={flowName}
        open={publishOpen}
        onClose={() => setPublishOpen(false)}
        onPublish={runPublish}
      />
      <ShareDialog flowName={flowName} open={shareOpen} onClose={() => setShareOpen(false)} />
    </div>
  );
}

export function BuilderPage() {
  const { flowName } = useParams<{ flowName: string }>();
  if (!flowName) return null;
  return (
    <ReactFlowProvider>
      <BuilderInner flowName={flowName} />
    </ReactFlowProvider>
  );
}
