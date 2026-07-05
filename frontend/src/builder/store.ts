import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import { create } from "zustand";

import type { ComponentInfo, Flow, ValidationIssue } from "@/api/types";
import { toast } from "@/components/ui/toast";
import {
  ATTACH_SOURCE_HANDLE,
  ATTACH_TARGET_HANDLE,
  type CanvasNode,
  type ComponentCanvasNode,
  specToCanvas,
} from "./convert";
import { checkConnection } from "./guards";
import { defaultsFromSchema } from "./forms/schema";

interface BuilderState {
  flow: Flow | null;
  components: Record<string, ComponentInfo>;
  nodes: CanvasNode[];
  edges: Edge[];
  selectedNodeId: string | null;
  issues: ValidationIssue[];
  dirty: boolean;

  init: (flow: Flow, components: ComponentInfo[]) => void;
  onNodesChange: (changes: NodeChange<CanvasNode>[]) => void;
  onEdgesChange: (changes: EdgeChange[]) => void;
  onConnect: (connection: Connection) => void;
  addComponent: (info: ComponentInfo, position: { x: number; y: number }) => void;
  updateConfig: (nodeId: string, config: Record<string, unknown>) => void;
  select: (nodeId: string | null) => void;
  setIssues: (issues: ValidationIssue[]) => void;
  markSaved: (flow: Flow) => void;
}

export const useBuilder = create<BuilderState>((set, get) => ({
  flow: null,
  components: {},
  nodes: [],
  edges: [],
  selectedNodeId: null,
  issues: [],
  dirty: false,

  init: (flow, componentList) => {
    const components = Object.fromEntries(componentList.map((c) => [c.name, c]));
    const { nodes, edges } = specToCanvas(flow, components);
    set({ flow, components, nodes, edges, dirty: false, issues: [], selectedNodeId: null });
  },

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

  onConnect: (connection) => {
    const { nodes, edges } = get();
    const verdict = checkConnection(connection, nodes, edges);
    if (!verdict.ok) {
      toast.error(verdict.reason ?? "invalid connection");
      return;
    }
    const isAttach = connection.targetHandle === ATTACH_TARGET_HANDLE;
    const label =
      !isAttach &&
      connection.sourceHandle &&
      connection.sourceHandle !== "out" &&
      connection.sourceHandle !== ATTACH_SOURCE_HANDLE
        ? connection.sourceHandle
        : undefined;
    set((state) => ({
      edges: addEdge(
        {
          ...connection,
          type: isAttach ? "attach" : "default",
          animated: !isAttach,
          label,
        },
        state.edges,
      ),
      dirty: true,
    }));
  },

  addComponent: (info, position) => {
    const { nodes } = get();
    const base = info.name.replace(/[^a-zA-Z0-9]+/g, "_");
    let index = 1;
    let id = `${base}_${index}`;
    const taken = new Set(nodes.map((n) => n.id));
    while (taken.has(id)) id = `${base}_${++index}`;
    const node: ComponentCanvasNode = {
      id,
      type: "component",
      position,
      data: {
        component: info.name,
        componentVersion: info.version,
        config: defaultsFromSchema(info.config_json_schema),
        info,
        issues: [],
      },
    };
    set((state) => ({ nodes: [...state.nodes, node], dirty: true, selectedNodeId: id }));
  },

  updateConfig: (nodeId, config) =>
    set((state) => ({
      dirty: true,
      nodes: state.nodes.map((node) =>
        node.id === nodeId && node.type === "component"
          ? { ...node, data: { ...node.data, config } }
          : node,
      ),
    })),

  select: (nodeId) => set({ selectedNodeId: nodeId }),

  setIssues: (issues) =>
    set((state) => ({
      issues,
      nodes: state.nodes.map((node) =>
        node.type === "component"
          ? {
              ...node,
              data: { ...node.data, issues: issues.filter((i) => i.node_id === node.id) },
            }
          : node,
      ),
    })),

  markSaved: (flow) => set({ flow, dirty: false }),
}));
