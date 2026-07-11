import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Toaster, toast, useToasts } from "./toast";

describe("Toaster", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    act(() => {
      for (const t of useToasts.getState().toasts) useToasts.getState().dismiss(t.id);
    });
    vi.useRealTimers();
  });

  it("announces via a polite live region", () => {
    render(<Toaster />);
    const region = screen.getByRole("status");
    expect(region).toHaveAttribute("aria-live", "polite");
  });

  it("gives error toasts role=alert and an 8s timeout", () => {
    render(<Toaster />);
    act(() => toast.error("boom"));
    expect(screen.getByRole("alert")).toHaveTextContent("boom");
    act(() => vi.advanceTimersByTime(5000)); // past the 4.2s info timeout
    expect(screen.getByRole("alert")).toBeInTheDocument();
    act(() => vi.advanceTimersByTime(3100));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("pauses the dismiss timer on hover and resumes on leave", () => {
    render(<Toaster />);
    act(() => toast.error("hold"));
    const item = screen.getByRole("alert");
    fireEvent.mouseEnter(item);
    act(() => vi.advanceTimersByTime(30000));
    expect(screen.getByRole("alert")).toBeInTheDocument();
    fireEvent.mouseLeave(item);
    act(() => vi.advanceTimersByTime(8100));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
