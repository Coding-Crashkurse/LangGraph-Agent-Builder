/** Playground & Debug drawer (SPEC §11.5/§11.7): streaming chat with markdown
 * and tool-call blocks, per-node timeline, interrupt modals, sessions with
 * delete, debug stepping, cancel during any active run. Run orchestration
 * lives in `playground/useFlowRun.ts`; the A2A tab talks to the published
 * agent through `api/a2a.ts`. */

import { ListTree, Square, X } from "lucide-react";
import { useState } from "react";

import type { FlowInfo } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch, Tabs } from "@/components/ui/controls";
import { cn } from "@/lib/utils";
import { A2AChat } from "./playground/A2AChat";
import { ChatPane } from "./playground/ChatPane";
import { DebugControls } from "./playground/DebugControls";
import { InterruptModal } from "./playground/InterruptModal";
import { JsonTree } from "./playground/JsonTree";
import { SessionPicker } from "./playground/SessionPicker";
import { Timeline } from "./playground/Timeline";
import { useFlowRun } from "./playground/useFlowRun";

const TIMELINE_EVENTS = new Set([
  "node_started",
  "node_finished",
  "node_error",
  "node_status",
  "tool_call",
  "tool_result",
  "interrupt_raised",
]);

export function Playground({ flow, onClose }: { flow: FlowInfo; onClose: () => void }) {
  const [view, setView] = useState<"chat" | "a2a">("chat");
  const [input, setInput] = useState("");
  const [debugMode, setDebugMode] = useState(false);
  const [showTimeline, setShowTimeline] = useState(false);
  const run = useFlowRun(flow);

  const send = () => {
    if (!input.trim() || run.busy) return;
    const text = input.trim();
    setInput("");
    void run.send(text, debugMode);
  };

  const nodeEventCount = run.eventLog.filter((e) => TIMELINE_EVENTS.has(e.event)).length;

  return (
    <div className="relative flex w-[430px] flex-col border-l border-border bg-canvas">
      <header className="flex flex-wrap items-center gap-x-2 gap-y-1 border-b border-border px-3 py-2">
        <h2 className="text-sm font-semibold">Playground</h2>
        <Tabs
          value={view}
          onChange={setView}
          items={[
            { value: "chat", label: "Chat" },
            { value: "a2a", label: "A2A" },
          ]}
        />
        {view === "chat" && (
          <>
            <span className="flex items-center gap-1 text-[11px] text-text-3">
              debug
              <Switch checked={debugMode} onCheckedChange={setDebugMode} label="Debug mode" />
            </span>
            <button
              type="button"
              aria-pressed={showTimeline}
              aria-label="Node execution timeline"
              title="Node execution timeline"
              className={cn(
                "flex h-7 items-center gap-1 rounded-lg border border-border px-1.5",
                "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent",
                showTimeline ? "bg-surface-3 text-text-1" : "text-text-3 hover:text-text-1",
              )}
              onClick={() => setShowTimeline((v) => !v)}
            >
              <ListTree className="h-3.5 w-3.5" strokeWidth={1.75} />
              {nodeEventCount > 0 && (
                <span className="font-mono text-[10.5px] tabular-nums">{nodeEventCount}</span>
              )}
            </button>
            <SessionPicker
              threads={run.threads}
              value={run.sessionId}
              onChange={run.selectSession}
              onDelete={run.deleteSession}
            />
          </>
        )}
        <button
          type="button"
          aria-label="Close playground"
          className="ml-auto rounded p-0.5 text-text-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
          onClick={onClose}
        >
          <X className="h-4 w-4" strokeWidth={1.75} />
        </button>
      </header>

      {view === "a2a" ? (
        <A2AChat slug={flow.slug} />
      ) : (
        <>
          <ChatPane items={run.items} busy={run.busy} />

          {run.threadState && (
            <div className="max-h-56 overflow-y-auto border-t border-border bg-surface-1/70 px-3 py-2">
              <div className="mb-1 flex items-center justify-between">
                <p className="text-[11px] font-semibold uppercase tracking-widest text-text-3">
                  thread state
                </p>
                <button
                  type="button"
                  aria-label="Close thread state"
                  className="rounded p-0.5 text-text-3 hover:text-text-1 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-accent"
                  onClick={run.clearThreadState}
                >
                  <X className="h-3.5 w-3.5" strokeWidth={1.75} />
                </button>
              </div>
              <JsonTree value={run.threadState} />
            </div>
          )}

          {showTimeline && (
            <Timeline events={run.eventLog} onClose={() => setShowTimeline(false)} />
          )}

          {run.pending && (
            <InterruptModal payload={run.pending.payload} onAnswer={run.resume} />
          )}

          {debugMode && (
            <DebugControls
              onStep={() => run.resume(null, "step")}
              onContinue={() => run.resume(null, "continue")}
              onAbort={run.cancel}
              onInspectState={run.inspectState}
            />
          )}

          <footer className="flex gap-2 border-t border-border p-3">
            <Input
              value={input}
              placeholder={run.busy ? "running…" : "Message the flow…"}
              disabled={run.busy}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && send()}
            />
            {run.busy ? (
              <Button
                variant="danger"
                aria-label="Cancel run"
                onClick={run.cancel}
                disabled={!run.runId}
              >
                <Square className="h-3.5 w-3.5" strokeWidth={1.75} />
                Stop
              </Button>
            ) : (
              <Button onClick={send} disabled={!input.trim()}>
                Send
              </Button>
            )}
          </footer>
        </>
      )}
    </div>
  );
}
