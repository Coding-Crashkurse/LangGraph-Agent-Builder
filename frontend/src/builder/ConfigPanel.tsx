/** Node inspector: renders purely from the component descriptor via the
 * FieldWidgetRegistry; dynamic fields round-trip to /components/{cid}/config. */

import { useMemo, useRef, useState } from "react";

import { api } from "@/api/client";
import type { FieldDescriptor } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/toast";

import { widgetFor } from "./forms/registry";
import { useBuilder } from "./store";

export function ConfigPanel() {
  const selectedNodeId = useBuilder((s) => s.selectedNodeId);
  const nodes = useBuilder((s) => s.nodes);
  const descriptors = useBuilder((s) => s.descriptors);
  const updateNodeConfig = useBuilder((s) => s.updateNodeConfig);
  const diagnostics = useBuilder((s) => s.diagnostics);

  const node = nodes.find((n) => n.id === selectedNodeId);
  const descriptor = node ? descriptors.get(node.data.componentId) : undefined;
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [liveFields, setLiveFields] = useState<FieldDescriptor[] | null>(null);
  const debounce = useRef<number | null>(null);

  const fields = useMemo(() => {
    const list = liveFields ?? descriptor?.fields ?? [];
    return list.filter((f) => !f.port_only && f.show && !f.deprecated);
  }, [descriptor, liveFields]);

  if (!node || !descriptor) {
    return (
      <div className="p-4 text-sm text-zinc-500">
        Select a node to configure it. Fields are generated from the component
        descriptor — adding a component never needs frontend changes.
      </div>
    );
  }

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

  return (
    <div className="flex h-full flex-col overflow-y-auto">
      <div className="border-b border-surface-800 px-4 py-3">
        <div className="flex items-center gap-2">
          <h2 className="text-sm font-semibold text-zinc-100">{descriptor.display_name}</h2>
          <Badge tone="muted">{descriptor.node_kind}</Badge>
          {descriptor.beta && <Badge tone="violet">beta</Badge>}
        </div>
        <p className="mt-1 text-xs text-zinc-500">{descriptor.description}</p>
        <p className="mt-1 font-mono text-[10px] text-zinc-600">
          {descriptor.component_id} @ {descriptor.version} · node {node.id}
        </p>
      </div>

      {nodeDiags.length > 0 && (
        <div className="space-y-1 border-b border-surface-800 px-4 py-2">
          {nodeDiags.map((d, i) => (
            <p
              key={i}
              className={
                d.severity === "error"
                  ? "text-xs text-red-400"
                  : d.severity === "warning"
                    ? "text-xs text-amber-400"
                    : "text-xs text-sky-400"
              }
            >
              <span className="font-mono">{d.code}</span> {d.message}
              {d.fix_hint ? <span className="text-zinc-500"> — {d.fix_hint}</span> : null}
            </p>
          ))}
        </div>
      )}

      <div className="flex-1 space-y-4 px-4 py-3">
        {visible.map((field) => (
          <FieldRow key={field.name} field={field} node={node} setValue={setValue}
                    refresh={refresh} />
        ))}
        {advanced.length > 0 && (
          <div>
            <button
              type="button"
              className="text-xs font-medium text-zinc-400 hover:text-zinc-100"
              onClick={() => setShowAdvanced((v) => !v)}
            >
              {showAdvanced ? "▾" : "▸"} Advanced ({advanced.length})
            </button>
            {showAdvanced && (
              <div className="mt-3 space-y-4 border-l border-surface-800 pl-3">
                {advanced.map((field) => (
                  <FieldRow key={field.name} field={field} node={node} setValue={setValue}
                            refresh={refresh} />
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
  node,
  setValue,
  refresh,
}: {
  field: FieldDescriptor;
  node: { data: { config: Record<string, unknown> } };
  setValue: (field: FieldDescriptor, value: unknown) => void;
  refresh: (changedField: string, value: unknown) => void;
}) {
  const Widget = widgetFor(field);
  const value = node.data.config[field.name] ?? field.default;
  return (
    <label className="block">
      <span className="mb-1 flex items-center gap-1 text-xs font-medium text-zinc-300">
        {field.display_name}
        {field.required && <span className="text-red-400">*</span>}
        {field.info && (
          <span className="cursor-help text-zinc-600" title={field.info}>
            ⓘ
          </span>
        )}
      </span>
      <Widget
        field={field}
        value={value}
        onChange={(v) => setValue(field, v)}
        onRefresh={() => refresh(field.name, value)}
      />
    </label>
  );
}
