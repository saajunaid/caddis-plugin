---
description: End-of-session handoff — capture exact state so the next session resumes with zero re-discovery
---

# /handoff — stop cleanly, write the resume doc

You are ending a work session. Produce/refresh the resume doc (`.caddis/relay.md`) so the next session
(you, a future you, or another agent on any tool) can resume immediately. This is the anti-context-rot checkpoint.

## Step 1 — capture learnings FIRST (knowledge-transfer)
**Before** gathering git signals or writing relay.md, decide on `knowledge-transfer` — and the default
is to run it.

- **Trigger (default ON):** if this session's `git diff` touched any code or config, OR you debugged
  anything / proved a non-obvious behavior → you **MUST** dispatch the `knowledge-transfer` subagent first.
- **Skip ONLY if** the session was purely read-only, design/planning, or discussion — nothing was built,
  fixed, or proven. When in doubt, dispatch. "I already wrote some docs by hand" is **not** a reason to
  skip — the subagent routes/consolidates across the right files and catches what you'd miss.
- It writes durable findings (root causes, workarounds, constraints, rejected approaches) into the right
  AGENTS.md (the canonical rules file) / instructions / runbooks. Docs only — never code.
- **Record the outcome** in relay.md's `## Learnings captured` line (below). A skip must state its reason.

## Step 2 — gather verified signals (don't guess)
```
git status --short
git branch --show-current
git log --oneline -5
python scripts/caddis_inventory.py          # what EXISTS — do not compose this from memory
```
Then read the active plan in `.caddis/plans/` (falling back to legacy `.github/plans/` if present) and its tracker.

**Read the inventory before writing anything.** It enumerates plans, PRDs, prompts, handoffs, KB
notes, the parking-lot backlog, open comms, every script and its purpose, and any generated artefact
committed before its generator last changed. Paste the parts a next session needs; do not retype
them from memory.

**Why this step is mechanical.** A handover used to be composed from what the outgoing session
remembered, so it was only ever as complete as that memory. Bringing one Hub to a usable state took
nine corrective round trips and the user caught six of them — including *"the handover listed no
reports, documents, KB notes or scripts"*. None of those are judgement calls; every one is a
directory listing. An agent recalls **what it did**; a generator enumerates **what exists**, and
those are different sets. Your judgement is still needed for what matters and what to do next —
that half cannot be derived and is the only half you should be writing.

**Crash / interrupted-work check.** Cross-check the tracker against `git status` + `git log`: if a phase is
marked in-progress but has **uncommitted changes** (work left mid-flight), or a phase is marked done with
**no commit** to back it, the last session was interrupted. Say so explicitly in `## Next step` ("resume
mid-phase N — `<files>` left uncommitted; re-run its tests first") so the next session doesn't assume a
clean phase boundary and lose or double-do the work.

**Digression check.** If this session abandoned a mid-flight plan for a *different* one (relay.md or the
tracker shows plan A in progress, but the work moved to plan B), suggest the user run `/digress` to park
plan A on the workstream stack — so its exact resume point survives and `/resume` can pop it back later.

## Step 2b — Advisory-Hub handoff audit (conditional — skip silently if not applicable)

**Trigger:** the active plan found in Step 2 has a sibling `<slug>-advisory-context.md`. **No such file
→ skip this step entirely and silently** — no extra work on an ordinary handoff.

> **First, say which command the user actually wants.** A context doc means a Hub is running, and
> handing over a Hub is `/caddis:spawn-hub`, not this command. The two look interchangeable from
> outside and are not: `/handoff` writes a resume doc for the same workstream, while `spawn-hub`
> ends the Hub's tenure, runs the mechanical audit, conserves the carried-open ledger, and files
> `hub-NN.spawn.md` in `.caddis/advisory-hub-reports/`. Tell the user plainly, then continue only if
> they still want a plain handoff.

**Why it is a distinct step:** a context doc is written *before* the work happens, so it is **always
stale by the time it is needed**. The outgoing Hub's instinct is always "yes, this doc is designed for
exactly this" — **that instinct has been measured and found wrong**: a real audit found seven gaps in a
context file the outgoing Hub believed was current, including the single highest-value technique the Hub
had developed by then.

**Do not ask "are there gaps?" Assume there are, and find them mechanically** (full detail: the
`advisory-hub` skill's §G):
1. **List every technique, decision, and correction you actually used this session** — from your own
   actions in this transcript, not by re-reading the context doc.
2. **For each, check whether the context doc's instruction itself already covers it** — not whether the
   word appears. Would a fresh Hub, reading only that file, be told to do the same thing?
3. **The caveat that will burn you:** a literal-string grep over prose produces **false MISSINGs**. A
   `0 matches` result means "this exact string isn't here," not "this isn't covered." **Read the section
   before believing a 0-match grep.**
4. **Land every real gap as a durable rule** in the right section of the advisory-context, carrying the
   specific failure that earned it — a note left for later is not a fix.

Record the outcome in relay.md's `## Learnings captured` line (below).

## Step 3 — write the resume doc (overwrite) with exactly these sections
> **Where to write:** solo / single active branch → `.caddis/relay.md` (default).
> **Team / parallel branches** → write `.caddis/relay/<current-branch>.md` instead, so two
> developers never merge-conflict on one shared relay doc. The SessionStart hook prefers the
> per-branch file automatically when it exists, then `.caddis/relay.md`, then the legacy
> `.claude/relay/<branch>.md` and root `relay.md` (back-compat during the migration).
>
> A repo still on the pre-rename `.claudster/` won't see this relay until it's converted —
> `/caddis:migrate-dir` does that.

```markdown
# Relay — <feature>
**Updated:** <ISO timestamp>

## Current workstream
<Active plan path + which phase. One line on the goal.>

## Done (this session / across sessions)
- <evidence-backed bullet — cite file/commit, only what's actually complete>

## Next step (exact)
<The single next action. Include the command/phase. Add a fallback if blocked.>

## Read first on resume
- `<path>` — why it matters
- `.caddis/plans/<feature>.md` — the plan + tracker

## Validation state
<Commands run this session and their result: pass / fail / not-run. Be honest.>

## Open questions / blockers
<Decisions needed, ambiguities, anything unverified. "None" if truly none.>

## Learnings captured
knowledge-transfer: <✓ ran → files written | ✗ skipped → reason>
advisory-context audit: <N candidates → M gaps → landed in <path>> | n/a (no advisory-context for this plan)

## Resume prompt
\`\`\`
Read relay.md, then the plan it points to. Continue from <phase/step>. Next action: <exact>.
\`\`\`
```

## Step 4 — tidy finished artifacts
Flip any plan/prompt's frontmatter `status:` to `done` (or `superseded`) if this session actually
finished it — that is your judgment call; the script below never makes it and never auto-flips
status. Then run:
```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_tidy.py" --apply
```
(falls back to `scripts/caddis_tidy.py` from a source checkout). **If the script is missing,
skip this step** — it degrades open, same as the other machine gates; an older install must not
be blocked by a script it does not have. Include its report in your output. A **collision**
(`done/<name>` already exists) is reported by the script, not fatal — surface it, do not fail the
handoff over it.

## Step 5 — check the handover you just wrote

```
python "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_gate.py" handover-check --doc .caddis/relay.md
```
(falls back to `scripts/caddis_gate.py` in a source checkout; degrades open when the script is
missing.) **Run it in the repo the handover is about** — a handover describing another repo will
report that repo's paths as missing, which is the tool being right about the wrong question.

It fails when the handover names a file that does not exist. The incoming session has **no other
source** for those paths, so it cannot tell a typo from a real file: one live handover sent an
incoming Hub looking for a prompt that was never written. Fix what it lists, then re-run.

It also notes any generated artefact committed before its generator last changed. That is advisory,
not blocking — but do not quote a report the note names without rebuilding it first.

## Rules
- **One next action, by priority ladder.** `## Next step` names exactly ONE action — not a menu. Pick it in
  order: (1) interrupted mid-phase work → finish + commit it; else (2) the active plan's next not-started
  phase; else (3) the top open question/decision. Everything else is context, not the next step.
- Only verified facts and real paths. Mark anything unconfirmed as `Unknown`.
- Update the plan's tracker rows too (status + last commit) — relay and tracker must agree.
- Don't commit unless asked. Report where `relay.md` was written and the one next action.
- **Never hand off a Hub session on the strength of "the context doc is designed for this."** That is the
  one instinct that has been measured and found wrong. Run Step 2b's audit instead.
- **Prune the Done section — two rules, both apply:**
  1. **Merge-based:** Phases already merged to `main` (confirmed by a tag or commit) must be compressed
     to a single line: `- **RW-N**: merged to main as vYYYY.MM.DD.N (<commit>) ✅`. Only the current
     in-progress phase keeps detailed bullets.
  2. **Count-based:** The Done section must contain at most **8 bullets total** after writing. If there
     are more, collapse the oldest into one summary line:
     `- [N prior milestones — see git log for full history]`
     Keep the 8 most recent bullets below it.
  Target: relay.md stays under ~80 lines on disk. inject_relay.py caps injection at 120 lines as a
  safety net, but the file itself should never reach that ceiling.
