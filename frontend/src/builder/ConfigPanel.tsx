/** Node inspector: renders purely from the component descriptor via the
 * FieldWidgetRegistry; dynamic fields round-trip to /components/{cid}/config.
 *
 * The inner <Inspector> is keyed by node id so per-node UI state (liveFields
 * from dynamic refreshes, the Advanced disclosure, pending debounce timers)
 * can never leak from one node into another. */

import {
  BookOpen,
  Boxes,
  ChevronDown,
  ChevronRight,
  FlaskConical,
  GitBranch,
  MousePointerClick,
  Sparkles,
  Wrench,
  Zap,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import type { ComponentDescriptor, FieldDescriptor } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/toast";

import type { CanvasNode } from "./convert";
import { defaultConfig } from "./convert";
import { widgetFor } from "./forms/registry";
import { useBuilder } from "./store";

const CATEGORY_ICONS: Record<string, LucideIcon> = {
  llm: Sparkles,
  rag: BookOpen,
  flow_control: GitBranch,
  tools: Wrench,
  io: Zap,
  data: Boxes,
  testing: FlaskConical,
};

/** Conditional field visibility: a field with `show_when: {field, equals}` is
 * hidden unless the sibling field's current value equals the target. */
function showWhenSatisfied(
  field: FieldDescriptor,
  config: Record<string, unknown>,
): boolean {
  const sw = field.show_when as { field: string; equals: unknown } | undefined;
  if (!sw || typeof sw !== "object") return true;
  return config[sw.field] === sw.equals;
}

export function ConfigPanel() {
  const selectedNodeId = useBuilder((s) => s.selectedNodeId);
  const nodes = useBuilder((s) => s.nodes);
  const descriptors = useBuilder((s) => s.descriptors);

  const node = nodes.find((n) => n.id === selectedNodeId);
  const descriptor = node ? descriptors.get(node.data.componentId) : undefined;

  if (!node || !descriptor) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1.5 px-6 py-10 text-center">
        <MousePointerClick size={22} strokeWidth={1.75} className="text-text-3" aria-hidden />
        <p className="text-[13px] text-text-2">Select a node to configure</p>
        <p className="text-xs text-text-3">
          Fields are generated from the component descriptor — adding a
          component never needs frontend changes.
        </p>
      </div>
    );
  }

  return <Inspector key={node.id} node={node} descriptor={descriptor} />;
}

function Inspector({ node, descriptor }: { node: CanvasNode; descriptor: ComponentDescriptor }) {
  const updateNodeConfig = useBuilder((s) => s.updateNodeConfig);
  const diagnostics = useBuilder((s) => s.diagnostics);

  const [showAdvanced, setShowAdvanced] = useState(false);
  const [liveFields, setLiveFields] = useState<FieldDescriptor[] | null>(null);
  const debounce = useRef<number | null>(null);
  useEffect(
    () => () => {
      // never let a pending dynamic refresh outlive this node's inspector
      if (debounce.current) window.clearTimeout(debounce.current);
    },
    [],
  );

  // descriptor defaults materialize through convert.ts's defaultConfig — the
  // single source shared with node creation (inline widgets read the same map).
  const effectiveConfig = useMemo(
    () => ({ ...defaultConfig(descriptor), ...node.data.config }),
    [descriptor, node.data.config],
  );

  const fields = useMemo(() => {
    const list = liveFields ?? descriptor.fields;
    return list.filter(
      (f) => !f.port_only && f.show && !f.deprecated && showWhenSatisfied(f, effectiveConfig),
    );
  }, [descriptor, liveFields, effectiveConfig]);

  const nodeDiags = diagnostics.filter((d) => d.node_id === node.id);

  const refresh = async (changedField: string, value: unknown) => {
    try {
      const result = await api.components.configChange(descriptor.component_id, {
        config: { ...node.data.config, [changedField]: value },
        changed_field: changedField,
        value,
      });
      setLiveFields(result.fields);
      updateNodeConfig(node.id, result.config);
    } catch (error) {
      toast.error(`refresh failed: ${(error as Error).message}`);
    }
  };

  const setValue = (field: FieldDescriptor, value: unknown) => {
    updateNodeConfig(node.id, { ...node.data.config, [field.name]: value });
    if (field.real_time_refresh || field.dynamic) {
      if (debounce.current) window.clearTimeout(debounce.current);
      debounce.current = window.setTimeout(() => refresh(field.name, value), 300);
    }
  };

  const visible = fields.filter((f) => !f.advanced);
  const advanced = fields.filter((f) => f.advanced);
  const HeaderIcon = CATEGORY_ICONS[descriptor.category] ?? Boxes;

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-center gap-2">
          <span
            className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-surface-2 text-text-2"
            aria-hidden
          >
            <HeaderIcon size={14} strokeWidth={1.75} />
          </span>
          <h2 className="truncate text-[13px] font-semibold text-text-1">
            {node.data.label || descriptor.display_name}
          </h2>
          <Badge tone="muted">{descriptor.node_kind}</Badge>
          {descriptor.beta && <Badge tone="accent">beta</Badge>}
        </div>
        <p className="mt-1.5 text-xs leading-relaxed text-text-3">{descriptor.description}</p>
        <p className="mt-1 truncate font-mono text-[10.5px] text-text-3">
          {descriptor.component_id} @ {descriptor.version} · {node.id}
        </p>
      </div>

      {nodeDiags.length > 0 && (
        <div className="space-y-1 border-b border-border border-l-2 border-l-danger px-4 py-2">
          {nodeDiags.map((d, i) => (
            <p
              key={i}
              className={
                d.severity === "error"
                  ? "text-xs text-danger"
                  : d.severity === "warning"
                    ? "text-xs text-warning"
                    : "text-xs text-port-toolset"
              }
            >
              <span className="font-mono">{d.code}</span> {d.message}
              {d.fix_hint ? <span className="text-text-3"> — {d.fix_hint}</span> : null}
            </p>
          ))}
        </div>
      )}

      <div className="flex-1 px-4 py-3">
        <div className="space-y-4">
          {visible.map((field) => (
            <FieldRow
              key={field.name}
              field={field}
              value={effectiveConfig[field.name]}
              setValue={setValue}
              refresh={refresh}
            />
          ))}
        </div>
        {advanced.length > 0 && (
          <div className="mt-4 border-t border-border pt-3">
            <button
              type="button"
              aria-expanded={showAdvanced}
              className="flex items-center gap-1 rounded text-xs font-medium text-text-2 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? (
                <ChevronDown size={14} strokeWidth={1.75} aria-hidden />
              ) : (
                <ChevronRight size={14} strokeWidth={1.75} aria-hidden />
              )}
              Advanced · {advanced.length}
            </button>
            {showAdvanced && (
              <div className="mt-3 space-y-4 border-l border-border pl-3">
                {advanced.map((field) => (
                  <FieldRow
                    key={field.name}
                    field={field}
                    value={effectiveConfig[field.name]}
                    setValue={setValue}
                    refresh={refresh}
                  />
                ))}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function FieldRow({
  field,
  value,
  setValue,
  refresh,
}: {
  field: FieldDescriptor;
  value: unknown;
  setValue: (field: FieldDescriptor, value: unknown) => void;
  refresh: (changedField: string, value: unknown) => void;
}) {
  const Widget = widgetFor(field);
  return (
    <label className="block">
      <span className="mb-1 flex items-center gap-1 text-xs font-medium text-text-2">
        {field.display_name}
        {field.required && (
          <span className="text-danger" aria-label="required">
            *
          </span>
        )}
      </span>
      <Widget
        field={field}
        value={value}
        onChange={(v) => setValue(field, v)}
        onRefresh={() => refresh(field.name, value)}
      />
      {field.info ? (
        <span className="mt-1 block text-[11px] leading-relaxed text-text-3">{field.info}</span>
      ) : null}
    </label>
  );
}
