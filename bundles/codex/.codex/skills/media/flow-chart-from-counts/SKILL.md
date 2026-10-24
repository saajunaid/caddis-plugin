---
name: flow-chart-from-counts
description: Turn a from-to-count edge list into a zoomable Mermaid flow chart page with counts, a legend and a render check.
---

# flow-chart-from-counts

Turns counted paths (N cases went from step A to step B) into a flow chart page that a
reader can trust: counts on every arrow, a legend for the box types, a title with the date and
time zone, a note that names what is not drawn, and a viewer with zoom, pan and full screen.

Paths below are relative to the folder that holds this file.

## When to use it

- "Draw how cases move through the process", "show the journey with counts", "flow chart of
  calls / orders / tickets / sessions from this table".
- You have, or can query, rows of `from, to, count`, or an event table with one row per step.
- A Sankey or a funnel was asked for, but the paths branch and rejoin: a flow chart shows that
  better.

Use something else for:

- An interactive page from a JSON model with lanes, playback and an inspector: `flow-studio`.
- Mermaid syntax for other diagram kinds (sequence, ERD, class): `mermaid-diagrams`.
- A diagram of a SQL object's structure: `db-diagram`.

## What is in the folder

| file | use |
|---|---|
| `scripts/edges_to_mermaid.py` | CSV edge list to first-draft Mermaid source (standard library only) |
| `assets/viewer-template.html` | page with the zoom/pan/full-screen viewer, theme tokens and one example chart |
| `scripts/check-render.mjs` | headless render check: fails on no SVG, error text, too few nodes, page errors; saves screenshots |
| `references/edge-list-sql.md` | SQL pattern: event table to edge list and box counts, and the checks to run on it |

## Process

1. **Get the edge list.** From an event table, use `references/edge-list-sql.md`. Run its checks
   (START rows add up to the cases; path occurrences in equal path occurrences out per step).
   Count arrows as distinct cases per pair. Get the box counts (distinct cases per step) at the
   same time.
2. **Name the node types** with the reader, or from the process owner's own glossary: for
   example automatic step, in-scope step, optional step, hand-off, end. Write a `nodes.csv`
   (`name,type,count`).
3. **Make the first draft:**
   ```
   python scripts/edges_to_mermaid.py edges.csv --nodes nodes.csv --min 25 \
          --in-scope scope --optional choice --out chart.mmd --strict
   ```
   `--out` writes UTF-8 (do not use `>` in Windows PowerShell 5.1: it can write UTF-16). The note
   on hidden paths goes to stderr. Keep it: it goes under the chart. `--strict` exits 1 on a
   `warning:` line, which means an arrow is larger than its box: fix the query before you draw.
   Duplicate `from,to` rows are added together. Node types become classes named `t_<type>`.
4. **Put it in the page.** Copy `assets/viewer-template.html`. Paste the source into the
   `<script type="text/plain">` block. Set `data-title` (what, which day) and `data-sub` (the UTC
   window, the unit of the counts, the minimum path size). Replace the legend and the note.
   For more charts, add one `.fv` block and one source script per chart.
5. **Render and check:**
   ```
   node <skill folder>/scripts/check-render.mjs page.html --out shots [--channel msedge]
   ```
   Run it from a folder whose `node_modules` has `playwright`. It exits 1 when a check fails.
6. **Look at the screenshots** (`chart-N.png` is the chart at Fit, `chart-1-full.png` is full
   screen) and run the tidy checklist below. If a rule fails, change the layout with the layout
   fixes, and go back to step 5.
7. **Show** the page and the screenshots only when every checklist rule passes. Say which labels
   are your reading (see Wording). If a rule cannot be met, say which rule and why.

## Tidy checklist (the chart must pass it before you show it)

A clean, tidy chart is an acceptance rule, not a nice-to-have. A reader who has to trace a
line across the page stops trusting the numbers on it.

1. **No crossing lines.** No line passes through a box or a label. Use the tree rule with
   dashed stubs, and split shared targets (layout fixes 1 and 2).
2. **No overlaps.** No label or box sits on another. Edge labels are short: `(1,234)` and at
   most a few words. Long text goes in the note under the chart, not on the chart.
3. **Rows and side flows.** Boxes of the same kind line up in one row where the flow allows
   (layout fix 5). A side flow sits in its own dashed box at the bottom, pushed down with an
   invisible link (layout fix 4).
4. **One look per type.** One box shape per type, a small fixed palette (5 to 7 classes), a
   legend that matches the chart exactly (stubs included), and the title with the date and the
   time zone on the chart.
5. **Readable at Fit and at full screen** on a 1280 x 900 screen. Nothing is clipped.
6. **Checked by eye.** You opened both screenshots and checked rules 1 to 5 on them. The render
   check's warnings (box overlaps, labels on boxes) help, but they cannot see a crossing line.

## Count rules

- **Arrows and boxes both count distinct cases.** An arrow says how many distinct cases took
  that path (`COUNT(DISTINCT case_id)` per from-to pair). A box says how many distinct cases
  reached it. Do not draw path occurrences (`COUNT(*)`): a case that loops counts twice, and a
  reader who sees a box of 8,538 followed by an arrow of 8,541 stops trusting the chart. Label
  every number as cases.
- **Self-check: no arrow into or out of a box exceeds that box's count.** If one does, the
  query counts occurrences. The converter warns on stderr when this happens.
- **Say in the note that arrows into a box can sum to a little more than the box**, because a
  case can reach it by two paths.
- **Put counts in brackets, with thousands separators:** `(1,234)`. In Mermaid an edge label that
  holds brackets must be quoted: `A -->|"(1,234)"| B`. Unquoted, `(` starts a node shape and the
  chart fails to parse.
- **Hide small paths with a stated minimum.** Choose a minimum (for example 25), drop the paths
  under it, and write a note that names them and their total: "Not drawn because fewer than 25
  cases took them: X to Y (12), ... (41 in total)." A chart that drops paths without a note looks
  complete and is not.
- **Merge small boxes into one named box, and say so.** When you merge, the count is a sum of
  rounded or filtered parts: write `(about 600)`, and say in the note what the box holds.
- **Put the date and the time zone on the chart.** Write the title as HTML inside the zoomable
  stage (the template does this from `data-title` and `data-sub`), so it stays with the chart in
  full screen and in screenshots. Do not use a frontmatter `title:` as well: it would show a second title. Give the
  local day and the UTC window: `Mon 5 Oct 2026 (4 Oct 23:00 to 5 Oct 23:00 UTC)`.
- **Name the unit.** "Counts in brackets are calls / orders / cases." A count with no unit gets
  read as the wrong one.

## Node types and the legend

- One `classDef` per node type, and one `class id1,id2 type;` line per type. The converter writes
  these from `nodes.csv`.
- **In-scope boxes get a thick border** (`stroke-width:3px`), so the reader finds the subject of
  the chart first.
- **Optional or owner-choice boxes get a dashed border** (`stroke-dasharray:6 4`): a step that is
  a decision still open, or one that runs only for some cases.
- End boxes share one quiet grey class. Stubs share one class: white fill, thin dashed grey
  border (`stroke-dasharray:3 3`), so they read as pointers, not steps.
- Put a legend above the chart with one swatch per type, with the same fill, border width and
  dash as the chart. Use light fills with dark text. Keep the chart canvas light in dark mode
  too (the template's `--canvas` token does this), or the dark text loses contrast.

## Layout fixes that work

Mermaid's layout (dagre) puts each node on a rank and orders each rank to cut crossings. It does
not know what the reader looks for. These fixes move it.

1. **Draw the chart as a tree.** Give every box exactly one parent edge: the biggest path into
   it. For every other path into that box, add a small dashed stub under its own source,
   labelled with the target and the count: `B --> toB_C(["to C (412)"])`. Shared targets and
   back-edges are what make the layout cross lines; a tree with stubs has none. Add a legend
   entry for stubs ("dashed: the path continues at the box named"). The converter does this by
   default (`--no-tree` turns it off).
2. **Give each source its own end box.** One shared "Ends" box pulls a long line from every step
   across the chart. Write `A --> endA(["Ends"])` and `B --> endB(["Ends"])` instead. The
   converter does this. Apply the same fix to any shared target that sits far from its sources:
   a copy of the box next to each source is easier to read than one box with crossing lines.
3. **Do not draw a loop-back as an edge.** A line back up the chart crosses everything. End the
   path in a stub: `A --> backA(["back to Triage (190)"])`. The converter does this for every
   edge that points back to a step on the path.
4. **Put a side flow in its own subgraph and push it down.** For example the steps after a
   hand-off. Draw them in `subgraph AFTER[...] direction LR ... end` and add an invisible link
   from a low node of the main flow: `X2 ~~~ AFTER`. The subgraph then sits under the main
   flow, not beside it.
5. **Put same-kind boxes in one row.** Group them in a subgraph, and lengthen the edges into it
   (`---->`, one dash per extra rank) so they land on the same rank.
6. **Replace a long jump with a short stub or a dotted link.** When an edge must reach a box
   far away, end it in a small stub node near the source, or draw it dotted (`-.->`) with a
   label such as `"few"`, so the eye can tell it is secondary.
7. **Order the edges from a node in the order you want the boxes, left to right**, and declare
   the nodes in the same order. Dagre takes this as its first guess. It can still swap them to
   cut crossings: check the screenshot.
8. **Quote every label that holds brackets, quotes or `<br/>`:** `["Text<br/>(12)"]`,
   `|"(12)"|`. Write a quote inside a label as `#quot;`.

Change one thing at a time and re-render. Two fixes at once hide which one helped.

## Wording

- **Use the process owner's words for box labels** when a glossary or a list of step names
  exists. A reader checks the chart against those names.
- **Write neutral endings.** "Case ends" or "Call ends" means the data shows no further step.
  Do not write a guess such as "hangs up" or "gives up": the data does not say who ended it.
  Say what "ends" means in the note.
- **Mark your own reading.** When a label or a grouping is your interpretation, not a name from
  the source, say so in the note ("'Team queues' is our grouping of four queues").

## Verify

`scripts/check-render.mjs` fails (exit 1) when a chart has no SVG, shows an error message, has
fewer nodes than `--min-nodes`, or the page throws. Make it fail once on purpose (break one
line of the source) to see that it can. It also counts box overlaps and arrow labels on boxes
as warnings. Those are hints: open the screenshots and run the tidy checklist by eye, because
the check cannot see a crossing line.

Also check the numbers, not only the drawing: the START count equals the cases in the window,
and no arrow into or out of a box is larger than the box (the converter warns when one is).

## Publishing

- As an Artifact: follow the artifact-design rules. Mermaid loads from
  `https://cdnjs.cloudflare.com/ajax/libs/mermaid/10.9.1/mermaid.min.js` (an exact version on the
  allowed CDN). The template already has theme tokens for light and dark, an explicit body
  background, and a 16px side gutter for phone width.
- In an app: render with the app's own Mermaid package and keep the same source, title and note.
  Keep the count rules; they are what makes the chart trustworthy.
