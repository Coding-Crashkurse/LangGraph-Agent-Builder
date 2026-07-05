/** Custom React Flow nodes: component chrome by category, one labeled source
 * handle per router output, distinct attachment ports; plus __start__/__end__
 * terminals and the dashed attach edge. */

import {
  BaseEdge,
  getBezierPath,
  Handle,
  Position,
  type EdgeProps,
  type NodeProps,
} from "@xyflow/react";
import { AlertTriangle, Bot, Box, GitFork, Play, Square, Wrench } from "lucide-react";

import { cn } from "@/lib/utils";
import {
  ATTACH_SOURCE_HANDLE,
  ATTACH_TARGET_HANDLE,
  CONTROL_IN_HANDLE,
  CONTROL_OUT_HANDLE,
  routerOutputs,
  type ComponentCanvasNode,
  type TerminalCanvasNode,
} from "./convert";

const kindIcons = {
  node: Box,
  router: GitFork,
  tool_provider: Wrench,
} as const;

function summarizeConfig(config: Record<string, unknown>): string {
  const interesting = ["model", "collection", "url", "prompt", "labels", "name"];
  for (const key of interesting) {
    const value = config[key];
    if (value === undefined || value === "" || (Array.isArray(value) && !value.length)) continue;
    const text = Array.isArray(value) ? value.join(" · ") : String(value);
    return text.length > 34 ? `${text.slice(0, 34)}…` : text;
  }
  return "";
}

export function ComponentNode({ id, data, selected }: NodeProps<ComponentCanvasNode>) {
  const info = data.info;
  const kind = info?.kind ?? "node";
  const Icon = info ? (kindIcons[kind] ?? Box) : Bot;
  const outputs = kind === "router" ? routerOutputs(info, data.config) : [];
  const errors = data.issues.filter((issue) => issue.severity === "error");
  const catColor = `var(--color-cat-${info?.category ?? "io"})`;
  const isProvider = kind === "tool_provider";
  const acceptsTools = Boolean(info?.accepts_attachments.length);
  const summary = summarizeConfig(data.config);

  return (
    <div
      className={cn(
        "min-w-[190px] max-w-[240px] rounded-lg border bg-gradient-to-b from-surface-850 to-surface-900",
        "shadow-lg shadow-black/40 transition-all duration-150 hover:shadow-xl hover:shadow-black/60",
        selected
          ? "border-accent-500 shadow-accent-500/15 hover:shadow-accent-500/20"
          : "border-surface-700 hover:border-surface-600",
        errors.length && "border-red-700",
      )}
    >
      {!isProvider && (
        <Handle
          type="target"
          id={CONTROL_IN_HANDLE}
          position={Position.Left}
          className="!top-[22px]"
        />
      )}
      <div
        className="flex items-center gap-2 rounded-t-lg border-b border-surface-800 px-3 py-2"
        style={{ boxShadow: `inset 3px 0 0 0 ${catColor}` }}
      >
        <Icon className="h-3.5 w-3.5 shrink-0" style={{ color: catColor }} />
        <span className="truncate text-xs font-semibold text-zinc-100">
          {info?.display_name ?? data.component}
        </span>
        {errors.length > 0 && (
          <span className="ml-auto flex items-center gap-0.5 text-[10px] font-semibold text-red-400">
            <AlertTriangle className="h-3 w-3" />
            {errors.length}
          </span>
        )}
      </div>
      <div className="px-3 py-1.5">
        <div className="font-mono text-[10px] text-zinc-500">{id}</div>
        {summary && <div className="truncate text-[11px] text-zinc-400">{summary}</div>}
      </div>

      {kind === "router" && (
        <div className="border-t border-surface-800 pb-1.5">
          {outputs.map((label) => (
            <div key={label} className="relative flex justify-end px-3 py-[3px]">
              <span className="font-mono text-[10px] uppercase tracking-wider text-amber-300/90">
                {label}
              </span>
              <Handle
                type="source"
                id={label}
                position={Position.Right}
                className="!relative !right-[-15px] !top-auto !translate-y-0 !bg-amber-400/90"
              />
            </div>
          ))}
        </div>
      )}

      {kind === "node" && (
        <Handle
          type="source"
          id={CONTROL_OUT_HANDLE}
          position={Position.Right}
          className="!top-[22px]"
        />
      )}

      {isProvider && (
        <Handle
          type="source"
          id={ATTACH_SOURCE_HANDLE}
          position={Position.Top}
          className="!bg-sky-400"
        />
      )}
      {acceptsTools && (
        <Handle
          type="target"
          id={ATTACH_TARGET_HANDLE}
          position={Position.Bottom}
          className="!bg-sky-400"
        />
      )}
    </div>
  );
}

export function TerminalNode({ data }: NodeProps<TerminalCanvasNode>) {
  const isStart = data.terminal === "start";
  return (
    <div
      className={cn(
        "flex items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-semibold",
        isStart
          ? "border-emerald-800 bg-emerald-950/70 text-emerald-300"
          : "border-zinc-700 bg-surface-800 text-zinc-300",
      )}
    >
      {isStart ? <Play className="h-3 w-3" /> : <Square className="h-3 w-3" />}
      {isStart ? "start" : "end"}
      {isStart ? (
        <Handle type="source" id={CONTROL_OUT_HANDLE} position={Position.Right} />
      ) : (
        <Handle type="target" id={CONTROL_IN_HANDLE} position={Position.Left} />
      )}
    </div>
  );
}

export function AttachEdge({
  id,
  sourceX,
  sourceY,
  targetX,
  targetY,
  sourcePosition,
  targetPosition,
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
      style={{ stroke: "#38bdf8", strokeDasharray: "6 4", strokeWidth: 1.5, opacity: 0.8 }}
    />
  );
}

export const nodeTypes = { component: ComponentNode, terminal: TerminalNode };
export const edgeTypes = { attach: AttachEdge };
