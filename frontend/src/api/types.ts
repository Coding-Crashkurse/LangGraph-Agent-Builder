/**
 * Types mirroring the backend API (SPEC §3). The FlowDefinition shape is the
 * platform contract (agentplane flow-definition.schema.json); the frontend
 * never persists its own graph format — the backend is the single
 * serializer/deserializer.
 */

// ---------------------------------------------------------------- definition

export type PortType = "text" | "json" | "message" | "documents";
export type ExposeKind = "a2a" | "mcp";

export interface ExposeConfig {
  kind: ExposeKind;
  tool_name?: string | null;
  tool_description?: string;
}

export interface DefinitionNode {
  id: string;
  type: string;
  version: number;
  config: Record<string, unknown>;
}

export interface DefinitionEdge {
  from: string; // "node_id.port"
  to: string; // "node_id.port"
}

export interface LayoutPosition {
  x: number;
  y: number;
}

export interface FlowDefinition {
  schema_version: number;
  name: string;
  display_name?: string;
  description?: string;
  tags?: string[];
  expose: ExposeConfig;
  nodes: DefinitionNode[];
  edges: DefinitionEdge[];
  layout?: { nodes: Record<string, LayoutPosition> } | null;
}

/** JSON Schema documents are open-ended; treated as opaque objects. */
export type JsonSchema = Record<string, unknown>;

// ---------------------------------------------------------------- node catalog

export interface PortDecl {
  name: string;
  type: PortType;
  label: string;
}

export type WidgetKind =
  | "text"
  | "textarea"
  | "prompt"
  | "schema"
  | "json"
  | "switch"
  | "number"
  | "dict"
  | "resource";

export type ResourceGroup = "model_provider" | "vector_db" | "mcp_server";

export interface FieldUI {
  widget: WidgetKind;
  label: string;
  help: string;
  placeholder: string;
  resource_kind: ResourceGroup | null;
  advanced: boolean;
}

export interface NodeTypeInfo {
  type: string;
  version: number;
  label: string;
  icon: string;
  category: string;
  description: string;
  config_schema: JsonSchema;
  inputs: PortDecl[];
  outputs: PortDecl[];
  dynamic_inputs: "prompt_vars" | "arg_keys" | null;
  dynamic_outputs: "input_schema_properties" | "structured_output_json" | null;
  ui: Record<string, FieldUI>;
}

export interface NodeCatalog {
  node_types: NodeTypeInfo[];
  prompt_var_pattern: string;
  extra_compatible_ports: [PortType, PortType][];
}

// ---------------------------------------------------------------- validation

export type IssueSource = "local" | "runtime";
export type IssueSeverity = "error" | "warning";

export interface SourcedIssue {
  code: string;
  severity: IssueSeverity;
  path: string;
  message: string;
  source: IssueSource;
}

export interface ValidationResponse {
  valid: boolean;
  runtime_checked: boolean;
  issues: SourcedIssue[];
}

// ---------------------------------------------------------------- flows api

export interface FlowSummary {
  name: string;
  display_name: string;
  description: string;
  tags: string[];
  expose_kind: string;
  updated_at: string;
}

export interface FlowDetail {
  name: string;
  definition: FlowDefinition;
  created_at: string;
  updated_at: string;
}

export interface PublishResponse {
  name: string;
  version: number;
  endpoint_url: string;
  registry_id: string | null;
}

export interface PlaygroundResponse {
  name: string;
  endpoint_url: string;
}

export interface ImportResponse {
  name: string;
  created: boolean;
}

export interface ResourceSummary {
  name: string;
  kind: string;
  group: ResourceGroup;
  display_name: string;
}

export interface FrontendConfig {
  version: string;
  auth_mode: "none" | "oidc";
  oidc_issuer: string;
  oidc_client_id: string;
  runtime_configured: boolean;
  resources_ui_url: string;
  registry_ui_url: string;
}
