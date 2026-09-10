---
name: gate-review
description: Deterministic headless code review — adversarial diff review, self-contained (never depends on a skill activating)
---

# /caddis:gate-review — headless adversarial code review (self-contained)

> **On Claude Code, prefer the native `/code-review`.** It is a command, not a skill, so it always
> fires — including headless — and it has grown capabilities this one does not have: effort levels
> (`low`…`max`), an `ultra` mode that runs a multi-agent review in the cloud, `--comment` to post
> findings as inline PR comments, and `--fix` to apply them to the working tree. Reach for it first.
>
> This surface remains because caddis ships to harnesses that have **no** native equivalent — agy,
> Codex and Copilot. There it is the only review you get. Do not delete it to tidy up Claude Code.
>
> `/caddis:cross-review` is NOT replaced by either. It sends the diff to a **different vendor's**
> model, which neither this nor the native reviewer can do.

Perform an adversarial code review of **$ARGUMENTS** (a git range, e.g. `abc123..HEAD` — defaults
to the current working diff when empty).

This command exists because `/caddis:code-review` is a model-invoked `context: fork` **SKILL**, and
skills do not reliably activate under headless `claude -p` — proven live (2026-07-08): a run saw
the raw `/caddis:code-review <sha-range>` text, didn't recognise it, and replied "I don't see a
specific task in your message." No review happened. This command spells the task and criteria out
inline instead, so the review always happens whether or not the skill fires.

**What to do:** inspect the diff (`git diff $ARGUMENTS`, and `git show <sha>` per commit as
needed) and read the changed files in full context, not just the diff hunks. Judge, in priority
order:
1. **Correctness** — logic bugs, wrong results, missed edge cases.
2. **Tests** — would a test actually fail without this change; are the stated behaviors covered.
3. **Security** — injection, auth gaps, secret exposure, unvalidated input.
4. **Conventions** — the repo's `AGENTS.md` rules (canonical; `CLAUDE.md` is an `@AGENTS.md` shim).
5. **Simplicity** — unneeded abstraction, scope creep beyond what the diff needed to do.

Classify each issue as **blocking** (must fix before merge), **should-fix**, or **nit**.

If a `code-review` skill is available, use its methodology as a nudge. But do not wait on it or
treat it as required: the checklist above is enough to produce a real verdict on its own.

## HEADLESS RUN RULES (mandatory)
- **Non-interactive. No human is present. NEVER ask a question.**
- **READ-ONLY.** Do NOT edit code. Do NOT commit. Do NOT switch branches.
- Report only; do not fix — that is a different session's job.

End with EXACTLY one line and nothing after it: `REVIEW: CLEAN` (no blocking issues) or `REVIEW: BLOCKING` (one or more blocking issues).
