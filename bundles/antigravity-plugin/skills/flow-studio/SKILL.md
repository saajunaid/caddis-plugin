---
name: flow-studio
description: Design an interactive flow, lifecycle or journey page (nodes, lanes, links, motion, inspector, notes) from a JSON model as a self-contained demo, then build it in an app. Use for lineage, pipelines, ticket or agent journeys.
---

# flow-studio

Turns a one-paragraph brief into an explorable interactive flow page: stages across, lanes down, linked nodes, pan and zoom, a slide-in inspector, motion that carries meaning, and numbered implementation notes. One JSON model describes the scenario. One engine renders it. A check script proves it is sound.

Paths in the commands below are relative to the folder that holds this file, and `<skill folder>` in a command means that folder. Node 22.6 or newer is needed for `--experimental-strip-types`.

## When to use it

Use it for:
- Data lineage and dependency impact analysis.
- Ticket, case, and support workflows.
- Agent and customer journey mapping.
- CI/CD and release pipelines.
- Multi-step approval flows.
- Incident timelines and blast-radius exploration.
- Microservice architecture dependency maps.
See `references/patterns.md` for scenario recipes.

Do not use it for:
- Static UI layouts or component screen variants (use `mockup` or `sketch`).
- Manual whiteboard architectural diagrams (use `draw-io`).
- Simple text-based markdown diagrams (use `mermaid-diagrams`).
- Pure data schema specs without flow visualization (use `data-lineage`).

## What works today

- **Layouts**: columns and lanes, free coordinate placement (`layout: "free"`), and automatic layout (`layout: "auto"`).
- **Nodes and links**: forward links, loop-back links, gateway diamonds with labelled exits, collapsible groups, portal chips, placeholders, and cards.
- **Search and filter**: text search with an N-hop neighborhood filter.
- **Scenarios and playback**: token animation along links, SLA breach indicators, step mode with branch selection, speed control, and scrubber.
- **Metrics and what-if**: node metric badges with sparkline history, and inspector what-if ripple simulations.
- **Views and diffing**: baseline views with automatic addition and gap detection.
- **Live updates**: `FlowStudio.update(model)` updates data while preserving viewport, selection, and playback state.
- **Notes and demo pack**: numbered notes anchored to page elements, and built-in demo pack guidance (`--demo-pack`).

## Process: demo mode

1. **Ask at most three questions**: what is the page for, who reads it, and what are the stages, lanes, and states. If the brief already specifies them, ask nothing.
2. **Map the scenario** to columns, lanes, states, nodes, and links using `references/patterns.md`.
3. **Write `model.json`**. Check fields in `references/model-schema.md`. Use `examples/lineage.json` or `examples/order-desk.json` as references.
4. **Validate**: `node --experimental-strip-types scripts/validate.mjs model.json`. Fix every error and review warnings.
5. **Build**: `node --experimental-strip-types scripts/build.mjs model.json out/page.html` (optionally pass `--demo-pack` or `--notes`).
6. **Check**: run `node <skill folder>/scripts/check.mjs out/page.html --out shots [--channel msedge]` from a folder whose `node_modules` resolves `playwright`. Every check must pass. Open the screenshots to inspect visual hierarchy and legibility.
7. **Show**: present the standalone page and screenshots. Do not declare completion until checks pass.

## Build mode: implement it in a real app

Use `references/model-schema.md` as the data contract. Follow `references/implement-in-app.md` for the test-first procedure.

Choose one React route:
- **Fast wrapper route**: copy `templates/flow-studio.lib.mjs`, `templates/flow-studio.lib.d.mts`, `templates/flow-studio.css`, `react/`, and `src/` into the app. Import the CSS once and render `FlowStudioView`.
- **Native components route**: copy `react/native/` and `src/` into the app. Wire `useFlowGeometry`, `useViewport`, and `useTrace`. Style `FlowCanvas` and `Inspector` using the app design system.

In either route, derive node and link IDs from immutable business keys. Preserve these IDs across data refreshes so `update(model)` retains user state. Represent loading, empty, and error as typed states.

## Design rules

1. **No orphan**: every node sits in a lane and has a link. Missing neighbours use dotted placeholders.
2. **Readable first view**: the initial view fits width at zoom 0.6 or higher (up to 60 visible groups). Key `0` fits all.
3. **Read left to right**: pinned column headers and a phase ribbon guide the reader.
4. **Motion carries state**: links flow by state, gaps breathe, selected paths pulse, what-if ripples. Avoid decorative animation.
5. **No permanent side panel**: the inspector slides in on click and closes with Escape.
6. **Standard controls**: select, hand, zoom in/out, fit, 100%, zoom to selection, fullscreen, and keyboard shortcuts.
7. **Word and colour**: every state provides a label word and tone. Contrast meets 4.5:1 in light and dark themes.
8. **Short titles**: titles fit one line at column width. Long descriptions belong in subtitles or member lists.
9. **Fixed node dimensions**: node kinds use fixed box sizes so font rendering does not shift layout.
10. **Reduced motion**: removes all animations while preserving static borders and status glows.
11. **The lane is the owner**: a lane is the app, team or system that owns its row. Never add a column that repeats the owner (an "Apps" or "Owner" column); it adds a block between the real stages and the pages and says nothing new.
12. **Draw a shared node once**: when several rows use the same database, job or table, draw one node, centre it on the rows it serves, and link it to each node downstream. A chip (`kind: "chip"` with `ref`) is only for a node that lives in another lane, never a copy inside the same lane.
13. **Thin links, dotted canvas**: links are hairlines (about 0.8 px, with a 6 px arrowhead) and the canvas background is faint dots, not a grid. Both come from tokens (`--edge-w`, `--dot`, ...), so an app can change them with one CSS line; see `references/design-language.md`.

## Model summary

```
version 1, meta {title, help, asOf, source, labels?}, layout "columns-lanes" | "free" | "auto"
columns [{id, title, short?, width, phase?, continues?}]              stages, left to right
lanes   [{id, title, badge?, badgeTone?, note?, gap?}]    rows; gap true = dashed amber lane
states  {id: {word, tone, border, edge, motion, bucket}}  tone: ok|warn|crit|info|muted|accent; bucket: good|neutral|gap
nodes   [{id, kind, lane?, col?, colSpan?, row?, x?, y?, w?, h?, state, title, subtitle?, members?, weight?,
          ref?, upgrade?, contains?, collapsed?, stateIn?, visibleIn?, sla?, metrics?, bars?}]
links   [{id, from, to, state, kind?, label?, stateIn?, visibleIn?}]   kind: forward | loop-back
views   [{id, label, default?}]                           first view serves as baseline
inspector {relations [up to 3], actions [{id, label, dir, staleText}]}
notes   [{anchor, title, text}]                           anchor is a CSS selector in the page
scenarios [{id, label, steps:[{link, at?, dur?, caption?}]}] at in seconds, dur in milliseconds
```

## Limits

- **Size**: up to 60 visible groups for a readable initial view.
- **Node capacity**: up to 300 nodes using collapsible groups.
- **No image export**: the engine does not export PNG, SVG, or PDF files. Use browser print or screenshots.
- **No visual editor**: models are author-defined JSON; there is no drag-and-drop authoring canvas.

## Gotchas

- **Time units**: `at` and `sla` use seconds for business elapsed time; `dur` uses milliseconds for UI token transitions.
- **Fictional data only**: public repositories must never include real hosts, databases, jobs, or customer names.
- **Data over markup**: strings are treated as plain text and escaped safely. Do not insert raw HTML into model fields.
- **Generated engine**: `templates/engine.html` is generated. Run `node --experimental-strip-types scripts/build-engine.mjs` after modifying `src/`.
