/** Canvas state (zustand) — server state lives in react-query. */

import {
  applyEdgeChanges,
  applyNodeChanges,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import { create } from "zustand";

import type { ComponentDescriptor, Diagnostic, FlowInfo, FlowSpec } from "@/api/types";

import type { CanvasEdge, CanvasNode } from "./convert";
import { canvasToSpec, specToCanvas } from "./convert";

interface BuilderState {
  flow: FlowInfo | null;
  baseSpec: FlowSpec | null; // flow-level settings (a2a/mcp/…) live here
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  descriptors: Map<string, ComponentDescriptor>;
  selectedNodeId: string | null;
  diagnostics: Diagnostic[];
  dirty: boolean;

  loadFlow: (flow: FlowInfo) => void;
  setDescriptors: (list: ComponentDescriptor[]) => void;
  onNodesChange: (changes: NodeChange<CanvasNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<CanvasEdge>[]) => void;
  addNode: (node: CanvasNode) => void;
  addEdge: (edge: CanvasEdge) => void;
  removeEdge: (edgeId: string) => void;
  select: (nodeId: string | null) => void;
  updateNodeConfig: (nodeId: string, config: Record<string, unknown>) => void;
  updateFlowMeta: (patch: Partial<FlowSpec["flow"]>) => void;
  setDiagnostics: (diagnostics: Diagnostic[]) => void;
  currentSpec: () => FlowSpec;
  markSaved: () => void;
}

export const useBuilder = create<BuilderState>((set, get) => ({
  flow: null,
  baseSpec: null,
  nodes: [],
  edges: [],
  descriptors: new Map(),
  selectedNodeId: null,
  diagnostics: [],
  dirty: false,

  loadFlow: (flow) => {
    const { nodes, edges } = specToCanvas(flow.spec);
    set({ flow, baseSpec: flow.spec, nodes, edges, dirty: false, diagnostics: [] });
  },
  setDescriptors: (list) =>
    set({ descriptors: new Map(list.map((d) => [d.component_id, d])) }),
  onNodesChange: (changes) =>
    set((state) => ({
      nodes: applyNodeChanges(changes, state.nodes),
      dirty: state.dirty || changes.some((c) => c.type !== "select" && c.type !== "dimensions"),
    })),
  onEdgesChange: (changes) =>
    set((state) => ({
      edges: applyEdgeChanges(changes, state.edges),
      dirty: state.dirty || changes.some((c) => c.type !== "select"),
    })),
  addNode: (node) => set((state) => ({ nodes: [...state.nodes, node], dirty: true })),
  addEdge: (edge) => set((state) => ({ edges: [...state.edges, edge], dirty: true })),
  removeEdge: (edgeId) =>
    set((state) => ({ edges: state.edges.filter((e) => e.id !== edgeId), dirty: true })),
  select: (nodeId) => set({ selectedNodeId: nodeId }),
  updateNodeConfig: (nodeId, config) =>
    set((state) => ({
      dirty: true,
      nodes: state.nodes.map((node) =>
        node.id === nodeId ? { ...node, data: { ...node.data, config } } : node,
      ),
    })),
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
}));
