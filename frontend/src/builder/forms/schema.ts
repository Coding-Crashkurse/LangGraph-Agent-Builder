/** JSON-Schema helpers for the in-house form renderer.
 * Decision (CLAUDE.md §4): thin in-house renderer instead of @rjsf — our
 * component configs only need a small, predictable subset of JSON Schema. */

import type { JsonSchema } from "@/api/types";

export function resolveSchema(schema: JsonSchema, root: JsonSchema): JsonSchema {
  if (schema.$ref) {
    const key = schema.$ref.replace("#/$defs/", "");
    const resolved = root.$defs?.[key];
    return resolved ? { ...resolveSchema(resolved, root), ...omitRef(schema) } : schema;
  }
  if (schema.allOf && schema.allOf.length === 1) {
    return { ...resolveSchema(schema.allOf[0], root), ...omitKey(schema, "allOf") };
  }
  if (schema.anyOf) {
    const nonNull = schema.anyOf.filter((s) => s.type !== "null");
    if (nonNull.length === 1) {
      return { ...resolveSchema(nonNull[0], root), ...omitKey(schema, "anyOf") };
    }
  }
  return schema;
}

function omitRef(schema: JsonSchema): JsonSchema {
  const rest = { ...schema };
  delete rest.$ref;
  return rest;
}

function omitKey(schema: JsonSchema, key: "allOf" | "anyOf"): JsonSchema {
  const copy = { ...schema };
  delete copy[key];
  return copy;
}

export type Widget =
  | "text"
  | "textarea"
  | "number"
  | "integer"
  | "switch"
  | "select"
  | "tags"
  | "keyvalue"
  | "json";

const TEXTAREA_HINTS = ["prompt", "template", "instruction", "description", "text"];

export function widgetFor(key: string, schema: JsonSchema): Widget {
  if (schema.enum?.length) return "select";
  switch (schema.type) {
    case "boolean":
      return "switch";
    case "integer":
      return "integer";
    case "number":
      return "number";
    case "array":
      if (schema.items && resolvedType(schema.items) === "string") return "tags";
      return "json";
    case "object":
      if (
        schema.additionalProperties &&
        typeof schema.additionalProperties === "object" &&
        resolvedType(schema.additionalProperties) === "string"
      ) {
        return "keyvalue";
      }
      return "json";
    case "string":
      if (schema.format === "textarea") return "textarea";
      if (TEXTAREA_HINTS.some((hint) => key.toLowerCase().includes(hint))) return "textarea";
      return "text";
    default:
      return "json";
  }
}

function resolvedType(schema: JsonSchema): string | undefined {
  if (schema.anyOf) {
    const nonNull = schema.anyOf.filter((s) => s.type !== "null");
    if (nonNull.length === 1) return nonNull[0].type;
  }
  return schema.type;
}

export function defaultsFromSchema(schema: JsonSchema): Record<string, unknown> {
  const result: Record<string, unknown> = {};
  const properties = schema.properties ?? {};
  for (const [key, raw] of Object.entries(properties)) {
    const field = resolveSchema(raw, schema);
    if (field.default !== undefined) {
      result[key] = field.default;
      continue;
    }
    switch (field.type) {
      case "string":
        result[key] = "";
        break;
      case "boolean":
        result[key] = false;
        break;
      case "integer":
      case "number":
        result[key] = field.minimum ?? 0;
        break;
      case "array":
        result[key] = [];
        break;
      case "object":
        result[key] = {};
        break;
      default:
        break;
    }
  }
  return result;
}

export function prettyLabel(key: string, schema: JsonSchema): string {
  if (schema.title && schema.title !== key) return schema.title;
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
