import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  it("renders the primary variant by default with accent bg and canvas text", () => {
    render(<Button>go</Button>);
    const button = screen.getByRole("button", { name: "go" });
    expect(button).toHaveAttribute("type", "button");
    expect(button.className).toContain("bg-accent");
    expect(button.className).toContain("text-canvas");
  });

  it("styles the secondary variant from surface tokens", () => {
    render(<Button variant="secondary">s</Button>);
    const button = screen.getByRole("button", { name: "s" });
    expect(button.className).toContain("bg-surface-2");
    expect(button.className).toContain("border-border");
  });

  it("styles danger, ghost, and outline from tokens", () => {
    render(
      <>
        <Button variant="danger">d</Button>
        <Button variant="ghost">g</Button>
        <Button variant="outline">o</Button>
      </>,
    );
    const danger = screen.getByRole("button", { name: "d" });
    expect(danger.className).toContain("bg-danger/15");
    expect(danger.className).toContain("text-danger");
    expect(screen.getByRole("button", { name: "g" }).className).toContain("hover:bg-surface-2");
    expect(screen.getByRole("button", { name: "o" }).className).toContain("border-border");
  });

  it("has a visible focus ring and 45% disabled opacity on every variant", () => {
    render(<Button disabled>x</Button>);
    const button = screen.getByRole("button", { name: "x" });
    expect(button).toBeDisabled();
    expect(button.className).toContain("focus-visible:outline-2");
    expect(button.className).toContain("focus-visible:outline-accent");
    expect(button.className).toContain("disabled:opacity-45");
  });

  it("applies size classes", () => {
    render(
      <>
        <Button size="sm">small</Button>
        <Button size="md">medium</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "small" }).className).toContain("h-7");
    expect(screen.getByRole("button", { name: "medium" }).className).toContain("h-8.5");
  });
});
