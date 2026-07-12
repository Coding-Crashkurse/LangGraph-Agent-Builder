/**
 * Port derivation and connection guards — driven entirely by GET /node-types.
 *
 * The backend catalog carries the prompt-var pattern and the extra
 * compatibility pairs, so the client-side verdict matches
 * `agentplane_core.validation` exactly; POST /flows/validate stays the
 * authoritative check.
 */

import type {
  DefinitionNode,
  NodeCatalog,
  NodeTypeInfo,
  PortDecl,
  PortType,
} from "@/api/types";

export interface NodePorts {
  inputs: PortDecl[];
  outputs: PortDecl[];
}

function promptVariables(pattern: string, ...templates: unknown[]): string[] {
  const re = new RegExp(pattern, "g");
  const seen: string[] = [];
  for (const template of templates) {
    if (typeof template !== "string") continue;
    for (const match of template.matchAll(re)) {
      const name = match[1];
      if (name && !seen.includes(name)) seen.push(name);
    }
  }
  return seen;
}

function schemaPropertyPorts(inputSchema: unknown): PortDecl[] {
  if (typeof inputSchema !== "object" || inputSchema === null) return [];
  const props = (inputSchema as { properties?: unknown }).properties;
  if (typeof props !== "object" || props === null) return [];
  return Object.entries(props as Record<string, unknown>).map(([name, schema]) => {
    const type =
      typeof schema === "object" &&
      schema !== null &&
      (schema as { type?: unknown }).type === "string"
        ? ("text" as const)
        : ("json" as const);
    return { name, type, label: name };
  });
}

const PORT_TYPES: PortType[] = ["text", "json", "message", "documents"];

function asPortType(value: unknown): PortType {
  return PORT_TYPES.includes(value as PortType) ? (value as PortType) : "text";
}

function routerBranches(config: Record<string, unknown>): string[] {
  const rules = Array.isArray(config.rules) ? config.rules : [];
  const names = rules
    .map((rule) =>
      typeof rule === "object" && rule !== null
        ? (rule as { branch?: unknown }).branch
        : undefined,
    )
    .filter((branch): branch is string => typeof branch === "string" && branch !== "");
  const fallback =
    typeof config.default_branch === "string" && config.default_branch
      ? config.default_branch
      : "otherwise";
  if (!names.includes(fallback)) names.push(fallback);
  return names;
}

/** Typed ports of one node, config-dependent ports included. */
export function nodePorts(
  node: DefinitionNode,
  info: NodeTypeInfo | undefined,
  catalog: NodeCatalog,
): NodePorts {
  if (!info) return { inputs: [], outputs: [] };
  let inputs = [...info.inputs];
  let outputs = [...info.outputs];
  if (info.dynamic_inputs === "prompt_vars") {
    inputs = promptVariables(
      catalog.prompt_var_pattern,
      node.config.prompt,
      node.config.system_prompt,
    ).map((name) => ({ name, type: "text" as const, label: name }));
  } else if (info.dynamic_inputs === "arg_keys") {
    const args = node.config.args;
    const keys = typeof args === "object" && args !== null ? Object.keys(args) : [];
    inputs = keys.map((name) => ({ name, type: "text" as const, label: name }));
  } else if (info.dynamic_inputs === "template_vars") {
    inputs = [
      { name: "trigger", type: "text", label: "Trigger" },
      ...promptVariables(catalog.prompt_var_pattern, node.config.text)
        .filter((name) => name !== "trigger")
        .map((name) => ({ name, type: "text" as const, label: name })),
    ];
  } else if (info.dynamic_inputs === "router_input") {
    inputs = [{ name: "input", type: asPortType(node.config.input_type), label: "Input" }];
  }
  if (info.dynamic_outputs === "input_schema_properties") {
    outputs = schemaPropertyPorts(node.config.input_schema);
  } else if (info.dynamic_outputs === "structured_output_json") {
    outputs = [...outputs];
    if (node.config.structured_output != null) {
      outputs.push({ name: "json", type: "json", label: "JSON" });
    }
  } else if (info.dynamic_outputs === "router_branches") {
    const branchType = asPortType(node.config.input_type);
    outputs = routerBranches(node.config).map((name) => ({
      name,
      type: branchType,
      label: name,
    }));
  }
  return { inputs, outputs };
}

export function portsCompatible(src: PortType, dst: PortType, catalog: NodeCatalog): boolean {
  if (src === dst) return true;
  return catalog.extra_compatible_ports.some(([a, b]) => a === src && b === dst);
}

export interface ConnectionVerdict {
  ok: boolean;
  reason?: string;
}

/** Client-side verdict for a drag; the authoritative answer is /flows/validate. */
export function judgeConnection(
  source: { node: DefinitionNode; port: string },
  target: { node: DefinitionNode; port: string },
  infoByType: Map<string, NodeTypeInfo>,
  catalog: NodeCatalog,
): ConnectionVerdict {
  const srcPorts = nodePorts(source.node, infoByType.get(source.node.type), catalog);
  const dstPorts = nodePorts(target.node, infoByType.get(target.node.type), catalog);
  const srcDecl = srcPorts.outputs.find((p) => p.name === source.port);
  const dstDecl = dstPorts.inputs.find((p) => p.name === target.port);
  if (!srcDecl) return { ok: false, reason: `no output port ${source.port}` };
  if (!dstDecl) return { ok: false, reason: `no input port ${target.port}` };
  if (!portsCompatible(srcDecl.type, dstDecl.type, catalog)) {
    return { ok: false, reason: `${srcDecl.type} → ${dstDecl.type} is not connectable` };
  }
  return { ok: true };
}

/** Port refs ("node.port") that no longer exist after a config change. */
export function danglingEdgeIds(
  nodes: DefinitionNode[],
  edges: { from: string; to: string }[],
  infoByType: Map<string, NodeTypeInfo>,
  catalog: NodeCatalog,
): Set<string> {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const gone = new Set<string>();
  for (const edge of edges) {
    const [srcId, srcPort] = splitRef(edge.from);
    const [dstId, dstPort] = splitRef(edge.to);
    const src = byId.get(srcId);
    const dst = byId.get(dstId);
    const srcOk =
      src !== undefined &&
      nodePorts(src, infoByType.get(src.type), catalog).outputs.some((p) => p.name === srcPort);
    const dstOk =
      dst !== undefined &&
      nodePorts(dst, infoByType.get(dst.type), catalog).inputs.some((p) => p.name === dstPort);
    if (!srcOk || !dstOk) gone.add(`${edge.from}->${edge.to}`);
  }
  return gone;
}

export function splitRef(ref: string): [string, string] {
  const dot = ref.indexOf(".");
  return dot === -1 ? [ref, ""] : [ref.slice(0, dot), ref.slice(dot + 1)];
}
