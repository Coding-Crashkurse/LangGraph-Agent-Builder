/** Canvas node + edge renderers — Langflow-style cards (SPEC §11.2–§11.4, §18.4):
 * fields render INSIDE the node (label + inline widget per row), handles sit on
 * their field's row, connected fields collapse to a chip. Toolset ports live on
 * top/bottom, control-in on top, data left→right. Edges carry the SOURCE port
 * family color; during a run the active path animates (§11.4). */

import {
  BaseEdge,
  getBezierPath,
  Handle,
  Position,
  useConnection,
  useUpdateNodeInternals,
  type EdgeProps,
  type NodeProps,
} from "@xyflow/react";
import {
  AlertTriangle,
  ArrowUpRight,
  Boxes,
  Check,
  ChevronDown,
  ChevronRight,
  Copy,
  FlaskConical,
  GitBranch,
  Library,
  Loader2,
  MoreHorizontal,
  Pencil,
  Play,
  Sparkles,
  Square,
  Trash2,
  Wrench,
  X,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { memo, useEffect, useRef, useState, type ReactNode } from "react";

import { PORT_FAMILY_COLORS, type FieldDescriptor, type PortSpec } from "@/api/types";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";

import type { CanvasEdge, CanvasNode } from "./convert";
import { defaultConfig, ROUTER_TARGET_HANDLE } from "./convert";
import { widgetFor } from "./forms/registry";
import { compatSummary, indexPorts, judgeConnection, portAriaLabel } from "./guards";
import { useBuilder } from "./store";

/** §11.2: 24px icon chip — category color @12% background, category-color icon.
 * Category colors map onto the port-family tokens (theme.css owns all color). */
const CATEGORY_ICONS: Record<string, { Icon: LucideIcon; tone: string }> = {
  llm: { Icon: Sparkles, tone: "bg-port-embedding/12 text-port-embedding" },
  rag: { Icon: Library, tone: "bg-port-documents/12 text-port-documents" },
  flow_control: { Icon: GitBranch, tone: "bg-port-route/12 text-port-route" },
  tools: { Icon: Wrench, tone: "bg-port-toolset/12 text-port-toolset" },
  io: { Icon: Zap, tone: "bg-port-file/12 text-port-file" },
  data: { Icon: Boxes, tone: "bg-port-data/12 text-port-data" },
  testing: { Icon: FlaskConical, tone: "bg-port-vectorstore/12 text-port-vectorstore" },
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
/** While a connection drag is in progress: incompatible handles dim to 25%,
 * compatible ones scale 1.15 (§11.3). */
function useHandleDimmer(nodeId: string): {
  connecting: boolean;
  dimFor: (port: PortSpec | undefined, side: "in" | "out", handleId: string) => boolean;
} {
  const connection = useConnection();
  const descriptors = useBuilder((s) => s.descriptors);
  const nodes = useBuilder((s) => s.nodes);

  if (!connection.inProgress || !connection.fromHandle || !connection.fromNode) {
    return { connecting: false, dimFor: () => false };
  }
  const fromNode = nodes.find((n) => n.id === connection.fromNode?.id);
  const fromDescriptor = fromNode && descriptors.get(fromNode.data.componentId);
  if (!fromNode || !fromDescriptor) return { connecting: false, dimFor: () => false };
  const fromPorts = indexPorts(fromDescriptor, fromNode.data.config);
  const fromType = connection.fromHandle.type;
  const fromId = connection.fromHandle.id ?? "";
  const fromPort =
    fromType === "source" ? fromPorts.outputs.get(fromId) : fromPorts.inputs.get(fromId);

  const dimFor = (port: PortSpec | undefined, side: "in" | "out", handleId: string): boolean => {
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
  return { connecting: true, dimFor };
}

// ------------------------------------------------------------------ port row bits
function PortTooltip({ name, port, side }: { name: string; port: PortSpec; side: "in" | "out" }) {
  const color = PORT_FAMILY_COLORS[port.family] ?? "var(--color-port-any)";
  return (
    <div
      className={cn(
        "pointer-events-none absolute top-1/2 z-50 w-56 -translate-y-1/2 rounded-md border border-border bg-canvas/95 px-2.5 py-1.5 shadow-xl",
        side === "in" ? "right-full mr-3" : "left-full ml-3",
      )}
    >
      <p className="flex items-center gap-1.5 text-[11px] font-semibold text-text-1">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: color }} />
        {name}
        <span className="font-normal text-text-3">{side === "in" ? "input" : "output"}</span>
      </p>
      <p className="mt-0.5 font-mono text-[10.5px]" style={{ color }}>
        {port.schema_ref}
        {port.is_list ? "[]" : ""} · {port.family}
      </p>
      <p className="mt-0.5 text-[11px] text-text-2">{compatSummary(port, side)}</p>
    </div>
  );
}

/** The visible 12px diamond/circle inside a 16px invisible hit area (§11.2).
 * Pointer events stay on the parent Handle. */
function HandleDot({ port, active }: { port: PortSpec; active: boolean }) {
  const color = PORT_FAMILY_COLORS[port.family] ?? "var(--color-port-any)";
  const isDiamond = port.is_list; // §11.1 [MUST]: list = diamond, scalar = circle
  return (
    <span
      aria-hidden
      className="pointer-events-none absolute left-1/2 top-1/2 block"
      style={{
        width: 12,
        height: 12,
        background: port.family === "ANY" ? "var(--color-surface-1)" : color,
        border: `2px ${port.family === "ANY" ? "dashed" : "solid"} ${color}`,
        borderRadius: isDiamond ? 2 : 999,
        transform: `translate(-50%, -50%)${isDiamond ? " rotate(45deg)" : ""}${
          active ? " scale(1.15)" : ""
        }`,
        transition: "transform 120ms",
      }}
    />
  );
}

function RowHandle({
  id,
  port,
  side,
  dimmed,
  active,
}: {
  id: string;
  port: PortSpec;
  side: "in" | "out";
  dimmed: boolean;
  active: boolean;
}) {
  const [hovered, setHovered] = useState(false);
  return (
    <>
      <Handle
        id={id}
        type={side === "in" ? "target" : "source"}
        position={side === "in" ? Position.Left : Position.Right}
        aria-label={portAriaLabel(id, port, side)}
        tabIndex={0}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setHovered(true)}
        onBlur={() => setHovered(false)}
        style={{
          // 16px invisible hit area, dot centered ON the card border
          [side === "in" ? "left" : "right"]: -9,
          top: "50%",
          width: 16,
          height: 16,
          background: "transparent",
          border: "none",
          borderRadius: 999,
          opacity: dimmed ? 0.25 : 1,
          transition: "opacity 120ms",
        }}
      >
        <HandleDot port={port} active={active} />
      </Handle>
      {hovered && <PortTooltip name={id} port={port} side={side} />}
    </>
  );
}

function Row({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("relative px-3.5 py-1.5", className)}>{children}</div>;
}

// ------------------------------------------------------------------ kebab menu
function MenuItem({
  icon: Icon,
  label,
  danger,
  onSelect,
}: {
  icon: LucideIcon;
  label: string;
  danger?: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="menuitem"
      className={cn(
        "flex w-full items-center gap-2 rounded-md px-2 py-1 text-left text-[12px] focus-visible:outline-2 focus-visible:outline-accent",
        danger
          ? "text-danger hover:bg-danger/10"
          : "text-text-2 hover:bg-surface-3 hover:text-text-1",
      )}
      onClick={(e) => {
        e.stopPropagation();
        onSelect();
      }}
    >
      <Icon size={14} strokeWidth={1.75} aria-hidden />
      {label}
    </button>
  );
}

/** §11.2 header kebab: rename / duplicate / delete. ("disable" is omitted —
 * FlowSpec.NodeSpec does not round-trip a disabled flag yet.) */
function NodeMenu({ nodeId, onRename }: { nodeId: string; onRename: () => void }) {
  const [open, setOpen] = useState(false);
  const duplicateNode = useBuilder((s) => s.duplicateNode);
  const deleteNode = useBuilder((s) => s.deleteNode);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!ref.current?.contains(e.target as globalThis.Node)) setOpen(false);
    };
    window.addEventListener("pointerdown", onDown);
    return () => window.removeEventListener("pointerdown", onDown);
  }, [open]);

  return (
    <div
      className="relative"
      ref={ref}
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          setOpen(false);
        }
      }}
    >
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="node menu"
        className="nodrag flex h-5 w-5 items-center justify-center rounded text-text-3 hover:bg-surface-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
      >
        <MoreHorizontal size={14} strokeWidth={1.75} aria-hidden />
      </button>
      {open && (
        <div
          role="menu"
          className="nodrag nopan absolute right-0 top-6 z-50 w-36 rounded-lg border border-border bg-surface-2 p-1 shadow-xl"
        >
          <MenuItem
            icon={Pencil}
            label="Rename"
            onSelect={() => {
              setOpen(false);
              onRename();
            }}
          />
          <MenuItem
            icon={Copy}
            label="Duplicate"
            onSelect={() => {
              setOpen(false);
              duplicateNode(nodeId);
            }}
          />
          <MenuItem
            icon={Trash2}
            label="Delete"
            danger
            onSelect={() => {
              setOpen(false);
              deleteNode(nodeId);
            }}
          />
        </div>
      )}
    </div>
  );
}

// ------------------------------------------------------------------ node card
export const LabNode = memo(function LabNode({ id, data, selected }: NodeProps<CanvasNode>) {
  const descriptors = useBuilder((s) => s.descriptors);
  const diagnostics = useBuilder((s) => s.diagnostics);
  const edges = useBuilder((s) => s.edges);
  const updateNodeConfig = useBuilder((s) => s.updateNodeConfig);
  const select = useBuilder((s) => s.select);
  const renameNode = useBuilder((s) => s.renameNode);
  const toggleCollapsed = useBuilder((s) => s.toggleCollapsed);
  const runState = useBuilder((s) => s.runStates[id]);
  const partialTarget = useBuilder((s) => s.partialTarget);
  const runToNode = useBuilder((s) => s.runToNode);
  const descriptor = descriptors.get(data.componentId);
  const { connecting, dimFor } = useHandleDimmer(id);
  const [renaming, setRenaming] = useState(false);
  const [draftLabel, setDraftLabel] = useState("");
  const collapsed = Boolean(data.collapsed);
  const updateInternals = useUpdateNodeInternals();

  // handles move when the body folds — tell React Flow to re-measure
  useEffect(() => {
    updateInternals(id);
  }, [collapsed, id, updateInternals]);

  if (!descriptor) {
    return (
      <div className="rounded-xl border border-danger bg-surface-1 px-3 py-2 text-xs text-danger">
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
  const dataInputs = allInputs.filter(([, p]) => p.family !== "TOOLSET");
  const dataOutputs = allOutputs.filter(([, p]) => p.family !== "TOOLSET");
  const nodeDiags = diagnostics.filter((d) => d.node_id === id);
  const errorCount = nodeDiags.filter((d) => d.severity === "error").length;
  const warnCount = nodeDiags.filter((d) => d.severity === "warning").length;

  // ---------------- pills (start/end)
  if (isPill) {
    return (
      <div
        className={cn(
          "relative flex items-center gap-1.5 rounded-full border bg-surface-2 px-5 py-2 text-sm font-semibold",
          id === "start" ? "border-success text-success" : "border-border-strong text-text-1",
          selected && "ring-2 ring-accent",
        )}
      >
        {id === "start" ? (
          <Play size={12} strokeWidth={2} aria-hidden />
        ) : (
          <Square size={11} strokeWidth={2} aria-hidden />
        )}
        {id}
        {allInputs.map(([name, port], index) => (
          <Handle
            key={name}
            id={name}
            type="target"
            position={Position.Left}
            aria-label={portAriaLabel(name, port, "in")}
            tabIndex={0}
            style={{
              top: 12 + index * 14,
              background: PORT_FAMILY_COLORS[port.family],
              border: `2px solid ${PORT_FAMILY_COLORS[port.family]}`,
              width: 11,
              height: 11,
              opacity: dimFor(port, "in", name) ? 0.25 : 1,
            }}
          />
        ))}
        {allOutputs.map(([name, port], index) => (
          <Handle
            key={name}
            id={name}
            type="source"
            position={Position.Right}
            aria-label={portAriaLabel(name, port, "out")}
            tabIndex={0}
            style={{
              top: 12 + index * 14,
              background: PORT_FAMILY_COLORS[port.family],
              border: `2px solid ${PORT_FAMILY_COLORS[port.family]}`,
              width: 11,
              height: 11,
              opacity: dimFor(port, "out", name) ? 0.25 : 1,
            }}
          />
        ))}
      </div>
    );
  }

  // ---------------- field partitioning
  const fields = descriptor.fields.filter((f) => !f.port_only && f.show !== false && !f.advanced);
  // same {...defaults, ...config} merge as the inspector (ConfigPanel) — the
  // node card and the panel must never disagree on a field's effective value
  const effectiveConfig = { ...defaultConfig(descriptor), ...data.config };
  const inline = fields.filter((f) => INLINE_TYPES.has(f.type));
  const panelOnly = fields.filter((f) => !INLINE_TYPES.has(f.type));
  const inlineNames = new Set(inline.map((f) => f.name));
  // ports without an inline widget row (HandleFields, prompt vars)
  const bareInputs = dataInputs.filter(([name]) => !inlineNames.has(name));

  const isConnected = (input: string) =>
    edges.some((e) => e.target === id && e.targetHandle === input);

  const chip = CATEGORY_ICONS[descriptor.category] ?? CATEGORY_ICONS.data;
  const running = runState?.status === "running";
  const stateClass =
    runState?.status === "running"
      ? "gf-node-active"
      : runState?.status === "finished"
        ? "gf-node-finished"
        : runState?.status === "error"
          ? "gf-node-error"
          : runState?.status === "interrupted"
            ? "gf-node-interrupted"
            : "";
  // §6.4: during a partial run, nodes outside the executed subgraph dim out
  const dimmedByPartial = partialTarget !== null && id !== partialTarget && !runState;
  const installed = descriptor.version;
  const pinned = data.componentVersion;
  const updateAvailable = Boolean(pinned && installed && pinned !== installed && !descriptor.legacy);

  const startRename = () => {
    setDraftLabel(data.label || descriptor.display_name);
    setRenaming(true);
  };
  const commitRename = () => {
    setRenaming(false);
    const label = draftLabel.trim();
    if (label && label !== data.label) renameNode(id, label);
  };

  const collapsedStubs = Math.max(dataInputs.length, dataOutputs.length);

  return (
    <div
      className={cn(
        "group relative w-72 rounded-xl border bg-surface-1 gf-node-shadow",
        selected ? "border-accent ring-1 ring-accent/50" : "border-border hover:border-border-strong",
        stateClass,
        dimmedByPartial && "gf-node-dimmed",
      )}
    >
      {/* header: 40px surface-2 band (§11.2) */}
      <div
        className={cn(
          "flex h-10 items-center gap-2 rounded-t-xl border-b border-border bg-surface-2 px-3",
          selected && "gf-header-selected",
          collapsed && collapsedStubs === 0 && "rounded-b-xl border-b-0",
        )}
      >
        <span
          className={cn("flex h-6 w-6 shrink-0 items-center justify-center rounded-md", chip.tone)}
        >
          {running ? (
            <Loader2
              size={16}
              strokeWidth={1.75}
              className="animate-spin motion-reduce:animate-none"
              aria-label="running"
            />
          ) : (
            <chip.Icon size={16} strokeWidth={1.75} aria-hidden />
          )}
        </span>
        <div className="min-w-0 flex-1 leading-tight">
          {renaming ? (
            <input
              autoFocus
              value={draftLabel}
              aria-label="node name"
              onChange={(e) => setDraftLabel(e.target.value)}
              onBlur={commitRename}
              onKeyDown={(e) => {
                e.stopPropagation();
                if (e.key === "Enter") commitRename();
                if (e.key === "Escape") setRenaming(false);
              }}
              className="nodrag w-full rounded border border-accent bg-surface-1 px-1 text-[13px] font-semibold text-text-1 outline-none"
            />
          ) : (
            <p
              className="truncate text-[13px] font-semibold text-text-1"
              onDoubleClick={startRename}
            >
              {data.label || descriptor.display_name}
            </p>
          )}
          {/* mono id — hover/selected only (§11.2) */}
          <p
            className={cn(
              "truncate font-mono text-[10.5px] text-text-3 transition-opacity duration-[120ms]",
              selected ? "opacity-100" : "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100",
            )}
          >
            {id}
          </p>
        </div>
        {descriptor.node_kind === "interrupt" && (
          <span className="rounded bg-warning/15 px-1 py-0.5 text-[10.5px] font-bold text-warning">
            HITL
          </span>
        )}
        {descriptor.beta && (
          <span className="rounded bg-accent/15 px-1 py-0.5 text-[10.5px] font-bold text-accent">
            BETA
          </span>
        )}
        {errorCount > 0 && (
          <span className="rounded-full bg-danger/15 px-1.5 text-[10.5px] font-bold text-danger">
            {errorCount}
          </span>
        )}
        {errorCount === 0 && warnCount > 0 && (
          <span className="rounded-full bg-warning/15 px-1.5 text-[10.5px] font-bold text-warning">
            {warnCount}
          </span>
        )}
        <button
          type="button"
          title="Run to here (partial run, §6.4)"
          aria-label="run to this node"
          className="nodrag flex h-5 w-5 items-center justify-center rounded text-text-3 opacity-0 hover:bg-surface-3 hover:text-accent focus-visible:opacity-100 focus-visible:outline-2 focus-visible:outline-accent group-hover:opacity-100"
          onClick={(e) => {
            e.stopPropagation();
            runToNode(id)
              .then((preview) =>
                toast.success(`ran to ${id}${preview ? `: ${preview.slice(0, 60)}` : ""}`),
              )
              .catch((err) => toast.error(`run failed: ${(err as Error).message}`));
          }}
        >
          <Play size={13} strokeWidth={1.75} aria-hidden />
        </button>
        <button
          type="button"
          aria-label={collapsed ? "expand node" : "collapse node"}
          aria-expanded={!collapsed}
          className="nodrag flex h-5 w-5 items-center justify-center rounded text-text-3 hover:bg-surface-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-accent"
          onClick={(e) => {
            e.stopPropagation();
            toggleCollapsed(id);
          }}
        >
          {collapsed ? (
            <ChevronRight size={14} strokeWidth={1.75} aria-hidden />
          ) : (
            <ChevronDown size={14} strokeWidth={1.75} aria-hidden />
          )}
        </button>
        <NodeMenu nodeId={id} onRename={startRename} />
      </div>

      {/* control-in for router branches (§18.4 top) */}
      <Handle
        id={ROUTER_TARGET_HANDLE}
        type="target"
        position={Position.Top}
        aria-label="control input, accepts router branches"
        tabIndex={0}
        style={{
          top: -9,
          width: 16,
          height: 16,
          background: "transparent",
          border: "none",
          opacity: dimFor(undefined, "in", ROUTER_TARGET_HANDLE) ? 0.25 : 0.9,
          transition: "opacity 120ms",
        }}
      >
        <span
          aria-hidden
          className="pointer-events-none absolute left-1/2 top-1/2 block h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full"
          style={{ background: "var(--color-port-route)" }}
        />
      </Handle>
      {/* toolset OUT on top (§18.4: providers point up to their agent) */}
      {toolOutputs.map(([name, port], index) => {
        const dim = dimFor(port, "out", name);
        return (
          <Handle
            key={name}
            id={name}
            type="source"
            position={Position.Top}
            aria-label={portAriaLabel(name, port, "out")}
            tabIndex={0}
            style={{
              left: `${72 + index * 12}%`,
              top: -9,
              width: 16,
              height: 16,
              background: "transparent",
              border: "none",
              opacity: dim ? 0.25 : 1,
              transition: "opacity 120ms",
            }}
          >
            <HandleDot port={port} active={connecting && !dim} />
          </Handle>
        );
      })}

      {collapsed ? (
        // §11.2 collapse: body folds to header + port stubs (handles stay live)
        collapsedStubs > 0 && (
          <div className="py-1.5">
            {Array.from({ length: collapsedStubs }).map((_, index) => {
              const input = dataInputs[index];
              const output = dataOutputs[index];
              return (
                <div key={input?.[0] ?? output?.[0] ?? index} className="relative h-3.5">
                  {input && (
                    <RowHandle
                      id={input[0]}
                      port={input[1]}
                      side="in"
                      dimmed={dimFor(input[1], "in", input[0])}
                      active={connecting && !dimFor(input[1], "in", input[0])}
                    />
                  )}
                  {output && (
                    <RowHandle
                      id={output[0]}
                      port={output[1]}
                      side="out"
                      dimmed={dimFor(output[1], "out", output[0])}
                      active={connecting && !dimFor(output[1], "out", output[0])}
                    />
                  )}
                </div>
              );
            })}
          </div>
        )
      ) : (
        <>
          {(inline.length > 0 || bareInputs.length > 0 || panelOnly.length > 0) && (
            <div className="pb-1 pt-1.5">
              {/* bare input ports (HandleFields, prompt {vars}) */}
              {bareInputs.map(([name, port]) => {
                const dim = dimFor(port, "in", name);
                return (
                  <Row key={name} className="py-1">
                    <RowHandle
                      id={name}
                      port={port}
                      side="in"
                      dimmed={dim}
                      active={connecting && !dim}
                    />
                    <span className="text-[11px] text-text-2">
                      {name}
                      {isConnected(name) && (
                        <span
                          className="ml-1.5 inline-block h-1.5 w-1.5 rounded-full bg-success"
                          title="connected"
                          aria-hidden
                        />
                      )}
                    </span>
                  </Row>
                );
              })}

              {/* inline widgets (Langflow style) */}
              {inline.map((field) => {
                const port = ports.inputs.get(field.name);
                const connected = isConnected(field.name);
                const Widget = widgetFor(field as FieldDescriptor);
                const dim = port ? dimFor(port, "in", field.name) : false;
                return (
                  <Row key={field.name}>
                    {port && (
                      <RowHandle
                        id={field.name}
                        port={port}
                        side="in"
                        dimmed={dim}
                        active={connecting && !dim}
                      />
                    )}
                    <p className="mb-1 text-[11px] font-medium text-text-2">
                      {field.display_name}
                      {field.required && <span className="ml-0.5 text-danger">*</span>}
                    </p>
                    {connected ? (
                      <p className="rounded-md border border-dashed border-success/40 bg-success/10 px-2 py-1 text-[11px] text-success">
                        ← connected
                      </p>
                    ) : (
                      <div className="nodrag nowheel text-xs">
                        <Widget
                          field={field as FieldDescriptor}
                          value={effectiveConfig[field.name]}
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
                    className="nodrag inline-flex items-center gap-0.5 text-[11px] text-text-3 underline-offset-2 hover:text-accent hover:underline focus-visible:outline-2 focus-visible:outline-accent"
                    onClick={() => select(id)}
                  >
                    {panelOnly.map((f) => f.display_name).join(", ")} — edit in panel
                    <ArrowUpRight size={11} strokeWidth={1.75} aria-hidden />
                  </button>
                </Row>
              )}
            </div>
          )}

          {/* outputs */}
          {dataOutputs.length > 0 && (
            <div className="border-t border-border py-1">
              {dataOutputs.map(([name, port]) => {
                const dim = dimFor(port, "out", name);
                return (
                  <Row key={name} className="py-1 text-right">
                    <RowHandle
                      id={name}
                      port={port}
                      side="out"
                      dimmed={dim}
                      active={connecting && !dim}
                    />
                    <span
                      className={cn(
                        "text-[11px]",
                        port.family === "ROUTE" ? "font-semibold text-port-route" : "text-text-2",
                      )}
                    >
                      {name}
                    </span>
                  </Row>
                );
              })}
            </div>
          )}

          {/* footer: last-run chip + version badge with update indicator (§11.2/§4.11) */}
          <div className="flex items-center justify-between border-t border-border px-3.5 py-1 text-[10.5px]">
            <span className="font-mono tabular-nums">
              {runState?.status === "finished" && (
                <span className="inline-flex items-center gap-0.5 text-success">
                  <Check size={11} strokeWidth={2} aria-hidden />
                  {runState.durationMs ?? 0}ms
                </span>
              )}
              {runState?.status === "error" && (
                <span className="inline-flex items-center gap-0.5 text-danger">
                  <X size={11} strokeWidth={2} aria-hidden />
                  {runState.errorCode}
                </span>
              )}
              {runState?.status === "running" && <span className="text-accent">running…</span>}
              {runState?.status === "interrupted" && (
                <span className="text-warning">awaiting input</span>
              )}
            </span>
            <span className="flex items-center gap-1 font-mono text-text-3">
              {descriptor.legacy && <span className="text-warning">LEGACY</span>}
              v{installed}
              {updateAvailable && (
                <span
                  className="inline-flex items-center gap-0.5 text-warning"
                  title={`pinned ${pinned} → installed ${installed}`}
                >
                  <AlertTriangle size={11} strokeWidth={1.75} aria-hidden />
                  update
                </span>
              )}
            </span>
          </div>
        </>
      )}

      {/* tools IN on the bottom (§18.4: tools hang below the agent) */}
      {toolInputs.map(([name, port], index) => {
        const dim = dimFor(port, "in", name);
        return (
          <Handle
            key={name}
            id={name}
            type="target"
            position={Position.Bottom}
            aria-label={portAriaLabel(name, port, "in")}
            tabIndex={0}
            style={{
              left: `${50 + index * 12}%`,
              bottom: -9,
              width: 16,
              height: 16,
              background: "transparent",
              border: "none",
              opacity: dim ? 0.25 : 1,
              transition: "opacity 120ms",
            }}
          >
            <HandleDot port={port} active={connecting && !dim} />
          </Handle>
        );
      })}
      {toolInputs.length > 0 && !collapsed && (
        <p className="pb-1 text-center text-[10.5px] font-medium text-port-toolset">tools</p>
      )}
    </div>
  );
});

// ------------------------------------------------------------------ sticky notes
const NOTE_COLORS: Record<string, string> = {
  amber: "bg-warning/85 border-warning text-canvas",
  sky: "bg-port-toolset/85 border-port-toolset text-canvas",
  emerald: "bg-success/85 border-success text-canvas",
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
        selected && "ring-2 ring-accent",
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

// ------------------------------------------------------------------ edges (§11.3/§11.4)
export function LabEdge(props: EdgeProps<CanvasEdge>) {
  const [path, labelX, labelY] = getBezierPath(props);
  const kind = props.data?.kind ?? "data";
  const family =
    props.data?.family ?? (kind === "tool" ? "TOOLSET" : kind === "router" ? "ROUTE" : undefined);
  const color = family ? PORT_FAMILY_COLORS[family] : "var(--color-border-strong)";
  // §11.4 signature moment: while a run is active, edges leaving running or
  // finished nodes carry a slow dash-flow in the family color.
  const live = useBuilder((s) => {
    const status = s.runStates[props.source]?.status;
    return s.runActive && (status === "running" || status === "finished");
  });
  const coercion = props.data?.coercion;
  return (
    <>
      <BaseEdge
        id={props.id}
        path={path}
        className={cn("gf-edge", kind === "tool" && "gf-edge-tool", live && "gf-edge-live")}
        style={{ stroke: color }}
      />
      {/* endpoint dots — visible on hover/selected (§11.3) */}
      <circle className="gf-edge-dot" cx={props.sourceX} cy={props.sourceY} r={3} fill={color} />
      <circle className="gf-edge-dot" cx={props.targetX} cy={props.targetY} r={3} fill={color} />
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

export const nodeTypes = { lab: LabNode, note: NoteNode };
export const edgeTypes = { lab: LabEdge };
