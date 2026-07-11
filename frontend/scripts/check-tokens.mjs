#!/usr/bin/env node
/**
 * Token lint (SPEC §11.5 / Appendix C): colours come exclusively from the
 * theme.css tokens. Fails on
 *   1. raw hex colours (#abc, #aabbcc, …) in src/ outside theme.css/index.css
 *   2. stock Tailwind palette utilities (zinc-500, red-400, …) in src *.ts/tsx
 * Generated files (schema.gen.ts) are exempt. Cross-platform (no shell grep).
 */
import { readdirSync, readFileSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const frontendRoot = fileURLToPath(new URL("..", import.meta.url));
const srcRoot = join(frontendRoot, "src");

const HEX = /#[0-9a-fA-F]{3,8}\b/g;
const PALETTE = /\b(?:zinc|slate|gray|red|amber|emerald|violet|sky|green|pink)-[0-9]/g;

// theme.css owns the palette; index.css may reference tokens but not define
// new hex — it is exempt only for historical comments, keep it clean anyway.
const HEX_EXEMPT_FILES = new Set(["theme.css", "index.css"]);
const GENERATED_FILES = new Set(["schema.gen.ts"]);

function* walk(dir) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) yield* walk(path);
    else yield path;
  }
}

const violations = [];
for (const file of walk(srcRoot)) {
  const base = file.replace(/\\/g, "/").split("/").pop() ?? "";
  if (GENERATED_FILES.has(base)) continue;
  const isTs = /\.(ts|tsx)$/.test(base);
  const isCss = base.endsWith(".css");
  if (!isTs && !isCss) continue;

  const rel = relative(frontendRoot, file).replace(/\\/g, "/");
  const lines = readFileSync(file, "utf8").split("\n");
  lines.forEach((line, index) => {
    if (!HEX_EXEMPT_FILES.has(base)) {
      for (const match of line.matchAll(HEX)) {
        violations.push(`${rel}:${index + 1}  raw hex ${match[0]} — use var(--color-…) from theme.css`);
      }
    }
    if (isTs) {
      for (const match of line.matchAll(PALETTE)) {
        violations.push(`${rel}:${index + 1}  palette utility "${match[0]}…" — use theme tokens (text-1/2/3, surface-1/2/3, border, accent, success/warning/danger, port-*)`);
      }
    }
  });
}

if (violations.length > 0) {
  console.error(`check-tokens: ${violations.length} colour-token violation(s) (SPEC §11.5):`);
  for (const violation of violations) console.error(`  ${violation}`);
  process.exit(1);
}
console.log("check-tokens: OK — no raw hex or stock palette utilities in src/");
