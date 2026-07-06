/** Client-side edge guards (SPEC §11.3): family-level compat while dragging;
 * the exact structural verdict comes from /validate on drop. */

import type { ComponentDescriptor, PortFamily, PortSpec } from "@/api/types";

const COERCIBLE: ReadonlySet<string> = new Set([
  "MESSAGE>DATA", // message_to_text
  "DATA>MESSAGE", // text_to_message
  "DOCUMENTS>DATA", // documents_to_text
]);

export function familiesCompatible(source: PortFamily, target: PortFamily): boolean {
  if (source === "ANY" || target === "ANY") return true;
  if (source === target) return source !== "ROUTE"; // ROUTE is control-only
  return COERCIBLE.has(`${source}>${target}`);
}

export interface PortIndex {
  outputs: Map<string, PortSpec>; // handle id → port
  inputs: Map<string, PortSpec>;
  routeLabels: Set<string>;
}

export function indexPorts(
  descriptor: ComponentDescriptor,
  config: Record<string, unknown>,
): PortIndex {
  const outputs = new Map<string, PortSpec>();
  const routeLabels = new Set<string>();
  for (const output of descriptor.outputs) {
    outputs.set(output.name, output.port);
    if (output.port.family === "ROUTE") routeLabels.add(output.name);
  }
  // dynamic router labels regenerate outputs client-side
  if (descriptor.dynamic_outputs_from) {
    const labels = config[descriptor.dynamic_outputs_from];
    if (Array.isArray(labels) && labels.length > 0) {
      outputs.clear();
      routeLabels.clear();
      for (const label of labels as string[]) {
        outputs.set(label, {
          schema_ref: "lga:Route",
          json_schema: { type: "string" },
          family: "ROUTE",
          is_list: false,
        });
        routeLabels.add(label);
      }
      // keep non-route outputs (e.g. implicit toolset)
      for (const output of descriptor.outputs) {
        if (output.port.family !== "ROUTE") outputs.set(output.name, output.port);
      }
    }
  }
  const inputs = new Map<string, PortSpec>(Object.entries(descriptor.input_ports));
  return { outputs, inputs, routeLabels };
}

export type ConnectionVerdict =
  | { ok: true; kind: "data" | "tool" | "router" }
  | { ok: false; reason: string };

const ALL_FAMILIES: PortFamily[] = [
  "MESSAGE",
  "DATA",
  "DOCUMENTS",
  "EMBEDDING",
  "MODEL",
  "TOOLSET",
  "ROUTE",
  "FILE",
  "ANY",
];

/** Human-readable "connects to …" line for port tooltips. */
export function compatSummary(port: PortSpec, side: "in" | "out"): string {
  if (port.family === "ROUTE") {
    return side === "out"
      ? "control branch → drop on any node (amber top handle)"
      : "accepts router branches only";
  }
  if (port.family === "TOOLSET") {
    return side === "out"
      ? "→ Tools input of an agent (dashed edge)"
      : "← Toolset outputs (dashed edge)";
  }
  const partners = ALL_FAMILIES.filter((family) =>
    side === "out"
      ? familiesCompatible(port.family, family)
      : familiesCompatible(family, port.family),
  ).filter((family) => family !== "ROUTE" && family !== "TOOLSET");
  return (side === "out" ? "→ " : "← ") + partners.join(", ");
}

export function judgeConnection(
  sourcePort: PortSpec | undefined,
  targetPort: PortSpec | undefined,
  targetIsRouterSink: boolean,
): ConnectionVerdict {
  if (!sourcePort) return { ok: false, reason: "unknown output port" };
  if (sourcePort.family === "ROUTE") {
    // router branches connect to any node's control-in (the amber top handle)
    return { ok: true, kind: "router" };
  }
  if (targetIsRouterSink) {
    return { ok: false, reason: "the control-in handle only accepts router branches" };
  }
  if (!targetPort) return { ok: false, reason: "unknown input port" };
  if (sourcePort.family === "TOOLSET" || targetPort.family === "TOOLSET") {
    if (sourcePort.family === "TOOLSET" && targetPort.family === "TOOLSET") {
      return { ok: true, kind: "tool" };
    }
    return { ok: false, reason: "toolset edges connect Toolset → Tools only" };
  }
  if (!familiesCompatible(sourcePort.family, targetPort.family)) {
    return {
      ok: false,
      reason: `${sourcePort.schema_ref} → ${targetPort.schema_ref} is incompatible`,
    };
  }
  return { ok: true, kind: "data" };
}
