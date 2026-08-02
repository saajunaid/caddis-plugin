---
name: validate-phase
description: Advisory Hub phase validation — consume a phase report, RE-DERIVE its claims independently, and return ACCEPT / ACCEPT-WITH-CORRECTION / REJECT
---

# /caddis:validate-phase — the Advisory Hub validates a phase (never trusts it)

> **THE RULE: re-derive, do not trust.** A phase report is a self-assessment. Reading it and nodding
> makes you a rubber stamp, and a rubber stamp is worse than no check at all — it manufactures false
> confidence. Every step below exists to prevent exactly that. Skipping the re-derivation is the one way
> this command can fail at its actual job while still producing a plausible-looking verdict.

Full methodology, templates, and rationale: the **`advisory-hub`** skill. This command is the thin,
operational driver — run it after an implementing session (usually `/caddis:implement` in Advisory-Hub
mode) has filed a phase report.

## Step 0 — resolve inputs

Use **$ARGUMENTS** if given. Otherwise, find the newest `phase-*.md` file in
`.caddis/advisory-hub-reports/` that has no matching `phase-NN-hub-verdict.md` sibling yet — that is the
one awaiting validation. Read its `PLAN:` and `ADVISORY CTX:` header fields and load both files.

**If no `<slug>-advisory-context.md` exists** for the plan named in the report: say so explicitly, offer
to bootstrap one from the `advisory-hub` skill's §A template, and continue in **degraded mode** — state in
the verdict exactly which checks (§4 locked-decision adjudication, §5 safety-rule re-check) were
unavailable without it. Never silently skip a check without recording that you skipped it.

## Step 1 — read the report once as a document

Before validating a single claim, check the report against itself: does CROSS-REVIEW agree with
DEVIATIONS? Does MODEL/LANE name a vendor's model that doesn't match the claimed lane? On the reference
run this pattern's design was validated against, two of three real findings in one phase came from
exactly this kind of internal contradiction — not from re-checking the code.

## Step 2 — re-derive (the Hub validation checklist)

Run every item in the `advisory-hub` skill's §D checklist yourself:
1. Re-derive every VALUE CHECK using the method advisory-context §3a names — actually run it, don't read
   the reported result.
2. Re-run the exit gates, at minimum the fast ones (unit tests, lint, type-check).
3. `git log` / `git show --stat` the commits — do they match the phase's claimed touches? Anything
   unexpected, especially tooling/config/CI that never appeared in DEVIATIONS?
4. Re-check every rule in advisory-context §5, or record `N/A — none declared`.
5. Flag any deviation that touches a §4 locked decision — this is step 3 below, not your call to make here.
6. Flag any surprise that contradicts the plan's `## Current state` — this is step 4 below.
7. If this milestone boundary ships to a real deployed environment, smoke-test it there, not in dev.

Also apply the `advisory-hub` skill's §E techniques where they fit — mutation-test any seam a new test
claims to prove, and if a cross-review provider timed out, try the other configured provider before
recording "inconclusive."

## Step 3 — adjudicate deviations

For each deviation the report lists: is it a locked decision in advisory-context §4? If so, this is a
**Hub decision, never the implementer's** — rule allowed / reverted / plan amended, and record the reason.

## Step 4 — plan drift

If the report's SURPRISES / CONTRADICTIONS section is non-empty: correct the plan file's
`## Current state` **now, in this step** — do not defer it to a note in the verdict. This is the Hub's
job and the step most likely to be skipped (`advisory-hub` skill §F).

## Step 5 — write the verdict

Write `.caddis/advisory-hub-reports/phase-NN-hub-verdict.md` beside the report, using the `advisory-hub`
skill's §C template in full, including the mandatory **WHAT IS NOW STRUCTURAL** table.

## Step 6 — push every correction into `advisory-context.md`

A correction that lives only in this verdict file dies with the session that reads it; a correction told
to the implementing session dies with that session too, which has already closed. Every correction in
"WHAT IS NOW STRUCTURAL" must actually be landed in the named section of `advisory-context.md` in this
step, not just described.

## Step 7 — update the reports-directory index

Add or update this phase's row in `.caddis/advisory-hub-reports/README.md` (Phase | Report | Verdict |
Outcome | Date).

## Rules

- **Fail closed.** A gate you could not re-run is `NOT RE-RUN`, never `PASS`. A claim you could not
  reproduce is `UNVERIFIABLE`, never `AGREES: YES`.
- **Never accept a claim on the report's own word.** That is the one failure mode this command exists to
  prevent.
- If a cross-review provider times out, try the other configured provider before recording
  "inconclusive" — a single provider's outage is not grounds for skipping independent review.
- **The Hub is not exempt from its own contract.** If a fault traces back to advice the Hub itself gave
  earlier, the verdict says so plainly rather than attributing it to the implementer.
- Read-only toward the implementing session — it has already closed. Corrections land in files
  (`advisory-context.md`, the plan), never fed back to a session that no longer exists.
