import { expectTypeOf } from "vitest";

import type { Edge, ExposeConfig, FlowDefinition } from "./generated/flow-definition";

// Smoke test for the generated schema types: keeps src/api/generated/ in the
// test graph and pins the core shapes at the type level (tsc fails on drift).
describe("generated flow-definition types", () => {
  it("model the core definition shape", () => {
    const definition: FlowDefinition = {
      schema_version: 1,
      name: "hello-flow",
      expose: { kind: "a2a" },
      nodes: [
        { id: "start", version: 1, type: "start", config: { input_schema: {} } },
        { id: "end", version: 1, type: "end", config: {} },
      ],
      edges: [{ from: "start", to: "end" }],
    };

    expectTypeOf(definition.schema_version).toEqualTypeOf<number>();
    expectTypeOf(definition.nodes).items.toHaveProperty("type");
    expectTypeOf<FlowDefinition["edges"]>().toEqualTypeOf<Edge[] | undefined>();
    expectTypeOf<ExposeConfig["kind"]>().toEqualTypeOf<"a2a" | "mcp">();

    expect(definition.nodes).toHaveLength(2);
    expect(definition.edges?.[0]).toEqual({ from: "start", to: "end" });
  });
});
