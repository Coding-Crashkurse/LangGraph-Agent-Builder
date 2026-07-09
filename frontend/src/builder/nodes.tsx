/** Canvas node + edge renderers — Langflow-style cards (SPEC §11.3, §18.4):
 * fields render INSIDE the node (label + inline widget per row), handles sit on
 * their field's row, connected fields collapse to a chip. Toolset ports live on
 * top/bottom, control-in on top, data left→right. */

import {
  BaseEdge,
  getBezierPath,
  Handle,
  Position,
  useConnection,
  type EdgeProps,
  type NodeProps,
} from "@xyflow/react";
import { memo, useState, type ReactNode } from "react";

import { PORT_FAMILY_COLORS, type FieldDescriptor, type PortSpec } from "@/api/types";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import type { CanvasEdge, CanvasNode } from "./convert";
import { ROUTER_TARGET_HANDLE } from "./convert";
import { widgetFor } from "./forms/registry";
import { compatSummary, indexPorts, judgeConnection } from "./guards";
import { useBuilder } from "./store";

const CATEGORY_CHIP: Record<string, { emoji: string; tone: string }> = {
  llm: { emoji: "✨", tone: "bg-violet-500/15 text-violet-300" },
  rag: { emoji: "📚", tone: "bg-emerald-500/15 text-emerald-300" },
  flow_control: { emoji: "🔀", tone: "bg-amber-500/15 text-amber-300" },
  tools: { emoji: "🔧", tone: "bg-sky-500/15 text-sky-300" },
  io: { emoji: "⚡", tone: "bg-zinc-500/15 text-zinc-300" },
  data: { emoji: "🧩", tone: "bg-slate-500/15 text-slate-300" },
  testing: { emoji: "🧪", tone: "bg-pink-500/15 text-pink-300" },
};

/** field types rendered inline in the node card (Langflow parity); the rest
 * (tables, JSON editors, MCP pickers) open in the inspector panel */
const INLINE_TYPES = new Set([
  "StrInput",
  "MultilineInput",
  "IntInput",
  "FloatInput",
  "BoolInput",
  "SliderInput",
  "DropdownInput",
  "TabInput",
  "SecretInput",
  "MultilineSecretInput",
  "ModelInput",
  "QueryInput",
  "PromptInput",
]);

// ------------------------------------------------------------------ dimming
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
  const fromType = connection.fromHandle.type;
  const fromId = connection.fromHandle.id ?? "";
  const fromPort =
    fromType === "source" ? fromPorts.outputs.get(fromId) : fromPorts.inputs.get(fromId);

  return (port: PortSpec | undefined, side: "in" | "out", handleId: string): boolean => {
    if (connection.fromNode?.id === nodeId && fromId === handleId) return false;
    if (fromType === "source") {
      if (side === "out") return true;
      const verdict = judgeConnection(fromPort, port, handleId === ROUTER_TARGET_HANDLE);
      return !verdict.ok;
    }
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

// ------------------------------------------------------------------ port row bits
function PortTooltip({ name, port, side }: { name: string; port: PortSpec; side: "in" | "out" }) {
  const color = PORT_FAMILY_COLORS[port.family] ?? "#9ca3af";
  return (
    <div
      className={cn(
        "pointer-events-none absolute top-1/2 z-50 w-56 -translate-y-1/2 rounded-md border border-surface-700 bg-surface-950/95 px-2.5 py-1.5 shadow-xl",
        side === "in" ? "right-full mr-3" : "left-full ml-3",
      )}
    >
      <p className="flex items-center gap-1.5 text-[11px] font-semibold text-zinc-100">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
        {name}
        <span className="font-normal text-zinc-500">{side === "in" ? "input" : "output"}</span>
      </p>
      <p className="mt-0.5 font-mono text-[10px]" style={{ color }}>
        {port.schema_ref}
        {port.is_list ? "[]" : ""} · {port.family}
      </p>
      <p className="mt-0.5 text-[10px] text-zinc-400">{compatSummary(port, side)}</p>
    </div>
  );
}

function RowHandle({
  id,
  port,
  side,
  dimmed,
}: {
  id: string;
  port: PortSpec;
  side: "in" | "out";
  dimmed: boolean;
}) {
  const [hovered, setHovered] = useState(false);
  const color = PORT_FAMILY_COLORS[port.family] ?? "var(--color-port-any)";
  // §11.1 [MUST]: list ports render as diamonds (square rotated 45°), scalars as circles.
  const isDiamond = port.is_list;
  return (
    <>
      <Handle
        id={id}
        type={side === "in" ? "target" : "source"}
        position={side === "in" ? Position.Left : Position.Right}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        style={{
          // centered ON the card border (row spans to the card edge)
          [side === "in" ? "left" : "right"]: -7,
          top: "50%",
          background: port.family === "ANY" ? "var(--color-surface-1)" : color,
          border: `2px ${port.family === "ANY" ? "dashed" : "solid"} ${color}`,
          width: 12,
          height: 12,
          borderRadius: isDiamond ? 2 : 999,
          transform: isDiamond ? "translateY(-50%) rotate(45deg)" : undefined,
          opacity: dimmed ? 0.15 : 1,
          transition: "opacity 120ms",
        }}
      />
      {hovered && <PortTooltip name={id} port={port} side={side} />}
    </>
  );
}

function Row({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("relative px-3.5 py-1.5", className)}>{children}</div>;
}

// ------------------------------------------------------------------ node card
export const LgaNode = memo(function LgaNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const descriptors = useBuilder((s) => s.descriptors);
  const diagnostics = useBuilder((s) => s.diagnostics);
  const edges = useBuilder((s) => s.edges);
  const updateNodeConfig = useBuilder((s) => s.updateNodeConfig);
  const select = useBuilder((s) => s.select);
  const runState = useBuilder((s) => s.runStates[id]);
  const partialTarget = useBuilder((s) => s.partialTarget);
  const runToNode = useBuilder((s) => s.runToNode);
  const descriptor = descriptors.get(data.componentId);
  const dimFor = useHandleDimmer(id);

  if (!descriptor) {
    return (
      <div className="rounded-xl border border-red-700 bg-surface-900 px-3 py-2 text-xs text-red-400">
        unknown component: {data.componentId}
      </div>
    );
  }

  const isPill = id === "start" || id === "end";
  const ports = indexPorts(descriptor, data.config);
  const allInputs = [...ports.inputs.entries()];
  const allOutputs = [...ports.outputs.entries()];
  const toolInputs = allInputs.filter(([, p]) => p.family === "TOOLSET");
  const toolOutputs = allOutputs.filter(([, p]) => p.family === "TOOLSET");
  const dataOutputs = allOutputs.filter(([, p]) => p.family !== "TOOLSET");
  const nodeDiags = diagnostics.filter((d) => d.node_id === id);
  const errorCount = nodeDiags.filter((d) => d.severity === "error").length;
  const warnCount = nodeDiags.filter((d) => d.severity === "warning").length;

  // ---------------- pills (start/end)
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
        {allInputs.map(([name, port], index) => (
          <Handle
            key={name}
            id={name}
            type="target"
            position={Position.Left}
            style={{
              top: 12 + index * 14,
              background: PORT_FAMILY_COLORS[port.family],
              border: `2px solid ${PORT_FAMILY_COLORS[port.family]}`,
              width: 11,
              height: 11,
              opacity: dimFor(port, "in", name) ? 0.15 : 1,
            }}
          />
        ))}
        {allOutputs.map(([name, port], index) => (
          <Handle
            key={name}
            id={name}
            type="source"
            position={Position.Right}
            style={{
              top: 12 + index * 14,
              background: PORT_FAMILY_COLORS[port.family],
              border: `2px solid ${PORT_FAMILY_COLORS[port.family]}`,
              width: 11,
              height: 11,
              opacity: dimFor(port, "out", name) ? 0.15 : 1,
            }}
          />
        ))}
      </div>
    );
  }

  // ---------------- field partitioning
  const fields = descriptor.fields.filter((f) => !f.port_only && f.show !== false && !f.advanced);
  const inline = fields.filter((f) => INLINE_TYPES.has(f.type));
  const panelOnly = fields.filter((f) => !INLINE_TYPES.has(f.type));
  const inlineNames = new Set(inline.map((f) => f.name));
  // ports without an inline widget row (HandleFields, prompt vars)
  const bareInputs = allInputs.filter(
    ([name, port]) => port.family !== "TOOLSET" && !inlineNames.has(name),
  );

  const isConnected = (input: string) =>
    edges.some((e) => e.target === id && e.targetHandle === input);

  const chip = CATEGORY_CHIP[descriptor.category] ?? CATEGORY_CHIP.data;
  const stateClass =
    runState?.status === "running"
      ? "gf-node-active"
      : runState?.status === "finished"
        ? "gf-node-finished"
        : runState?.status === "error"
          ? "gf-node-error"
          : "";
  // §6.4: during a partial run, nodes outside the executed subgraph dim out
  const dimmedByPartial = partialTarget !== null && id !== partialTarget && !runState;
  const installed = descriptor.version;
  const pinned = data.componentVersion;
  const updateAvailable = Boolean(pinned && installed && pinned !== installed && !descriptor.legacy);

  return (
    <div
      className={cn(
        "group relative w-72 rounded-xl border bg-surface-900 shadow-lg shadow-black/30",
        selected ? "border-accent-500 ring-1 ring-accent-500/50" : "border-surface-700",
        stateClass,
        dimmedByPartial && "gf-node-dimmed",
      )}
    >
      {/* header */}
      <div className="flex items-center gap-2.5 px-3.5 pb-2 pt-3">
        <span
          className={cn(
            "flex h-8 w-8 items-center justify-center rounded-lg text-base",
            chip.tone,
          )}
        >
          {chip.emoji}
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-[13px] font-semibold text-zinc-100">
            {data.label || descriptor.display_name}
          </p>
          <p className="truncate font-mono text-[9px] text-zinc-600">{id}</p>
        </div>
        <button
          type="button"
          title="Run to here (partial run, §6.4)"
          className="nodrag hidden text-zinc-500 hover:text-accent-300 group-hover:block"
          onClick={(e) => {
            e.stopPropagation();
            runToNode(id)
              .then((preview) => toast.success(`ran to ${id}${preview ? `: ${preview.slice(0, 60)}` : ""}`))
              .catch((err) => toast.error(`run failed: ${(err as Error).message}`));
          }}
        >
          ▶
        </button>
        {descriptor.node_kind === "interrupt" && (
          <span className="rounded bg-amber-900/60 px-1 py-0.5 text-[9px] font-bold text-amber-300">
            HITL
          </span>
        )}
        {descriptor.beta && (
          <span className="rounded bg-violet-900/60 px-1 py-0.5 text-[9px] font-bold text-violet-300">
            BETA
          </span>
        )}
        {errorCount > 0 && (
          <span className="rounded-full bg-red-900/70 px-1.5 text-[10px] font-bold text-red-300">
            {errorCount}
          </span>
        )}
        {errorCount === 0 && warnCount > 0 && (
          <span className="rounded-full bg-amber-900/70 px-1.5 text-[10px] font-bold text-amber-300">
            {warnCount}
          </span>
        )}
      </div>

      {/* control-in for router branches (§18.4 top) */}
      <Handle
        id={ROUTER_TARGET_HANDLE}
        type="target"
        position={Position.Top}
        style={{
          background: "#f59e0b",
          width: 10,
          height: 10,
          opacity: dimFor(undefined, "in", ROUTER_TARGET_HANDLE) ? 0.15 : 0.9,
          transition: "opacity 120ms",
        }}
      />
      {/* toolset OUT on top (§18.4: providers point up to their agent) */}
      {toolOutputs.map(([name, port], index) => (
        <Handle
          key={name}
          id={name}
          type="source"
          position={Position.Top}
          style={{
            left: `${72 + index * 12}%`,
            background: PORT_FAMILY_COLORS.TOOLSET,
            border: `2px solid ${PORT_FAMILY_COLORS.TOOLSET}`,
            width: 12,
            height: 12,
            opacity: dimFor(port, "out", name) ? 0.15 : 1,
          }}
        />
      ))}

      {(inline.length > 0 || bareInputs.length > 0 || panelOnly.length > 0) && (
        <div className="border-t border-surface-800 pb-1 pt-1.5">
          {/* bare input ports (HandleFields, prompt {vars}) */}
          {bareInputs.map(([name, port]) => (
            <Row key={name} className="py-1">
              <RowHandle id={name} port={port} side="in" dimmed={dimFor(port, "in", name)} />
              <span className="text-[11px] text-zinc-400">
                {name}
                {isConnected(name) && <span className="ml-1.5 text-[9px] text-emerald-400">●</span>}
              </span>
            </Row>
          ))}

          {/* inline widgets (Langflow style) */}
          {inline.map((field) => {
            const port = ports.inputs.get(field.name);
            const connected = isConnected(field.name);
            const Widget = widgetFor(field as FieldDescriptor);
            return (
              <Row key={field.name}>
                {port && (
                  <RowHandle
                    id={field.name}
                    port={port}
                    side="in"
                    dimmed={dimFor(port, "in", field.name)}
                  />
                )}
                <p className="mb-1 text-[11px] font-medium text-zinc-300">
                  {field.display_name}
                  {field.required && <span className="ml-0.5 text-red-400">*</span>}
                </p>
                {connected ? (
                  <p className="rounded-md border border-dashed border-emerald-800/70 bg-emerald-950/20 px-2 py-1 text-[10px] text-emerald-300">
                    ← connected
                  </p>
                ) : (
                  <div className="nodrag nowheel text-xs">
                    <Widget
                      field={field as FieldDescriptor}
                      value={data.config[field.name]}
                      onChange={(value) =>
                        updateNodeConfig(id, { ...data.config, [field.name]: value })
                      }
                    />
                  </div>
                )}
              </Row>
            );
          })}

          {panelOnly.length > 0 && (
            <Row className="py-1">
              <button
                type="button"
                className="nodrag text-[10px] text-zinc-500 underline-offset-2 hover:text-accent-300 hover:underline"
                onClick={() => select(id)}
              >
                {panelOnly.map((f) => f.display_name).join(", ")} — edit in panel ↗
              </button>
            </Row>
          )}
        </div>
      )}

      {/* outputs */}
      {dataOutputs.length > 0 && (
        <div className="border-t border-surface-800 py-1">
          {dataOutputs.map(([name, port]) => (
            <Row key={name} className="py-1 text-right">
              <RowHandle id={name} port={port} side="out" dimmed={dimFor(port, "out", name)} />
              <span
                className={cn(
                  "text-[11px]",
                  port.family === "ROUTE" ? "font-semibold text-amber-400" : "text-zinc-400",
                )}
              >
                {name}
              </span>
            </Row>
          ))}
        </div>
      )}

      {/* footer: last-run chip + version badge with update indicator (§11.2/§4.11) */}
      <div className="flex items-center justify-between border-t border-surface-800 px-3.5 py-1 text-[10px]">
        <span className="font-mono tabular-nums">
          {runState?.status === "finished" && (
            <span className="text-emerald-400">✓ {runState.durationMs ?? 0}ms</span>
          )}
          {runState?.status === "error" && (
            <span className="text-red-400">✗ {runState.errorCode}</span>
          )}
          {runState?.status === "running" && <span className="text-accent-300">running…</span>}
        </span>
        <span className="flex items-center gap-1 font-mono text-zinc-600">
          {descriptor.legacy && <span className="text-amber-500">LEGACY</span>}
          v{installed}
          {updateAvailable && (
            <span className="text-amber-400" title={`pinned ${pinned} → installed ${installed}`}>
              ⚠ update
            </span>
          )}
        </span>
      </div>

      {/* tools IN on the bottom (§18.4: tools hang below the agent) */}
      {toolInputs.map(([name, port], index) => (
        <Handle
          key={name}
          id={name}
          type="target"
          position={Position.Bottom}
          style={{
            left: `${50 + index * 12}%`,
            background: PORT_FAMILY_COLORS.TOOLSET,
            border: `2px solid ${PORT_FAMILY_COLORS.TOOLSET}`,
            width: 12,
            height: 12,
            opacity: dimFor(port, "in", name) ? 0.15 : 1,
          }}
        />
      ))}
      {toolInputs.length > 0 && (
        <p className="pb-1 text-center text-[9px] font-medium text-sky-400">tools</p>
      )}
    </div>
  );
});

// ------------------------------------------------------------------ sticky notes
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
            e.stopPropagation();
          }}
          className="nodrag w-full resize-none bg-transparent outline-none"
          placeholder="Type a note…"
        />
      ) : (
        <p className="min-h-[2.5rem] whitespace-pre-wrap">
          {String(data.notes ?? "") || <span className="opacity-50">Double-click to edit…</span>}
        </p>
      )}
    </div>
  );
});

export function LgaEdge(props: EdgeProps<CanvasEdge>) {
  const [path, labelX, labelY] = getBezierPath(props);
  const kind = props.data?.kind ?? "data";
  const style =
    kind === "tool"
      ? {
          stroke: "var(--color-port-toolset)",
          strokeDasharray: "6 4",
          strokeWidth: 1.75,
        }
      : kind === "router"
        ? { stroke: "var(--color-port-route)", strokeWidth: 1.75 }
        : { stroke: "var(--color-border-strong)", strokeWidth: 1.75 };
  const coercion = props.data?.coercion;
  return (
    <>
      <BaseEdge id={props.id} path={path} style={style} />
      {coercion && (
        <foreignObject x={labelX - 9} y={labelY - 9} width={18} height={18}>
          <div
            title={`coercion: ${coercion}`}
            className="flex h-[18px] w-[18px] items-center justify-center rounded-full border border-border-strong bg-surface-2 text-[11px] text-text-2"
          >
            ≈
          </div>
        </foreignObject>
      )}
    </>
  );
}

export const nodeTypes = { lga: LgaNode, note: NoteNode };
export const edgeTypes = { lga: LgaEdge };
