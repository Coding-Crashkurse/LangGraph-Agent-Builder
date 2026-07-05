import { useMutation } from "@tanstack/react-query";
import { Check, Copy, Globe, Server } from "lucide-react";
import { useMemo, useState } from "react";

import { api } from "@/api/client";
import type { Flow, PublishResult, PublishSpec } from "@/api/types";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/controls";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import { copyToClipboard } from "@/lib/utils";
import { AgentCardEditor } from "./AgentCardEditor";

export function PublishDialog({
  flow,
  open,
  onClose,
  onBeforePublish,
  onPublished,
}: {
  flow: Flow;
  open: boolean;
  onClose: () => void;
  onBeforePublish: () => Promise<void>; // save the canvas first
  onPublished: () => void;
}) {
  const [spec, setSpec] = useState<PublishSpec>(() => structuredClone(flow.publish));
  const [result, setResult] = useState<PublishResult | null>(null);

  const cardPreview = useMemo(
    () =>
      JSON.stringify(
        {
          name: spec.agent_card.name || flow.name,
          description: spec.agent_card.description || flow.description || flow.name,
          url: `${window.location.origin}/serve/a2a/${flow.slug}/`,
          version: String(flow.version),
          capabilities: { streaming: true, pushNotifications: false },
          defaultInputModes: spec.agent_card.default_input_modes,
          defaultOutputModes: spec.agent_card.default_output_modes,
          skills: spec.agent_card.skills,
        },
        null,
        2,
      ),
    [spec, flow],
  );

  const publish = useMutation({
    mutationFn: async () => {
      await onBeforePublish();
      return api.flows.publish(flow.id, spec);
    },
    onSuccess: (data) => {
      setResult(data);
      if (data.published) {
        toast.success("Flow published");
        onPublished();
      } else {
        toast.error("Publish failed — fix the validation issues");
      }
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const unpublish = useMutation({
    mutationFn: () => api.flows.unpublish(flow.id),
    onSuccess: () => {
      toast.info("Flow unpublished");
      setResult(null);
      onPublished();
    },
  });

  return (
    <Dialog open={open} onClose={onClose} title={`Publish “${flow.name}”`} className="w-[760px]">
      <div className="grid grid-cols-[1fr_280px] gap-5">
        <div className="space-y-4">
          <div className="flex items-center gap-6 rounded-lg border border-surface-700 bg-surface-850 px-4 py-3">
            <label className="flex items-center gap-2.5 text-sm text-zinc-200">
              <Switch
                checked={spec.a2a}
                onCheckedChange={(a2a) => setSpec({ ...spec, a2a })}
                label="A2A"
              />
              <Globe className="h-4 w-4 text-violet-400" /> A2A server
            </label>
            <label className="flex items-center gap-2.5 text-sm text-zinc-200">
              <Switch
                checked={spec.mcp}
                onCheckedChange={(mcp) => setSpec({ ...spec, mcp })}
                label="MCP"
              />
              <Server className="h-4 w-4 text-sky-400" /> MCP server
            </label>
          </div>

          {spec.mcp && (
            <div className="grid grid-cols-2 gap-3 rounded-lg border border-surface-700 bg-surface-850 px-4 py-3">
              <div>
                <Label>MCP tool name</Label>
                <Input
                  value={spec.mcp_tool.name}
                  className="font-mono text-xs"
                  onChange={(e) =>
                    setSpec({ ...spec, mcp_tool: { ...spec.mcp_tool, name: e.target.value } })
                  }
                />
              </div>
              <div>
                <Label>Tool description</Label>
                <Input
                  value={spec.mcp_tool.description}
                  onChange={(e) =>
                    setSpec({
                      ...spec,
                      mcp_tool: { ...spec.mcp_tool, description: e.target.value },
                    })
                  }
                />
              </div>
            </div>
          )}

          <AgentCardEditor
            value={spec.agent_card}
            onChange={(agent_card) => setSpec({ ...spec, agent_card })}
            flowName={flow.name}
          />
        </div>

        <div className="space-y-3">
          <div>
            <Label>Agent card preview</Label>
            <pre className="max-h-72 overflow-auto rounded-lg border border-surface-700 bg-surface-950 p-3 font-mono text-[10px] leading-relaxed text-zinc-400">
              {cardPreview}
            </pre>
          </div>

          {result?.issues?.length ? (
            <div className="space-y-1">
              {result.issues.map((issue, index) => (
                <div
                  key={index}
                  className="rounded-md border border-red-900/50 bg-red-950/30 px-2 py-1.5 text-[11px] text-red-300"
                >
                  {issue.message}
                </div>
              ))}
            </div>
          ) : null}

          {result?.published && result.endpoints ? (
            <div className="space-y-1.5">
              <Label>Endpoints</Label>
              {Object.entries(result.endpoints).map(([key, url]) => (
                <EndpointRow key={key} label={key.replace("_url", "")} url={url} />
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <div className="mt-5 flex items-center justify-between border-t border-surface-800 pt-4">
        {flow.is_published ? (
          <Button
            variant="destructive"
            size="sm"
            disabled={unpublish.isPending}
            onClick={() => unpublish.mutate()}
          >
            Unpublish
          </Button>
        ) : (
          <span />
        )}
        <div className="flex items-center gap-2">
          {flow.is_published && <Badge color="emerald">currently live</Badge>}
          <Button
            disabled={publish.isPending || (!spec.a2a && !spec.mcp)}
            onClick={() => publish.mutate()}
          >
            {publish.isPending ? "Publishing…" : flow.is_published ? "Republish" : "Publish"}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

export function EndpointRow({ label, url }: { label: string; url: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <div className="flex items-center gap-1.5 rounded-md border border-surface-700 bg-surface-950 px-2 py-1.5">
      <span className="w-16 shrink-0 font-mono text-[9px] uppercase tracking-wider text-zinc-500">
        {label}
      </span>
      <span className="flex-1 truncate font-mono text-[10px] text-zinc-300">{url}</span>
      <button
        type="button"
        aria-label={`copy ${label} url`}
        className="text-zinc-500 hover:text-zinc-100"
        onClick={async () => {
          await copyToClipboard(url);
          setCopied(true);
          setTimeout(() => setCopied(false), 1200);
        }}
      >
        {copied ? <Check className="h-3.5 w-3.5 text-emerald-400" /> : <Copy className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}
