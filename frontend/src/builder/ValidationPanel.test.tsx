/** ValidationPanel: severity grouping with counts, honest empty copy, and the
 * Update-all affordance for version drift (SPEC §11.6/§4.11). */

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ComponentDescriptor, Diagnostic } from "@/api/types";

import type { CanvasNode } from "./convert";
import { useBuilder } from "./store";
import { ValidationPanel } from "./ValidationPanel";

const initialState = useBuilder.getState();

beforeEach(() => {
  useBuilder.setState(initialState, true);
  useBuilder.setState({ diagnostics: [], nodes: [], descriptors: new Map() });
});

function diag(partial: Partial<Diagnostic> & { code: string }): Diagnostic {
  return { severity: "error", message: "boom", ...partial };
}

describe("ValidationPanel", () => {
  it("groups diagnostics by severity with counts", () => {
    useBuilder.setState({
      diagnostics: [
        diag({ code: "E020", severity: "error", node_id: "llm_1" }),
        diag({ code: "E031", severity: "error" }),
        diag({ code: "W201", severity: "warning", message: "ANY-typed edge" }),
      ],
    });
    render(<ValidationPanel onFocusNode={() => {}} needsValidation={false} />);

    expect(screen.getByText("2 errors")).toBeInTheDocument();
    expect(screen.getByText("1 warning")).toBeInTheDocument();
    expect(screen.getByText("Errors")).toBeInTheDocument();
    expect(screen.getByText("Warnings")).toBeInTheDocument();
    expect(screen.getByText("E020")).toBeInTheDocument();
    expect(screen.getByText("W201")).toBeInTheDocument();
  });

  it("clicking a diagnostic with a node focuses that node", () => {
    const onFocusNode = vi.fn();
    useBuilder.setState({
      diagnostics: [diag({ code: "E020", node_id: "llm_1" })],
    });
    render(<ValidationPanel onFocusNode={onFocusNode} needsValidation={false} />);

    fireEvent.click(screen.getByRole("button", { name: /E020/ }));
    expect(onFocusNode).toHaveBeenCalledWith("llm_1");
  });

  it("shows honest empty copy: 'validate to refresh' while unvalidated", () => {
    render(<ValidationPanel onFocusNode={() => {}} needsValidation={true} />);
    expect(screen.getByText(/validate to refresh/i)).toBeInTheDocument();
    expect(screen.queryByText(/No issues/)).not.toBeInTheDocument();
  });

  it("shows 'No issues' once the current graph validated clean", () => {
    render(<ValidationPanel onFocusNode={() => {}} needsValidation={false} />);
    expect(screen.getByText(/No issues/)).toBeInTheDocument();
    expect(screen.queryByText(/validate to refresh/i)).not.toBeInTheDocument();
  });

  it("surfaces a (disabled) Update-all button when pinned versions are stale", () => {
    const descriptor = {
      component_id: "lga.llm.model",
      version: "1.1.0",
      legacy: false,
    } as unknown as ComponentDescriptor;
    const node: CanvasNode = {
      id: "model_1",
      type: "lga",
      position: { x: 0, y: 0 },
      data: {
        componentId: "lga.llm.model",
        componentVersion: "1.0.0",
        label: "Model",
        config: {},
        notes: "",
      },
    };
    useBuilder.setState({
      nodes: [node],
      descriptors: new Map([["lga.llm.model", descriptor]]),
    });
    render(<ValidationPanel onFocusNode={() => {}} needsValidation={false} />);

    const button = screen.getByRole("button", { name: /Update all/ });
    expect(button).toHaveTextContent("Update all (1)");
    expect(button).toBeDisabled();
  });

  it("hides Update-all when every node matches the installed version", () => {
    const descriptor = {
      component_id: "lga.llm.model",
      version: "1.0.0",
      legacy: false,
    } as unknown as ComponentDescriptor;
    const node: CanvasNode = {
      id: "model_1",
      type: "lga",
      position: { x: 0, y: 0 },
      data: {
        componentId: "lga.llm.model",
        componentVersion: "1.0.0",
        label: "Model",
        config: {},
        notes: "",
      },
    };
    useBuilder.setState({
      nodes: [node],
      descriptors: new Map([["lga.llm.model", descriptor]]),
    });
    render(<ValidationPanel onFocusNode={() => {}} needsValidation={false} />);

    expect(screen.queryByRole("button", { name: /Update all/ })).not.toBeInTheDocument();
  });
});
