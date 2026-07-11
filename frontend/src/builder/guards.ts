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
          schema_ref: "lab:Route",
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
  // PromptInput {vars} spawn input ports LIVE while typing — mirror of the
  // backend's Component.input_ports_for_config (SPEC §4.2 PromptInput)
  for (const field of descriptor.fields) {
    if (field.type !== "PromptInput") continue;
    const template = String(config[field.name] ?? field.default ?? "");
    for (const variable of extractPromptVars(template)) {
      if (!inputs.has(variable)) {
        inputs.set(variable, TEXT_PORT);
      }
    }
  }
  applyDynamicPortMirrors(descriptor, config, outputs, inputs, routeLabels);
  return { outputs, inputs, routeLabels };
}

const TEXT_PORT: PortSpec = {
  schema_ref: "lab:Text",
  json_schema: { type: "string" },
  family: "DATA",
  is_list: false,
};
const ROUTE_PORT: PortSpec = {
  schema_ref: "lab:Route",
  json_schema: { type: "string" },
  family: "ROUTE",
  is_list: false,
};
const TOOLSET_PORT: PortSpec = {
  schema_ref: "lab:Toolset",
  json_schema: {},
  family: "TOOLSET",
  is_list: true,
};
const MESSAGE_PORT: PortSpec = {
  schema_ref: "lab:Message",
  json_schema: {},
  family: "MESSAGE",
  is_list: false,
};
const JSON_PORT: PortSpec = {
  schema_ref: "lab:Json",
  json_schema: { type: "object" },
  family: "DATA",
  is_list: false,
};
const DOCUMENTS_PORT: PortSpec = {
  schema_ref: "lab:Documents",
  json_schema: {},
  family: "DOCUMENTS",
  is_list: true,
};

/** Live mirrors of server-side `outputs_for_config`/`input_ports_for_config`
 * overrides so ports update while typing. Built-ins only — custom components
 * fall back to the on_field_change round-trip (SPEC §4.6). */
function applyDynamicPortMirrors(
  descriptor: ComponentDescriptor,
  config: Record<string, unknown>,
  outputs: Map<string, PortSpec>,
  inputs: Map<string, PortSpec>,
  routeLabels: Set<string>,
): void {
  // Tool Mode toggle (§4.7/§18): toolset output only while enabled
  if (descriptor.tool_mode_supported) {
    const enabled = Boolean(config.tool_mode ?? descriptor.tool_mode_default);
    if (enabled) outputs.set("toolset", TOOLSET_PORT);
    else outputs.delete("toolset");
  }

  if (descriptor.component_id === "lab.flow.rule_router") {
    outputs.clear();
    routeLabels.clear();
    const rows = Array.isArray(config.rules) ? (config.rules as { label?: string }[]) : [];
    const labels = rows.map((r) => String(r.label ?? "").trim()).filter(Boolean);
    const fallback = String(config.default_label ?? "default");
    if (!labels.includes(fallback)) labels.push(fallback);
    for (const label of labels) {
      outputs.set(label, ROUTE_PORT);
      routeLabels.add(label);
    }
  }

  if (descriptor.component_id === "lab.data.type_convert") {
    const conversions: Record<string, [PortSpec, PortSpec]> = {
      message_to_text: [MESSAGE_PORT, TEXT_PORT],
      text_to_message: [TEXT_PORT, MESSAGE_PORT],
      documents_to_text: [DOCUMENTS_PORT, TEXT_PORT],
      json_to_text: [JSON_PORT, TEXT_PORT],
      text_to_json: [TEXT_PORT, JSON_PORT],
    };
    const pair = conversions[String(config.conversion ?? "message_to_text")];
    if (pair) {
      inputs.set("input", pair[0]);
      outputs.set("output", pair[1]);
    }
  }

  if (descriptor.component_id === "lab.tools.a2a_remote_agent") {
    if (String(config.mode ?? "node") === "tool") {
      outputs.clear();
      outputs.set("toolset", TOOLSET_PORT);
    } else {
      outputs.delete("toolset");
    }
  }
}

// same rule as the backend PROMPT_VAR_RE: {var}, but not {{escaped}}
const PROMPT_VAR_RE = /(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}(?!\})/g;

export function extractPromptVars(template: string): string[] {
  const seen = new Set<string>();
  for (const match of template.matchAll(PROMPT_VAR_RE)) {
    seen.add(match[1]);
  }
  return [...seen];
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

/** §11.4 [MUST]: screen-readable port label — `"output message, type lab:Message"`.
 * Applied as aria-label on every canvas handle. */
export function portAriaLabel(name: string, port: PortSpec, side: "in" | "out"): string {
  const list = port.is_list ? " list" : "";
  return `${side === "in" ? "input" : "output"} ${name}, type ${port.schema_ref}${list}`;
}

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
