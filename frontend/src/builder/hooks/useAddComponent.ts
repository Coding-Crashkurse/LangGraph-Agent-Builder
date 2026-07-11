/** Shared "add component to canvas" action (SPEC §11.3) — used by both the
 * drag-drop path (Canvas onDrop) and the keyboard path (palette Enter, which
 * places the node at the visual canvas center). */

import { useReactFlow } from "@xyflow/react";
import { useCallback } from "react";

import { toast } from "@/components/ui/toast";

import { defaultConfig, newNodeId } from "../convert";
import { useBuilder } from "../store";

export function useAddComponent() {
  const { screenToFlowPosition } = useReactFlow();

  return useCallback(
    (componentId: string, screen?: { x: number; y: number }): boolean => {
      const store = useBuilder.getState();
      const descriptor = store.descriptors.get(componentId);
      if (!descriptor) return false;
      const taken = new Set(store.nodes.map((n) => n.id));
      const id = newNodeId(descriptor, taken);
      if (taken.has(id)) {
        toast.error(`node ${id} already exists`);
        return false;
      }
      // keyboard path: canvas center, nudged so repeated adds do not stack
      const nudge = (store.nodes.length % 4) * 24;
      const at = screen ?? {
        x: window.innerWidth / 2 + nudge,
        y: window.innerHeight / 2 + nudge,
      };
      store.addNode({
        id,
        type: "lga",
        deletable: id !== "start" && id !== "end",
        position: screenToFlowPosition(at),
        data: {
          componentId,
          componentVersion: descriptor.version,
          label: descriptor.display_name,
          config: defaultConfig(descriptor),
          notes: "",
        },
      });
      store.select(id);
      return true;
    },
    [screenToFlowPosition],
  );
}
