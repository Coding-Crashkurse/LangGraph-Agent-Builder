/** Read-only mini render of the flow; nodes highlight from node.start /
 * node.end events, the interrupted node pulses amber. */

import {
  Background,
  BackgroundVariant,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import { useMemo } from "react";

import type { Flow, TaskEvent } from "@/api/types";
import { specToCanvas } from "@/builder/convert";
import { edgeTypes, nodeTypes } from "@/builder/nodes";
import { cn } from "@/lib/utils";

type NodePhase = "idle" | "active" | "done" | "interrupted";

export function nodePhases(events: TaskEvent[]): Record<string, NodePhase> {
  const phases: Record<string, NodePhase> = {};
  for (const event of events) {
    if (!event.node) continue;
    if (event.type === "node.start") phases[event.node] = "active";
    else if (event.type === "node.end" && phases[event.node] !== "interrupted") {
      phases[event.node] = "done";
    } else if (event.type === "interrupt") phases[event.node] = "interrupted";
  }
  // a resume clears the interrupt: if the node started again afterwards it wins
  return phases;
}

export function GraphReplay({ flow, events }: { flow: Flow; events: TaskEvent[] }) {
  const phases = useMemo(() => nodePhases(events), [events]);

  const { nodes, edges } = useMemo(() => {
    const canvas = specToCanvas(flow, {});
    return {
      edges: canvas.edges,
      nodes: canvas.nodes.map((node) => ({
        ...node,
        selectable: false,
        draggable: false,
        className: cn(
          phases[node.id] === "active" && "gf-node-active rounded-lg",
          phases[node.id] === "interrupted" && "gf-node-interrupted rounded-lg",
          phases[node.id] === "done" && "opacity-90",
          !phases[node.id] && node.type === "component" && "opacity-55",
        ),
      })),
    };
  }, [flow, phases]);

  return (
    <ReactFlowProvider>
      <div className="h-full w-full">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={nodeTypes}
          edgeTypes={edgeTypes}
          fitView
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable={false}
          zoomOnScroll
          panOnDrag
          proOptions={{ hideAttribution: true }}
        >
          <Background variant={BackgroundVariant.Dots} gap={22} size={1} color="#1e1e2a" />
        </ReactFlow>
      </div>
    </ReactFlowProvider>
  );
}
