---
name: db-diagram
context: fork
description: Turn a SQL artifact — a stored procedure, view, query, .sql file, or table name — into a diagram that explains it to a human. Use when the user says "diagram this query/proc/view/schema", "explain this SQL visually", "draw the ER diagram", "show me the data flow of this stored proc", "/mermaid-db", or "/excalidraw-db". Produces Mermaid (default, git-diffable) or Excalidraw (for design reviews). Read-only — never touches the database.
---

# db-diagram — explain SQL as a diagram

Take a SQL artifact and produce a diagram that explains it to a human. Two output formats, one shared
extraction: **Mermaid** (default — plain text, diffs cleanly, renders in VS Code/Gitea, regenerable) and
**Excalidraw** (for a design review / ARB pack / slide — someone drags boxes around).

The structure is extracted **deterministically** by `scripts/sql_to_graph.py` (a real sqlglot-based
parser); you (the model) add the **business narration** on top. Never hand-derive the node graph when the
script can run — its whole value is reproducibility.

## Two non-negotiable safety rules

1. **Never write to the database.** Read-only by definition — no DDL, no DML, not even in a rolled-back
   transaction. The extractor only ever parses SQL *text*.
2. **Never guess schema.** Inspect the actual tables/columns before diagramming. If you can't reach the
   database, diagram only what's provable from the SQL text and **mark inferred elements clearly**.

## Step 1 — get the SQL

Resolve the argument:
- **A file path** → read that file.
- **A database object name** (proc/view/table) → look it up. Prefer a registered DB **MCP tool** if one
  is available in the session; else `sqlcmd`/`psql` **read-only**; else ask the user to paste it. Never
  guess an object's body.
- **No argument** → operate on the SQL in the current file/context, or ask.
- **Multiple objects** → diagram the **relationships between them**, in ONE diagram — not one diagram each.

## Step 2 — run the deterministic extractor

```bash
python <skill-dir>/scripts/sql_to_graph.py --file <path>                       # Mermaid block (default)
python <skill-dir>/scripts/sql_to_graph.py --file <path> --format excalidraw   # native .excalidraw JSON
python <skill-dir>/scripts/sql_to_graph.py --file <path> --format html --title "..."   # self-contained page
python <skill-dir>/scripts/sql_to_graph.py --file <path> --format svg          # self-contained .svg
python <skill-dir>/scripts/sql_to_graph.py --sql "<SELECT ...>" --json         # full graph JSON
```
All five formats (`mermaid` | `excalidraw` | `svg` | `html` | `json`) come from **one deterministic layout**
— same SQL always produces byte-identical output, boxes are grid-aligned, and every label is wrapped to fit
*inside* its box.

**Notation (relational algebra — keep it when narrating):** operations carry the professional symbols
DB engineers already read — `σ` selection (WHERE), `Σ` aggregation (GROUP BY/HAVING, its own pipeline
stage), `π` projection (TOP/ORDER BY), `⋈` join (in the joined table's box), `ρ` rename (a CTE),
`∪`/`∩`/`∖` set operations (annotated on the result). Tables stay symbol-free — the name is the star.
Palette is the skill's own "jewel on ivory" identity (harbor teal / plum / saffron / madder / ink-blue /
viridian) — don't restyle it per diagram.

`--dialect` defaults to `tsql`; pass `postgres`/`mysql`/etc. for other engines. Requires `sqlglot`
(`pip install sqlglot` — pure-Python, no DB driver). **If sqlglot is absent** the script exits with an
actionable message; then hand-parse the SQL yourself and mark every inferred element (per safety rule 2).

The extractor classifies the input and picks the diagram type:

| Input | Diagram type | Extractor emits |
|---|---|---|
| `CREATE TABLE` / schema DDL | `erDiagram` | entities, columns, PK/FK, FK relationships |
| A query, proc, or CTE chain | `flowchart LR` | a strict pipeline: tables `[(T)]` / CTEs `{{CTE: name}}` → ONE `WHERE` box (all ANDed predicates, one per line) → `result` → projection `[/…/]`; join type+key labels ride on the source edges |
| An API/service path ending in a DB call | `sequenceDiagram` | *not structural — you build this from the code path; the extractor won't* |
| A status/lifecycle column | `stateDiagram-v2` | *not structural — you build this from the state values* |

The `sequenceDiagram`/`stateDiagram-v2` cases are judgement, not parsing — build those yourself and say so.
For the two structural cases, **trust the extractor's graph**; your job is narration, not re-deriving nodes.

The extractor returns `confidence` (`high` | `partial`) and an `inferred` list. If `partial`, the SQL
couldn't be fully parsed — surface the `inferred` notes in the output and mark those parts.

## Step 3 — wrap it with narration (your job)

Around the extractor's Mermaid block, add:
- **Above the diagram**: one paragraph explaining what the query/proc is *for* in **business terms** (not
  a restatement of the SQL — the *why*).
- **Below the diagram**: a bulleted list of every source table with a **one-line description** of what it
  holds and why this query touches it. Inspect the real table (MCP/`sqlcmd`) for this — don't invent.
- **Traceability**: the source file path or object name, and a **generation date**.
- **This caveat, verbatim:**

  > This diagram shows the SQL as written, not the execution plan. For performance analysis use the
  > actual execution plan (SSMS Ctrl+M), which reflects what the optimiser actually chose — the two
  > diverge frequently.

## Step 4 — validate before saving

Malformed Mermaid renders as an error block — worse than no diagram. Before writing:
- Confirm the diagram **parses** (the extractor already sanitizes labels — no unescaped `"`/`[`/`]` — but
  if you hand-edited or hand-built the diagram, re-check).
- Common breakages: unescaped parentheses, quotes, and square brackets inside node labels.

## Output rules — `/mermaid-db` (the default)

- Save as a **`.md`** file. Default path `docs/diagrams/<object-name>.md`, overridable by an argument.
- **If the file already exists**, diff against it and tell the user *what changed* — don't silently
  overwrite. (Regenerating on a schema change and showing the delta is the point of Mermaid-as-text.)

## Output rules — `/excalidraw-db` (for human conversation)

Use for a design review / ARB / slide deck. **The extractor emits the `.excalidraw` JSON directly** — run
`--format excalidraw` and save the output as a `.excalidraw` file. No separate drawing skill, no MCP server.
The generator already guarantees what a hand-drawn diagram gets wrong.

**Flowchart (query / proc):**
- **Layout**: a strict left-to-right pipeline — sources → `WHERE` → `result` → projection — on a
  deterministic grid (same-column boxes share an x; columns balanced on one mid-line). **Edges connect
  adjacent stages only**, so an arrow can never cross a box; fan-in arrows land on distinct anchor
  points (never one pile-up).
- **Arrows carry no text**: each join condition is a `⋈ …` sub-line INSIDE the joined table's box —
  in a converging fan a floating label always ends up covering some arrow, so text never floats.
- **One WHERE box**: all ANDed predicates in a single box, one per line — stacked filter boxes read as
  alternative paths, which is wrong.
- **Containment**: every label is a container-**bound** text element that auto-wraps and stays vertically
  centred *inside* its box; box heights are computed from the wrapped line count, so text never overflows.

**ER diagram (schema DDL):**
- **Header + bullet columns**: each entity renders its name as a distinct **header** (bold, larger, in the
  role colour, with a divider rule) and every column as a **bullet-list** item (`•  col  type · PK/FK`) —
  the title never reads as just another column.
- **Arrows never cross a box**: entities are stacked in one column and every FK is routed as an
  **orthogonal elbow through a left-side channel** (out the child's edge → down/up its own lane → into
  the parent's edge). Every segment lives left of the boxes, so on a hub / chain / self-reference the FK
  arrows can never run through — or hide behind — an intervening box (the old grid+straight-arrow bug).
  Arrows are painted **on top** so every FK is unmistakably visible.

- **Canvas**: pure white (`#ffffff`) by default, both outputs.
- **Theme**: Excalidraw `appState.theme` is `"light"` (it re-tints for dark itself if toggled).
- **Determinism**: fixed ids/seeds — regenerating on a schema change produces a clean diff, not a reshuffle.

Then add the narration around it (business context + per-table descriptions + the execution-plan caveat).
If someone wants a **shareable, no-app preview**, `--format html` produces a self-contained page (the SVG
inline + a light/dark toggle) and `--format svg` a standalone SVG. The HTML theme is **fully
attribute-driven**: an inline head script seeds light/dark from the OS once, both themes are defined under
`:root[data-theme=…]` with the full variable set, and there is **no `@media` rule** to fight the toggle —
so the toggle always applies cleanly (no half-applied / black-page state). Zero external requests.

- **Do not maintain both formats for the same artifact.** If a Mermaid diagram already exists for an
  object and the user runs `/excalidraw-db` on it, say so and ask: a one-off review copy, or a replacement?

## The read-only, never-guess discipline (restated because it matters)

- Never run anything that mutates the DB.
- Never assert a table's columns or relationships you haven't verified against the real schema; mark
  anything inferred-from-SQL-text-only.
- If the extractor's `confidence` is `partial` or sqlglot is unavailable, the diagram is best-effort —
  say so in the output, don't present it as authoritative.
