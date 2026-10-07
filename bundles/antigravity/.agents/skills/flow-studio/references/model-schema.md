# Model schema reference

This reference documents the structure and properties of the flow-studio model specified in `model.schema.json`. Every property is listed with its type, requirement status, default value, and semantic description.

## 1. Top-level model object

A valid model requires the core structural properties.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `version` | `integer` | Required | `1` | Schema version (must equal 1). |
| `meta` | `object` | Required | - | Metadata describing the scenario, authorship, and timestamp. |
| `layout` | `string` | Required | - | Layout mode: `"columns-lanes"`, `"free"`, or `"auto"`. |
| `columns` | `array` | Required | - | Array of vertical column definitions. |
| `lanes` | `array` | Required | - | Array of horizontal swimlane definitions. |
| `states` | `object` | Required | - | Dictionary of visual state definitions keyed by state ID. |
| `nodes` | `array` | Required | - | Array of node and card elements. |
| `links` | `array` | Required | - | Array of directional connections between nodes. |
| `views` | `array` | Optional | - | Optional filtered or perspective views. |
| `inspector` | `object` | Optional | - | Inspector relationships and what-if simulation actions. |
| `scenarios` | `array` | Optional | - | Playback scenarios for animated token traces. |
| `notes` | `array` | Optional | - | Implementation and design callout notes. |

---

## 2. `meta` object

Contains descriptive and provenance metadata for the diagram.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `title` | `string` | Required | - | Header title of the flow. |
| `help` | `string` | Required | - | Subtitle explaining the scenario purpose and context. |
| `asOf` | `string` | Required | - | Date or timestamp representing data freshness (e.g. `"2026-10-06"`). |
| `source` | `string` | Required | - | Provenance, API, database, or owning team. |
| `labels` | `object` | Optional | - | Key-value dictionary of auxiliary string labels. |

---

## 3. `columns` array items

Columns provide vertical partitioning for time, stages, or architecture tiers.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `id` | `string` | Required | - | Unique column identifier. |
| `title` | `string` | Required | - | Display title shown in the column header. |
| `short` | `string` | Optional | - | Compact abbreviated title for tight viewports. |
| `width` | `number` | Required | - | Column width in pixels (minimum 60). |
| `phase` | `string` | Optional | - | Super-category phase grouping shown in top banner. |
| `continues` | `boolean` | Optional | `false` | This column is a wrapped continuation of the column before it (for example one long list laid out in three side-by-side columns). It shows no header label and no strip cell of its own: its nodes count into the cell of the column it continues. Not allowed on the first column. |

---

## 4. `lanes` array items

Swimlanes partition the canvas horizontally by owning team, system, or tier.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `id` | `string` | Required | - | Unique lane identifier. |
| `title` | `string` | Required | - | Display title of the swimlane. |
| `badge` | `string` | Optional | - | Small uppercase pill badge text (e.g. `"PROD"`). |
| `badgeTone` | `string` | Optional | `"muted"` | Badge color tone: `"ok"`, `"warn"`, or `"muted"`. |
| `note` | `string` | Optional | - | Explanatory note rendered beside the lane title. |
| `gap` | `boolean` | Optional | `false` | When true, renders the lane with an amber dashed border indicating unverified systems. |

---

## 5. `states` dictionary items

States define semantic styling, borders, and animations for nodes and edges.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `word` | `string` | Required | - | Human-readable state badge text (e.g. `"HEALTHY"`, `"FAILED"`). |
| `tone` | `string` | Required | - | Semantic color: `"ok"`, `"warn"`, `"crit"`, `"info"`, `"muted"`, or `"accent"`. |
| `border` | `string` | Required | - | Card border style: `"solid"`, `"dashed"`, or `"dotted"`. |
| `edge` | `string` | Required | - | Link stroke dash pattern: `"flow"`, `"dash"`, `"dash-short"`, or `"dot"`. |
| `motion` | `string` | Required | - | State animation: `"flow"`, `"flow-slow"`, `"breathe"`, or `"none"`. |
| `bucket` | `string` | Required | - | Health bucket category: `"good"`, `"neutral"`, or `"gap"`. |

---

## 6. `nodes` array items

Nodes represent processing units, cards, gateways, groups, and milestones.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `id` | `string` | Required | - | Unique node identifier. |
| `kind` | `string` | Required | - | Node kind: `"card"`, `"group"`, `"chip"`, `"gateway"`, `"start"`, `"end"`, `"event"`, `"placeholder"`, or `"note"`. |
| `state` | `string` | Required | - | Key referencing a valid state in `states`. |
| `title` | `string` | Required | - | Primary label or name of the node. |
| `subtitle` | `string` | Optional | - | Secondary description line. |
| `lane` | `string` | Required (grid/free) | - | ID of the lane containing this node. |
| `col` | `integer` | Required (grid) | - | Zero-based column index where the node begins. |
| `colSpan` | `integer` | Optional | `1` | Number of columns spanned (minimum 1). |
| `row` | `number` | Required (grid) | - | Vertical slot index within the lane. |
| `x` | `number` | Required (free) | - | Absolute horizontal coordinate in pixels. |
| `y` | `number` | Required (free) | - | Absolute vertical coordinate in pixels. |
| `w` | `number` | Optional | auto | Explicit node width in pixels. |
| `h` | `number` | Optional | auto | Explicit node height in pixels. |
| `stateIn` | `object` | Optional | - | View-specific state overrides keyed by view ID. |
| `visibleIn` | `array` | Optional | all | Array of view IDs where this node appears. |
| `members` | `array` | Optional | - | Array of member entity names or IDs. |
| `weight` | `number` | Optional | - | Numerical priority or item count (minimum 0). |
| `ref` | `string` | Optional | - | Target node ID if this node acts as a portal chip. |
| `upgrade` | `string` | Optional | - | Recommended action or upgrade path. |
| `allowIsolated` | `boolean` | Optional | `false` | Explicitly permits node to have zero links without failing validation. |
| `contains` | `array` | Optional | - | Child node IDs contained in this group. |
| `collapsed` | `boolean` | Optional | `true` | When true, group starts collapsed hiding child nodes. |
| `sla` | `number` | Optional | - | Target service level agreement threshold in seconds. |
| `metrics` | `object` | Optional | - | Telemetry payload (see metrics table). |
| `bars` | `array` | Optional | - | A small bar chart on the node, one bar per `key` (see bars table). |

---

## 7. `metrics` object (under `nodes`)

Provides numerical telemetry, health bars, and sparklines.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `value` | `number` | Required | - | Primary current numerical metric value. |
| `max` | `number` or `null` | Optional | `null` | Upper bound for the badge fill bar (null for unbounded). |
| `unit` | `string` | Optional | - | Display unit (e.g. `"ms"`, `"rps"`, `"MB"`). |
| `label` | `string` | Optional | - | Descriptive metric label. |
| `series` | `array` | Optional | - | Historical series array (up to 60 numbers) rendered as sparkline. |

---

### `bars` items (under `nodes`)

A bar chart drawn inside the node, for example rows per day. Hovering a bar marks the bars with the same `key` on
every node, so a reader can ask "was this day bad everywhere?". The host page can follow the hover with the
`onHoverKey` mount option and drive it with `highlightKey(key)`. At most 120 bars.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `key` | `string` | Required | - | Opaque id of the bar (a date or a step). Equal keys are linked across charts. |
| `value` | `number` or `null` | Required | - | Bar size (finite, not negative). `null` means no data for that key: a short red tick, never a zero bar. |
| `kind` | `string` | Optional | - | `"low"` draws the bar in the critical colour. The last bar with data is drawn in the accent colour, unless it is `low`. |
| `label` | `string` | Optional | - | Tooltip text; defaults to `key: value`. |

---

## 8. `links` array items

Links represent directional data transit, dependencies, or workflow transitions.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `id` | `string` | Required | - | Unique link identifier. |
| `from` | `string` | Required | - | Source node ID. |
| `to` | `string` | Required | - | Target node ID. |
| `state` | `string` | Required | - | Key referencing a valid state in `states`. |
| `stateIn` | `object` | Optional | - | View-specific state overrides keyed by view ID. |
| `visibleIn` | `array` | Optional | all | Array of view IDs where this link appears. |
| `label` | `string` | Optional | - | Text label displayed on the link path. |
| `kind` | `string` | Optional | `"forward"` | Link direction: `"forward"` or `"loop-back"`. |

---

## 9. `views` array items

Permit switching between different operational layers or time slices.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `id` | `string` | Required | - | Unique view identifier. |
| `label` | `string` | Required | - | Button label shown in the mode switch toolbar. |
| `default` | `boolean` | Optional | `false` | Marks the initial default active view. |

---

## 10. `inspector` object

Configures the drill-down side panel and simulation capabilities.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `relations` | `array` | Optional | - | Array of up to 3 relation queries (see below). |
| `actions` | `array` | Optional | - | Array of what-if simulation buttons. |

### `relations` array items
- `id` (`string`, required): Unique relation query identifier.
- `label` (`string`, required): Button text displayed in the inspector header.
- `dir` (`string`, required): Traversal direction: `"up"` (upstream) or `"down"` (downstream).
- `filter` (`object`, optional): Criteria to filter matched nodes:
  - `col` (`integer`, optional): Restrict matches to a specific column index.
  - `kind` (`string`, optional): Restrict matches to a specific node kind.

### `actions` array items
- `id` (`string`, required): Unique action identifier.
- `label` (`string`, required): Button label (e.g. `"Simulate: DB Failure"`).
- `dir` (`string`, required): Must be `"down"`.
- `staleText` (`string`, required): Description of the simulated failure consequence.

---

## 11. `scenarios` array items

Configures interactive playback traces through the diagram.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `id` | `string` | Required | - | Unique scenario identifier. |
| `label` | `string` | Required | - | Scenario name shown in the playbar dropdown. |
| `steps` | `array` | Required | - | Ordered sequence of animation steps. |

### `steps` array items
- `link` (`string`, required): ID of the link traversed during this step.
- `at` (`number`, optional): Relative elapsed offset from scenario start in seconds.
- `dur` (`number`, optional): Token travel duration in milliseconds (default: 900).
- `caption` (`string`, optional): Narrative text displayed in the playbar during this step.

---

## 12. `notes` array items

Callouts anchored to HTML elements or nodes.

| Property | Type | Required? | Default | Description |
|---|---|---|---|---|
| `anchor` | `string` | Required | - | CSS selector resolved with `document.querySelector` at runtime. Target a shell element by id (`#viewport`) or a node card by its generated element id (`#n_` + node id). A bare node id is not a selector. A selector that matches nothing shows no marker. |
| `title` | `string` | Required | - | Short title of the implementation note. |
| `text` | `string` | Required | - | Guidance text for building this section. |

---

## 13. Minimal valid model example

A complete valid model under 20 lines:

```json
{
  "version": 1,
  "meta": { "title": "Minimal Flow", "help": "Minimal valid model", "asOf": "2026-10-06", "source": "Core API" },
  "layout": "auto",
  "columns": [{ "id": "c1", "title": "Step 1", "width": 160 }, { "id": "c2", "title": "Step 2", "width": 160 }],
  "lanes": [{ "id": "main", "title": "Primary Lane" }],
  "states": {
    "ok": { "word": "OK", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" }
  },
  "nodes": [
    { "id": "n1", "kind": "card", "lane": "main", "state": "ok", "title": "Input Node" },
    { "id": "n2", "kind": "card", "lane": "main", "state": "ok", "title": "Output Node" }
  ],
  "links": [{ "id": "l1", "from": "n1", "to": "n2", "state": "ok" }]
}
```

---

## 14. Common validation errors and fixes

### Error 1: Missing required column/lane position in grid layout
- **Schema error message:** `must have required property 'col'`, `must have required property 'row'`
- **Cause:** When `layout` is `"columns-lanes"`, all nodes must specify `lane`, `col`, and `row`.
- **Fix:** Add `"col": 0, "row": 0` to each node, or change `layout` to `"auto"`.

### Error 2: Missing state reference
- **Validator error message:** `node 'n1' references unknown state 'active'`
- **Cause:** A node or link sets `state: "active"`, but `"active"` is not defined in the top-level `states` dictionary.
- **Fix:** Define `"active"` under `states` with valid `word`, `tone`, `border`, `edge`, `motion`, and `bucket`.

### Error 3: Backward link without loop-back marker
- **Validator warning:** `link 'l2' goes right-to-left from column 2 to column 0; mark as loop-back`
- **Cause:** A link connects a later column back to an earlier column without declaring `kind: "loop-back"`.
- **Fix:** Add `"kind": "loop-back"` to the link definition.
