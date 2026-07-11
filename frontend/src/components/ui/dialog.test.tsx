import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { Dialog } from "./dialog";

describe("Dialog", () => {
  it("wires aria-modal and aria-labelledby to the title", () => {
    render(
      <Dialog open onClose={vi.fn()} title="Delete flow">
        <p>body</p>
      </Dialog>,
    );
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    const labelId = dialog.getAttribute("aria-labelledby");
    expect(labelId).toBeTruthy();
    expect(document.getElementById(labelId!)).toHaveTextContent("Delete flow");
  });

  it("moves initial focus to the first focusable element", () => {
    render(
      <Dialog open onClose={vi.fn()} title="Trap">
        <button>one</button>
      </Dialog>,
    );
    expect(screen.getByRole("button", { name: "Close dialog" })).toHaveFocus();
  });

  it("traps Tab and Shift+Tab inside the panel", async () => {
    const user = userEvent.setup();
    render(
      <Dialog open onClose={vi.fn()} title="Trap">
        <button>one</button>
        <button>two</button>
      </Dialog>,
    );
    const close = screen.getByRole("button", { name: "Close dialog" });
    const one = screen.getByRole("button", { name: "one" });
    const two = screen.getByRole("button", { name: "two" });

    expect(close).toHaveFocus();
    await user.tab();
    expect(one).toHaveFocus();
    await user.tab();
    expect(two).toHaveFocus();
    await user.tab(); // wraps forward to the first focusable
    expect(close).toHaveFocus();
    await user.tab({ shift: true }); // wraps backward to the last focusable
    expect(two).toHaveFocus();
  });

  it("closes on Escape and on backdrop click", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    render(
      <Dialog open onClose={onClose} title="Trap">
        <button>one</button>
      </Dialog>,
    );
    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByTestId("dialog-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("restores focus to the opener when closed", async () => {
    const user = userEvent.setup();
    function Harness() {
      const [open, setOpen] = useState(false);
      return (
        <>
          <button onClick={() => setOpen(true)}>open dialog</button>
          <Dialog open={open} onClose={() => setOpen(false)} title="Trap">
            <button>inner</button>
          </Dialog>
        </>
      );
    }
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "open dialog" });
    await user.click(opener);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(opener).not.toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});
