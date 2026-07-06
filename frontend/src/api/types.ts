/** Domain types for the /api/v1 contracts.
 *
 * Path/method safety comes from the generated `schema.gen.ts` (npm run gen:api,
 * SPEC §11.2); these interfaces mirror the backend's *pydantic-exported JSON
 * schemas* (FlowSpec, Diagnostic, RunEvent, component descriptors) and are
 * structurally checked against fixtures in vitest.
 */

// ------------------------------------------------------------------ FlowSpec (§5.2)
export interface Position {
  x: number;
  y: number;
}

export interface NodeSpec {
  id: string;
  component_id: string;
  component_version: string;
  label?: string;
  config: Record<string, unknown>;
  position: Position;
  notes?: string;
}

export type EdgeKind = "data" | "tool" | "router";

export interface EdgeSpec {
  id: string;
  kind: EdgeKind;
  source: { node: string; output: string };
  target: { node: string; input: string };
}

export interface A2ASettings {
  enabled: boolean;
  agent_name?: string;
  description?: string;
  tags?: string[];
  examples?: string[];
  input_modes?: string[];
  output_modes?: string[];
  auth?: "public" | "api-key";
  stream_tokens?: boolean;
  push_notifications?: boolean;
}

export interface McpSettings {
  enabled: boolean;
  tool_name?: string;
  description?: string;
  auto_resolve_interrupts?: "approve" | "reject" | null;
}

export interface FlowMeta {
  name: string;
  slug: string;
  description?: string;
  icon?: string;
  tags?: string[];
  a2a?: A2ASettings;
  mcp?: McpSettings;
  settings?: { recursion_limit?: number };
}

export interface FlowSpec {
  schema_version: string;
  flow: FlowMeta;
  nodes: NodeSpec[];
  edges: EdgeSpec[];
  ui?: { viewport?: Record<string, unknown>; sticky_notes?: unknown[] };
  meta?: Record<string, unknown>;
}

export interface FlowInfo {
  id: string;
  slug: string;
  name: string;
  description: string;
  spec: FlowSpec;
  serve_version: string;
  published_version: string | null;
  created_at: string;
  updated_at: string;
}

export interface VersionInfo {
  id: string;
  flow_id: string;
  semver: string;
  changelog: string;
  published_at: string;
}

// ------------------------------------------------------------------ diagnostics (§5.4)
export type Severity = "error" | "warning" | "info";

export interface Diagnostic {
  code: string;
  severity: Severity;
  node_id?: string | null;
  field?: string | null;
  edge_id?: string | null;
  message: string;
  fix_hint?: string | null;
}

export interface ValidateResponse {
  diagnostics: Diagnostic[];
  compile_report: CompileReport | null;
}

export interface CompileReport {
  nodes: { id: string; component_id: string; kind: string; graph_node: boolean }[];
  coercions: { edge_id: string; coercion: string }[];
  channels: Record<string, string>;
  interrupt_points: string[];
  router_tables: Record<string, Record<string, string>>;
  tool_bindings: Record<string, string[]>;
  recursion_limit: number;
  fingerprint: string;
}

// ------------------------------------------------------------------ components (§4.2)
export type PortFamily =
  | "MESSAGE"
  | "DATA"
  | "DOCUMENTS"
  | "EMBEDDING"
  | "MODEL"
  | "TOOLSET"
  | "ROUTE"
  | "FILE"
  | "ANY";

export interface PortSpec {
  schema_ref: string;
  json_schema: Record<string, unknown>;
  family: PortFamily;
  is_list: boolean;
  display_name?: string | null;
}

export interface FieldDescriptor {
  type: string; // widget key for the FieldWidgetRegistry
  name: string;
  display_name: string;
  info: string;
  required: boolean;
  default: unknown;
  advanced: boolean;
  show: boolean;
  dynamic: boolean;
  real_time_refresh: boolean;
  refresh_button: boolean;
  placeholder: string;
  tool_mode: boolean;
  accepts_global_variable: boolean;
  deprecated: boolean;
  as_port: PortSpec | null;
  port_only: boolean;
  // widget extras (options, min/max/step, columns, schema, …)
  [key: string]: unknown;
}

export interface OutputDescriptor {
  name: string;
  display_name: string;
  port: PortSpec;
  method: string | null;
  group: string | null;
}

export type NodeKind = "task" | "router" | "interrupt" | "terminal";

export interface ComponentDescriptor {
  component_id: string;
  version: string;
  display_name: string;
  description: string;
  icon: string;
  category: string;
  tags: string[];
  beta: boolean;
  legacy: boolean;
  node_kind: NodeKind;
  tool_mode_supported: boolean;
  dynamic_outputs_from: string | null;
  fields: FieldDescriptor[];
  outputs: OutputDescriptor[];
  input_ports: Record<string, PortSpec>;
  config_schema: Record<string, unknown>;
}

// ------------------------------------------------------------------ runs & events (§6.2)
export type RunStatus =
  | "pending"
  | "running"
  | "input_required"
  | "completed"
  | "failed"
  | "cancelled";

export interface RunInfo {
  run_id: string;
  flow_id: string | null;
  flow_slug: string;
  thread_id: string;
  mode: string;
  status: RunStatus;
  error_code: string | null;
  error_message: string | null;
  result_preview: string;
  started_at: string;
  finished_at: string | null;
}

export interface RunEvent {
  event: string;
  run_id: string;
  thread_id: string;
  seq: number;
  ts: string;
  data: Record<string, unknown>;
}

export interface RunResult {
  run_id: string;
  thread_id: string;
  status: RunStatus;
  result_text: string;
  result_json: Record<string, unknown> | null;
  interrupt: InterruptPayload | null;
  interrupt_node: string | null;
  error_code: string | null;
  error_message: string | null;
}

/** Normative interrupt payloads (§5.5) — single source for modals AND A2A. */
export interface InterruptPayload {
  kind?: "approval" | "free_text" | "debug_step" | string;
  prompt?: string;
  options?: string[];
  schema?: Record<string, unknown> | null;
  context?: Record<string, unknown>;
  [key: string]: unknown;
}

// ------------------------------------------------------------------ settings surfaces
export interface VariableInfo {
  name: string;
  kind: "generic" | "credential";
  created_at: string;
  updated_at: string;
}

export interface ApiKeyInfo {
  id: string;
  name: string;
  prefix: string;
  scopes: string[];
  created_at: string;
  last_used_at: string | null;
  total_uses: number;
  revoked: boolean;
  key?: string; // present exactly once, on create
}

export interface McpServerInfo {
  id: string;
  name: string;
  transport: "stdio" | "streamable_http" | "sse";
  config: Record<string, unknown>;
  created_at: string;
}

export interface ThreadInfo {
  thread_id: string;
  flow_slug: string;
  runs: number;
  last_run_at: string;
  last_status: string;
}

export const PORT_FAMILY_COLORS: Record<PortFamily, string> = {
  MESSAGE: "#6366f1", // indigo
  DATA: "#64748b", // slate
  DOCUMENTS: "#10b981", // emerald
  EMBEDDING: "#8b5cf6", // violet
  MODEL: "#06b6d4", // cyan
  TOOLSET: "#0ea5e9", // sky
  ROUTE: "#f59e0b", // amber
  FILE: "#f97316", // orange
  ANY: "#9ca3af", // gray (dashed)
};
