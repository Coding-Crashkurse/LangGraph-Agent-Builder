import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { JsonSchema } from "@/api/types";
import { defaultsFromSchema } from "./schema";
import { SchemaForm } from "./SchemaForm";

const schema: JsonSchema = {
  type: "object",
  properties: {
    model: { type: "string", default: "openai:gpt-4o-mini", description: "model string" },
    system_prompt: { type: "string", default: "hi" },
    use_documents: { type: "boolean", default: false },
    top_k: { type: "integer", default: 4, minimum: 1 },
    transport: { type: "string", enum: ["streamable_http", "stdio"], default: "streamable_http" },
    labels: { type: "array", items: { type: "string" }, default: ["yes", "no"] },
  },
  required: ["model"],
};

describe("SchemaForm", () => {
  it("renders one widget per schema property", () => {
    render(
      <SchemaForm schema={schema} value={defaultsFromSchema(schema)} onChange={() => {}} />,
    );
    expect(screen.getByText("Model")).toBeInTheDocument();
    expect(screen.getByDisplayValue("openai:gpt-4o-mini")).toBeInTheDocument();
    expect(screen.getByRole("switch")).toBeInTheDocument(); // boolean
    expect(screen.getByRole("combobox")).toBeInTheDocument(); // enum select
    expect(screen.getByDisplayValue("4")).toBeInTheDocument(); // integer
    expect(screen.getByText("yes")).toBeInTheDocument(); // tag list
  });

  it("emits partial config updates", () => {
    const onChange = vi.fn();
    render(
      <SchemaForm schema={schema} value={defaultsFromSchema(schema)} onChange={onChange} />,
    );
    fireEvent.change(screen.getByDisplayValue("openai:gpt-4o-mini"), {
      target: { value: "openai:gpt-4.1" },
    });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ model: "openai:gpt-4.1" }));

    fireEvent.click(screen.getByRole("switch"));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ use_documents: true }));
  });

  it("resolves $ref enums from $defs (pydantic Literal style)", () => {
    const refSchema: JsonSchema = {
      type: "object",
      $defs: { Mode: { enum: ["a", "b"], type: "string" } },
      properties: { mode: { $ref: "#/$defs/Mode", default: "a" } },
    };
    render(<SchemaForm schema={refSchema} value={{ mode: "a" }} onChange={() => {}} />);
    const select = screen.getByRole("combobox");
    expect(select).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "b" })).toBeInTheDocument();
  });
});

describe("defaultsFromSchema", () => {
  it("uses schema defaults and zero-values", () => {
    expect(defaultsFromSchema(schema)).toEqual({
      model: "openai:gpt-4o-mini",
      system_prompt: "hi",
      use_documents: false,
      top_k: 4,
      transport: "streamable_http",
      labels: ["yes", "no"],
    });
  });
});
