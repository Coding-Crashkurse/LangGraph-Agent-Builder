/** TS mirror of backend/src/graphforge/compiler/spec.py and API payloads.
 * The pydantic models are the source of truth (CLAUDE.md §7). */

export const START_NODE = "__start__";
export const END_NODE = "__end__";

export interface Position {
  x: number;
  y: number;
}

export interface NodeSpec {
  id: string;
  component: string;
  component_version: number;
  config: Record<string, unknown>;
  position: Position;
}

export type EdgeKind = "control" | "attach";

export interface EdgeSpec {
  kind: EdgeKind;
  source: string;
  source_handle?: string | null;
  target: string;
}

export interface AgentSkillSpec {
  id: string;
  name: string;
  description: string;
  tags: string[];
  examples: string[];
}

export interface AgentCardSpec {
  name: string;
  description: string;
  skills: AgentSkillSpec[];
  default_input_modes: string[];
  default_output_modes: string[];
  provider_organization: string;
  provider_url: string;
}

export interface MCPToolSpec {
  name: string;
  description: string;
}

export interface PublishSpec {
  a2a: boolean;
  mcp: boolean;
  agent_card: AgentCardSpec;
  mcp_tool: MCPToolSpec;
}

export interface FlowEndpoints {
  a2a_url?: string;
  agent_card_url?: string;
  rest_url?: string;
  mcp_url?: string;
}

export interface Flow {
  id: string;
  slug: string;
  name: string;
  description: string;
  version: number;
  nodes: NodeSpec[];
  edges: EdgeSpec[];
  publish: PublishSpec;
  is_published: boolean;
  endpoints: FlowEndpoints;
  created_at: string;
  updated_at: string;
}

export interface ValidationIssue {
  severity: "error" | "warning";
  code: string;
  message: string;
  node_id?: string | null;
  edge_index?: number | null;
}

export interface ValidationReport {
  valid: boolean;
  issues: ValidationIssue[];
}

export type ComponentKind = "node" | "router" | "tool_provider";

export interface ComponentInfo {
  name: string;
  display_name: string;
  description: string;
  category: "llm" | "rag" | "flow" | "tools" | "io";
  version: number;
  kind: ComponentKind;
  accepts_attachments: string[];
  state_reads: string[];
  state_writes: string[];
  config_json_schema: JsonSchema;
  outputs_static?: string[] | null;
  outputs_from_config?: string | null;
  attachment_kind?: string;
}

export interface JsonSchema {
  type?: string;
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  const?: unknown;
  format?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  items?: JsonSchema;
  additionalProperties?: JsonSchema | boolean;
  anyOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  [key: string]: unknown;
}

/** Debug envelope — mirror of runtime/events.py TaskEvent. */
export interface TaskEvent {
  id: string;
  task_id: string;
  flow_id: string;
  source: "a2a" | "mcp" | "system";
  type: string;
  node?: string | null;
  data: Record<string, unknown>;
  ts: string;
}

export type RunState =
  | "submitted"
  | "working"
  | "input-required"
  | "completed"
  | "failed"
  | "canceled"
  | "rejected"
  | "unknown";

export interface Run {
  id: string;
  flow_id: string;
  context_id: string;
  source: "a2a" | "mcp";
  state: RunState;
  input_preview: string;
  error?: string | null;
  created_at: string;
  updated_at: string;
}

/** A2A protocol shapes (camelCase wire format, subset we render). */
export interface A2APart {
  kind: "text" | "data" | "file";
  text?: string;
  data?: Record<string, unknown>;
}

export interface A2AMessage {
  role: "user" | "agent";
  parts: A2APart[];
  messageId?: string;
  taskId?: string;
  contextId?: string;
}

export interface A2AArtifact {
  artifactId?: string;
  name?: string;
  parts: A2APart[];
}

export interface A2ATask {
  id: string;
  contextId: string;
  status: { state: RunState; message?: A2AMessage; timestamp?: string };
  history?: A2AMessage[];
  artifacts?: A2AArtifact[];
}

export interface TaskDetail {
  run: Run;
  task: A2ATask | null;
}

export interface SendMessageResult {
  task: A2ATask | null;
  events: number;
}

export interface PublishResult {
  published: boolean;
  issues: ValidationIssue[];
  endpoints?: FlowEndpoints;
  agent_card?: Record<string, unknown> | null;
}

export interface CollectionInfo {
  name: string;
  documents: number;
}
