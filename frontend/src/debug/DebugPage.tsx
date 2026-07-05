import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, ExternalLink, Hammer } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api } from "@/api/client";
import { useEventStream } from "@/api/sse";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs } from "@/components/ui/controls";
import { EndpointRow } from "@/builder/PublishDialog";
import { Playground } from "./Playground";
import { TaskDetail } from "./TaskDetail";
import { TaskList } from "./TaskList";

export function DebugPage() {
  const { flowId = "" } = useParams();
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<"tasks" | "playground">("tasks");
  const [selectedTask, setSelectedTask] = useState<string | null>(null);

  const flow = useQuery({ queryKey: ["flow", flowId], queryFn: () => api.flows.get(flowId) });

  // flow firehose keeps the task list live
  const firehose = useEventStream(flowId ? `/api/debug/flows/${flowId}/events` : null, 500);
  const refetchTimer = useRef<number | null>(null);
  useEffect(() => {
    if (!firehose.events.length) return;
    if (refetchTimer.current) window.clearTimeout(refetchTimer.current);
    refetchTimer.current = window.setTimeout(() => {
      queryClient.invalidateQueries({ queryKey: ["tasks", flowId] });
    }, 400);
  }, [firehose.events, flowId, queryClient]);

  const endpoints = useMemo(() => Object.entries(flow.data?.endpoints ?? {}), [flow.data]);

  if (flow.isLoading) return <div className="p-8 text-sm text-zinc-500">Loading…</div>;
  if (!flow.data) return <div className="p-8 text-sm text-red-400">Flow not found.</div>;

  return (
    <div className="flex h-screen flex-col">
      <header className="shrink-0 border-b border-surface-800 bg-surface-900 px-4 py-3">
        <div className="flex items-center gap-3">
          <Link to="/" className="text-zinc-500 hover:text-zinc-200" aria-label="back">
            <ArrowLeft className="h-4 w-4" />
          </Link>
          <div className="flex items-baseline gap-2">
            <h1 className="text-sm font-semibold text-zinc-100">{flow.data.name}</h1>
            <span className="font-mono text-[10px] text-zinc-600">
              debug · v{flow.data.version}
            </span>
          </div>
          {flow.data.is_published ? (
            <Badge color="emerald">published</Badge>
          ) : (
            <Badge color="amber">not published — publish from the builder first</Badge>
          )}
          <span
            className={
              firehose.connected
                ? "text-[10px] font-medium text-emerald-400"
                : "text-[10px] text-zinc-600"
            }
          >
            ● live
          </span>
          <div className="ml-auto flex items-center gap-1.5">
            <Tabs
              value={tab}
              onChange={setTab}
              items={[
                { value: "tasks", label: "Tasks" },
                { value: "playground", label: "Playground" },
              ]}
            />
            <Link to={`/flows/${flowId}`}>
              <Button variant="secondary" size="sm">
                <Hammer className="h-3.5 w-3.5" /> Builder
              </Button>
            </Link>
          </div>
        </div>
        {endpoints.length > 0 && (
          <div className="mt-2.5 grid grid-cols-2 gap-1.5 xl:grid-cols-4">
            {endpoints.map(([key, url]) => (
              <EndpointRow key={key} label={key.replace("_url", "")} url={url} />
            ))}
            {flow.data.endpoints.agent_card_url && (
              <a
                href={flow.data.endpoints.agent_card_url}
                target="_blank"
                rel="noreferrer"
                className="col-span-2 inline-flex items-center gap-1 text-[10px] text-zinc-500 hover:text-accent-300 xl:col-span-4"
              >
                <ExternalLink className="h-3 w-3" /> open agent-card.json
              </a>
            )}
          </div>
        )}
      </header>

      <div className="flex min-h-0 flex-1">
        {tab === "tasks" ? (
          <>
            <div className="min-w-0 flex-1 overflow-y-auto">
              <TaskList flowId={flowId} selected={selectedTask} onSelect={setSelectedTask} />
            </div>
            {selectedTask && (
              <TaskDetail
                flow={flow.data}
                taskId={selectedTask}
                onClose={() => setSelectedTask(null)}
              />
            )}
          </>
        ) : (
          <Playground flow={flow.data} onOpenTask={(id) => {
            setTab("tasks");
            setSelectedTask(id);
          }} />
        )}
      </div>
    </div>
  );
}
