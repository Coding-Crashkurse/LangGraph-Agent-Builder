/**
 * Playground = ephemeral deploy + chat (SPEC §2.5). The Playground button
 * deploys the current draft ephemerally; this panel then talks A2A to
 * `…/a2a/_draft/{name}` through the gateway. One execution path — the
 * builder runs nothing in-process.
 */

import { RotateCcw, Send, X } from "lucide-react";
import { useRef, useState } from "react";

import { streamMessage, taskText, userMessage, type A2aTask } from "@/api/a2a";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

interface ChatItem {
  role: "user" | "agent";
  text: string;
}

export function Playground({
  endpoint,
  onClose,
  onRedeploy,
}: {
  endpoint: string;
  onClose: () => void;
  onRedeploy: () => void;
}) {
  const [items, setItems] = useState<ChatItem[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const task = useRef<A2aTask | null>(null);

  const send = async () => {
    const text = draft.trim();
    if (!text || busy) return;
    setDraft("");
    setError(null);
    setBusy(true);
    setItems((prev) => [...prev, { role: "user", text }, { role: "agent", text: "" }]);
    const append = (delta: string) =>
      setItems((prev) => {
        const next = [...prev];
        next[next.length - 1] = {
          role: "agent",
          text: next[next.length - 1].text + delta,
        };
        return next;
      });
    try {
      const message = userMessage(text, {
        taskId: undefined,
        contextId: task.current?.contextId,
      });
      const finalTask = await streamMessage(endpoint, message, { onDelta: append });
      if (finalTask) {
        task.current = finalTask;
        setItems((prev) => {
          const next = [...prev];
          if (!next[next.length - 1].text) {
            next[next.length - 1] = { role: "agent", text: taskText(finalTask) };
          }
          return next;
        });
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <aside className="flex w-96 shrink-0 flex-col border-l border-border bg-surface-1">
      <header className="flex items-center gap-2 border-b border-border px-3 py-2">
        <span className="text-xs font-semibold text-text-1">Playground</span>
        <span className="truncate font-mono text-[10px] text-text-3" title={endpoint}>
          {endpoint.replace(/^https?:\/\//, "")}
        </span>
        <span className="ml-auto flex items-center gap-1">
          <Button
            size="icon"
            variant="ghost"
            onClick={onRedeploy}
            title="Redeploy current draft"
            aria-label="Redeploy current draft"
          >
            <RotateCcw size={13} />
          </Button>
          <Button size="icon" variant="ghost" onClick={onClose} aria-label="Close playground">
            <X size={13} />
          </Button>
        </span>
      </header>
      <div className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3">
        {items.length === 0 && (
          <p className="text-xs leading-relaxed text-text-3">
            Ephemeral draft deploy is live (expires automatically). Messages go through the
            gateway to the runtime — nothing runs inside the builder.
          </p>
        )}
        {items.map((item, index) => (
          <div
            key={index}
            className={cn(
              "max-w-[85%] whitespace-pre-wrap rounded-lg px-2.5 py-1.5 text-xs leading-relaxed",
              item.role === "user"
                ? "ml-auto bg-accent/15 text-text-1"
                : "bg-surface-2 text-text-1",
            )}
          >
            {item.text || (busy && index === items.length - 1 ? "…" : "")}
          </div>
        ))}
        {error && <p className="text-[11px] text-danger">{error}</p>}
      </div>
      <form
        className="flex items-center gap-1.5 border-t border-border p-2"
        onSubmit={(event) => {
          event.preventDefault();
          void send();
        }}
      >
        <Input
          value={draft}
          placeholder="Message the draft agent…"
          onChange={(e) => setDraft(e.target.value)}
          disabled={busy}
        />
        <Button size="icon" type="submit" disabled={busy || !draft.trim()} aria-label="Send">
          <Send size={13} />
        </Button>
      </form>
    </aside>
  );
}
