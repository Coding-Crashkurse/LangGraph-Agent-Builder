/** Canvas node + edge renderers: family-colored handles (SPEC §11.3),
 * amber router outputs, dashed sky tool edges, start/end pills. */

import {
  BaseEdge,
  getBezierPath,
  Handle,
  Position,
  type EdgeProps,
  type NodeProps,
} from "@xyflow/react";
import { memo } from "react";

import { PORT_FAMILY_COLORS, type PortSpec } from "@/api/types";
import { cn } from "@/lib/utils";

import type { CanvasEdge, CanvasNode } from "./convert";
import { ROUTER_TARGET_HANDLE } from "./convert";
import { indexPorts } from "./guards";
import { useBuilder } from "./store";

const CATEGORY_ACCENTS: Record<string, string> = {
  llm: "border-l-violet-500",
  rag: "border-l-emerald-500",
  flow_control: "border-l-amber-500",
  tools: "border-l-sky-500",
  io: "border-l-zinc-400",
  data: "border-l-slate-400",
  testing: "border-l-pink-500",
};

function PortDot({
  id,
  port,
  side,
  offset,
  label,
}: {
  id: string;
  port: PortSpec;
  side: "in" | "out";
  offset: number;
  label?: string;
}) {
  const color = PORT_FAMILY_COLORS[port.family] ?? "#9ca3af";
  return (
    <Handle
      id={id}
      type={side === "in" ? "target" : "source"}
      position={side === "in" ? Position.Left : Position.Right}
      style={{
        top: offset,
        background: port.family === "ANY" ? "transparent" : color,
        border: `2px ${port.family === "ANY" ? "dashed" : "solid"} ${color}`,
        width: 10,
        height: 10,
      }}
      title={`${label ?? id} · ${port.schema_ref}${port.is_list ? "[]" : ""}`}
    />
  );
}

export const LgaNode = memo(function LgaNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const descriptors = useBuilder((s) => s.descriptors);
  const diagnostics = useBuilder((s) => s.diagnostics);
  const descriptor = descriptors.get(data.componentId);

  if (!descriptor) {
    return (
      <div className="rounded-lg border border-red-700 bg-surface-900 px-3 py-2 text-xs text-red-400">
        unknown component: {data.componentId}
      </div>
    );
  }

  const isPill = id === "start" || id === "end";
  const ports = indexPorts(descriptor, data.config);
  const inputs = [...ports.inputs.entries()];
  const outputs = [...ports.outputs.entries()];
  const nodeDiags = diagnostics.filter((d) => d.node_id === id);
  const errorCount = nodeDiags.filter((d) => d.severity === "error").length;
  const warnCount = nodeDiags.filter((d) => d.severity === "warning").length;

  const HEADER = 34;
  const ROW = 20;
  const rows = Math.max(inputs.length, outputs.length, 1);

  if (isPill) {
    return (
      <div
        className={cn(
          "relative rounded-full border bg-surface-800 px-5 py-2 text-sm font-semibold",
          id === "start" ? "border-emerald-600 text-emerald-300" : "border-zinc-500 text-zinc-200",
          selected && "ring-2 ring-accent-500",
        )}
      >
        {id === "start" ? "▶ start" : "■ end"}
        {inputs.map(([name, port], index) => (
          <PortDot key={name} id={name} port={port} side="in" offset={14 + index * 12} />
        ))}
        {outputs.map(([name, port], index) => (
          <PortDot key={name} id={name} port={port} side="out" offset={14 + index * 12} />
        ))}
      </div>
    );
  }

  return (
    <div
      className={cn(
        "relative min-w-[190px] rounded-lg border border-surface-700 border-l-4 bg-surface-900 shadow-md",
        CATEGORY_ACCENTS[descriptor.category] ?? "border-l-zinc-500",
        selected && "ring-2 ring-accent-500",
      )}
      style={{ paddingBottom: 6, minHeight: HEADER + rows * ROW }}
    >
      <div className="flex items-center gap-2 border-b border-surface-800 px-3 py-1.5">
        <span className="truncate text-[13px] font-medium text-zinc-100">
          {data.label || descriptor.display_name}
        </span>
        {descriptor.beta && (
          <span className="rounded bg-violet-900/60 px-1 text-[9px] font-bold text-violet-300">
            BETA
          </span>
        )}
        {descriptor.node_kind === "interrupt" && (
          <span className="rounded bg-amber-900/60 px-1 text-[9px] font-bold text-amber-300">
            HITL
          </span>
        )}
        <span className="ml-auto flex gap-1">
          {errorCount > 0 && (
            <span className="rounded-full bg-red-900/70 px-1.5 text-[10px] font-bold text-red-300">
              {errorCount}
            </span>
          )}
          {warnCount > 0 && (
            <span className="rounded-full bg-amber-900/70 px-1.5 text-[10px] font-bold text-amber-300">
              {warnCount}
            </span>
          )}
        </span>
      </div>
      <div className="px-3 pt-1 text-[10px] text-zinc-500">{id}</div>

      {/* implicit control-in for router edges */}
      <Handle
        id={ROUTER_TARGET_HANDLE}
        type="target"
        position={Position.Top}
        style={{ background: "#f59e0b", width: 8, height: 8, opacity: 0.85 }}
        title="control in (router branches)"
      />
      {inputs.map(([name, port], index) => (
        <div key={name}>
          <PortDot id={name} port={port} side="in" offset={HEADER + index * ROW} />
          <span
            className="absolute text-[10px] text-zinc-400"
            style={{ left: 10, top: HEADER + index * ROW - 8 }}
          >
            {name}
          </span>
        </div>
      ))}
      {outputs.map(([name, port], index) => (
        <div key={name}>
          <PortDot id={name} port={port} side="out" offset={HEADER + index * ROW} />
          <span
            className={cn(
              "absolute text-right text-[10px]",
              port.family === "ROUTE" ? "font-semibold text-amber-400" : "text-zinc-400",
            )}
            style={{ right: 10, top: HEADER + index * ROW - 8 }}
          >
            {name}
          </span>
        </div>
      ))}
    </div>
  );
});

export function LgaEdge(props: EdgeProps<CanvasEdge>) {
  const [path] = getBezierPath(props);
  const kind = props.data?.kind ?? "data";
  const style =
    kind === "tool"
      ? { stroke: "#0ea5e9", strokeDasharray: "6 4", strokeWidth: 1.6 }
      : kind === "router"
        ? { stroke: "#f59e0b", strokeWidth: 1.8 }
        : { stroke: "#71717a", strokeWidth: 1.6 };
  return <BaseEdge id={props.id} path={path} style={style} />;
}

export const nodeTypes = { lga: LgaNode };
export const edgeTypes = { lga: LgaEdge };
