/** New-flow dialog — shared by the Home dashboard and the Flows list. */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Loader2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { api } from "@/api/client";
import { Button } from "@/components/ui/button";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";

import { emptyDefinition } from "./convert";

const NAME_RE = /^[a-z0-9][a-z0-9-]{1,62}$/;

export function NewFlowDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [name, setName] = useState("");
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const valid = NAME_RE.test(name);
  const create = useMutation({
    mutationFn: () => api.flows.create(emptyDefinition(name)),
    onSuccess: async (flow) => {
      await queryClient.invalidateQueries({ queryKey: ["flows"] });
      navigate(`/flows/${flow.name}`);
    },
    onError: (err) => toast.error(err instanceof Error ? err.message : "create failed"),
  });
  return (
    <Dialog open={open} onClose={onClose} title="New flow">
      <Label hint="^[a-z0-9][a-z0-9-]{1,62}$">Name</Label>
      <Input
        autoFocus
        value={name}
        placeholder="support-rag"
        className="font-mono"
        onChange={(e) => setName(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && valid) create.mutate();
        }}
      />
      <p className="mt-1 text-[11px] text-text-3">
        The name is the platform-wide identity of the flow (unique per owner).
      </p>
      <div className="mt-3 flex justify-end gap-2">
        <Button size="sm" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button size="sm" disabled={!valid || create.isPending} onClick={() => create.mutate()}>
          {create.isPending && <Loader2 size={13} className="animate-spin" />} Create
        </Button>
      </div>
    </Dialog>
  );
}
