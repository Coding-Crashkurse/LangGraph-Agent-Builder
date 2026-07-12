/**
 * Publish dialog — choose the door (SPEC §5): the runtime serves every flow
 * as an A2A agent or an MCP tool. The choice and its fields (tool name,
 * description → agent card) are part of the definition's `expose` block;
 * runtime validation stays authoritative (rejections land in the
 * validation panel).
 */

import { useQuery } from "@tanstack/react-query";
import {
  Bot,
  Check,
  CircleCheck,
  Copy,
  ExternalLink,
  Loader2,
  Rocket,
  Wrench,
} from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import type { PublishResponse } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label, Textarea } from "@/components/ui/input";
import { cn, copyToClipboard } from "@/lib/utils";

import { useBuilder } from "./store";

const TOOL_NAME_RE = /^[a-z][a-z0-9_]*$/;

const DOORS = [
  {
    kind: "a2a" as const,
    icon: Bot,
    title: "A2A agent",
    detail: "Served at /a2a/{name}; other agents discover it via its agent card.",
  },
  {
    kind: "mcp" as const,
    icon: Wrench,
    title: "MCP tool",
    detail: "Served at /mcp/{name}; one tool per flow, args from the start input schema.",
  },
];

function SuccessView({
  result,
  exposeKind,
  registryUiUrl,
  onClose,
}: {
  result: PublishResponse;
  exposeKind: "a2a" | "mcp";
  registryUiUrl: string;
  onClose: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const cardUrl = `${result.endpoint_url.replace(/\/$/, "")}/.well-known/agent-card.json`;
  return (
    <div>
      <p className="inline-flex items-center gap-1.5 text-sm text-success">
        <CircleCheck size={15} /> Version {result.version} is live on the runtime.
      </p>
      <div className="mt-3 rounded-lg border border-border bg-canvas p-2.5">
        <p className="text-[11px] uppercase tracking-wide text-text-3">Endpoint</p>
        <div className="mt-1 flex items-center gap-2">
          <code className="min-w-0 flex-1 truncate font-mono text-xs text-text-1">
            {result.endpoint_url}
          </code>
          <Button
            size="icon"
            variant="ghost"
            aria-label="Copy endpoint URL"
            onClick={() => {
              void copyToClipboard(result.endpoint_url).then(() => setCopied(true));
            }}
          >
            {copied ? <Check size={13} /> : <Copy size={13} />}
          </Button>
        </div>
      </div>
      <div className="mt-2 flex flex-col gap-1 text-xs text-text-3">
        {exposeKind === "a2a" ? (
          <a
            className="inline-flex items-center gap-1 text-accent hover:underline"
            href={cardUrl}
            target="_blank"
            rel="noreferrer"
          >
            View the served agent card <ExternalLink size={11} />
          </a>
        ) : (
          <span>
            Connect MCP clients via streamable HTTP at the endpoint above (tool args =
            start input schema).
          </span>
        )}
        {registryUiUrl && (
          <a
            className="inline-flex items-center gap-1 text-accent hover:underline"
            href={
              result.registry_id
                ? `${registryUiUrl.replace(/\/$/, "")}/${result.registry_id}`
                : registryUiUrl
            }
            target="_blank"
            rel="noreferrer"
          >
            Open in registry <ExternalLink size={11} />
          </a>
        )}
      </div>
      <div className="mt-4 flex justify-end">
        <Button size="sm" variant="secondary" onClick={onClose}>
          Done
        </Button>
      </div>
    </div>
  );
}

export function PublishDialog({
  flowName,
  open,
  onClose,
  onPublish,
}: {
  flowName: string;
  open: boolean;
  onClose: () => void;
  onPublish: () => Promise<PublishResponse | null>;
}) {
  const meta = useBuilder((s) => s.meta);
  const updateMeta = useBuilder((s) => s.updateMeta);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<PublishResponse | null>(null);
  const config = useQuery({ queryKey: ["config"], queryFn: api.config.get });

  const expose = meta.expose;
  const isMcp = expose.kind === "mcp";
  const toolNameOk = !isMcp || TOOL_NAME_RE.test(expose.tool_name ?? "");
  const cardSparse = !isMcp && !meta.description && !meta.display_name;

  const close = () => {
    setResult(null);
    onClose();
  };

  const publish = async () => {
    setBusy(true);
    try {
      const published = await onPublish();
      if (published) setResult(published);
      else onClose(); // rejection details are in the validation panel
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onClose={close} title={`Publish ${flowName}`} className="max-w-lg">
      {result ? (
        <SuccessView
          result={result}
          exposeKind={expose.kind}
          registryUiUrl={config.data?.registry_ui_url ?? ""}
          onClose={close}
        />
      ) : (
        <div className="flex flex-col gap-3">
          <div>
            <Label hint="How the runtime serves this flow.">Choose the door</Label>
            <div className="grid grid-cols-2 gap-2">
              {DOORS.map((door) => (
                <button
                  key={door.kind}
                  type="button"
                  onClick={() => updateMeta({ expose: { ...expose, kind: door.kind } })}
                  className={cn(
                    "rounded-lg border p-2.5 text-left transition-colors",
                    expose.kind === door.kind
                      ? "border-accent bg-accent/10"
                      : "border-border bg-surface-2 hover:border-border-strong",
                  )}
                >
                  <span
                    className={cn(
                      "flex items-center gap-1.5 text-xs font-semibold",
                      expose.kind === door.kind ? "text-accent" : "text-text-1",
                    )}
                  >
                    <door.icon size={13} /> {door.title}
                  </span>
                  <span className="mt-1 block text-[11px] leading-relaxed text-text-3">
                    {door.detail}
                  </span>
                </button>
              ))}
            </div>
          </div>
          <div>
            <Label>Display name</Label>
            <Input
              value={meta.display_name}
              placeholder={flowName}
              onChange={(e) => updateMeta({ display_name: e.target.value })}
            />
          </div>
          <div>
            <Label hint={isMcp ? "" : "becomes the agent card description"}>Description</Label>
            <Textarea
              rows={2}
              value={meta.description}
              onChange={(e) => updateMeta({ description: e.target.value })}
            />
            {cardSparse && (
              <p className="mt-1 text-[11px] text-warning">
                Empty description → a sparse agent card; agents route better with one.
              </p>
            )}
          </div>
          <div>
            <Label hint={isMcp ? "comma separated" : "comma separated — become the card's skill tags"}>
              Tags
            </Label>
            <Input
              value={meta.tags.join(", ")}
              placeholder="support, rag"
              onChange={(e) =>
                updateMeta({
                  tags: e.target.value
                    .split(",")
                    .map((t) => t.trim())
                    .filter(Boolean),
                })
              }
            />
          </div>
          {isMcp && (
            <>
              <div>
                <Label hint="^[a-z][a-z0-9_]*$">Tool name</Label>
                <Input
                  className="font-mono"
                  value={expose.tool_name ?? ""}
                  placeholder="search_support_kb"
                  onChange={(e) =>
                    updateMeta({ expose: { ...expose, tool_name: e.target.value || null } })
                  }
                />
                {!toolNameOk && (
                  <p className="mt-1 text-[11px] text-danger">
                    Required for MCP (E050): lowercase, digits, underscores.
                  </p>
                )}
              </div>
              <div>
                <Label>Tool description</Label>
                <Textarea
                  rows={2}
                  value={expose.tool_description ?? ""}
                  onChange={(e) =>
                    updateMeta({ expose: { ...expose, tool_description: e.target.value } })
                  }
                />
              </div>
              <p className="text-[11px] text-text-3">
                MCP tools need a start input schema — it becomes the tool's argument
                schema (E050 otherwise).
              </p>
            </>
          )}
          <div className="mt-1 flex items-center justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={close}>
              Cancel
            </Button>
            <Button size="sm" disabled={busy || !toolNameOk} onClick={() => void publish()}>
              {busy ? <Loader2 size={13} className="animate-spin" /> : <Rocket size={13} />}
              Publish
            </Button>
          </div>
        </div>
      )}
    </Dialog>
  );
}
