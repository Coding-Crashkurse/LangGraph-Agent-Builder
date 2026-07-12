/**
 * Builder canvas state (zustand). Single source of truth for the definition
 * being edited; `currentDefinition()` is what Save/Validate/Share send — the
 * backend remains the single serializer of the format.
 *
 * History: semantic mutations (add/connect/config/meta/delete/move) snapshot
 * into `past` before applying; rapid same-key mutations (typing) coalesce
 * into one undo step. Undo/redo restore nodes+edges+meta.
 */

import {
  applyEdgeChanges,
  applyNodeChanges,
  type Connection,
  type EdgeChange,
  type NodeChange,
} from "@xyflow/react";
import { create } from "zustand";

import type {
  FlowDefinition,
  NodeCatalog,
  NodeTypeInfo,
  SourcedIssue,
  ValidationResponse,
} from "@/api/types";

import {
  canvasToDefinition,
  type CanvasEdge,
  type CanvasNode,
  definitionToCanvas,
  edgeId,
  type FlowMeta,
  metaOf,
} from "./convert";
import { danglingEdgeIds, judgeConnection } from "./guards";

const ID_PREFIX: Record<string, string> = {
  llm_call: "call",
  mcp_tool: "tool",
  retrieval: "retrieve",
  start: "start",
  end: "end",
};

interface Snapshot {
  meta: FlowMeta;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
}

const HISTORY_LIMIT = 50;
const COALESCE_MS = 800;

export interface BuilderState {
  loaded: boolean;
  meta: FlowMeta;
  nodes: CanvasNode[];
  edges: CanvasEdge[];
  catalog: NodeCatalog | null;
  issues: SourcedIssue[];
  runtimeChecked: boolean;
  validated: boolean;
  dirty: boolean;
  selectedNodeId: string | null;
  past: Snapshot[];
  future: Snapshot[];

  infoByType: () => Map<string, NodeTypeInfo>;
  load: (definition: FlowDefinition, catalog: NodeCatalog) => void;
  currentDefinition: () => FlowDefinition;
  onNodesChange: (changes: NodeChange<CanvasNode>[]) => void;
  onEdgesChange: (changes: EdgeChange<CanvasEdge>[]) => void;
  onConnect: (connection: Connection) => void;
  isValidConnection: (connection: CanvasEdge | Connection) => boolean;
  addNode: (type: string, position: { x: number; y: number }) => void;
  updateNodeConfig: (nodeId: string, patch: Record<string, unknown>) => void;
  updateMeta: (patch: Partial<FlowMeta>) => void;
  undo: () => void;
  redo: () => void;
  setValidation: (response: ValidationResponse) => void;
  setIssues: (issues: SourcedIssue[]) => void;
  select: (nodeId: string | null) => void;
  markSaved: () => void;
  markDirty: () => void;
}

export const useBuilder = create<BuilderState>((set, get) => {
  // History bookkeeping lives in the closure — not reactive state.
  let lastKey = "";
  let lastAt = 0;
  let suppressHistory = false;
  let draggingNodes = false;

  const snapshot = (): Snapshot => {
    const state = get();
    return structuredClone({ meta: state.meta, nodes: state.nodes, edges: state.edges });
  };

  /** Push the CURRENT state to `past` (call before mutating). */
  const record = (key: string) => {
    if (suppressHistory) return;
    const now = Date.now();
    if (key === lastKey && now - lastAt < COALESCE_MS) {
      lastAt = now;
      return;
    }
    lastKey = key;
    lastAt = now;
    const entry = snapshot();
    set((state) => ({
      past: [...state.past.slice(-(HISTORY_LIMIT - 1)), entry],
      future: [],
    }));
  };

  const resetHistory = () => {
    lastKey = "";
    lastAt = 0;
    draggingNodes = false;
  };

  return {
    loaded: false,
    meta: { name: "", display_name: "", description: "", tags: [], expose: { kind: "a2a" } },
    nodes: [],
    edges: [],
    catalog: null,
    issues: [],
    runtimeChecked: false,
    validated: false,
    dirty: false,
    selectedNodeId: null,
    past: [],
    future: [],

    infoByType: () => new Map((get().catalog?.node_types ?? []).map((t) => [t.type, t])),

    load: (definition, catalog) => {
      resetHistory();
      const { nodes, edges } = definitionToCanvas(definition);
      set({
        loaded: true,
        meta: metaOf(definition),
        nodes,
        edges,
        catalog,
        issues: [],
        runtimeChecked: false,
        validated: false,
        dirty: false,
        selectedNodeId: null,
        past: [],
        future: [],
      });
    },

    currentDefinition: () => {
      const { meta, nodes, edges } = get();
      return canvasToDefinition(meta, nodes, edges);
    },

    onNodesChange: (changes) => {
      const semantic = changes.some((c) => c.type === "remove");
      if (semantic) record("delete");
      const drag = changes.find((c) => c.type === "position");
      if (drag && "dragging" in drag) {
        if (drag.dragging && !draggingNodes) {
          record("move");
          draggingNodes = true;
        }
        if (!drag.dragging) draggingNodes = false;
      }
      set((state) => ({
        nodes: applyNodeChanges(changes, state.nodes),
        // node moves are layout-only, but layout is part of the saved draft
        dirty: state.dirty || changes.some((c) => c.type !== "select"),
        validated: state.validated && !semantic,
      }));
      if (semantic) get().onEdgesChange([]); // re-prune edges against removed nodes
    },

    onEdgesChange: (changes) => {
      if (changes.some((c) => c.type === "remove")) record("delete");
      set((state) => {
        const prevEdges = state.edges;
        let edges = applyEdgeChanges(changes, prevEdges);
        const catalog = state.catalog;
        if (catalog) {
          const defs = state.nodes.map((n) => n.data.def);
          const refs = edges.map((e) => ({
            from: `${e.source}.${e.sourceHandle ?? ""}`,
            to: `${e.target}.${e.targetHandle ?? ""}`,
          }));
          const gone = danglingEdgeIds(defs, refs, get().infoByType(), catalog);
          edges = edges.filter((e) => !gone.has(e.id));
        }
        // Keep end.output_from in sync with the wire feeding Input: when the
        // edge that fed it disappears, fall back to another inbound wire or
        // clear it. Hand-typed refs that never had a wire are left alone.
        const feeds = (list: CanvasEdge[], endId: string, ref: string) =>
          list.some(
            (e) =>
              e.target === endId &&
              (e.targetHandle ?? "") === "input" &&
              `${e.source}.${e.sourceHandle ?? ""}` === ref,
          );
        let nodes = state.nodes;
        for (const node of state.nodes) {
          const def = node.data.def;
          if (def.type !== "end") continue;
          const ref = typeof def.config.output_from === "string" ? def.config.output_from : "";
          if (!ref || !feeds(prevEdges, node.id, ref) || feeds(edges, node.id, ref)) continue;
          const fallback = edges.find(
            (e) => e.target === node.id && (e.targetHandle ?? "") === "input",
          );
          const replacement = fallback
            ? `${fallback.source}.${fallback.sourceHandle ?? ""}`
            : "";
          nodes = nodes.map((n) =>
            n.id === node.id
              ? {
                  ...n,
                  data: { def: { ...def, config: { ...def.config, output_from: replacement } } },
                }
              : n,
          );
        }
        const synced = nodes !== state.nodes;
        return {
          edges,
          nodes,
          dirty: state.dirty || changes.length > 0 || synced,
          validated: state.validated && changes.length === 0 && !synced,
        };
      });
    },

    onConnect: (connection) => {
      if (!get().isValidConnection(connection)) return;
      const from = `${connection.source}.${connection.sourceHandle ?? ""}`;
      const to = `${connection.target}.${connection.targetHandle ?? ""}`;
      if (get().edges.some((e) => e.id === edgeId(from, to))) return;
      record(`connect:${from}->${to}`);
      set((state) => ({
        edges: [
          ...state.edges,
          {
            id: edgeId(from, to),
            type: "flow",
            source: connection.source,
            sourceHandle: connection.sourceHandle,
            target: connection.target,
            targetHandle: connection.targetHandle,
          },
        ],
        dirty: true,
        validated: false,
      }));
      // Wiring into End IS the declaration of the flow output — reflect the
      // gesture into config so nobody has to type "node.port" by hand. Part
      // of the same gesture → same history entry (suppressed).
      const target = get().nodes.find((n) => n.id === connection.target);
      if (target?.data.def.type === "end" && (connection.targetHandle ?? "") === "input") {
        suppressHistory = true;
        try {
          get().updateNodeConfig(target.id, { output_from: from });
        } finally {
          suppressHistory = false;
        }
      }
    },

    isValidConnection: (connection) => {
      const { catalog, nodes } = get();
      if (!catalog || !connection.source || !connection.target) return false;
      const source = nodes.find((n) => n.id === connection.source);
      const target = nodes.find((n) => n.id === connection.target);
      if (!source || !target) return false;
      return judgeConnection(
        { node: source.data.def, port: connection.sourceHandle ?? "" },
        { node: target.data.def, port: connection.targetHandle ?? "" },
        get().infoByType(),
        catalog,
      ).ok;
    },

    addNode: (type, position) => {
      const info = get().infoByType().get(type);
      if (!info) return;
      const prefix = ID_PREFIX[type] ?? type.replace(/[^a-z0-9_]/g, "_");
      const taken = new Set(get().nodes.map((n) => n.id));
      let index = 1;
      while (taken.has(`${prefix}_${index}`)) index += 1;
      const id = `${prefix}_${index}`;
      record(`add:${id}`); // unique key — quick successive adds stay separate undo steps
      set((state) => ({
        nodes: [
          ...state.nodes,
          {
            id,
            type: "flow",
            position,
            data: {
              def: {
                id,
                type,
                version: info.version,
                config: structuredClone(info.default_config ?? {}),
              },
            },
            deletable: type !== "start" && type !== "end",
          },
        ],
        dirty: true,
        validated: false,
        selectedNodeId: id,
      }));
    },

    updateNodeConfig: (nodeId, patch) => {
      record(`config:${nodeId}`);
      set((state) => ({
        nodes: state.nodes.map((node) =>
          node.id === nodeId
            ? {
                ...node,
                data: {
                  def: { ...node.data.def, config: { ...node.data.def.config, ...patch } },
                },
              }
            : node,
        ),
        dirty: true,
        validated: false,
      }));
      get().onEdgesChange([]); // prune edges whose ports vanished with the config
    },

    updateMeta: (patch) => {
      record("meta");
      set((state) => ({
        meta: { ...state.meta, ...patch },
        dirty: true,
        validated: false,
      }));
    },

    undo: () => {
      const { past } = get();
      if (past.length === 0) return;
      const previous = past[past.length - 1];
      const current = snapshot();
      resetHistory();
      set((state) => ({
        past: state.past.slice(0, -1),
        future: [current, ...state.future].slice(0, HISTORY_LIMIT),
        meta: previous.meta,
        nodes: previous.nodes,
        edges: previous.edges,
        dirty: true,
        validated: false,
        selectedNodeId: null,
      }));
    },

    redo: () => {
      const { future } = get();
      if (future.length === 0) return;
      const next = future[0];
      const current = snapshot();
      resetHistory();
      set((state) => ({
        future: state.future.slice(1),
        past: [...state.past.slice(-(HISTORY_LIMIT - 1)), current],
        meta: next.meta,
        nodes: next.nodes,
        edges: next.edges,
        dirty: true,
        validated: false,
        selectedNodeId: null,
      }));
    },

    setValidation: (response) => {
      set({ issues: response.issues, runtimeChecked: response.runtime_checked, validated: true });
    },

    setIssues: (issues) => set({ issues, validated: true }),

    select: (nodeId) => set({ selectedNodeId: nodeId }),
    markSaved: () => set({ dirty: false }),
    markDirty: () => set({ dirty: true, validated: false }),
  };
});

/** Errors block publish; warnings do not (SPEC §2.3). */
export function hasErrors(issues: SourcedIssue[]): boolean {
  return issues.some((issue) => issue.severity === "error");
}

/** Node id targeted by an issue path like `nodes/call_1/config/prompt`. */
export function issueNodeId(path: string): string | null {
  const match = /^nodes\/([a-z0-9_-]+)/.exec(path);
  return match ? match[1] : null;
}
