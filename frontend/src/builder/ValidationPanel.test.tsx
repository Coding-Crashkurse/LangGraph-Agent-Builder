import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { SourcedIssue } from "@/api/types";

import { ValidationPanel } from "./ValidationPanel";
import { catalogFixture, definitionFixture } from "./fixtures";
import { useBuilder } from "./store";

const issues: SourcedIssue[] = [
  {
    code: "E010",
    severity: "error",
    path: "nodes/call_1/config/prompt",
    message: "prompt must not be empty",
    source: "local",
  },
  {
    code: "E020",
    severity: "error",
    path: "nodes/call_1/config/resource",
    message: "unknown resource",
    source: "runtime",
  },
  {
    code: "W003",
    severity: "warning",
    path: "nodes/call_1/config/stream",
    message: "stream ignored for MCP",
    source: "local",
  },
];

function setup(withIssues: SourcedIssue[]) {
  useBuilder.getState().load(definitionFixture(), catalogFixture);
  useBuilder.getState().setIssues(withIssues);
}

describe("ValidationPanel", () => {
  it("renders local and runtime issues identically with a source badge", () => {
    setup(issues);
    render(<ValidationPanel onFocusIssue={() => {}} />);
    expect(screen.getByText("E010")).toBeInTheDocument();
    expect(screen.getByText("E020")).toBeInTheDocument();
    expect(screen.getByText("runtime")).toBeInTheDocument();
    expect(screen.getAllByText("local")).toHaveLength(2);
    expect(screen.getByText("2 errors")).toBeInTheDocument();
    expect(screen.getByText("1 warnings")).toBeInTheDocument();
  });

  it("click focuses the offending node via the issue path", async () => {
    setup(issues);
    const onFocus = vi.fn();
    render(<ValidationPanel onFocusIssue={onFocus} />);
    await userEvent.click(screen.getByText("E020"));
    expect(onFocus).toHaveBeenCalledWith("call_1", "nodes/call_1/config/resource");
  });

  it("shows not-validated-yet before the first run and clean state after", () => {
    useBuilder.getState().load(definitionFixture(), catalogFixture);
    const { rerender } = render(<ValidationPanel onFocusIssue={() => {}} />);
    expect(screen.getByText(/Not validated yet/)).toBeInTheDocument();
    useBuilder.getState().setValidation({ valid: true, runtime_checked: true, issues: [] });
    rerender(<ValidationPanel onFocusIssue={() => {}} />);
    expect(screen.getByText(/No issues found/)).toBeInTheDocument();
    expect(screen.getByText(/local \+ runtime/)).toBeInTheDocument();
  });

  it("flags local-only results when the runtime was not reachable", () => {
    useBuilder.getState().load(definitionFixture(), catalogFixture);
    useBuilder.getState().setValidation({ valid: true, runtime_checked: false, issues: [] });
    render(<ValidationPanel onFocusIssue={() => {}} />);
    expect(screen.getByText(/runtime not checked/)).toBeInTheDocument();
  });
});
