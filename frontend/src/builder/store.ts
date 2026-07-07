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

import type { ComponentDescriptor, Diagnostic, FlowInfo, FlowSpec } from "@/api/types";

import type { CanvasEdge, CanvasNode } from "./convert";
import {
  canvasToSpec,
  isNoteNode,
  newEdgeId,
  newNodeId,
  NOTE_COMPONENT,
  ROUTER_TARGET_HANDLE,
  specToCanvas,
} from "./convert";
import { indexPorts } from "./guards";

interface Snapshot {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

const HISTORY_LIMIT = 50;

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

  loadFlow: (flow: FlowInfo) => void;
  setDescriptors: (list: ComponentDescriptor[]) => void;
  onNodesChange: (changes: NodeChange<CanvasNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<CanvasEdge>[]) => void;
  addNode: (node: CanvasNode) => void;
  addEdge: (edge: CanvasEdge) => void;
  removeEdge: (edgeId: string) => void;
  select: (nodeId: string | null) => void;
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

    loadFlow: (flow) => {
      const { nodes, edges } = specToCanvas(flow.spec);
      set({
        flow,
        baseSpec: flow.spec,
        nodes,
        edges,
        dirty: false,
        diagnostics: [],
        past: [],
        future: [],
      });
    },
    setDescriptors: (list) => set({ descriptors: new Map(list.map((d) => [d.component_id, d])) }),

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
      set((state) => ({ edges: [...state.edges, edge], dirty: true }));
    },
    removeEdge: (edgeId) => {
      checkpoint();
      set((state) => ({ edges: state.edges.filter((e) => e.id !== edgeId), dirty: true }));
    },
    select: (nodeId) => set({ selectedNodeId: nodeId }),
    updateNodeConfig: (nodeId, config) => {
      checkpoint();
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
      const control = edges.filter((e) => e.data?.kind !== "tool");
      const successors = new Map<string, string[]>();
      for (const edge of control) {
        successors.set(edge.source, [...(successors.get(edge.source) ?? []), edge.target]);
      }
      // BFS depth from start → column index
      const depth = new Map<string, number>();
      const queue: string[] = [];
      if (flowNodes.some((n) => n.id === "start")) {
        depth.set("start", 0);
        queue.push("start");
      }
      while (queue.length) {
        const current = queue.shift()!;
        for (const next of successors.get(current) ?? []) {
          if (!depth.has(next) || depth.get(next)! < depth.get(current)! + 1) {
            depth.set(next, depth.get(current)! + 1);
            if (!queue.includes(next)) queue.push(next);
          }
        }
      }
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
  };
});
