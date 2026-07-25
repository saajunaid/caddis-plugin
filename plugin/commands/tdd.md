---
description: Run a strict red-green-refactor TDD cycle for a unit of behavior
argument-hint: <behavior to build>
---

# /tdd — red → green → refactor

Build this behavior test-first: **$ARGUMENTS**

If empty, ask what behavior to build and stop. Read the relevant `AGENTS.md` (root + the folder you'll
touch, e.g. `tests/AGENTS.md`) before starting.

## The cycle — do not skip or reorder

**1. PLAN the cases.** List happy path, edge cases (empty/None/boundary), and error cases. One line each.

**2. RED.** Write the *first* failing test (or a tight parametrized set). Run it. Confirm it fails — and
fails for the *right reason* (asserts the missing behavior, not an import typo). Show the failure output.
> If it passes immediately, the test is wrong or the behavior exists — stop and reassess.

**3. GREEN.** Write the **minimum** code to pass. No extra features, no speculative abstraction. Run the
test. Show it green.

**4. REFACTOR.** Improve names/structure/duplication in both code and test while keeping green. Re-run.

**5. Repeat** for the next case until the behavior is complete.

**6. VERIFY.** Run the full relevant suite so you didn't regress anything. For heavier coverage or a UI
layer, dispatch the **tester** subagent.

## Rules
- Never write production code with no failing test demanding it.
- Test behavior, not internals. Assert what a caller observes.
- Each test independent; shared setup in fixtures.
- Show real command output at RED and GREEN — don't claim a state you didn't run.

End by stating: cases covered, final command run + result, and whether a commit is warranted.
