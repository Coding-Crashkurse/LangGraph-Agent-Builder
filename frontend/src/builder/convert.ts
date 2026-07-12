/**
 * FlowDefinition ↔ React-Flow canvas. Canvas positions live ONLY in `layout`
 * (CLAUDE.md invariant 6); moving a node never changes semantic content. The
 * React Flow state is derived at load time and serialized back on save.
 */

import type { Edge as RFEdge, Node as RFNode } from "@xyflow/react";

import type { DefinitionNode, FlowDefinition } from "@/api/types";

export interface FlowMeta {
  name: string;
  display_name: string;
  description: string;
  tags: string[];
  expose: FlowDefinition["expose"];
}

export type CanvasNodeData = { def: DefinitionNode } & Record<string, unknown>;
export type CanvasNode = RFNode<CanvasNodeData>;
export type CanvasEdge = RFEdge;

export function edgeId(from: string, to: string): string {
  return `${from}->${to}`;
}

export function metaOf(definition: FlowDefinition): FlowMeta {
  return {
    name: definition.name,
    display_name: definition.display_name ?? "",
    description: definition.description ?? "",
    tags: definition.tags ?? [],
    expose: definition.expose ?? { kind: "a2a" },
  };
}

export function definitionToCanvas(definition: FlowDefinition): {
  nodes: CanvasNode[];
  edges: CanvasEdge[];
} {
  const positions = definition.layout?.nodes ?? {};
  const nodes: CanvasNode[] = definition.nodes.map((def, index) => ({
    id: def.id,
    type: "flow",
    position: positions[def.id] ?? { x: 80 + index * 260, y: 220 },
    data: { def },
    deletable: def.type !== "start" && def.type !== "end",
  }));
  const edges: CanvasEdge[] = definition.edges.map((edge) => {
    const [source, sourceHandle] = split(edge.from);
    const [target, targetHandle] = split(edge.to);
    return {
      id: edgeId(edge.from, edge.to),
      type: "flow",
      source,
      sourceHandle,
      target,
      targetHandle,
    };
  });
  return { nodes, edges };
}

export function canvasToDefinition(
  meta: FlowMeta,
  nodes: CanvasNode[],
  edges: CanvasEdge[],
): FlowDefinition {
  const layoutNodes: Record<string, { x: number; y: number }> = {};
  for (const node of nodes) {
    layoutNodes[node.id] = {
      x: Math.round(node.position.x),
      y: Math.round(node.position.y),
    };
  }
  return {
    schema_version: 1,
    name: meta.name,
    display_name: meta.display_name,
    description: meta.description,
    tags: meta.tags,
    expose: meta.expose,
    nodes: nodes.map((n) => n.data.def),
    edges: edges.map((e) => ({
      from: `${e.source}.${e.sourceHandle ?? ""}`,
      to: `${e.target}.${e.targetHandle ?? ""}`,
    })),
    layout: { nodes: layoutNodes },
  };
}

/** Starter definition for a fresh canvas: start + end, nothing wired. */
export function emptyDefinition(name: string): FlowDefinition {
  return {
    schema_version: 1,
    name,
    display_name: "",
    description: "",
    tags: [],
    expose: { kind: "a2a" },
    nodes: [
      {
        id: "start_1",
        type: "start",
        version: 1,
        config: {
          input_schema: {
            type: "object",
            properties: { message: { type: "string" } },
            required: ["message"],
          },
        },
      },
      { id: "end_1", type: "end", version: 1, config: { output_from: "" } },
    ],
    edges: [],
    layout: { nodes: { start_1: { x: 80, y: 240 }, end_1: { x: 640, y: 240 } } },
  };
}

function split(ref: string): [string, string] {
  const dot = ref.indexOf(".");
  return dot === -1 ? [ref, ""] : [ref.slice(0, dot), ref.slice(dot + 1)];
}
