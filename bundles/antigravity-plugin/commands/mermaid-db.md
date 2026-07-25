---
description: Turn a SQL artifact (proc, view, query, .sql file, or table name) into a Mermaid diagram that explains it — git-diffable, saved as .md
argument-hint: [file path | object name | pasted SQL] [output path]
---

# /mermaid-db — diagram a SQL artifact as Mermaid

Explain a SQL artifact to a human as a **Mermaid** diagram (the default format: plain text, diffs cleanly
in git, renders natively in VS Code and Gitea, regenerable when the schema changes).

Input: **$ARGUMENTS**

## Do this

Load and follow the **`db-diagram`** skill end-to-end. In short:

1. **Get the SQL** — from a file path, a DB object name (look it up via a DB MCP tool if available, else
   read-only `sqlcmd`/`psql`, else ask), the current file in context, or pasted SQL. Multiple objects →
   ONE diagram of their relationships.
2. **Extract deterministically** — run the skill's `scripts/sql_to_graph.py` (sqlglot-based) to get the
   typed node/edge graph + a Mermaid skeleton. Don't hand-derive the nodes when the script can run.
3. **Narrate** — add a business-terms paragraph above, a per-source-table description list below, the
   source path/object name, a generation date, and the execution-plan caveat (verbatim, per the skill).
4. **Validate + save** — confirm the Mermaid parses; save as `.md` (default `docs/diagrams/<object>.md`,
   overridable by a second argument). If the file exists, **diff and report what changed** — never
   silently overwrite.

## Rules (from the skill — non-negotiable)

- **Read-only.** Never run DDL/DML. The extractor only parses SQL text.
- **Never guess schema.** Verify tables/columns against the real DB; mark anything inferred-from-SQL-only.
- If the extractor reports `partial` confidence (or sqlglot is missing), say so — the diagram is
  best-effort, not authoritative.
