/** Input-required panel: approval buttons or free-text, per interrupt kind. */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Check, Send, X } from "lucide-react";
import { useState } from "react";

import { api } from "@/api/client";
import type { TaskEvent } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Input, Textarea } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";

export function InputPanel({ taskId, events }: { taskId: string; events: TaskEvent[] }) {
  const queryClient = useQueryClient();
  const [comment, setComment] = useState("");
  const [text, setText] = useState("");

  const interrupt = [...events].reverse().find((event) => event.type === "interrupt");
  const kind = String(interrupt?.data.kind ?? "input");
  const prompt = String(interrupt?.data.prompt ?? "Input required");
  const preview = interrupt?.data.preview ? String(interrupt.data.preview) : "";

  const submit = useMutation({
    mutationFn: (body: { text?: string; data?: Record<string, unknown> }) =>
      api.debug.sendInput(taskId, body),
    onSuccess: () => {
      toast.success("Input submitted — task resumed");
      queryClient.invalidateQueries({ queryKey: ["task", taskId] });
      queryClient.invalidateQueries({ queryKey: ["tasks"] });
      setComment("");
      setText("");
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <div className="border-t border-amber-900/40 bg-amber-950/20 px-4 py-3">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-widest text-amber-400">
        input required
      </div>
      <div className="text-xs font-medium text-amber-100">{prompt}</div>
      {preview ? (
        <blockquote className="mt-2 max-h-28 overflow-y-auto rounded-md border border-amber-900/40 bg-surface-950/60 px-3 py-2 text-[11px] leading-relaxed text-zinc-400">
          {preview}
        </blockquote>
      ) : null}

      {kind === "approval" ? (
        <div className="mt-3 space-y-2">
          <Input
            value={comment}
            placeholder="optional comment (returned to the flow on reject)"
            onChange={(e) => setComment(e.target.value)}
          />
          <div className="flex gap-2">
            <Button
              size="sm"
              className="bg-emerald-700 hover:bg-emerald-600"
              disabled={submit.isPending}
              onClick={() => submit.mutate({ data: { approved: true, comment } })}
            >
              <Check className="h-3.5 w-3.5" /> Approve
            </Button>
            <Button
              size="sm"
              variant="destructive"
              disabled={submit.isPending}
              onClick={() => submit.mutate({ data: { approved: false, comment } })}
            >
              <X className="h-3.5 w-3.5" /> Reject
            </Button>
          </div>
        </div>
      ) : (
        <div className="mt-3 flex items-end gap-2">
          <Textarea
            value={text}
            rows={2}
            placeholder="your reply…"
            onChange={(e) => setText(e.target.value)}
          />
          <Button
            size="sm"
            disabled={!text.trim() || submit.isPending}
            onClick={() => submit.mutate({ text })}
          >
            <Send className="h-3.5 w-3.5" /> Send
          </Button>
        </div>
      )}
    </div>
  );
}
