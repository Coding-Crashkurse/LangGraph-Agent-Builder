#!/usr/bin/env node
/**
 * Generate TypeScript types from the pinned platform contract
 * (../schemas/flow-definition.schema.json) into src/api/generated/.
 *
 * json-schema-to-typescript formats its output with its bundled prettier;
 * the repo has no prettier config, so the style below is pinned explicitly
 * to keep regeneration byte-for-byte deterministic (CI diffs the output).
 * Line endings are forced to LF so Windows and the Linux CI runner agree.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import { compileFromFile } from "json-schema-to-typescript";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const schemaPath = join(frontendRoot, "..", "schemas", "flow-definition.schema.json");
const outDir = join(frontendRoot, "src", "api", "generated");
const outFile = join(outDir, "flow-definition.ts");

const ts = await compileFromFile(schemaPath, {
  style: {
    printWidth: 100,
    tabWidth: 2,
    useTabs: false,
    semi: true,
    singleQuote: false,
    trailingComma: "all",
    endOfLine: "lf",
  },
});

mkdirSync(outDir, { recursive: true });
writeFileSync(outFile, ts, "utf8");
console.log(`gen-types: wrote ${join("src", "api", "generated", "flow-definition.ts")}`);
