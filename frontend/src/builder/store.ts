/** Canvas state (zustand) — server state lives in react-query.
 * SPEC §11.8: undo/redo history, copy/paste (secrets stripped), sticky notes,
 * auto-layout. */

import {
  applyEdgeChanges,
  applyNodeChanges,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import { create } from "zustand";

import { api } from "@/api/client";
import { streamRun } from "@/api/sse";
import type { ComponentDescriptor, Diagnostic, FlowInfo, FlowSpec, RunEvent } from "@/api/types";

import type { CanvasEdge, CanvasNode } from "./convert";
import {
  canvasToSpec,
  edgeSourceFamily,
  isNoteNode,
  newEdgeId,
  newNodeId,
  NOTE_COMPONENT,
  ROUTER_TARGET_HANDLE,
  specToCanvas,
  withEdgeFamilies,
} from "./convert";
import { indexPorts } from "./guards";

interface Snapshot {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

export interface NodeRunState {
  /** `interrupted` = HITL node parked in input_required (§11.2 amber ring) */
  status: "running" | "finished" | "error" | "interrupted";
  durationMs?: number;
  errorCode?: string;
}

const HISTORY_LIMIT = 50;
let lastConfigCheckpoint = 0;

function cloneGraph(nodes: CanvasNode[], edges: CanvasEdge[]): Snapshot {
  return structuredClone({ nodes, edges });
}

interface BuilderState {
  flow: FlowInfo | null;
  baseSpec: FlowSpec | null; // flow-level settings (a2a/mcp/…) live here
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  descriptors: Map<string, ComponentDescriptor>;
  selectedNodeId: string | null;
  diagnostics: Diagnostic[];
  dirty: boolean;
  past: Snapshot[];
  future: Snapshot[];
  clipboard: Snapshot | null;
  dragging: boolean;
  runStates: Record<string, NodeRunState>;
  runActive: boolean; // a run is in flight → §11.4 live-edge animation
  partialTarget: string | null; // node an active partial run targets (dims the rest)

  loadFlow: (flow: FlowInfo) => void;
  setDescriptors: (list: ComponentDescriptor[]) => void;
  onNodesChange: (changes: NodeChange<CanvasNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<CanvasEdge>[]) => void;
  addNode: (node: CanvasNode) => void;
  addEdge: (edge: CanvasEdge) => void;
  removeEdge: (edgeId: string) => void;
  select: (nodeId: string | null) => void;
  renameNode: (nodeId: string, label: string) => void;
  duplicateNode: (nodeId: string) => string | null;
  deleteNode: (nodeId: string) => void;
  toggleCollapsed: (nodeId: string) => void;
  updateNodeConfig: (nodeId: string, config: Record<string, unknown>) => void;
  updateNoteText: (nodeId: string, text: string) => void;
  addNote: (position: { x: number; y: number }) => void;
  updateFlowMeta: (patch: Partial<FlowSpec["flow"]>) => void;
  setDiagnostics: (diagnostics: Diagnostic[]) => void;
  currentSpec: () => FlowSpec;
  markSaved: () => void;

  undo: () => void;
  redo: () => void;
  copySelection: () => number;
  paste: () => number;
  autoLayout: () => void;

  applyRunEvent: (event: RunEvent) => void;
  resetRunStates: () => void;
  setPartialTarget: (nodeId: string | null) => void;
  applyCoercions: (coercions: { edge_id: string; coercion: string }[]) => void;
  runToNode: (nodeId: string) => Promise<string>; // partial run (§6.4); returns result preview
}

export const useBuilder = create<BuilderState>((set, get) => {
  /** push the current graph onto the undo stack (clears redo) */
  const checkpoint = () => {
    const { nodes, edges, past } = get();
    set({
      past: [...past.slice(-(HISTORY_LIMIT - 1)), cloneGraph(nodes, edges)],
      future: [],
    });
  };

  return {
    flow: null,
    baseSpec: null,
    nodes: [],
    edges: [],
    descriptors: new Map(),
    selectedNodeId: null,
    diagnostics: [],
    dirty: false,
    past: [],
    future: [],
    clipboard: null,
    dragging: false,
    runStates: {},
    runActive: false,
    partialTarget: null,

    loadFlow: (flow) => {
      // §11.3: edge stroke = source port family — resolve at load time
      const { nodes, edges } = specToCanvas(flow.spec, get().descriptors);
      set({
        flow,
        baseSpec: flow.spec,
        nodes,
        edges,
        dirty: false,
        diagnostics: [],
        past: [],
        future: [],
        runStates: {},
        runActive: false,
        partialTarget: null,
      });
    },
    setDescriptors: (list) =>
      set((state) => {
        const descriptors = new Map(list.map((d) => [d.component_id, d]));
        // descriptors may arrive after loadFlow — backfill edge families then
        return { descriptors, edges: withEdgeFamilies(state.nodes, state.edges, descriptors) };
      }),

    onNodesChange: (changes) => {
      const meaningful = changes.some((c) => c.type !== "select" && c.type !== "dimensions");
      const removes = changes.some((c) => c.type === "remove");
      const dragStart = changes.some(
        (c) => c.type === "position" && "dragging" in c && c.dragging === true,
      );
      const dragEnd = changes.some(
        (c) => c.type === "position" && "dragging" in c && c.dragging === false,
      );
      if (removes || (dragStart && !get().dragging)) checkpoint();
      set((state) => ({
        nodes: applyNodeChanges(changes, state.nodes),
        dirty: state.dirty || meaningful,
        dragging: dragStart ? true : dragEnd ? false : state.dragging,
      }));
    },
    onEdgesChange: (changes) => {
      if (changes.some((c) => c.type === "remove")) checkpoint();
      set((state) => ({
        edges: applyEdgeChanges(changes, state.edges),
        dirty: state.dirty || changes.some((c) => c.type !== "select"),
      }));
    },
    addNode: (node) => {
      checkpoint();
      set((state) => ({ nodes: [...state.nodes, node], dirty: true }));
    },
    addEdge: (edge) => {
      checkpoint();
      set((state) => {
        // §11.3: stamp the source port family at creation time
        const family = edge.data?.family ?? edgeSourceFamily(edge, state.nodes, state.descriptors);
        const stamped: CanvasEdge = {
          ...edge,
          data: { ...(edge.data ?? { kind: "data" }), family },
        };
        return { edges: [...state.edges, stamped], dirty: true };
      });
    },
    removeEdge: (edgeId) => {
      checkpoint();
      set((state) => ({ edges: state.edges.filter((e) => e.id !== edgeId), dirty: true }));
    },
    select: (nodeId) => set({ selectedNodeId: nodeId }),
    renameNode: (nodeId, label) => {
      checkpoint();
      set((state) => ({
        dirty: true,
        nodes: state.nodes.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, label } } : node,
        ),
      }));
    },
    duplicateNode: (nodeId) => {
      const { nodes, descriptors } = get();
      const node = nodes.find((n) => n.id === nodeId);
      if (!node || node.id === "start" || node.id === "end" || isNoteNode(node)) return null;
      checkpoint();
      const taken = new Set(nodes.map((n) => n.id));
      const descriptor = descriptors.get(node.data.componentId);
      let id: string;
      if (descriptor) {
        id = newNodeId(descriptor, taken);
      } else {
        id = `${node.id}_copy`;
        while (taken.has(id)) id = `${id}_copy`;
      }
      const clone = structuredClone(node);
      // SPEC §11.8: secrets never travel on copy/duplicate
      if (descriptor) {
        for (const field of descriptor.fields) {
          if (field.type.includes("Secret")) delete clone.data.config[field.name];
        }
      }
      const duplicate: CanvasNode = {
        ...clone,
        id,
        selected: true,
        position: { x: node.position.x + 48, y: node.position.y + 48 },
      };
      set((state) => ({
        dirty: true,
        selectedNodeId: id,
        nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), duplicate],
      }));
      return id;
    },
    deleteNode: (nodeId) => {
      const node = get().nodes.find((n) => n.id === nodeId);
      if (!node || node.deletable === false) return; // start/end are required (E030)
      checkpoint();
      set((state) => ({
        dirty: true,
        nodes: state.nodes.filter((n) => n.id !== nodeId),
        edges: state.edges.filter((e) => e.source !== nodeId && e.target !== nodeId),
        selectedNodeId: state.selectedNodeId === nodeId ? null : state.selectedNodeId,
      }));
    },
    // collapse is canvas-only view state — snapshots carry it (undo restores),
    // but it never dirties the draft (nothing to persist, §11.2)
    toggleCollapsed: (nodeId) =>
      set((state) => ({
        nodes: state.nodes.map((node) =>
          node.id === nodeId
            ? { ...node, data: { ...node.data, collapsed: !node.data.collapsed } }
            : node,
        ),
      })),
    updateNodeConfig: (nodeId, config) => {
      // inline editing fires per keystroke — coalesce history to 1 step/800ms
      const now = Date.now();
      if (now - lastConfigCheckpoint > 800) checkpoint();
      lastConfigCheckpoint = now;
      set((state) => {
        const nodes = state.nodes.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, config } } : node,
        );
        // prune edges whose target port vanished (e.g. renamed {prompt_var})
        const node = nodes.find((n) => n.id === nodeId);
        const descriptor = node && state.descriptors.get(node.data.componentId);
        let edges = state.edges;
        if (descriptor) {
          const ports = indexPorts(descriptor, config);
          edges = state.edges.filter(
            (edge) =>
              edge.target !== nodeId ||
              edge.targetHandle === ROUTER_TARGET_HANDLE ||
              ports.inputs.has(edge.targetHandle ?? ""),
          );
        }
        return { dirty: true, nodes, edges };
      });
    },
    updateNoteText: (nodeId, text) => {
      checkpoint();
      set((state) => ({
        dirty: true,
        nodes: state.nodes.map((node) =>
          node.id === nodeId ? { ...node, data: { ...node.data, notes: text } } : node,
        ),
      }));
    },
    addNote: (position) => {
      checkpoint();
      const id = `note_${Date.now().toString(36)}`;
      set((state) => ({
        dirty: true,
        nodes: [
          ...state.nodes,
          {
            id,
            type: "note",
            deletable: true,
            position,
            data: {
              componentId: NOTE_COMPONENT,
              componentVersion: "",
              label: "",
              config: { color: "amber" },
              notes: "",
            },
          },
        ],
      }));
    },
    updateFlowMeta: (patch) =>
      set((state) =>
        state.baseSpec
          ? {
              dirty: true,
              baseSpec: { ...state.baseSpec, flow: { ...state.baseSpec.flow, ...patch } },
            }
          : {},
      ),
    setDiagnostics: (diagnostics) => set({ diagnostics }),
    currentSpec: () => {
      const { baseSpec, nodes, edges } = get();
      if (!baseSpec) throw new Error("no flow loaded");
      return canvasToSpec(baseSpec, nodes, edges);
    },
    markSaved: () => set({ dirty: false }),

    // ---------------------------------------------------------------- history
    undo: () => {
      const { past, future, nodes, edges } = get();
      const previous = past[past.length - 1];
      if (!previous) return;
      set({
        past: past.slice(0, -1),
        future: [...future, cloneGraph(nodes, edges)],
        nodes: previous.nodes,
        edges: previous.edges,
        dirty: true,
      });
    },
    redo: () => {
      const { past, future, nodes, edges } = get();
      const next = future[future.length - 1];
      if (!next) return;
      set({
        future: future.slice(0, -1),
        past: [...past, cloneGraph(nodes, edges)],
        nodes: next.nodes,
        edges: next.edges,
        dirty: true,
      });
    },

    // ---------------------------------------------------------------- clipboard
    copySelection: () => {
      const { nodes, edges, descriptors } = get();
      const picked = nodes.filter(
        (n) => n.selected && n.id !== "start" && n.id !== "end",
      );
      if (picked.length === 0) return 0;
      const ids = new Set(picked.map((n) => n.id));
      const cloned = structuredClone(picked);
      // SPEC §11.8: secrets are stripped on copy
      for (const node of cloned) {
        const descriptor = descriptors.get(node.data.componentId);
        if (!descriptor) continue;
        for (const field of descriptor.fields) {
          if (field.type.includes("Secret")) delete node.data.config[field.name];
        }
      }
      const internalEdges = structuredClone(
        edges.filter((e) => ids.has(e.source) && ids.has(e.target)),
      );
      set({ clipboard: { nodes: cloned, edges: internalEdges } });
      return cloned.length;
    },
    paste: () => {
      const { clipboard, nodes, descriptors } = get();
      if (!clipboard || clipboard.nodes.length === 0) return 0;
      checkpoint();
      const taken = new Set(nodes.map((n) => n.id));
      const idMap = new Map<string, string>();
      const newNodes: CanvasNode[] = clipboard.nodes.map((node) => {
        let id: string;
        if (isNoteNode(node)) {
          id = `note_${Date.now().toString(36)}_${idMap.size}`;
        } else {
          const descriptor = descriptors.get(node.data.componentId);
          id = descriptor
            ? newNodeId(descriptor, taken)
            : `${node.id}_copy_${idMap.size}`;
        }
        taken.add(id);
        idMap.set(node.id, id);
        return {
          ...structuredClone(node),
          id,
          selected: true,
          position: { x: node.position.x + 48, y: node.position.y + 48 },
        };
      });
      const newEdges: CanvasEdge[] = clipboard.edges.map((edge) => ({
        ...structuredClone(edge),
        id: newEdgeId(),
        source: idMap.get(edge.source) ?? edge.source,
        target: idMap.get(edge.target) ?? edge.target,
      }));
      set((state) => ({
        dirty: true,
        nodes: [...state.nodes.map((n) => ({ ...n, selected: false })), ...newNodes],
        edges: [...state.edges, ...newEdges],
      }));
      return newNodes.length;
    },

    // ---------------------------------------------------------------- layout
    autoLayout: () => {
      const { nodes, edges } = get();
      checkpoint();
      const flowNodes = nodes.filter((n) => !isNoteNode(n));
      const flowIds = new Set(flowNodes.map((n) => n.id));
      const control = edges.filter(
        (e) => e.data?.kind !== "tool" && flowIds.has(e.source) && flowIds.has(e.target),
      );
      const successors = new Map<string, string[]>();
      const indegree = new Map<string, number>(flowNodes.map((n) => [n.id, 0]));
      for (const edge of control) {
        successors.set(edge.source, [...(successors.get(edge.source) ?? []), edge.target]);
        indegree.set(edge.target, (indegree.get(edge.target) ?? 0) + 1);
      }
      // Kahn longest-path layering → column index. Guaranteed to terminate on
      // cyclic flows (loops are legal, §5: recursion_limit) — every node is
      // dequeued at most once, unlike a naive BFS relaxation.
      const depth = new Map<string, number>();
      const queue: string[] = [];
      for (const node of flowNodes) {
        if (indegree.get(node.id) === 0) {
          depth.set(node.id, 0);
          queue.push(node.id);
        }
      }
      while (queue.length) {
        const current = queue.shift()!;
        for (const next of successors.get(current) ?? []) {
          depth.set(next, Math.max(depth.get(next) ?? 0, depth.get(current)! + 1));
          const remaining = indegree.get(next)! - 1;
          indegree.set(next, remaining);
          if (remaining === 0) queue.push(next);
        }
      }
      // cycle members never reach indegree 0; those relaxed from a layered
      // predecessor already hold an approximate depth — the rest fall through
      // to the ++maxDepth columns below, same as unreachable nodes.
      // pure tool providers hang under the node they equip (§18.4)
      const providers = new Map<string, string>(); // provider id → agent id
      for (const edge of edges) {
        if (edge.data?.kind === "tool") providers.set(edge.source, edge.target);
      }
      let maxDepth = 0;
      for (const d of depth.values()) maxDepth = Math.max(maxDepth, d);
      for (const node of flowNodes) {
        if (!depth.has(node.id) && !providers.has(node.id)) {
          depth.set(node.id, ++maxDepth);
        }
      }
      const COL_W = 290;
      const ROW_H = 170;
      const columns = new Map<number, string[]>();
      for (const node of flowNodes) {
        if (providers.has(node.id)) continue;
        const d = depth.get(node.id) ?? 0;
        columns.set(d, [...(columns.get(d) ?? []), node.id]);
      }
      const target = new Map<string, { x: number; y: number }>();
      for (const [d, ids] of columns) {
        ids.sort();
        ids.forEach((id, index) => {
          target.set(id, { x: 80 + d * COL_W, y: 100 + index * ROW_H });
        });
      }
      // providers below their agent, fanned out horizontally
      const providerIndex = new Map<string, number>();
      for (const [provider, agent] of providers) {
        const base = target.get(agent) ?? { x: 80, y: 100 };
        const index = providerIndex.get(agent) ?? 0;
        providerIndex.set(agent, index + 1);
        target.set(provider, { x: base.x + index * 120, y: base.y + ROW_H });
      }
      set((state) => ({
        dirty: true,
        nodes: state.nodes.map((node) =>
          target.has(node.id) ? { ...node, position: target.get(node.id)! } : node,
        ),
      }));
    },

    // ---------------------------------------------------------------- run states (§11.2)
    applyRunEvent: (event) => {
      const nodeId = String(event.data?.node_id ?? "");
      set((state) => {
        // run lifecycle drives the §11.4 live-edge animation. A raised
        // interrupt parks the run (input_required) and closes the stream —
        // stop the flow animation; the amber node ring marks the wait.
        if (event.event === "run_started") return { runActive: true };
        if (event.event === "run_finished" || event.event === "run_cancelled") {
          return { runActive: false };
        }
        if (event.event === "run_resumed") {
          const runStates = Object.fromEntries(
            Object.entries(state.runStates).filter(([, s]) => s.status !== "interrupted"),
          );
          return { runActive: true, runStates };
        }
        if (!nodeId) return {};
        const runStates = { ...state.runStates };
        if (event.event === "node_started") {
          runStates[nodeId] = { status: "running" };
        } else if (event.event === "node_finished") {
          runStates[nodeId] = {
            status: "finished",
            durationMs: Number(event.data?.duration_ms ?? 0),
          };
        } else if (event.event === "node_error") {
          runStates[nodeId] = {
            status: "error",
            errorCode: String(event.data?.code ?? "RT103"),
          };
        } else if (event.event === "interrupt_raised") {
          // §11.2: HITL node waiting on input → gf-node-interrupted (was dead CSS)
          runStates[nodeId] = { status: "interrupted" };
          return { runStates, runActive: false };
        } else {
          return {};
        }
        return { runStates };
      });
    },
    resetRunStates: () => set({ runStates: {}, runActive: false }),
    setPartialTarget: (nodeId) => set({ partialTarget: nodeId }),
    applyCoercions: (coercions) => {
      const map = new Map(coercions.map((c) => [c.edge_id, c.coercion]));
      set((state) => ({
        edges: state.edges.map((edge) =>
          map.has(edge.id)
            ? { ...edge, data: { ...(edge.data ?? { kind: "data" }), coercion: map.get(edge.id) } }
            : edge,
        ),
      }));
    },

    // ---------------------------------------------------------------- run to node (§6.4)
    runToNode: async (nodeId) => {
      const { flow, dirty } = get();
      if (!flow) throw new Error("no flow loaded");
      // partial runs execute the STORED spec — persist the draft first
      if (dirty) {
        await api.flows.update(flow.id, get().currentSpec());
        set({ dirty: false });
      }
      set({ runStates: {}, partialTarget: nodeId });
      let preview = "";
      try {
        await streamRun(flow.id, { input_text: "", until_node: nodeId }, (event) => {
          get().applyRunEvent(event);
          if (event.event === "run_finished") {
            preview = String(event.data.result_preview ?? "");
          }
        });
      } finally {
        set({ partialTarget: null, runActive: false });
      }
      return preview;
    },
  };
});
