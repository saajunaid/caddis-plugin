---
name: writing-plans
description: Use when you have a spec or requirements for a multi-step task, before touching code. In caddis, plans are written with /caddis:feature-plan, the only plan writer; this skill sends you there.
---

# Writing plans

Plans in caddis are written with **`/caddis:feature-plan`**. It is the only plan writer. Run it with the
feature description, the spec path or the PRD path:

```
/caddis:feature-plan <feature, spec path or PRD path>
```

Do not write a plan by hand from this skill. `/caddis:feature-plan` writes the plan to
`.caddis/plans/<feature-slug>.md`, where handoff, resume, `/caddis:implement` and the Tracker read it. It
gives each phase a model, a `Lane:` and an `Execution: inline | per-task` line. For a `per-task` phase it
writes each task with `Files:`, `Interfaces:` and its TDD steps. It also writes Global Constraints, a
Review Focus list and runs a self-review.

To run the plan, use `/caddis:implement <plan path>`.

The plan file's header follows `.github/instructions/document-frontmatter.instructions.md`;
`/caddis:feature-plan` writes it.

This skill was once a copy of obra/superpowers `writing-plans` (MIT). Its ideas now live in
`/caddis:feature-plan` and `/caddis:implement`; see NOTICE.md and `.github/upstream-sources.json`.
