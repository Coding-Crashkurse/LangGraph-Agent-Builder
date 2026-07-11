/** buildTimelineRows folds the raw event stream into per-node rows with
 * status, duration, outputs and paired tool calls (§11.6). */

import { describe, expect, it } from "vitest";

import type { RunEvent } from "@/api/types";
import { buildTimelineRows } from "./Timeline";

let seq = 0;
const ev = (event: string, data: Record<string, unknown>): RunEvent => ({
  event,
  run_id: "r1",
  thread_id: "t1",
  seq: seq++,
  ts: "",
  data,
});

describe("buildTimelineRows", () => {
  it("pairs started/finished into one ok row with duration + outputs", () => {
    const rows = buildTimelineRows([
      ev("node_started", { node_id: "agent" }),
      ev("node_finished", {
        node_id: "agent",
        duration_ms: 42,
        outputs_preview: { message: "hi" },
      }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({
      nodeId: "agent",
      status: "ok",
      durationMs: 42,
      outputs: { message: "hi" },
    });
  });

  it("attaches tool_call/tool_result pairs to the running node's row", () => {
    const rows = buildTimelineRows([
      ev("node_started", { node_id: "agent" }),
      ev("tool_call", { node_id: "agent", tool_name: "search", args_preview: { q: "x" } }),
      ev("tool_result", { node_id: "agent", result_preview: "found", duration_ms: 7 }),
      ev("node_finished", { node_id: "agent", duration_ms: 99 }),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0].tools).toEqual([
      { role: "tool", name: "search", args: { q: "x" }, done: true, result: "found", durationMs: 7 },
    ]);
  });

  it("marks node_error and interrupt_raised rows", () => {
    const rows = buildTimelineRows([
      ev("node_started", { node_id: "a" }),
      ev("node_error", { node_id: "a", code: "RT201", message: "boom" }),
      ev("node_started", { node_id: "approve" }),
      ev("interrupt_raised", { node_id: "approve" }),
    ]);
    expect(rows.map((r) => r.status)).toEqual(["error", "interrupted"]);
    expect(rows[0].error).toBe("RT201: boom");
  });

  it("opens a fresh row when a node re-executes (loops)", () => {
    const rows = buildTimelineRows([
      ev("node_started", { node_id: "loop" }),
      ev("node_finished", { node_id: "loop", duration_ms: 1 }),
      ev("node_started", { node_id: "loop" }),
      ev("node_finished", { node_id: "loop", duration_ms: 2 }),
    ]);
    expect(rows.map((r) => r.durationMs)).toEqual([1, 2]);
  });
});
