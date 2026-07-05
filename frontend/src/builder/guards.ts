/** Client-side edge guards mirroring the compiler rules (CLAUDE.md §14.1). */

import type { Connection, Edge } from "@xyflow/react";

import { END_NODE, START_NODE } from "@/api/types";
import {
  ATTACH_SOURCE_HANDLE,
  ATTACH_TARGET_HANDLE,
  type CanvasNode,
  routerOutputs,
} from "./convert";

export interface GuardResult {
  ok: boolean;
  reason?: string;
}

export function checkConnection(
  connection: Connection,
  nodes: CanvasNode[],
  edges: Edge[],
): GuardResult {
  const source = nodes.find((n) => n.id === connection.source);
  const target = nodes.find((n) => n.id === connection.target);
  if (!source || !target) return { ok: false, reason: "unknown node" };

  const wantsAttach =
    connection.sourceHandle === ATTACH_SOURCE_HANDLE ||
    connection.targetHandle === ATTACH_TARGET_HANDLE;

  const sourceInfo = source.type === "component" ? source.data.info : undefined;
  const targetInfo = target.type === "component" ? target.data.info : undefined;

  if (wantsAttach) {
    if (
      connection.sourceHandle !== ATTACH_SOURCE_HANDLE ||
      connection.targetHandle !== ATTACH_TARGET_HANDLE
    ) {
      return { ok: false, reason: "tool providers connect to the attachment port only" };
    }
    if (sourceInfo?.kind !== "tool_provider") {
      return { ok: false, reason: "attach edges must start at a tool provider" };
    }
    const kind = sourceInfo.attachment_kind ?? "tools";
    if (!targetInfo?.accepts_attachments.includes(kind)) {
      return { ok: false, reason: `${target.id} does not accept ${kind} attachments` };
    }
    const duplicate = edges.some(
      (e) => e.source === source.id && e.target === target.id && e.targetHandle === ATTACH_TARGET_HANDLE,
    );
    if (duplicate) return { ok: false, reason: "already attached" };
    return { ok: true };
  }

  // control edge rules -------------------------------------------------------
  if (sourceInfo?.kind === "tool_provider" || targetInfo?.kind === "tool_provider") {
    return { ok: false, reason: "tool providers are not control-flow nodes" };
  }
  if (source.id === END_NODE) return { ok: false, reason: "__end__ has no outputs" };
  if (target.id === START_NODE) return { ok: false, reason: "__start__ has no inputs" };

  const controlOut = edges.filter(
    (e) => e.source === source.id && e.targetHandle !== ATTACH_TARGET_HANDLE,
  );

  if (source.id === START_NODE) {
    if (controlOut.length > 0) return { ok: false, reason: "__start__ already has an edge" };
    return { ok: true };
  }

  if (sourceInfo?.kind === "router") {
    const outputs = routerOutputs(sourceInfo, source.type === "component" ? source.data.config : {});
    const handle = connection.sourceHandle ?? "";
    if (!outputs.includes(handle)) {
      return { ok: false, reason: `router output '${handle}' is not one of: ${outputs.join(", ")}` };
    }
    if (controlOut.some((e) => e.sourceHandle === handle)) {
      return { ok: false, reason: `output '${handle}' is already wired` };
    }
    return { ok: true };
  }

  if (controlOut.length > 0) {
    return { ok: false, reason: "only one outgoing control edge per node" };
  }
  return { ok: true };
}
