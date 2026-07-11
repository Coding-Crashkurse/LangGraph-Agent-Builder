import { describe, expect, it } from "vitest";

import type { ComponentDescriptor, PortSpec } from "@/api/types";

import { extractPromptVars, indexPorts, portAriaLabel } from "./guards";

describe("PromptInput {vars} → live input ports (SPEC §4.2)", () => {
  it("extracts vars, ignores {{escaped}} and invalid names", () => {
    expect(extractPromptVars("test {dsada} sdasda {q_1} {dsada}")).toEqual(["dsada", "q_1"]);
    expect(extractPromptVars("json {{literal}} and {1bad}")).toEqual([]);
    expect(extractPromptVars("")).toEqual([]);
  });

  it("portAriaLabel matches the §11.4 screen-reader contract", () => {
    const message: PortSpec = {
      schema_ref: "lga:Message",
      json_schema: {},
      family: "MESSAGE",
      is_list: false,
    };
    expect(portAriaLabel("message", message, "out")).toBe("output message, type lga:Message");
    expect(portAriaLabel("input", message, "in")).toBe("input input, type lga:Message");
    const documents: PortSpec = { ...message, schema_ref: "lga:Documents", is_list: true };
    expect(portAriaLabel("docs", documents, "in")).toBe("input docs, type lga:Documents list");
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
