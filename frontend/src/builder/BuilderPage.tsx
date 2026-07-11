/** Builder: canvas + palette + inspector + validation + toolbar (SPEC §11.1). */

import {
  Background,
  Controls,
  MiniMap,
  Panel,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Connection,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useQuery } from "@tanstack/react-query";
import {
  AlertTriangle,
  ArrowLeft,
  Check,
  ChevronDown,
  LayoutGrid,
  Redo2,
  StickyNote,
  Undo2,
  Workflow,
} from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/client";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { toast } from "@/components/ui/toast";

import { ConfigPanel } from "./ConfigPanel";
import type { CanvasEdge } from "./convert";
import { newEdgeId, ROUTER_TARGET_HANDLE } from "./convert";
import { indexPorts, judgeConnection } from "./guards";
import { useAddComponent } from "./hooks/useAddComponent";
import { useSaveValidate } from "./hooks/useSaveValidate";
import { edgeTypes, nodeTypes } from "./nodes";
import { Palette } from "./Palette";
import { Playground } from "./Playground";
import { PublishDialog, ShareDialog } from "./PublishDialog";
import { useBuilder } from "./store";
import { ValidationPanel } from "./ValidationPanel";

// ---------------------------------------------------------------- connection judging
// Plain function over the store snapshot: keeps the ReactFlow callbacks below
// referentially stable (no re-reconcile per keystroke/drag frame).
type ConnectionLike = {
  source: string | null;
  target: string | null;
  sourceHandle?: string | null;
  targetHandle?: string | null;
};

function judgeCanvasConnection(connection: ConnectionLike) {
  const { nodes, descriptors } = useBuilder.getState();
  const sourceNode = nodes.find((n) => n.id === connection.source);
  const targetNode = nodes.find((n) => n.id === connection.target);
  const sourceDesc = sourceNode && descriptors.get(sourceNode.data.componentId);
  const targetDesc = targetNode && descriptors.get(targetNode.data.componentId);
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
}

function Kbd({ children }: { children: ReactNode }) {
  return (
    <kbd className="rounded-md border border-border bg-surface-2 px-1 py-0.5 font-mono text-[10.5px] text-text-2">
      {children}
    </kbd>
  );
}

// ---------------------------------------------------------------- canvas
function Canvas({ needsValidation }: { needsValidation: boolean }) {
  // selective subscriptions — the whole-store hook forced ReactFlow to get new
  // callback identities on every store mutation (zustand actions are stable)
  const nodes = useBuilder((s) => s.nodes);
  const edges = useBuilder((s) => s.edges);
  const onNodesChange = useBuilder((s) => s.onNodesChange);
  const onEdgesChange = useBuilder((s) => s.onEdgesChange);
  const undo = useBuilder((s) => s.undo);
  const redo = useBuilder((s) => s.redo);
  const autoLayout = useBuilder((s) => s.autoLayout);
  const canUndo = useBuilder((s) => s.past.length > 0);
  const canRedo = useBuilder((s) => s.future.length > 0);
  const flowId = useBuilder((s) => s.flow?.id);
  const isEmpty = useBuilder(
    (s) => s.nodes.filter((n) => n.type !== "note").length <= 2 && s.edges.length === 0,
  );
  const { screenToFlowPosition, fitView, setCenter, getNode } = useReactFlow();
  const addComponent = useAddComponent();

  const onConnect = useCallback((connection: Connection) => {
    const verdict = judgeCanvasConnection(connection);
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
      type: "lab",
    };
    useBuilder.getState().addEdge(edge);
  }, []);

  const isValidConnection = useCallback(
    (connection: Connection | CanvasEdge) => judgeCanvasConnection(connection).ok,
    [],
  );

  const onDrop = useCallback(
    (event: React.DragEvent) => {
      event.preventDefault();
      const componentId = event.dataTransfer.getData("application/lab-component");
      if (componentId) addComponent(componentId, { x: event.clientX, y: event.clientY });
    },
    [addComponent],
  );

  const onNodeClick = useCallback(
    (_: unknown, node: { id: string }) => useBuilder.getState().select(node.id),
    [],
  );
  const onPaneClick = useCallback(() => useBuilder.getState().select(null), []);

  const focusNode = useCallback(
    (nodeId: string) => {
      const node = getNode(nodeId);
      if (node) {
        setCenter(node.position.x + 100, node.position.y + 40, { zoom: 1.2, duration: 350 });
        useBuilder.getState().select(nodeId);
      }
    },
    [getNode, setCenter],
  );

  useEffect(() => {
    const t = window.setTimeout(() => fitView({ padding: 0.2 }), 60);
    return () => window.clearTimeout(t);
  }, [flowId, fitView]);

  // §11.8 keyboard: undo/redo, copy/paste/duplicate, "/" = palette search.
  // Bound once — handlers read fresh state via getState().
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement;
      if (
        target.tagName === "INPUT" ||
        target.tagName === "TEXTAREA" ||
        target.isContentEditable
      ) {
        return;
      }
      const store = useBuilder.getState();
      const mod = e.ctrlKey || e.metaKey;
      const key = e.key.toLowerCase();
      if (mod && key === "z" && !e.shiftKey) {
        e.preventDefault();
        store.undo();
      } else if ((mod && key === "y") || (mod && e.shiftKey && key === "z")) {
        e.preventDefault();
        store.redo();
      } else if (mod && key === "c") {
        const count = store.copySelection();
        if (count) toast.success(`${count} node(s) copied`);
      } else if (mod && key === "v") {
        const count = store.paste();
        if (count) toast.success(`${count} node(s) pasted`);
      } else if (mod && key === "d") {
        e.preventDefault();
        if (store.copySelection()) store.paste();
      } else if (e.key === "/") {
        e.preventDefault();
        document.getElementById("palette-search")?.focus();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const addNoteAtCenter = useCallback(() => {
    const position = screenToFlowPosition({
      x: window.innerWidth / 2,
      y: window.innerHeight / 2,
    });
    useBuilder.getState().addNote(position);
  }, [screenToFlowPosition]);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="min-w-0 flex-1" onDrop={onDrop} onDragOver={(e) => e.preventDefault()}>
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onConnect={onConnect}
          isValidConnection={isValidConnection}
          onNodeClick={onNodeClick}
          onPaneClick={onPaneClick}
          deleteKeyCode={["Delete", "Backspace"]}
          connectionRadius={36}
          snapToGrid
          snapGrid={[16, 16]}
          proOptions={{ hideAttribution: true }}
          colorMode="dark"
          fitView
        >
          {/* single dot grid — 24px, token color (SPEC §11.1) */}
          <Background gap={24} size={1} color="var(--color-border)" />
          <MiniMap pannable zoomable className="!bg-surface-1" />
          <Controls showInteractive={false} />
          <Panel position="top-left">
            <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface-1/95 p-0.5 shadow-md shadow-black/20">
              <Button
                variant="ghost"
                size="icon"
                aria-label="Undo"
                title="Undo (Ctrl+Z)"
                disabled={!canUndo}
                onClick={undo}
              >
                <Undo2 size={15} strokeWidth={1.75} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Redo"
                title="Redo (Ctrl+Shift+Z)"
                disabled={!canRedo}
                onClick={redo}
              >
                <Redo2 size={15} strokeWidth={1.75} />
              </Button>
              <div className="mx-0.5 h-4 w-px bg-border" aria-hidden />
              <Button
                variant="ghost"
                size="icon"
                aria-label="Add sticky note"
                title="Add sticky note"
                onClick={addNoteAtCenter}
              >
                <StickyNote size={15} strokeWidth={1.75} />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                aria-label="Auto-layout"
                title="Auto-layout (left to right)"
                onClick={() => {
                  autoLayout();
                  window.setTimeout(() => fitView({ padding: 0.2, duration: 300 }), 50);
                }}
              >
                <LayoutGrid size={15} strokeWidth={1.75} />
              </Button>
            </div>
          </Panel>
          {isEmpty && (
            <Panel position="top-center" className="!pointer-events-none mt-24">
              <div className="flex flex-col items-center gap-1.5 rounded-lg border border-dashed border-border bg-canvas/80 px-8 py-6 text-center">
                <Workflow size={24} strokeWidth={1.75} className="text-text-3" />
                <p className="text-[13px] font-medium text-text-2">Build your flow</p>
                <p className="text-xs text-text-3">
                  Drag components from the left — ports connect by matching colors
                </p>
                <p className="mt-1.5 flex items-center gap-2 text-[11px] text-text-3">
                  <span>
                    <Kbd>/</Kbd> search
                  </span>
                  <span>
                    <Kbd>Ctrl+Z</Kbd> undo
                  </span>
                  <span>
                    <Kbd>Ctrl+D</Kbd> duplicate
                  </span>
                  <span>
                    <Kbd>Del</Kbd> delete
                  </span>
                </p>
              </div>
            </Panel>
          )}
        </ReactFlow>
      </div>
      <div className="flex w-80 flex-col border-l border-border bg-canvas">
        <div className="min-h-0 flex-1 overflow-hidden">
          <ConfigPanel />
        </div>
        <ValidationPanel onFocusNode={focusNode} needsValidation={needsValidation} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- validate split button
function ValidateSplitButton({
  deep,
  onToggleDeep,
  onValidate,
}: {
  deep: boolean;
  onToggleDeep: () => void;
  onValidate: (deep: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onEsc = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onEsc);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onEsc);
    };
  }, [open]);

  return (
    <div ref={ref} className="relative flex items-center">
      <Button
        variant="ghost"
        className="rounded-r-none pr-2"
        title={deep ? "Deep validate — also checks providers and stores" : "Validate the graph"}
        onClick={() => onValidate(deep)}
      >
        Validate
        {deep && <span className="text-[11px] font-semibold text-accent">deep</span>}
      </Button>
      <Button
        variant="ghost"
        size="icon"
        className="w-5 rounded-l-none"
        aria-label="Validation options"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <ChevronDown size={14} strokeWidth={1.75} />
      </Button>
      {open && (
        <div
          role="menu"
          className="absolute right-0 top-full z-50 mt-1 w-64 rounded-lg border border-border bg-surface-1 p-1 shadow-xl shadow-black/40"
        >
          <button
            type="button"
            role="menuitemcheckbox"
            aria-checked={deep}
            onClick={onToggleDeep}
            className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-surface-2 focus-visible:outline-2 focus-visible:outline-accent"
          >
            <span className="mt-0.5 flex h-3.5 w-3.5 items-center justify-center text-accent">
              {deep && <Check size={14} strokeWidth={2} />}
            </span>
            <span>
              <span className="block text-xs font-medium text-text-1">Deep validate</span>
              <span className="block text-[11px] leading-snug text-text-3">
                Also reach model providers, vector stores and MCP servers (§11.6)
              </span>
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- loading / error states
function BuilderSkeleton() {
  return (
    <div className="flex h-screen flex-col bg-canvas" aria-busy="true" aria-label="Loading flow">
      <div className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
        <div className="h-4 w-16 animate-pulse rounded-md bg-surface-2" />
        <div className="h-4 w-40 animate-pulse rounded-md bg-surface-2" />
        <div className="h-4 w-14 animate-pulse rounded-full bg-surface-2" />
        <div className="ml-auto flex items-center gap-2">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="h-7 w-20 animate-pulse rounded-md bg-surface-2" />
          ))}
        </div>
      </div>
      <div className="flex min-h-0 flex-1">
        <div className="w-60 space-y-2 border-r border-border p-3">
          <div className="h-8 animate-pulse rounded-md bg-surface-2" />
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <div key={i} className="h-8 animate-pulse rounded-md bg-surface-1" />
          ))}
        </div>
        <div className="flex-1 p-8">
          <div className="flex h-full items-center justify-center gap-8">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-40 w-64 animate-pulse rounded-xl bg-surface-1" />
            ))}
          </div>
        </div>
        <div className="w-80 space-y-2 border-l border-border p-4">
          <div className="h-4 w-24 animate-pulse rounded-md bg-surface-2" />
          {[0, 1, 2].map((i) => (
            <div key={i} className="h-8 animate-pulse rounded-md bg-surface-1" />
          ))}
        </div>
      </div>
    </div>
  );
}

function BuilderError({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="flex h-screen items-center justify-center bg-canvas p-6">
      <div
        role="alert"
        className="w-full max-w-md rounded-lg border border-border border-l-2 border-l-danger bg-surface-1 p-4 shadow-xl shadow-black/30"
      >
        <p className="flex items-center gap-2 text-sm font-semibold text-text-1">
          <AlertTriangle size={16} strokeWidth={1.75} className="text-danger" />
          Failed to load the flow
        </p>
        <p className="mt-1.5 break-words text-xs text-text-2">{message}</p>
        <div className="mt-3 flex items-center gap-2">
          <Button size="sm" variant="secondary" onClick={onRetry}>
            Retry
          </Button>
          <Link
            to="/"
            className="rounded-md px-2 py-1 text-xs text-text-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent"
          >
            Back to flows
          </Link>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- page
export function BuilderPage() {
  const { flowId } = useParams<{ flowId: string }>();
  const flow = useBuilder((s) => s.flow);
  const dirty = useBuilder((s) => s.dirty);
  const hasErrors = useBuilder((s) => s.diagnostics.some((d) => d.severity === "error"));
  const setDescriptors = useBuilder((s) => s.setDescriptors);
  const loadFlow = useBuilder((s) => s.loadFlow);
  const [publishOpen, setPublishOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [playgroundOpen, setPlaygroundOpen] = useState(false);
  const [deepValidate, setDeepValidate] = useState(false);

  const componentsQuery = useQuery({ queryKey: ["components"], queryFn: api.components.list });
  const flowQuery = useQuery({
    queryKey: ["flow", flowId],
    queryFn: () => api.flows.get(flowId!),
    enabled: Boolean(flowId),
  });

  const { save, saveDraft, validate, needsValidation } = useSaveValidate();

  useEffect(() => {
    if (componentsQuery.data) setDescriptors(componentsQuery.data);
  }, [componentsQuery.data, setDescriptors]);

  useEffect(() => {
    if (flowQuery.data) loadFlow(flowQuery.data);
  }, [flowQuery.data, loadFlow]);

  // warn on tab close with unsaved changes (autosave usually beats this)
  useEffect(() => {
    const onBeforeUnload = (e: BeforeUnloadEvent) => {
      if (useBuilder.getState().dirty) e.preventDefault();
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    return () => window.removeEventListener("beforeunload", onBeforeUnload);
  }, []);

  // §11.9 keyboard: Ctrl/⌘+S saves (never the browser dialog), Ctrl/⌘+Enter
  // opens the playground (skipped while typing so chat inputs keep it).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey)) return;
      const key = e.key.toLowerCase();
      if (key === "s") {
        e.preventDefault();
        void save();
      } else if (key === "enter") {
        const target = e.target as HTMLElement;
        if (
          target.tagName === "INPUT" ||
          target.tagName === "TEXTAREA" ||
          target.isContentEditable
        ) {
          return;
        }
        e.preventDefault();
        setPlaygroundOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save]);

  const publishBlocked = hasErrors || needsValidation;

  if (flowQuery.isError || componentsQuery.isError) {
    const error = (flowQuery.error ?? componentsQuery.error) as Error;
    return (
      <BuilderError
        message={error?.message || "unknown error"}
        onRetry={() => {
          void flowQuery.refetch();
          void componentsQuery.refetch();
        }}
      />
    );
  }

  if (!flowQuery.data || !componentsQuery.data) {
    return <BuilderSkeleton />;
  }

  return (
    <ReactFlowProvider>
      <div className="flex h-screen flex-col bg-canvas text-text-1">
        <header className="flex h-12 shrink-0 items-center gap-3 border-b border-border px-4">
          <Link
            to="/"
            aria-label="Back to flows"
            className="flex items-center gap-1 rounded-md text-[13px] text-text-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent"
          >
            <ArrowLeft size={14} strokeWidth={1.75} />
            Flows
          </Link>
          <div className="h-4 w-px bg-border" aria-hidden />
          <div className="flex min-w-0 items-center gap-2">
            <h1 className="truncate text-sm font-semibold">{flow?.name}</h1>
            <Badge tone="muted">
              {flow?.published_version ? `v${flow.published_version} · published` : "draft"}
            </Badge>
            {dirty && <Badge tone="warning">unsaved</Badge>}
          </div>
          <div className="ml-auto flex items-center gap-1.5">
            <ValidateSplitButton
              deep={deepValidate}
              onToggleDeep={() => setDeepValidate((v) => !v)}
              onValidate={(deep) => void validate(deep)}
            />
            <Button variant="ghost" title="Save (Ctrl+S)" onClick={() => void save()}>
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
              disabled={publishBlocked}
              title={
                hasErrors
                  ? "fix validation errors first"
                  : needsValidation
                    ? "validating…"
                    : "publish a version"
              }
            >
              Publish
            </Button>
            <Button
              variant="ghost"
              title="Playground (Ctrl+Enter)"
              onClick={() => setPlaygroundOpen((v) => !v)}
            >
              Playground
            </Button>
          </div>
        </header>
        <div className="flex min-h-0 flex-1">
          <Palette components={componentsQuery.data} />
          <Canvas needsValidation={needsValidation} />
          {playgroundOpen && flow && (
            <Playground flow={flow} onClose={() => setPlaygroundOpen(false)} />
          )}
        </div>
        {flow && (
          <>
            <PublishDialog
              open={publishOpen}
              onClose={() => setPublishOpen(false)}
              flow={flow}
              beforePublish={saveDraft}
            />
            <ShareDialog open={shareOpen} onClose={() => setShareOpen(false)} flow={flow} />
          </>
        )}
      </div>
    </ReactFlowProvider>
  );
}
