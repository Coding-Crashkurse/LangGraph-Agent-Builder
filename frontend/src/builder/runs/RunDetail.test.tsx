/** RunDetail (§7.3): buildNodeRows groups a looping node into one row per
 * iteration, and RunDetailView renders one expandable row per execution whose
 * inspector opens on click, with a prominent banner for parked/interrupted runs. */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NodeRunInfo } from "@/api/types";

import { buildNodeRows, RunDetailView } from "./RunDetail";

function node(partial: Partial<NodeRunInfo> & { node_id: string }): NodeRunInfo {
  return {
    iteration: 0,
    status: "ok",
    started_at: "2026-07-11T10:00:00Z",
    finished_at: "2026-07-11T10:00:01Z",
    duration_ms: 10,
    input_snapshot: null,
    output_snapshot: null,
    tokens: null,
    cost: null,
    error_code: null,
    ...partial,
  };
}

const NODES: NodeRunInfo[] = [
  node({ node_id: "start", input_snapshot: { q: "hi" }, output_snapshot: { greeting: "hello" } }),
  node({ node_id: "loop", iteration: 0, output_snapshot: "iter one" }),
  node({ node_id: "loop", iteration: 1, status: "error", error_code: "RT201" }),
  node({
    node_id: "answer",
    status: "interrupted",
    duration_ms: null,
    output_snapshot: "hello world",
    tokens: 42,
    cost: 0.001,
  }),
];

describe("buildNodeRows", () => {
  it("keeps one row per execution and flags repeated node_ids as iterations", () => {
    const rows = buildNodeRows(NODES);
    expect(rows).toHaveLength(4);
    const loops = rows.filter((r) => r.node_id === "loop");
    expect(loops).toHaveLength(2);
    expect(loops.every((r) => r.repeated)).toBe(true);
    expect(loops.map((r) => r.iteration)).toEqual([0, 1]);
    expect(rows.find((r) => r.node_id === "start")?.repeated).toBe(false);
  });
});

describe("RunDetailView", () => {
  it("renders one row per node execution and marks loop iterations", () => {
    render(<RunDetailView nodes={NODES} />);
    expect(screen.getAllByText("loop")).toHaveLength(2);
    expect(screen.getByText("start")).toBeInTheDocument();
    expect(screen.getByText("answer")).toBeInTheDocument();
    expect(screen.getByText(/iteration 0/)).toBeInTheDocument();
    expect(screen.getByText(/iteration 1/)).toBeInTheDocument();
  });

  it("opens the input/output inspector when a row is expanded", () => {
    render(<RunDetailView nodes={NODES} />);
    expect(screen.queryByText("hello world")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /answer/i }));
    expect(screen.getByText("hello world")).toBeInTheDocument();
  });

  it("surfaces a prominent waiting-for-input banner when a node is interrupted", () => {
    render(<RunDetailView nodes={NODES} />);
    expect(screen.getByText(/waiting for input/i)).toBeInTheDocument();
  });

  it("raises the banner from an input_required run status even without an interrupted node", () => {
    render(<RunDetailView nodes={[node({ node_id: "n1" })]} runStatus="input_required" />);
    expect(screen.getByText(/waiting for input/i)).toBeInTheDocument();
  });

  it("shows an empty state when the run recorded no node executions", () => {
    render(<RunDetailView nodes={[]} />);
    expect(screen.getByText(/no node executions recorded/i)).toBeInTheDocument();
  });
});
