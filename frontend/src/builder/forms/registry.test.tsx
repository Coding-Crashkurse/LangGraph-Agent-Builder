import { describe, expect, it } from "vitest";

import { FieldWidgetRegistry } from "./registry";

/** SPEC §11.2: every §4.2 field type maps to a widget (port-only types render
 * as handles, not widgets). */
const SPEC_FIELD_TYPES = [
  "StrInput",
  "MultilineInput",
  "IntInput",
  "FloatInput",
  "BoolInput",
  "SliderInput",
  "DropdownInput",
  "MultiselectInput",
  "TabInput",
  "SecretInput",
  "MultilineSecretInput",
  "DictInput",
  "NestedDictInput",
  "TableInput",
  "FileInput",
  "CodeInput",
  "PromptInput",
  "ModelInput",
  "QueryInput",
  "LinkInput",
  "McpInput",
];

describe("FieldWidgetRegistry", () => {
  it("covers every widget-capable field type from SPEC §4.2", () => {
    for (const type of SPEC_FIELD_TYPES) {
      expect(FieldWidgetRegistry[type], `missing widget for ${type}`).toBeDefined();
    }
  });

  it("port-only field types intentionally have no widget", () => {
    expect(FieldWidgetRegistry.HandleField).toBeUndefined();
    expect(FieldWidgetRegistry.ToolsInput).toBeUndefined();
  });
});
