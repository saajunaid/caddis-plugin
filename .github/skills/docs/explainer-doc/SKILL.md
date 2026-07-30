---
name: explainer-doc
context: fork
description: Write a document that hands off work to a team who did NOT do the investigation — an external vendor, another team, a contractor — and who must be able to act on it alone. Use when the user says "write a spec for the X team", "document this for someone outside the team", "explainer doc", "implementation spec for a vendor", "hand this off to Y", or is about to write a design doc whose primary reader did not live through the debugging/design process. NOT for internal specs where the reader already has full context (use technical-writing or writing-plans instead) — this is specifically for the "stranger must follow it alone" case.
---

# explainer-doc — write for the reader who has no other context

A spec written by the people who did the investigation is unreadable by the team who must implement
it. The authors compress away the reasoning, so every design choice looks arbitrary, and the reader
either follows it blindly or argues with it. **The fix is not "add more detail" — it is to lead with
*why*, and to make the document survive being read alone.**

Proven in anger on a Genesys→ETL cutover spec handed to an external vendor team. The user's verdict:
*"nailed it — the document was perfect, simple, this should be the standard for explainer documents."*
Reference implementation to study: `serve-sight/docs/genesys-cutover/etl-implementation-spec.md` (full
spec) and `pega-cticallid-change-request.md` (the same pattern compressed to one page for a single ask).

## When this is NOT the right skill

If the reader already lived through the investigation (a teammate, your future self, an internal
handoff with shared context), use `technical-writing` or `writing-plans` instead — those are lighter
and don't need the "assume zero shared context" discipline below. Reach for `explainer-doc` specifically
when the reader is a **stranger to the problem**: an external vendor, a different team, a contractor,
anyone who will act on the document with no one in the room to ask.

## The shape — in order. The order IS the pattern

Do not reorder these. Each section's position is load-bearing: later sections lean on earlier ones for
their justification, and a reader working top-to-bottom needs the "why" before the "what."

| § | Section | Why it must come here |
|---|---|---|
| 1 | **Why this exists** — what broke, in a diagram | Every later decision is justified by this. Lead with the failure, not the solution. |
| 2 | **What we're asking for, in one picture** + a size table | The reader decides here whether the ask is reasonable. Include what you are explicitly **not** asking for. |
| 3 | **Understanding the source data** — the 3-5 things that catch people out | Each one should have already caused a real bug. Not a data dictionary. |
| 4 | **The one thing that matters most** | Usually not the new build. Say so plainly, with the number that proves it. |
| 5 | **Where it runs** + access needed | The blocker nobody writes down until the first deploy fails. |
| 6 | **What to build**, with the reasoning *beside* each choice | Not in an appendix. Next to the DDL / the query / the config. |
| 6b | **Changes to what already exists** | Always under-specified. Ask "what did I only half-mention?" — this is where the gaps hide. |
| 7-8 | The actual implementation (extract/build queries, load procedure, etc.) | |
| 9 | Schedule / retention / first load | The one-off backfill is always forgotten. |
| 10 | **Validation, with EXPECTED VALUES** | "Run this, expect ~64%" beats "verify the data." |
| 11 | Priority · acceptance (who signs off) · **what we excluded** | The exclusion list stops speculative building. |
| 12 | **Glossary** | Every acronym, inline. Not a link. |

Adapt section names to the domain (this table is ETL-flavored from its origin; a UI handoff, an API
contract, or an infra runbook will rename §6-9) — but keep the **order and the intent of each slot**.

## The ten rules

1. **Self-contained.** If the reader needs another document to follow this one, the document has
   failed. Companions are optional background, stated as such — never load-bearing.
2. **Lead with the failure mode, not the solution.** State what actually went wrong, concretely, before
   proposing anything. Everything cautious later inherits its justification from that paragraph.
3. **Reasoning beside the artefact, not in an appendix.** "Cluster on the date not the GUID" with the
   3-row comparison table right there. An appendix is never read.
4. **Every number carries its measurement date and a way to reproduce it.** "1.4% of reality (measured
   2026-07-14, `SELECT ...`)" — not "a small fraction."
5. **Say what you are NOT asking for.** Prevents speculative work and pre-answers "why not X?" before
   it's asked.
6. **Name what is not the reader's fault.** If a gap traces to a third system or a decision made
   elsewhere, say so explicitly. Saves the reader a week of misdirected chasing and buys credibility for
   the rest of the document.
7. **Diagrams for the shape, tables for the detail, prose only for judgement.** No diagram should repeat
   what a table already says better.
8. **Validation states expected values.** "It ran" and "it is right" must be two different checks — give
   the reader the number to compare against.
9. **Route by owner.** If an item belongs to a third team, mark it as theirs, explicitly, in the document
   — don't let it read as part of the reader's scope.
10. **Glossary inline.** The reader will not follow a link mid-implementation; every acronym gets defined
    where it's used, plus a glossary section as the fallback lookup.

## Process

1. **Confirm the reader.** Ask (or infer from context) who this is actually for and how much they
   already know. If they have real shared context, stop and suggest `technical-writing`/`writing-plans`
   instead — this skill's discipline is overhead they don't need.
2. **Draft §1 first, alone, and get it right before writing anything else.** Every other section's
   justification traces back to it. If you can't state the failure mode plainly and concretely, the
   rest of the document will inherit that vagueness.
3. **Write the shape table above as your outline**, adapting section names to the domain, then fill it
   in top to bottom. Keep reasoning next to the artefact it justifies (rule 3), not in a separate
   "design decisions" section.
4. **Before sending, ask the two questions below** — they are an exit gate, not a suggestion.

## The two-question exit gate

Ask both, honestly, before the document ships:

- **"Could someone who has read nothing else follow this end to end?"** If the answer requires "well,
  they'd also need to know X" — X is either missing or should be a stated, explicit companion doc.
- **"What did I mention once and never specify?"** This is the question that surfaces the gaps — in the
  origin case it found an entire missing section (§6b, changes to existing infrastructure) that had been
  gestured at once and never actually written.

If either question fails, fix the document — don't ship it and hope the reader asks.
