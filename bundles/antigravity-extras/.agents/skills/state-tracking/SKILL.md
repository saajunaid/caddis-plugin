---
name: state-tracking
context: fork
description: "USE THIS SKILL when an agent needs to maintain a living record of task progress across multiple sessions or hand-offs. Covers append-only audit logs, CURRENT_STATE head-of-line pattern, relay hand-off protocol, and recovery from mid-session interruptions. Works in both generic and junai-pipeline modes."
---

# State Tracking Skill

## When to Use

Load this skill when you are:

- Running a multi-session implementation where work spans more than one chat context
- Handing off to another agent mid-plan and need to capture exactly where you stopped
- Working on a long task where context compaction may occur
- Recovering from an interrupted session and need to reconstruct current state

---

## The Two-Document Pattern

State tracking uses two distinct documents with different write semantics:

| Document | Write mode | Purpose |
|----------|-----------|---------|
| **Plan Tracker** (`.github/plans/tracker/<slug>-tracker.md`) | Overwrite each row | Per-phase completion record, linked to commits |
| **CURRENT_STATE** (`.github/agent-docs/CURRENT_STATE.md`) | Overwrite head section | Single-view of right now: what phase, what's done, what's blocked |
| **Session Log** (inline in CURRENT_STATE, append-only) | Append only | Chronological audit trail — never rewrite past entries |

Never mix them: the tracker is the long-term ledger; CURRENT_STATE is the working note.

---

## CURRENT_STATE.md — Head-of-Line Pattern

The CURRENT_STATE document has two sections:

### Section 1: Current Status (overwrite on every update)

Replace this section wholesale each time:

```markdown
## Current Status

**Plan:** `.github/plans/<feature-slug>.md`
**Tracker:** `.github/plans/tracker/<feature-slug>-tracker.md`
**Last updated:** YYYY-MM-DDTHH:MM:SSZ
**Active agent:** @[Agent] (model: [Model])
**Current phase:** Phase N — [Name]
**Phase status:** [Not started | In progress | Blocked | Complete]

### What is done
- Phase 1 ([Name]): complete — commit `abc1234`
- Phase 2 ([Name]): complete — commit `def5678`

### What is in progress
- Phase 3 ([Name]): step 2 of 5 — [short note on current step]

### What is blocked
- [blocker description, or "nothing"]

### Next action
[One sentence: exactly what the next agent session should start with]
```

### Section 2: Session Log (append-only)

Append one entry per session, never edit past entries:

```markdown
## Session Log

### [YYYY-MM-DDTHH:MM:SSZ] — @[Agent] (model: [Model])
**Phase covered:** Phase N [partial | complete]
**Commits:** `abc1234` (phase(3): [Name] complete)
**Stopped at:** [exact description of stopping point]
**Handoff note:** [any context the next agent needs]
---
```

---

## Relay Hand-off Protocol

When you are about to end a session mid-plan:

1. **Complete the current atomic unit** — do not stop at a half-edited file. Reach the next clean commit point.
2. **Update CURRENT_STATE.md:**
   - Rewrite the "Current Status" section with the exact stopping point.
   - Append a new entry to the Session Log.
3. **Update the plan tracker** — mark your current phase's row with `In Progress` if incomplete, or `Complete` if you just finished it.
4. **Commit both files** with the current phase commit or as a separate `chore(state): update CURRENT_STATE` commit.
5. **State the hand-off note** in the session log and in your final reply — the next agent must be able to read CURRENT_STATE.md and know exactly where to start.

---

## Recovery Protocol

When starting a session on a plan that has a CURRENT_STATE.md:

1. Read `.github/agent-docs/CURRENT_STATE.md` — Current Status section first.
2. Read the last entry in the Session Log to understand what the previous session did.
3. Read the plan tracker row for the current phase.
4. Confirm the stated commit exists: `git show <commit> --stat`.
5. Start from **"Next action"** in the Current Status section.
6. Do NOT re-run phases that are marked Complete in the tracker unless the user explicitly asks you to.

---

## Template: CURRENT_STATE.md

The canonical template is at `.github/agent-docs/CURRENT_STATE.md`. Copy it for new plans or use it as the single shared state file (overwriting the Current Status section each session).

---

## Integration with Golden-Plan

When running a golden-plan:
- The plan tracker (`.github/plans/tracker/<slug>-tracker.md`) is the commitment ledger.
- CURRENT_STATE.md is the working scratch-pad for the current session.
- After completing a phase, update BOTH the tracker row AND the CURRENT_STATE current-status section.
- When all tracker rows are `Complete`, follow the Plan Completion Protocol in golden-plan: move the plan to `plans/done/`, set `status: done`.

---

## Standing Rules

1. **Never rewrite past Session Log entries** — the log is append-only. Corrections go in the next entry.
2. **One CURRENT_STATE per active plan** — if running two plans in parallel, use two separate state files named `CURRENT_STATE-<slug>.md`.
3. **CURRENT_STATE is not the tracker** — do not put commit hashes or gate results in CURRENT_STATE; they belong in the tracker. CURRENT_STATE is for human-readable context.
4. **Commit state files** — CURRENT_STATE updates must be committed, not left as unstaged changes.
