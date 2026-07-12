/**
 * React-Flow node/edge renderers. Ports are typed (text/json/message/
 * documents); the dot colour encodes the port type, identical on both sides
 * of a connectable pair.
 */

import {
  BaseEdge,
  getBezierPath,
  Handle,
  Position,
  type EdgeProps,
  type NodeProps,
} from "@xyflow/react";
import { Database, Flag, Play, Sparkles, Wrench, type LucideIcon } from "lucide-react";
import { memo } from "react";

import type { PortDecl, PortType } from "@/api/types";
import { cn } from "@/lib/utils";

import type { CanvasNode } from "./convert";
import { nodePorts } from "./guards";
import { issueNodeId, useBuilder } from "./store";

export const NODE_ICONS: Record<string, LucideIcon> = {
  play: Play,
  flag: Flag,
  sparkles: Sparkles,
  wrench: Wrench,
  database: Database,
};

const PORT_COLOR: Record<PortType, string> = {
  text: "var(--color-port-data)",
  json: "var(--color-port-table)",
  documents: "var(--color-port-documents)",
  message: "var(--color-port-message)",
};

function PortRow({
  port,
  side,
}: {
  port: PortDecl;
  side: "in" | "out";
}) {
  return (
    <div
      className={cn(
        "relative flex h-6 items-center text-[11px] text-text-2",
        side === "in" ? "justify-start pl-3" : "justify-end pr-3",
      )}
    >
      <span className="truncate font-mono">{port.label || port.name}</span>
      <Handle
        type={side === "in" ? "target" : "source"}
        id={port.name}
        position={side === "in" ? Position.Left : Position.Right}
        className="!h-2.5 !w-2.5 !border-2 !border-canvas"
        style={{ background: PORT_COLOR[port.type] }}
      />
    </div>
  );
}

export const FlowNode = memo(function FlowNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const catalog = useBuilder((s) => s.catalog);
  const issues = useBuilder((s) => s.issues);
  const infoByType = useBuilder((s) => s.infoByType);
  if (!catalog) return null;
  const def = data.def;
  const info = infoByType().get(def.type);
  const { inputs, outputs } = nodePorts(def, info, catalog);
  const Icon = NODE_ICONS[info?.icon ?? ""] ?? Sparkles;
  const nodeIssues = issues.filter((issue) => issueNodeId(issue.path) === id);
  const errorCount = nodeIssues.filter((i) => i.severity === "error").length;
  const warnCount = nodeIssues.length - errorCount;
  const rows = Math.max(inputs.length, outputs.length);

  return (
    <div
      className={cn(
        "min-w-44 rounded-node border bg-surface-1 shadow-lg shadow-black/25 transition-colors",
        selected ? "border-accent" : "border-border hover:border-border-strong",
      )}
    >
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Icon size={14} strokeWidth={1.75} className="shrink-0 text-accent" />
        <span className="truncate text-xs font-semibold text-text-1">
          {info?.label ?? def.type}
        </span>
        <span className="ml-auto font-mono text-[10px] text-text-3">{id}</span>
        {errorCount > 0 && (
          <span className="rounded-md bg-danger/15 px-1.5 font-mono text-[10px] text-danger">
            {errorCount}
          </span>
        )}
        {errorCount === 0 && warnCount > 0 && (
          <span className="rounded-md bg-warning/15 px-1.5 font-mono text-[10px] text-warning">
            {warnCount}
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 gap-x-4 py-1.5">
        <div>
          {inputs.map((port) => (
            <PortRow key={port.name} port={port} side="in" />
          ))}
        </div>
        <div className="col-start-2">
          {outputs.map((port) => (
            <PortRow key={port.name} port={port} side="out" />
          ))}
        </div>
        {rows === 0 && <div className="col-span-2 h-1" />}
      </div>
    </div>
  );
});

export function FlowEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
  selected,
}: EdgeProps) {
  const [path] = getBezierPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
  });
  return (
    <BaseEdge
      id={id}
      path={path}
      style={{
        stroke: selected ? "var(--color-accent)" : "var(--color-border-strong)",
        strokeWidth: 1.5,
      }}
    />
  );
}

export const nodeTypes = { flow: FlowNode };
export const edgeTypes = { flow: FlowEdge };
