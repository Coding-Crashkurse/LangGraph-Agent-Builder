import { describe, expect, it } from "vitest";

import type { ComponentDescriptor } from "@/api/types";

import { extractPromptVars, indexPorts } from "./guards";

describe("PromptInput {vars} → live input ports (SPEC §4.2)", () => {
  it("extracts vars, ignores {{escaped}} and invalid names", () => {
    expect(extractPromptVars("test {dsada} sdasda {q_1} {dsada}")).toEqual(["dsada", "q_1"]);
    expect(extractPromptVars("json {{literal}} and {1bad}")).toEqual([]);
    expect(extractPromptVars("")).toEqual([]);
  });

  it("indexPorts adds a TEXT port per template var from the live config", () => {
    const descriptor = {
      component_id: "lga.data.prompt_template",
      dynamic_outputs_from: null,
      fields: [{ name: "template", type: "PromptInput", default: "" }],
      outputs: [],
      input_ports: {},
    } as unknown as ComponentDescriptor;
    const ports = indexPorts(descriptor, { template: "Hi {context} — {question}?" });
    expect([...ports.inputs.keys()]).toEqual(["context", "question"]);
    expect(ports.inputs.get("context")?.family).toBe("DATA");
  });
});
