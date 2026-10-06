# Implementation notes and model specification

This document explains how implementation notes and the model reference specification work in flow-studio.

## 1. How implementation notes work

Implementation notes provide inline architectural, design, and engineering guidance for someone building the production page in an app.
- Notes are defined as an array of objects: `{ "anchor": "<css-selector>", "title": "...", "text": "..." }`.
- In `scripts/build.mjs`, all active notes are collected, assigned sequential numeric IDs (`1..n`), and embedded into the HTML via `/*__NOTES__*/[]`.
- In the browser, `src/notes.ts` renders a slide-out drawer on the left (`#drawer`) and creates circular purple numbered markers (`.marker`) positioned over the anchored target elements.
- Notes mode toggles via the "Implementation notes (N)" header button (`#notesBtn`) or by pressing the `N` key.

---

## 2. Shell anchors and valid IDs

A note can anchor to any node card (for example `#n_crm-db`: the engine gives each node element the id `n_` followed by the node id) or to any of the 13 canonical shell elements defined in `templates/shell-body.html`:

| Anchor ID | Shell element | Description |
|---|---|---|
| `#title` | Main title | Scenario headline and timestamp metadata |
| `#layerstrip` | Completeness strip | Column completeness health indicators |
| `#kpis` | Summary tiles | Summary metrics and gap count indicators |
| `#modeSwitch` | View switch | Perspective and layer selector buttons |
| `#q` | Search input | Text search and N-hop filter controls |
| `#viewport` | Canvas viewport | Pan, zoom, and interactive graph container |
| `#tools` | Toolbar | Zoom in/out, fit, and pan hand tool buttons |
| `#inspector` | Side inspector | Slide-in panel for relations, telemetry, and actions |
| `#legend` | Legend | State color keyline and evidence definitions |
| `#ledger` | Change ledger | Historical changes or audit log entries |
| `#tbl` | Table view | Accessible tabular rendering of all graph nodes |
| `#playbar` | Playback bar | Scenario controls, step scrubber, and branch options |
| `#notesBtn` | Notes toggle button | Header button to toggle the implementation notes drawer |

---

## 3. The demo pack mechanism

The `--demo-pack` option provides comprehensive out-of-the-box guidance:
- When running `scripts/build.mjs` with `--demo-pack`:
  1. Default shell notes are loaded from `scripts/default-notes.json`.
  2. Conditional shell notes are filtered based on the model:
     - `#playbar` note is dropped if the model has no scenarios (`!model.scenarios?.length`).
     - `#modeSwitch` note is dropped if the model has fewer than two views (`(model.views?.length ?? 0) < 2`).
     - A default note whose anchor starts with `#` is dropped when no element with that id exists in the generated shell. Class and attribute selectors are not checked at build time.
  3. Per-model notes from `model.notes` are appended.
  4. Additional external notes from `--notes <file.json>` are appended.
  5. The combined list is re-indexed from 1 to `N`.

  Model and extra notes are never filtered at build time. At runtime, a note whose selector matches nothing simply gets no marker (see section 4).

---

## 4. Notes panel interaction

`src/notes.ts` manages bidirectional interaction between cards and markers:
- **Marker placement:** Markers calculate bounding client rectangles and hover beside anchored elements.
- **Hovering a card:** Adds `.anchored` outline to the target element on the canvas and highlights the card in the drawer.
- **Hovering a marker:** Highlights the target element and scrolls the corresponding card into view in the drawer.
- **Clicking a marker:** Focuses and scrolls directly to the note text.
- **Safety:** Hostile selectors in notes (e.g. malformed CSS or script strings) are safely evaluated inside a `try ... catch` block using `document.querySelector`, returning null without throwing errors.

---

## 5. Model reference and specification tab

At the bottom of the page, the collapsible `<details class="spec" id="spec">` element renders the complete scenario model specification:
- **Summary information:** Model title, description, provenance source, and generation date.
- **States list:** Every state with its word, tone, border style, and edge animation.
- **Columns & Lanes:** Ordered sequence of columns with phases, and lanes with ownership badges.
- **Graph size:** Total node count and link count.
- **Copy buttons:**
  - `Copy as Markdown`: Copies a clean markdown summary formatted with tables and lists.
  - `Copy model JSON`: Copies the formatted JSON payload directly to the clipboard for reuse in an app.
