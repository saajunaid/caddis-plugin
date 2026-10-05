---
name: flow-studio
description: Design an interactive flow, lifecycle or journey page (nodes, lanes, links, motion, inspector, notes) from a JSON model as a self-contained demo, then build it in an app. Use for lineage, pipelines, ticket or agent journeys.
---

# flow-studio

Turns a one-paragraph brief into an explorable page: stages across, lanes down, linked nodes, pan and zoom,
a slide-in inspector, motion that carries meaning, and numbered implementation notes. One JSON **model**
describes the scenario. One engine draws it. A check script proves it is sound.

Use it for: data lineage and dependency impact, a ticket or case lifecycle, an agent or customer journey, a CI/CD
or release pipeline, an approval flow, an incident timeline, a service map. See `references/patterns.md`.
Not for: a static screen or UI variants (use `mockup` or `sketch`), a chart, a graph with more than 300 nodes.

## What works today (version 0.1)

Left-to-right flows in **columns** (stages) and **lanes** (apps, systems or actors): states with their own look
and motion, portal chips for shared nodes, wide placeholders for what is not recorded, two or more views
(for example Today and Complete), search, a what-if action (a red ripple downstream), a table view, and notes.

**Not yet** (planned, do not promise them): links that go back to an earlier stage (loops), gateway diamonds,
automatic placement, token playback along a path, live data updates, free x and y placement. If the scenario
needs a loop, show the return as its own node in a later column (for example "Reopened") and say so.

## Process: demo mode

1. **Ask at most three questions**: what is the page for, who reads it, and what are the nouns (the stages, the
   lanes, the states). If the brief already says, ask none.
2. **Map the scenario** to the model (`references/patterns.md` has a recipe per scenario):
   columns = stages left to right, lanes = who or what owns the row, states = the vocabulary (for example
   new, open, waiting, breached, resolved), nodes = the things, links = the flow.
3. **Write `model.json`.** Fields are in `model.schema.json`; `examples/lineage.json` is a complete model.
4. **Validate:** `node --experimental-strip-types scripts/validate.mjs model.json`. Fix every error. Read every
   warning.
5. **Build:** `node --experimental-strip-types scripts/build.mjs model.json out/page.html`. It is one file with
   no network use.
6. **Check:** from a folder that has `playwright`:
   `node <skill folder>/scripts/check.mjs out/page.html --out shots [--channel msedge]`.
   Every check must pass. Open the screenshots and look at them: the checks do not judge taste.
7. **Show** the page and the screenshots. Do not call it done until the checks pass and you have looked.

Paths above are relative to the folder that holds this file. Node 22.6 or newer is needed.

## Design rules (the engine and the checks enforce most of them)

1. **No orphan.** Every node sits in a lane and has a link. A missing neighbour is a dotted placeholder that says
   what is missing. Never guess a link.
2. **The first view is readable**: fit to width at zoom 0.6 or more (up to 60 groups). Key `0` shows everything.
3. **Read left to right**, with pinned column headers and a phase ribbon.
4. **Motion carries state**: links flow by state, gaps breathe, the selected path draws in, a what-if ripples.
   No decorative loops, no sweeping scan line, no bounce.
5. **No permanent side panel.** The inspector slides in on a click and closes with Esc.
6. **Standard controls**: select, hand, zoom in and out, fit, 100 percent, zoom to selection, fullscreen, keys.
7. **Every state has a word as well as a colour.** Contrast at least 4.5 in light and dark.
8. **Titles stay short** (one line at the column width). Long text goes in `subtitle` or `members`.
9. **Fixed node sizes per kind.** The engine never measures text, so layout does not depend on fonts.
10. **Reduced motion** removes all motion and keeps the glow.

## Model in one screen

```
version 1, meta {title, help, asOf, source, labels?}, layout "columns-lanes"
columns [{id, title, short?, width, phase?}]              stages, left to right
lanes   [{id, title, badge?, badgeTone?, note?, gap?}]    rows; gap true = dashed amber "no document" lane
states  {id: {word, tone, border, edge, motion, bucket}} the vocabulary; bucket good|neutral|gap
nodes   [{id, kind, lane, col, colSpan?, row, state, title, subtitle?, members?, weight?, ref?, upgrade?,
          stateIn?, visibleIn?}]                          kind: card group chip placeholder (others draw as cards)
links   [{id, from, to, state, label?, stateIn?, visibleIn?}]   from must be in an earlier column than to
views   [{id, label, default?}]                           the first view is the baseline
inspector {relations [3 of {id,label,dir,filter?}], actions [{id,label,dir,staleText}]}
notes   [{anchor, title, text}]                           anchor is a CSS selector for a part of the page
```

Rows are numbers (1 row = 62 px). Keep nodes in one column at least 1 row apart. A lane needs about 1.75 rows of
space between single-row lanes. `validate.mjs` checks all of this and names the node or link at fault.

## Build mode: implement it in a real app

Use the demo page as the visual contract and `model.schema.json` as the data contract.

1. Copy the pure modules from `src/` into the app: `model.ts`, `layout.ts`, `viewport.ts`, `routing.ts`,
   `trace.ts`, `rules.ts`, `stateCss.ts`, and their `*.test.ts` files. They have no DOM and no dependencies.
2. Work test first: run the copied tests, then write a failing test for each change.
3. Write the components in the app's own framework and design system (the demo's DOM and CSS are in
   `src/render.ts`, `src/controls.ts`, `src/inspector.ts`, `src/chrome.ts`, `src/styles.css`). Feed them from the
   app's real data through the app's hook and service layer. Make node and link ids stable (use business keys, not
   array positions).
4. Keep typed loading, empty and error states. A failed refresh keeps the last good graph. Never draw a missing
   value as zero.
5. Run `scripts/check.mjs` against the running app page for the structural, interaction and accessibility checks
   (the page must expose the same element ids, or copy the harness and adapt it).

A packaged React kit and live-update API are planned; until then, build mode is "copy the pure modules, port the
DOM modules".

## Gotchas

- Examples and any committed data must be invented: a public repo must not carry real host, job or repo names.
- A model string is data, never markup. The engine renders text safely; keep it that way in any port.
- The caddis pool budgets all skill descriptions together. Keep this one short.
- `templates/engine.html` is generated. After changing `src/`, run `node --experimental-strip-types
  scripts/build-engine.mjs` (it needs `esbuild`; see `README.md`).
