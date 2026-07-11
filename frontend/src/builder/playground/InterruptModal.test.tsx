/** InterruptModal renders the normative §5.5 payloads: ApprovalRequest →
 * option buttons, InputRequest with schema → generated form (typed coercion),
 * raw-JSON advanced fallback, plain text without a schema. */

import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InterruptModal } from "./InterruptModal";

describe("InterruptModal", () => {
  it("renders approval options and answers with decision + comment", () => {
    const onAnswer = vi.fn();
    render(
      <InterruptModal
        payload={{ kind: "approval", prompt: "Deploy?", options: ["approve", "reject"] }}
        onAnswer={onAnswer}
      />,
    );
    expect(screen.getByText("Deploy?")).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("optional comment"), {
      target: { value: "lgtm" },
    });
    fireEvent.click(screen.getByRole("button", { name: "approve" }));
    expect(onAnswer).toHaveBeenCalledWith({ decision: "approve", comment: "lgtm" });
  });

  it("renders a form from the InputRequest schema and coerces field types", () => {
    const onAnswer = vi.fn();
    render(
      <InterruptModal
        payload={{
          kind: "free_text",
          prompt: "Fill in",
          schema: {
            type: "object",
            properties: {
              name: { type: "string" },
              count: { type: "integer" },
              ok: { type: "boolean" },
              mode: { enum: ["fast", "slow"] },
            },
            required: ["name"],
          },
        }}
        onAnswer={onAnswer}
      />,
    );
    const answer = screen.getByRole("button", { name: "Answer" });
    expect(answer).toBeDisabled(); // required "name" still empty

    fireEvent.change(screen.getByLabelText(/^name/), { target: { value: "alice" } });
    fireEvent.change(screen.getByLabelText("count"), { target: { value: "3" } });
    fireEvent.click(screen.getByLabelText("ok")); // boolean Switch
    fireEvent.change(screen.getByLabelText("mode"), { target: { value: "fast" } });
    fireEvent.click(answer);
    expect(onAnswer).toHaveBeenCalledWith({ name: "alice", count: 3, ok: true, mode: "fast" });
  });

  it("keeps a raw-JSON advanced fallback behind a toggle", () => {
    const onAnswer = vi.fn();
    render(
      <InterruptModal
        payload={{ schema: { type: "object", properties: { name: { type: "string" } } } }}
        onAnswer={onAnswer}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /raw JSON/ }));
    const textarea = screen.getByLabelText("Raw JSON answer");

    fireEvent.change(textarea, { target: { value: "{not json" } });
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    expect(onAnswer).not.toHaveBeenCalled(); // invalid JSON → toast, no answer

    fireEvent.change(textarea, { target: { value: '{"name": "bob"}' } });
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    expect(onAnswer).toHaveBeenCalledWith({ name: "bob" });
  });

  it("answers { text } when the InputRequest has no schema", () => {
    const onAnswer = vi.fn();
    render(<InterruptModal payload={{ prompt: "your name?" }} onAnswer={onAnswer} />);
    fireEvent.change(screen.getByPlaceholderText("your answer"), {
      target: { value: "carol" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Answer" }));
    expect(onAnswer).toHaveBeenCalledWith({ text: "carol" });
  });
});
