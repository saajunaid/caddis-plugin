# flow-studio (engine source)

The `flow-studio` skill: a model file (JSON) describes a flow, lifecycle or journey, and one
engine draws it as a self-contained HTML page with pan and zoom, lanes, linked nodes, a slide-in
inspector, scenario playback, metric overlays, live update, motion that carries state, and numbered implementation notes. The design is in
`.caddis/plans/flow-studio-skill-design.md`; the S4 stage status is in `.caddis/plans/flow-studio-s4-status.md`.
`SKILL.md` is the current playbook.

## Use it

```bash
# from this folder (Node 22.6 or newer)
node --experimental-strip-types scripts/validate.mjs examples/lineage.json
node --experimental-strip-types scripts/build.mjs examples/lineage.json out/lineage.html
node --experimental-strip-types scripts/validate.mjs examples/order-desk.json
node --experimental-strip-types scripts/build.mjs examples/order-desk.json out/order-desk.html
```

Open `out/lineage.html`. It has no network access and no libraries.
`order-desk.json` shows auto layout, a loop-back link, a gateway with labelled exits, a group that opens, two playback scenarios, an SLA, and metrics.
See [examples/README.md](examples/README.md) for the full catalog of worked scenario models.
A group with `contains` starts collapsed unless `collapsed` is `false`.

Play or step through a scenario with the playbar. At a gateway, step mode offers each exit and marks the scenario's next link as suggested. A model can provide `metrics` on nodes and `scenarios` with exact link ids. `FlowStudio.update(model)` validates a new model and keeps the current view, selection, search and playback position. The caller must derive node and link ids from stable business keys. Array positions are not stable ids.

`build.mjs` embeds the model's own `notes` plus any extra notes from `--notes notes.json`. Pass
`--demo-pack` to include the standard shell implementation notes: default notes come first, then
the model's notes, then extra notes, numbered sequentially 1..n. Default notes whose target elements
do not exist in the page are dropped (such as `#playbar` when there are no scenarios, or `#modeSwitch`
when there are fewer than two views). Note anchors are CSS selectors for parts of the page, for example
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

## Build inside a React app

Choose the route in [implement-in-app.md](references/implement-in-app.md):

- **Fast wrapper:** copy `templates/flow-studio.lib.mjs`, its `flow-studio.lib.d.mts` declaration,
  `templates/flow-studio.css`, `react/`, and `src/`. Keep the relative folder layout. Import the CSS once and
  render `FlowStudioView` with a validated `Model`. This route uses the engine's own look and behaviour.
- **Native components:** copy `react/native/` and `src/`. The hooks handle viewport, geometry, and trace
  state. Adapt `FlowCanvas` and `Inspector` to the app's design system. The app owns the final behaviour and
  visual checks.

Both routes need stable node and link ids based on business keys. Use typed loading, empty, ready, and error
states. Keep the last good graph on a failed refresh. See [react/README.md](react/README.md) for wrapper props
and the proof app command. The proof creates a temporary Vite app and removes it when finished:

```text
node scripts/react-proof.mjs
```

Run the browser harness against a running app page:

```text
node <skill>/scripts/check.mjs http://127.0.0.1:<port>/<route> --out shots --channel msedge --skip hostile
```

The `hostile` group needs a separate hostile page, which the proof app does not provide. Record any other
feature group that the app intentionally skips. A skipped check is not a pass.

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
- `build-engine.mjs` needs `esbuild`. It looks in `FLOW_STUDIO_NODE_MODULES` first, then this folder, the caddis `cli/` folder, then in the
  current folder. In a caddis checkout, `cli/node_modules` already has it. Elsewhere, run `npm i -D esbuild`. The stale-engine check compares bytes, so use the same esbuild version as the checkout that committed the file (the caddis `cli/` one).
- Set `FLOW_STUDIO_NODE_MODULES` to a shared `node_modules` folder to use its `esbuild` first when building in a worktree.
- Type check with `tsc -p tsconfig.json` (TypeScript from `cli/node_modules` or your own install).
- Examples use fictional data only: this repository is public.
- Delete the `out/` folder before exporting bundles. It is ignored by git but not by a file copy.
