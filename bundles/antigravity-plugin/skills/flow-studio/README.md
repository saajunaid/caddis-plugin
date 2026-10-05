# flow-studio (engine source)

Stage S1a of the `flow-studio` skill: a model file (JSON) describes a flow, lifecycle or journey, and one
engine draws it as a self-contained HTML page with pan and zoom, lanes, linked nodes, a slide-in
inspector, motion that carries state, and numbered implementation notes. The design is in
`.caddis/plans/flow-studio-skill-design.md`; the plan for this stage is `.caddis/plans/flow-studio-s1a-plan.md`.
There is no `SKILL.md` yet: the playbook arrives in stage S2.

## Use it

```bash
# from this folder (Node 22.6 or newer)
node --experimental-strip-types scripts/validate.mjs examples/lineage.json
node --experimental-strip-types scripts/build.mjs examples/lineage.json out/lineage.html
```

Open `out/lineage.html`. It has no network access and no libraries.

`build.mjs` embeds the model's own `notes` plus any extra notes from `--notes notes.json` (the model's
notes come first, then the file's). Note anchors are CSS selectors for parts of the page, for example
`#viewport`.

## Check a page

The harness drives a real browser. Run it from a folder whose `node_modules` has `playwright`
(it is looked up from the current folder, not from this one):

```bash
node /path/to/flow-studio/scripts/check.mjs out/lineage.html --out shots --hostile out/hostile.html --channel msedge
```

It checks structure (no overlap, links touch their nodes, text stays inside cards, readable first view),
interaction (zoom, pan, select, what-if, view switch), accessibility (names, focus, contrast in both themes,
reduced motion), safety (no network, hostile text stays inert) and performance (200 nodes). Exit code 0 means
every check passed.

`scripts/lib/check-selftest.test.mjs` feeds the harness pages with one deliberate defect each and fails
if a defect is not caught. It is skipped when Playwright cannot be resolved, so run it from a folder that has
it: `FLOW_STUDIO_CHANNEL=msedge node --test /path/to/flow-studio/scripts/lib/check-selftest.test.mjs`.

## Develop it

- The source of truth is `src/*.ts`. The pure modules (`model`, `viewport`, `routing`, `trace`, `layout`,
  `rules`, `stateCss`) have unit tests. The DOM modules (`render`, `controls`, `interact`, `inspector`,
  `chrome`, `notes`, `engine`) are tested through the check harness.
- `npm test` runs the unit tests (`node --experimental-strip-types --test`).
- `templates/engine.html` is generated and committed. After you change `src/` or `templates/engine.shell.html`,
  run `node --experimental-strip-types scripts/build-engine.mjs`. A test fails when the committed file is stale.
- `build-engine.mjs` needs `esbuild`. It looks in this folder, then in the caddis `cli/` folder, then in the
  current folder. In a caddis checkout, `cli/node_modules` already has it. Elsewhere, run `npm i -D esbuild`. The stale-engine check compares bytes, so use the same esbuild version as the checkout that committed the file (the caddis `cli/` one).
- Type check with `tsc -p tsconfig.json` (TypeScript from `cli/node_modules` or your own install).
- Examples use fictional data only: this repository is public.
- Delete the `out/` folder before exporting bundles. It is ignored by git but not by a file copy.
