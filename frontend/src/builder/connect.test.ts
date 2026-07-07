/** Repro: start.message → prompt_template.{x} must be a valid connection. */
import { describe, expect, it } from "vitest";

import type { ComponentDescriptor } from "@/api/types";

import fixtures from "./__fixtures__/descriptors.json";
import { indexPorts, judgeConnection } from "./guards";

const startDesc = fixtures.start as unknown as ComponentDescriptor;
const promptDesc = fixtures.prompt_template as unknown as ComponentDescriptor;

describe("start → prompt var connection", () => {
  it("judges start.message → prompt_template.x as a data edge", () => {
    const sourcePorts = indexPorts(startDesc, {});
    const targetPorts = indexPorts(promptDesc, { template: "test {x} test" });
    const sourcePort = sourcePorts.outputs.get("message");
    const targetPort = targetPorts.inputs.get("x");
    expect(sourcePort?.family).toBe("MESSAGE");
    expect(targetPort?.family).toBe("DATA");
    const verdict = judgeConnection(sourcePort, targetPort, false);
    expect(verdict).toEqual({ ok: true, kind: "data" });
  });
});
