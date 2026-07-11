/** Domain types for the /api/v1 contracts.
 *
 * Path/method safety comes from the generated `schema.gen.ts` (pnpm gen:api,
 * SPEC §11.2); these interfaces mirror the backend's *pydantic-exported JSON
 * schemas* (FlowSpec, Diagnostic, RunEvent, component descriptors).
 *
 * KNOWN DEBT (SPEC §11.5 forbids hand-written mirrors): these should be
 * aliases of `components["schemas"]` once the backend endpoints expose the
 * real pydantic models to OpenAPI — until then schema.gen.ts types FlowSpec
 * as a plain object and this file is the single hand-written mirror.
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
  /** Single active serving surface (SPEC §5.2) — authoritative over the
   * legacy enabled booleans; must be written together with them. */
  serving?: { mode: "api" | "mcp" | "a2a" };
  settings?: { recursion_limit?: number };
}

export interface StickyNote {
  id: string;
  text: string;
  position: { x: number; y: number };
  color: string;
}

export interface FlowSpec {
  schema_version: string;
  flow: FlowMeta;
  nodes: NodeSpec[];
  edges: EdgeSpec[];
  ui?: { viewport?: Record<string, unknown>; sticky_notes?: StickyNote[] };
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
  | "TABLE"
  | "DOCUMENTS"
  | "EMBEDDING"
  | "MODEL"
  | "VECTORSTORE"
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
  priority?: number | null;
  beta: boolean;
  legacy: boolean;
  node_kind: NodeKind;
  tool_mode_supported: boolean;
  tool_mode_default?: boolean;
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

// ------------------------------------------------------------------ resources layer
/** Long-lived, flow-referenced configuration. Flows point at these by name via
 * a {"$resource": name} binding (model_provider additionally carries an optional
 * `model`). Secrets are masked inside `config` on read. */
export type ResourceType =
  | "model_provider"
  | "knowledge_base"
  | "mcp_server"
  | "a2a_agent";

export interface ResourceInfo {
  name: string;
  config: Record<string, unknown>;
  updated_at: string;
  ok?: boolean;
  error?: string | null;
  // per-type extras (cached card, models, …) may ride on the row
  [key: string]: unknown;
}

/** provider ∈ openai | anthropic | ollama | custom. */
export interface ModelProviderConfig {
  provider?: string;
  base_url?: string;
  api_key?: unknown; // {"$secret": name} ref (masked on read)
  models?: string[];
  [key: string]: unknown;
}

export interface KnowledgeBaseConfig {
  vectorstore?: string;
  collection?: string;
  embedding?: { provider?: string; model?: string };
  [key: string]: unknown;
}

export interface A2AAgentConfig {
  url?: string;
  auth?: unknown; // optional {"$secret": name}
  card?: Record<string, unknown>; // cached Agent Card
  [key: string]: unknown;
}

/** Result of POST /resources/{type}/{name}/test (health / card-fetch / auth). */
export interface ResourceTestResult {
  ok: boolean;
  error?: string;
  detail?: unknown;
}

/** A flow field bound to a resource: {"$resource": name} (+ model for providers). */
export interface ResourceRef {
  $resource: string;
  model?: string;
}

// Port family colours resolve to the Appendix C theme tokens — the token file
// is the single source of colour (SPEC §11.1/§11.5).
export const PORT_FAMILY_COLORS: Record<PortFamily, string> = {
  MESSAGE: "var(--color-port-message)",
  DATA: "var(--color-port-data)",
  TABLE: "var(--color-port-table)",
  DOCUMENTS: "var(--color-port-documents)",
  EMBEDDING: "var(--color-port-embedding)",
  MODEL: "var(--color-port-model)",
  VECTORSTORE: "var(--color-port-vectorstore)",
  TOOLSET: "var(--color-port-toolset)",
  ROUTE: "var(--color-port-route)",
  FILE: "var(--color-port-file)",
  ANY: "var(--color-port-any)",
};
