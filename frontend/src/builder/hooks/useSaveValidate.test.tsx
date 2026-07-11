/** useSaveValidate: serialized draft saves that never wipe undo history, and
 * validation that chains after persistence (SPEC §11.6/§18.1). */

import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

vi.mock("@/api/client", () => {
  class ApiError extends Error {
    constructor(
      public status: number,
      message: string,
      public diagnostics?: unknown[],
    ) {
      super(message);
    }
  }
  return {
    ApiError,
    api: {
      flows: {
        update: vi.fn(),
        validate: vi.fn(),
      },
    },
  };
});
vi.mock("./useServerConfig", () => ({
  useServerConfig: () => ({ auto_saving: false, auto_saving_interval_ms: 1000 }),
}));

import { api, ApiError } from "@/api/client";
import type { FlowInfo } from "@/api/types";

import { emptyFlowSpec, type CanvasNode } from "../convert";
import { useBuilder } from "../store";
import { useSaveValidate } from "./useSaveValidate";

const updateMock = api.flows.update as Mock;
const validateMock = api.flows.validate as Mock;

const flow: FlowInfo = {
  id: "f1",
  slug: "test",
  name: "Test",
  description: "",
  spec: emptyFlowSpec("Test", "test"),
  serve_version: "draft",
  published_version: null,
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function fakeNode(id: string): CanvasNode {
  return {
    id,
    type: "lga",
    position: { x: 0, y: 0 },
    data: {
      componentId: "lga.testing.echo",
      componentVersion: "1.0.0",
      label: id,
      config: {},
      notes: "",
    },
  };
}

const initialState = useBuilder.getState();

beforeEach(() => {
  vi.clearAllMocks();
  useBuilder.setState(initialState, true);
  updateMock.mockResolvedValue(flow);
  validateMock.mockResolvedValue({ diagnostics: [], compile_report: null });
});

/** Load the flow and make one edit → dirty graph with one undo step. */
function seedDirtyFlow() {
  act(() => {
    useBuilder.getState().loadFlow(flow);
    useBuilder.getState().addNode(fakeNode("echo_1"));
  });
}

/** Let queued microtasks run (saveDraft executes on the next tick). */
function flushTasks() {
  return act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("useSaveValidate", () => {
  it("manual save persists the draft WITHOUT wiping the undo history", async () => {
    const { result } = renderHook(() => useSaveValidate());
    seedDirtyFlow();
    expect(useBuilder.getState().dirty).toBe(true);
    expect(useBuilder.getState().past).toHaveLength(1);

    await act(() => result.current.save());

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(updateMock).toHaveBeenCalledWith("f1", expect.objectContaining({ nodes: expect.anything() }));
    const state = useBuilder.getState();
    expect(state.dirty).toBe(false);
    // the old save() called loadFlow(updated), which reset past/future
    expect(state.past).toHaveLength(1);
    expect(state.nodes.some((n) => n.id === "echo_1")).toBe(true);
  });

  it("serializes overlapping saves — never two PATCHes in flight", async () => {
    const { result } = renderHook(() => useSaveValidate());
    seedDirtyFlow();

    let resolveFirst!: (value: FlowInfo) => void;
    updateMock
      .mockImplementationOnce(() => new Promise<FlowInfo>((r) => (resolveFirst = r)))
      .mockResolvedValue(flow);

    let p1: Promise<void>;
    act(() => {
      p1 = result.current.saveDraft();
    });
    await flushTasks(); // first PATCH is now in flight
    expect(updateMock).toHaveBeenCalledTimes(1);

    let p2: Promise<void>;
    act(() => {
      // edit while the first PATCH is in flight → second save must pick it up
      useBuilder.getState().addNode(fakeNode("echo_2"));
      p2 = result.current.saveDraft();
    });
    await flushTasks();
    // second PATCH must not start until the first resolves
    expect(updateMock).toHaveBeenCalledTimes(1);

    resolveFirst(flow);
    await act(async () => {
      await p1!;
      await p2!;
    });
    expect(updateMock).toHaveBeenCalledTimes(2);
    expect(useBuilder.getState().dirty).toBe(false);
  });

  it("keeps the graph dirty when edits land while a PATCH is in flight", async () => {
    const { result } = renderHook(() => useSaveValidate());
    seedDirtyFlow();

    let resolveFirst!: (value: FlowInfo) => void;
    updateMock.mockImplementationOnce(() => new Promise<FlowInfo>((r) => (resolveFirst = r)));

    let p1: Promise<void>;
    act(() => {
      p1 = result.current.saveDraft();
    });
    await flushTasks(); // PATCH in flight, pre-edit graph captured
    act(() => {
      useBuilder.getState().addNode(fakeNode("echo_2"));
    });
    resolveFirst(flow);
    await act(async () => {
      await p1!;
    });
    // the in-flight save did NOT cover echo_2 → must stay dirty
    expect(useBuilder.getState().dirty).toBe(true);
  });

  it("validate persists a dirty draft first, then applies diagnostics", async () => {
    const { result } = renderHook(() => useSaveValidate());
    seedDirtyFlow();
    const diagnostic = {
      code: "W201",
      severity: "warning" as const,
      message: "ANY-typed edge",
    };
    validateMock.mockResolvedValue({ diagnostics: [diagnostic], compile_report: null });

    await act(() => result.current.validate(false, true));

    expect(updateMock).toHaveBeenCalledTimes(1);
    expect(validateMock).toHaveBeenCalledWith("f1", false);
    // save must complete before validation runs
    expect(updateMock.mock.invocationCallOrder[0]).toBeLessThan(
      validateMock.mock.invocationCallOrder[0],
    );
    expect(useBuilder.getState().diagnostics).toEqual([diagnostic]);
    expect(result.current.needsValidation).toBe(false);
  });

  it("passes the deep flag through to the API (§11.6 deep validate)", async () => {
    const { result } = renderHook(() => useSaveValidate());
    seedDirtyFlow();

    await act(() => result.current.validate(true, true));

    expect(validateMock).toHaveBeenCalledWith("f1", true);
  });

  it("routes structured 422 diagnostics from a failed save into the panel", async () => {
    const { result } = renderHook(() => useSaveValidate());
    seedDirtyFlow();
    const diagnostic = {
      code: "E010",
      severity: "error" as const,
      node_id: "echo_1",
      message: "Required field empty",
    };
    updateMock.mockRejectedValueOnce(new ApiError(422, "invalid spec", [diagnostic]));

    await act(() => result.current.save());

    expect(useBuilder.getState().diagnostics).toEqual([diagnostic]);
    expect(useBuilder.getState().dirty).toBe(true); // still unsaved
  });

  it("does not PATCH when the graph is clean", async () => {
    const { result } = renderHook(() => useSaveValidate());
    act(() => {
      useBuilder.getState().loadFlow(flow); // clean load, no edits
    });

    await act(() => result.current.save());

    expect(updateMock).not.toHaveBeenCalled();
  });
});
