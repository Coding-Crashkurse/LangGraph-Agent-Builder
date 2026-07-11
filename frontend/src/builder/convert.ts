/** FlowSpec ⇄ React-Flow conversion. Canvas mental model: output → input. */

import type { Edge, Node } from "@xyflow/react";

import type {
  ComponentDescriptor,
  EdgeKind,
  EdgeSpec,
  FlowSpec,
  NodeSpec,
  PortFamily,
  StickyNote,
} from "@/api/types";

import { indexPorts } from "./guards";

export interface CanvasNodeData extends Record<string, unknown> {
  componentId: string;
  componentVersion: string;
  label: string;
  config: Record<string, unknown>;
  notes: string;
  /** canvas-only view state (§11.2 collapse chevron) — never serialized */
  collapsed?: boolean;
}

export interface CanvasEdgeData extends Record<string, unknown> {
  kind: EdgeKind;
  coercion?: string;
  /** SOURCE port family (§11.3: edge stroke = source family color); canvas-only */
  family?: PortFamily;
}

export type CanvasNode = Node<CanvasNodeData>;
export type CanvasEdge = Edge<CanvasEdgeData>;

export const ROUTER_TARGET_HANDLE = "__in__";
/** sticky notes ride along as canvas nodes with this marker componentId (§11.8) */
export const NOTE_COMPONENT = "__note__";

export function isNoteNode(node: CanvasNode): boolean {
  return node.type === "note";
}

export function noteToNode(note: StickyNote): CanvasNode {
  return {
    id: note.id,
    type: "note",
    deletable: true,
    position: note.position ?? { x: 0, y: 0 },
    data: {
      componentId: NOTE_COMPONENT,
      componentVersion: "",
      label: "",
      config: { color: note.color ?? "amber" },
      notes: note.text ?? "",
    },
  };
}

/** Resolve the SOURCE port family of an edge (§11.3: stroke color) from the
 * source node's live port index. Router/tool edges have fixed families. */
export function edgeSourceFamily(
  edge: Pick<CanvasEdge, "source" | "sourceHandle" | "data">,
  nodes: CanvasNode[],
  descriptors: Map<string, ComponentDescriptor>,
): PortFamily | undefined {
  if (edge.data?.kind === "router") return "ROUTE";
  if (edge.data?.kind === "tool") return "TOOLSET";
  const node = nodes.find((n) => n.id === edge.source);
  const descriptor = node && descriptors.get(node.data.componentId);
  if (!node || !descriptor) return undefined;
  return indexPorts(descriptor, node.data.config).outputs.get(edge.sourceHandle ?? "")?.family;
}

/** Backfill `data.family` on edges that miss it (loaded before descriptors
 * arrived, or created by older canvas code). Edges that stay unresolvable are
 * returned untouched so a later pass can retry. */
export function withEdgeFamilies(
  nodes: CanvasNode[],
  edges: CanvasEdge[],
  descriptors: Map<string, ComponentDescriptor>,
): CanvasEdge[] {
  if (descriptors.size === 0) return edges;
  return edges.map((edge) => {
    if (edge.data?.family) return edge;
    const family = edgeSourceFamily(edge, nodes, descriptors);
    if (!family) return edge;
    return { ...edge, data: { ...(edge.data ?? { kind: "data" as EdgeKind }), family } };
  });
}

export function specToCanvas(
  spec: FlowSpec,
  descriptors?: Map<string, ComponentDescriptor>,
): { nodes: CanvasNode[]; edges: CanvasEdge[] } {
  const nodes: CanvasNode[] = spec.nodes.map((node) => ({
    id: node.id,
    type: "lga",
    // reserved nodes are required (E030) — Delete must not remove them
    deletable: node.id !== "start" && node.id !== "end",
    position: node.position ?? { x: 0, y: 0 },
    data: {
      componentId: node.component_id,
      componentVersion: node.component_version,
      label: node.label ?? "",
      config: node.config ?? {},
      notes: node.notes ?? "",
    },
  }));
  const edges: CanvasEdge[] = spec.edges.map((edge) => ({
    id: edge.id,
    source: edge.source.node,
    sourceHandle: edge.source.output,
    target: edge.target.node,
    targetHandle: edge.kind === "router" ? ROUTER_TARGET_HANDLE : edge.target.input,
    data: { kind: edge.kind },
    type: "lga",
  }));
  for (const note of spec.ui?.sticky_notes ?? []) {
    nodes.push(noteToNode(note));
  }
  return {
    nodes,
    edges: descriptors ? withEdgeFamilies(nodes, edges, descriptors) : edges,
  };
}

export function canvasToSpec(
  base: FlowSpec,
  nodes: CanvasNode[],
  edges: CanvasEdge[],
): FlowSpec {
  const stickyNotes: StickyNote[] = nodes.filter(isNoteNode).map((node) => ({
    id: node.id,
    text: node.data.notes,
    position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
    color: String(node.data.config.color ?? "amber"),
  }));
  const nodeSpecs: NodeSpec[] = nodes
    .filter((node) => !isNoteNode(node))
    .map((node) => ({
      id: node.id,
      component_id: node.data.componentId,
      component_version: node.data.componentVersion,
      label: node.data.label,
      config: node.data.config,
      position: { x: Math.round(node.position.x), y: Math.round(node.position.y) },
      notes: node.data.notes,
    }));
  const edgeSpecs: EdgeSpec[] = edges.map((edge) => ({
    id: edge.id,
    kind: edge.data?.kind ?? "data",
    source: { node: edge.source, output: edge.sourceHandle ?? "" },
    target: {
      node: edge.target,
      input: edge.targetHandle === ROUTER_TARGET_HANDLE ? "" : (edge.targetHandle ?? ""),
    },
  }));
  return {
    ...base,
    nodes: nodeSpecs,
    edges: edgeSpecs,
    ui: { ...(base.ui ?? {}), sticky_notes: stickyNotes },
  };
}

let edgeCounter = 0;

export function newEdgeId(): string {
  edgeCounter += 1;
  return `e${Date.now().toString(36)}${edgeCounter}`;
}

export function newNodeId(descriptor: ComponentDescriptor, taken: Set<string>): string {
  if (descriptor.component_id === "lga.io.start") return "start";
  if (descriptor.component_id === "lga.io.end") return "end";
  const base = descriptor.component_id.split(".").pop() ?? "node";
  let index = 1;
  let candidate = `${base}_${index}`;
  while (taken.has(candidate)) {
    index += 1;
    candidate = `${base}_${index}`;
  }
  return candidate;
}

/** Descriptor defaults as a config map. Node cards and the inspector both
 * resolve field values through the SAME `{...defaultConfig(d), ...config}`
 * merge so the two views of one field never disagree (e.g. after a
 * dynamic-field refresh returns fields whose defaults were never
 * materialized into config). */
export function defaultConfig(descriptor: ComponentDescriptor): Record<string, unknown> {
  const config: Record<string, unknown> = {};
  for (const field of descriptor.fields) {
    if (field.default !== null && field.default !== undefined && !field.port_only) {
      config[field.name] = field.default;
    }
  }
  return config;
}

export function emptyFlowSpec(name: string, slug: string): FlowSpec {
  return {
    schema_version: "1",
    // Serving is exclusive; A2A is the default surface for a new flow (SPEC §7.1).
    flow: { name, slug, description: "", a2a: { enabled: true }, mcp: { enabled: false } },
    nodes: [
      {
        id: "start",
        component_id: "lga.io.start",
        component_version: "1.0.0",
        config: {},
        position: { x: 80, y: 200 },
      },
      {
        id: "end",
        component_id: "lga.io.end",
        component_version: "1.0.0",
        config: {},
        position: { x: 640, y: 200 },
      },
    ],
    edges: [],
  };
}
