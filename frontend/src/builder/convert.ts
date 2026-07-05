/** FlowSpec <-> React Flow canvas mapping.
 * __start__/__end__ are canvas-only terminal nodes (never persisted in
 * FlowSpec.nodes); their positions are derived from the graph bounds. */

import type { Edge, Node } from "@xyflow/react";

import {
  END_NODE,
  START_NODE,
  type ComponentInfo,
  type EdgeSpec,
  type Flow,
  type NodeSpec,
  type ValidationIssue,
} from "@/api/types";

export interface ComponentNodeData extends Record<string, unknown> {
  component: string;
  componentVersion: number;
  config: Record<string, unknown>;
  info?: ComponentInfo;
  issues: ValidationIssue[];
}

export interface TerminalNodeData extends Record<string, unknown> {
  terminal: "start" | "end";
}

export type ComponentCanvasNode = Node<ComponentNodeData, "component">;
export type TerminalCanvasNode = Node<TerminalNodeData, "terminal">;
export type CanvasNode = ComponentCanvasNode | TerminalCanvasNode;

export const ATTACH_SOURCE_HANDLE = "attach-out";
export const ATTACH_TARGET_HANDLE = "attach";
export const CONTROL_IN_HANDLE = "in";
export const CONTROL_OUT_HANDLE = "out";

export function routerOutputs(
  info: ComponentInfo | undefined,
  config: Record<string, unknown>,
): string[] {
  if (!info || info.kind !== "router") return [];
  if (info.outputs_static?.length) return info.outputs_static;
  if (info.outputs_from_config) {
    const value = config[info.outputs_from_config];
    if (Array.isArray(value)) return value.map(String);
  }
  return [];
}

export function specToCanvas(
  flow: Flow,
  components: Record<string, ComponentInfo>,
): { nodes: CanvasNode[]; edges: Edge[] } {
  const componentNodes: ComponentCanvasNode[] = flow.nodes.map((node) => ({
    id: node.id,
    type: "component",
    position: node.position ?? { x: 0, y: 0 },
    data: {
      component: node.component,
      componentVersion: node.component_version,
      config: node.config ?? {},
      info: components[node.component],
      issues: [],
    },
  }));

  const xs = componentNodes.map((n) => n.position.x);
  const ys = componentNodes.map((n) => n.position.y);
  const midY = ys.length ? ys.reduce((a, b) => a + b, 0) / ys.length : 140;
  const minX = xs.length ? Math.min(...xs) : 300;
  const maxX = xs.length ? Math.max(...xs) : 300;

  const terminals: TerminalCanvasNode[] = [
    {
      id: START_NODE,
      type: "terminal",
      position: { x: minX - 190, y: midY },
      data: { terminal: "start" },
      deletable: false,
    },
    {
      id: END_NODE,
      type: "terminal",
      position: { x: maxX + 260, y: midY },
      data: { terminal: "end" },
      deletable: false,
    },
  ];

  const edges: Edge[] = flow.edges.map((edge, index) => canvasEdge(edge, index));
  return { nodes: [...terminals, ...componentNodes], edges };
}

export function canvasEdge(edge: EdgeSpec, index: number | string): Edge {
  const isAttach = edge.kind === "attach";
  return {
    id: `e-${index}-${edge.source}-${edge.source_handle ?? ""}-${edge.target}`,
    source: edge.source,
    target: edge.target,
    sourceHandle: isAttach ? ATTACH_SOURCE_HANDLE : (edge.source_handle ?? CONTROL_OUT_HANDLE),
    targetHandle: isAttach ? ATTACH_TARGET_HANDLE : CONTROL_IN_HANDLE,
    type: isAttach ? "attach" : "default",
    animated: !isAttach,
    label: !isAttach && edge.source_handle ? edge.source_handle : undefined,
  };
}

export function canvasToSpec(
  nodes: CanvasNode[],
  edges: Edge[],
): { nodes: NodeSpec[]; edges: EdgeSpec[] } {
  const specNodes: NodeSpec[] = nodes
    .filter((node): node is ComponentCanvasNode => node.type === "component")
    .map((node) => ({
      id: node.id,
      component: node.data.component,
      component_version: node.data.componentVersion,
      config: node.data.config,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
    }));

  const specEdges: EdgeSpec[] = edges.map((edge) => {
    const isAttach = edge.targetHandle === ATTACH_TARGET_HANDLE;
    if (isAttach) {
      return { kind: "attach", source: edge.source, target: edge.target };
    }
    const handle =
      edge.sourceHandle && edge.sourceHandle !== CONTROL_OUT_HANDLE ? edge.sourceHandle : null;
    return { kind: "control", source: edge.source, source_handle: handle, target: edge.target };
  });

  return { nodes: specNodes, edges: specEdges };
}
