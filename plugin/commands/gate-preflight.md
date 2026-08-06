---
description: Deterministic headless preflight — validates a plan against the actual codebase, self-contained (never depends on a skill activating)
argument-hint: <path to plan.md>
---

# /caddis:gate-preflight — headless plan-vs-codebase validation (self-contained)

Validate the implementation plan at **$ARGUMENTS** against the ACTUAL codebase before any code is
written.

This command exists because `/caddis:preflight` is a model-invoked `context: fork` **SKILL**, and
skills do not reliably activate under headless `claude -p` — proven live (2026-07-08): a run saw
the raw `/caddis:code-review <sha-range>` text, didn't recognise it, and replied "I don't see a
specific task in your message." No review happened. This command spells the task and criteria out
inline instead, so the check always happens whether or not the skill fires.

**What to do:** read the plan, then verify every technical claim with your tools — do the file
paths it cites exist (or are they correctly marked new)? Do referenced functions/classes/types
exist with the exact names (grep them, don't trust the plan's spelling)? Do API/route shapes and
data fields match what the codebase actually returns? Are required dependencies installed or
explicitly scheduled for installation in an earlier phase? **A claim you cannot verify is a
finding, not a pass.**

If a `preflight` skill is available, use its methodology as a nudge — its 8-category framework is
more thorough than the paragraph above. But do not wait on it or treat it as required: the check
above is enough to produce a real verdict on its own.

## HEADLESS RUN RULES (mandatory)
- **Non-interactive. No human is present. NEVER ask a question.** Where the plan leaves a genuine
  gap, that is itself a finding — note it and keep going.
- **READ-ONLY.** Do NOT write or edit any code. Do NOT switch branches. Do NOT commit.
- A plan **PASSES** only with zero blocking discrepancies.

End with EXACTLY one line and nothing after it: `PREFLIGHT: PASS` or `PREFLIGHT: FAIL`.
