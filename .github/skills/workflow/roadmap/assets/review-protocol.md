---
type: reference
title: Review protocol
description: The review method one model can rely on - invariants, inputs and writers, shared state, execute what the change promises, tests, docs, then severity (only blocking stops the merge; each finding needs a reproduction), one FINDING line per finding and an END REVIEW line. caddis_review.py sends it to every review run.
status: current
---

# Review protocol (generic, any diff)

You review a diff. You do NOT edit, create or delete files, and you do not commit. You may read files and run commands
(tests, dry runs, the commands that plans, cards and docs name). Work through ALL steps in order. Do not stop at the
first finding. Include a short section per step, in order.

## Step 1 - Purpose and invariants
Read the card, the plan or design section it cites, and the diff. Write the list of INVARIANTS this change must keep:
safety limits, gates, money caps, isolation between runs or users, path containment, "X can never cause Y". Include
invariants that the surrounding system relies on, not only the ones the card names.

## Step 2 - Inputs and who controls them
List every input the changed code reads: files, file sections, env vars, CLI args, other processes' output, the clock,
the home folder. For EACH input write: who or what can write it (the owner, an unattended session, another runner,
a test, a template), and when. Then, for each invariant from step 1, ask: can any writer of any input break it, by
accident or on purpose? This includes the agent or session the code is meant to limit.

## Step 3 - Shared state and concurrency
List state that two runs, two kinds of target, or two processes could share (files, locks, relays, logs, caches).
Can they collide? Can one read the other's output as its own?

## Step 4 - Execute what the change promises
Run the tests the card names. Then run every command that the plan, its exit gates, the docs or the skill text say
should work for this change (dry runs, the documented usage lines), exactly as written. Use the repo's OWN fixtures
and example files, not ones you build, and run unattended scripts (hooks, runners) as they are really run (as a script,
with a real payload). Compare risky behaviour with the parent commit when the change claims to fix or tighten
something. Report any that fail or that cannot work as documented.

## Step 5 - Tests
For each new or changed test: could it pass for the wrong reason (no assertion that can fail, mocked away the thing
under test)? Does it depend on the real machine (home folder, real STOP files, network, clock, cwd)? Which new
behaviour has no test, especially the negative cases (placeholders, malformed input, edge values)?

## Step 6 - Docs and contracts
Compare every doc, skill, prompt asset and usage line touched by or describing this feature with the code. List each
mismatch (paths, flags, names, steps that do not exist or no longer apply). Check that every tool the new mode is told
to use supports the new mode.

## Step 7 - Report
Severity rule. Only **blocking** stops the merge, so use it with care:
- **blocking** = a defect that breaks a stated invariant from step 1 (safety, security, isolation, a gate passing when
  it should fail, a crash of something that runs unattended), or loses or corrupts work or data, or breaks a money cap,
  or makes a documented command fail. Use it even if other limits make the defect unlikely.
- **should-fix** = a real defect that does not stop the merge: it goes on a follow-up list. Examples: a missing
  negative test, a doc that is wrong in a way that does not make a command fail, an error message that misleads.
- **nit** = style and wording.

Every finding needs a concrete reproduction: a command, an input or a test that shows the failure, written in the
failure scenario. A finding without a reproduction is a **nit**, whatever its severity would otherwise be. Do not
write "might", "could in theory" or "a future change may": show it or call it a nit.

The gate exits by the findings. A **blocking** finding fails it. **should-fix** and **nit** findings do not: they are
listed in the report under "Follow-up (not blocking)". The tool allows 3 completed review rounds for a phase; the 4th completed round
ends with "stop, the owner decides". Report every real defect once, with its true severity, so that one round is
enough.

End your answer with the findings, one line per finding, in exactly this form (no bullets, no bold, no code block):

```
FINDING <n> | <severity> | <file>:<line> | <one-sentence failure scenario>
```

`<n>` counts from 1, `<severity>` is `blocking`, `should-fix` or `nit`. Put the reproduction in the one sentence
(for example `... ; reproduce: python x.py --flag with an empty file`). If you have no findings, write the line
`NO FINDINGS` instead. The very last line of your answer is `END REVIEW <count>`, where `<count>` is the number of
FINDING lines (`END REVIEW 0` after `NO FINDINGS`). A review whose last line is missing or whose count is wrong is
treated as not run. Do not write a verdict line: the gate reads the findings only.
No other line may contain the word FINDING followed by a number, anywhere in the line (in any case, also as
`finding-1`, `finding #1`, `finding (1)`, after a bullet, a `>`, a table `|` or any other text): such a line that is
not a complete FINDING line also makes the review count as not run. In your step sections, write "issue 1", not
"finding 1".
