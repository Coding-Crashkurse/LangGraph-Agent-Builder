# Generated API types

`flow-definition.ts` is generated from the pinned platform contract
(`schemas/flow-definition.schema.json` at the repo root) by `pnpm gen:types`
(`scripts/gen-types.mjs`). Never edit it by hand — CI reruns the generator
and fails on any diff, so both a schema bump without regeneration and a
hand-edit of the output break the build.

Migration plan: `src/api/types.ts` is the hand-written mirror still used by
the app. New code should prefer the generated types from this directory; the
full import swap happens after the current WIP lands.
