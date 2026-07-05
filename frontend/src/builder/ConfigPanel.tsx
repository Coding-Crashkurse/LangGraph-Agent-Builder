import { AlertTriangle, Trash2 } from "lucide-react";

import { Badge, CategoryDot } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input, Label, Textarea } from "@/components/ui/input";
import { SchemaForm } from "./forms/SchemaForm";
import { useBuilder } from "./store";

export function ConfigPanel({
  flowName,
  flowDescription,
  onMetaChange,
}: {
  flowName: string;
  flowDescription: string;
  onMetaChange: (meta: { name: string; description: string }) => void;
}) {
  const { nodes, selectedNodeId, issues, updateConfig, select, onNodesChange } = useBuilder();
  const selected = nodes.find((n) => n.id === selectedNodeId && n.type === "component");

  return (
    <aside className="flex w-[340px] shrink-0 flex-col overflow-y-auto border-l border-surface-800 bg-surface-900">
      {selected && selected.type === "component" ? (
        <>
          <div className="border-b border-surface-800 px-4 py-3">
            <div className="flex items-center gap-2">
              <CategoryDot category={selected.data.info?.category ?? "io"} />
              <h3 className="text-sm font-semibold text-zinc-100">
                {selected.data.info?.display_name ?? selected.data.component}
              </h3>
              <Button
                variant="ghost"
                size="icon"
                className="ml-auto text-zinc-500 hover:text-red-400"
                aria-label="delete node"
                onClick={() => {
                  onNodesChange([{ type: "remove", id: selected.id }]);
                  select(null);
                }}
              >
                <Trash2 className="h-3.5 w-3.5" />
              </Button>
            </div>
            <div className="mt-1 font-mono text-[10px] text-zinc-500">{selected.id}</div>
            <p className="mt-1.5 text-[11px] leading-snug text-zinc-500">
              {selected.data.info?.description}
            </p>
            <div className="mt-2 flex flex-wrap gap-1">
              {selected.data.info?.state_reads.map((key) => (
                <Badge key={`r-${key}`} color="zinc">
                  reads {key}
                </Badge>
              ))}
              {selected.data.info?.state_writes.map((key) => (
                <Badge key={`w-${key}`} color="violet">
                  writes {key}
                </Badge>
              ))}
            </div>
          </div>
          {selected.data.issues.length > 0 && (
            <div className="border-b border-surface-800 bg-red-950/30 px-4 py-2.5">
              {selected.data.issues.map((issue, index) => (
                <div key={index} className="flex items-start gap-1.5 py-0.5 text-[11px] text-red-300">
                  <AlertTriangle className="mt-0.5 h-3 w-3 shrink-0" />
                  {issue.message}
                </div>
              ))}
            </div>
          )}
          <div className="flex-1 px-4 py-4">
            {selected.data.info ? (
              <SchemaForm
                schema={selected.data.info.config_json_schema}
                value={selected.data.config}
                onChange={(config) => updateConfig(selected.id, config)}
              />
            ) : (
              <p className="text-xs text-zinc-500">
                Unknown component "{selected.data.component}" — is it still registered?
              </p>
            )}
          </div>
        </>
      ) : (
        <div className="px-4 py-4">
          <h3 className="mb-3 text-sm font-semibold text-zinc-100">Flow settings</h3>
          <div className="space-y-3">
            <div>
              <Label>Name</Label>
              <Input
                value={flowName}
                onChange={(e) => onMetaChange({ name: e.target.value, description: flowDescription })}
              />
            </div>
            <div>
              <Label>Description</Label>
              <Textarea
                value={flowDescription}
                rows={3}
                onChange={(e) => onMetaChange({ name: flowName, description: e.target.value })}
              />
            </div>
          </div>
          <div className="mt-5">
            <h4 className="mb-2 text-xs font-semibold uppercase tracking-wider text-zinc-500">
              Validation
            </h4>
            {issues.length === 0 ? (
              <p className="text-[11px] text-zinc-600">
                No issues. Run “Validate” to check the current canvas against the compiler rules.
              </p>
            ) : (
              <div className="space-y-1">
                {issues.map((issue, index) => (
                  <div
                    key={index}
                    className={
                      issue.severity === "error"
                        ? "rounded-md border border-red-900/50 bg-red-950/30 px-2 py-1.5 text-[11px] text-red-300"
                        : "rounded-md border border-amber-900/50 bg-amber-950/20 px-2 py-1.5 text-[11px] text-amber-300"
                    }
                  >
                    <span className="font-mono text-[9px] uppercase opacity-70">{issue.code}</span>
                    <div>{issue.message}</div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
