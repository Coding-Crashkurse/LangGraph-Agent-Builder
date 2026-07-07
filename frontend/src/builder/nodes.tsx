/** Canvas node + edge renderers (SPEC §11.3): family-colored handles, amber
 * router outputs, dashed sky tool edges, start/end pills. While dragging a
 * connection, incompatible handles dim; hovering a port shows a typed tooltip. */

import {
  BaseEdge,
  getBezierPath,
  Handle,
  Position,
  useConnection,
  type EdgeProps,
  type NodeProps,
} from "@xyflow/react";
import { memo, useState } from "react";

import { PORT_FAMILY_COLORS, type PortSpec } from "@/api/types";
import { cn } from "@/lib/utils";

import type { CanvasEdge, CanvasNode } from "./convert";
import { ROUTER_TARGET_HANDLE } from "./convert";
import { compatSummary, indexPorts, judgeConnection } from "./guards";
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

interface PortTooltip {
  name: string;
  port: PortSpec;
  side: "in" | "out";
  top: number;
}

/** Is `port` a legal partner for the connection currently being dragged? */
function useHandleDimmer(nodeId: string) {
  const connection = useConnection();
  const descriptors = useBuilder((s) => s.descriptors);
  const nodes = useBuilder((s) => s.nodes);

  if (!connection.inProgress || !connection.fromHandle || !connection.fromNode) {
    return () => false;
  }
  const fromNode = nodes.find((n) => n.id === connection.fromNode?.id);
  const fromDescriptor = fromNode && descriptors.get(fromNode.data.componentId);
  if (!fromNode || !fromDescriptor) return () => false;
  const fromPorts = indexPorts(fromDescriptor, fromNode.data.config);
  const fromType = connection.fromHandle.type; // "source" | "target"
  const fromId = connection.fromHandle.id ?? "";
  const fromPort =
    fromType === "source" ? fromPorts.outputs.get(fromId) : fromPorts.inputs.get(fromId);

  return (port: PortSpec | undefined, side: "in" | "out", handleId: string): boolean => {
    // the handle the drag started from stays bright
    if (connection.fromNode?.id === nodeId && fromId === handleId) return false;
    if (fromType === "source") {
      if (side === "out") return true; // outputs can't receive a source drag
      const verdict = judgeConnection(fromPort, port, handleId === ROUTER_TARGET_HANDLE);
      return !verdict.ok;
    }
    // drag started from an input: only outputs are candidates
    if (side === "in") return true;
    const targetIsRouterSink = fromId === ROUTER_TARGET_HANDLE;
    const verdict = judgeConnection(
      port,
      targetIsRouterSink ? undefined : fromPort,
      targetIsRouterSink,
    );
    return !verdict.ok;
  };
}

function PortDot({
  id,
  port,
  side,
  offset,
  dimmed,
  onHover,
  position,
  crossOffset,
}: {
  id: string;
  port: PortSpec;
  side: "in" | "out";
  offset: number;
  dimmed: boolean;
  onHover: (tooltip: PortTooltip | null) => void;
  /** SPEC §18.4: left=data-in, right=data-out, top=toolset-out, bottom=tools-in */
  position?: Position;
  /** horizontal placement (%) for top/bottom handles */
  crossOffset?: number;
}) {
  const color = PORT_FAMILY_COLORS[port.family] ?? "#9ca3af";
  const pos = position ?? (side === "in" ? Position.Left : Position.Right);
  const vertical = pos === Position.Top || pos === Position.Bottom;
  return (
    <Handle
      id={id}
      type={side === "in" ? "target" : "source"}
      position={pos}
      onMouseEnter={() => onHover({ name: id, port, side, top: vertical ? 0 : offset })}
      onMouseLeave={() => onHover(null)}
      style={{
        ...(vertical ? { left: `${crossOffset ?? 50}%` } : { top: offset }),
        background: port.family === "ANY" ? "transparent" : color,
        border: `2px ${port.family === "ANY" ? "dashed" : "solid"} ${color}`,
        width: 10,
        height: 10,
        opacity: dimmed ? 0.15 : 1,
        transition: "opacity 120ms, transform 120ms",
        transform: dimmed ? "scale(0.8)" : "scale(1)",
      }}
    />
  );
}

function PortTooltipCard({ tooltip, nodeWidth }: { tooltip: PortTooltip; nodeWidth?: number }) {
  const color = PORT_FAMILY_COLORS[tooltip.port.family] ?? "#9ca3af";
  return (
    <div
      className="pointer-events-none absolute z-50 w-56 rounded-md border border-surface-700 bg-surface-950/95 px-2.5 py-1.5 shadow-xl"
      style={
        tooltip.side === "in"
          ? { right: (nodeWidth ?? 190) + 8, top: tooltip.top - 12 }
          : { left: (nodeWidth ?? 190) + 8, top: tooltip.top - 12 }
      }
    >
      <p className="flex items-center gap-1.5 text-[11px] font-semibold text-zinc-100">
        <span
          className="inline-block h-2 w-2 rounded-full"
          style={{ background: color }}
        />
        {tooltip.name}
        <span className="font-normal text-zinc-500">
          {tooltip.side === "in" ? "input" : "output"}
        </span>
      </p>
      <p className="mt-0.5 font-mono text-[10px]" style={{ color }}>
        {tooltip.port.schema_ref}
        {tooltip.port.is_list ? "[]" : ""} · {tooltip.port.family}
      </p>
      <p className="mt-0.5 text-[10px] text-zinc-400">
        {compatSummary(tooltip.port, tooltip.side)}
      </p>
    </div>
  );
}

export const LgaNode = memo(function LgaNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const descriptors = useBuilder((s) => s.descriptors);
  const diagnostics = useBuilder((s) => s.diagnostics);
  const descriptor = descriptors.get(data.componentId);
  const dimFor = useHandleDimmer(id);
  const [tooltip, setTooltip] = useState<PortTooltip | null>(null);

  if (!descriptor) {
    return (
      <div className="rounded-lg border border-red-700 bg-surface-900 px-3 py-2 text-xs text-red-400">
        unknown component: {data.componentId}
      </div>
    );
  }

  const isPill = id === "start" || id === "end";
  const ports = indexPorts(descriptor, data.config);
  // SPEC §18.4 handle geometry: toolset ports live on top/bottom, data left/right
  const allInputs = [...ports.inputs.entries()];
  const allOutputs = [...ports.outputs.entries()];
  const inputs = allInputs.filter(([, p]) => p.family !== "TOOLSET");
  const toolInputs = allInputs.filter(([, p]) => p.family === "TOOLSET");
  const outputs = allOutputs.filter(([, p]) => p.family !== "TOOLSET");
  const toolOutputs = allOutputs.filter(([, p]) => p.family === "TOOLSET");
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
          <PortDot
            key={name}
            id={name}
            port={port}
            side="in"
            offset={14 + index * 14}
            dimmed={dimFor(port, "in", name)}
            onHover={setTooltip}
          />
        ))}
        {outputs.map(([name, port], index) => (
          <PortDot
            key={name}
            id={name}
            port={port}
            side="out"
            offset={14 + index * 14}
            dimmed={dimFor(port, "out", name)}
            onHover={setTooltip}
          />
        ))}
        {tooltip && <PortTooltipCard tooltip={tooltip} nodeWidth={120} />}
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
      style={{ paddingBottom: toolInputs.length ? 16 : 6, minHeight: HEADER + rows * ROW }}
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

      {/* implicit control-in for router branches */}
      <Handle
        id={ROUTER_TARGET_HANDLE}
        type="target"
        position={Position.Top}
        onMouseEnter={() =>
          setTooltip({
            name: "control in",
            port: {
              schema_ref: "lga:Route",
              json_schema: {},
              family: "ROUTE",
              is_list: false,
            },
            side: "in",
            top: 0,
          })
        }
        onMouseLeave={() => setTooltip(null)}
        style={{
          background: "#f59e0b",
          width: 8,
          height: 8,
          opacity: dimFor(undefined, "in", ROUTER_TARGET_HANDLE) ? 0.15 : 0.9,
          transition: "opacity 120ms",
        }}
      />
      {inputs.map(([name, port], index) => (
        <div key={name}>
          <PortDot
            id={name}
            port={port}
            side="in"
            offset={HEADER + index * ROW}
            dimmed={dimFor(port, "in", name)}
            onHover={setTooltip}
          />
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
          <PortDot
            id={name}
            port={port}
            side="out"
            offset={HEADER + index * ROW}
            dimmed={dimFor(port, "out", name)}
            onHover={setTooltip}
          />
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

      {/* §18.4: toolset OUT on top (providers point up to the agent they equip) */}
      {toolOutputs.map(([name, port], index) => (
        <PortDot
          key={name}
          id={name}
          port={port}
          side="out"
          offset={0}
          position={Position.Top}
          crossOffset={72 + index * 14}
          dimmed={dimFor(port, "out", name)}
          onHover={setTooltip}
        />
      ))}
      {/* §18.4: tools IN on the bottom (tools hang below the agent) */}
      {toolInputs.map(([name, port], index) => (
        <div key={name}>
          <PortDot
            id={name}
            port={port}
            side="in"
            offset={0}
            position={Position.Bottom}
            crossOffset={50 + index * 14}
            dimmed={dimFor(port, "in", name)}
            onHover={setTooltip}
          />
          <span
            className="absolute bottom-0 left-1/2 -translate-x-1/2 text-[9px] font-medium text-sky-400"
            style={{ bottom: -1 }}
          >
            {name}
          </span>
        </div>
      ))}
      {tooltip && <PortTooltipCard tooltip={tooltip} />}
    </div>
  );
});

const NOTE_COLORS: Record<string, string> = {
  amber: "bg-amber-200/95 border-amber-400 text-amber-950",
  sky: "bg-sky-200/95 border-sky-400 text-sky-950",
  emerald: "bg-emerald-200/95 border-emerald-400 text-emerald-950",
};

export const NoteNode = memo(function NoteNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const updateNoteText = useBuilder((s) => s.updateNoteText);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(data.notes ?? ""));

  const commit = () => {
    setEditing(false);
    if (draft !== data.notes) updateNoteText(id, draft);
  };

  return (
    <div
      className={cn(
        "w-52 rounded-md border p-2 text-[11px] leading-snug shadow-md",
        NOTE_COLORS[String(data.config?.color ?? "amber")] ?? NOTE_COLORS.amber,
        selected && "ring-2 ring-accent-500",
      )}
      onDoubleClick={() => {
        setDraft(String(data.notes ?? ""));
        setEditing(true);
      }}
    >
      {editing ? (
        <textarea
          autoFocus
          value={draft}
          rows={Math.max(3, draft.split("\n").length)}
          onChange={(e) => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={(e) => {
            if (e.key === "Escape") commit();
            e.stopPropagation(); // keep Delete/Backspace inside the textarea
          }}
          className="nodrag w-full resize-none bg-transparent outline-none"
          placeholder="Type a note…"
        />
      ) : (
        <p className="min-h-[2.5rem] whitespace-pre-wrap">
          {String(data.notes ?? "") || (
            <span className="opacity-50">Double-click to edit…</span>
          )}
        </p>
      )}
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

export const nodeTypes = { lga: LgaNode, note: NoteNode };
export const edgeTypes = { lga: LgaEdge };
