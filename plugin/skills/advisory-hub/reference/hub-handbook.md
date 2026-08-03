# Advisory Hub — how the Hub actually validates — verdict template, checklist, techniques, plan drift

> **Loaded by:** `/caddis:validate-phase` Step 2
>
> Reference for `.github/skills/workflow/advisory-hub/SKILL.md`. The core card carries the
> model; this carries the detail for one moment of use. Every rule here was earned by a
> specific failure — the failure is stated alongside it, so a later reader can tell a hard-won
> rule from an opinion.

---

## §C — the Hub verdict

```
=== HUB VERDICT — PHASE <n> ===
REPORT:        .caddis/advisory-hub-reports/phase-NN.report.md
VALIDATED BY:  <hub session model/lane> on <ISO 8601 UTC>
VERDICT:       ACCEPT | ACCEPT-WITH-CORRECTION | REJECT

--- RE-DERIVATION (what the HUB ran itself, not what the report said) ---
CLAIM:     <…>
HUB RAN:   <the literal command the Hub executed>
HUB GOT:   <…>
AGREES:    YES | NO | UNVERIFIABLE — <why>          (repeat per claim)

--- GATES RE-RUN ---
$ <command>
<output>
RESULT: PASS | FAIL | NOT RE-RUN — <why>

--- COMMITS AUDITED ---
$ git show --stat <sha>
MATCHES THE PHASE'S CLAIMED TOUCHES: YES | NO — <what was unexpected>

--- SAFETY-RULE RE-CHECK ---
<per rule in advisory-context §5, or N/A — none declared>

--- DEVIATIONS ADJUDICATED ---
<deviation> → touches locked decision <#>? YES | NO
           → Hub ruling: allowed | reverted | plan amended — <reason>

--- PLAN CORRECTIONS LANDED ---
<what was edited in the plan file itself, section by section — or NONE>

--- CORRECTIONS REQUIRED BEFORE THE NEXT PHASE ---
1. <exact fix, not a direction>

--- WHAT IS NOW STRUCTURAL ---            (MANDATORY — a verdict without this is incomplete)
| Correction | Where it now lives (file + section) | The failure that earned it |
|---|---|---|

NEXT PHASE MAY START: YES | NO
=== END VERDICT ===
```

**Where does a correction live so it cannot recur?**
- **Telling the implementing session** — worthless. That session ends and the lesson dies with it.
- **Putting it in the next phase's prompt** — barely better. It works once, and the Hub must remember to
  repeat it every phase. It won't, eventually.
- **Putting it in the durable artifact** (`advisory-context.md`) — correct. It binds every future phase
  whether or not anyone remembers it, and it carries the failure that earned it so a later reader knows
  why it exists rather than deleting it as noise.

**A verdict that does not end in "what is now structural" is half a verdict.** And **the Hub is not
exempt from its own contract**: if a correction traces back to advice the Hub itself gave earlier, the
verdict says so plainly rather than attributing it to the implementer.

---

## §D — Hub validation checklist

1. **Re-derive every VALUE CHECK.** Run the re-derivation yourself. Do not read the reported result.
2. **Re-run the exit gates**, at minimum the fast ones (unit tests, lint, type-check). Reported output can
   be stale even when it was honestly captured.
   **And re-run them in a DIFFERENT ENVIRONMENT from the implementer's** — see §E's
   "re-running a gate identically is not independent verification". Re-running the same way
   reproduces the blind spot instead of testing it. This is the sharpest known limit on the
   Hub's one rule, and it cost a failed production deploy to learn.
3. **`git log` / `git show --stat` the commits** — do the changes match the phase's claimed touches?
   Anything unexpected, especially tooling/config/CI files that never appeared in DEVIATIONS?
4. **Re-check every rule in advisory-context §5** — or record `N/A — none declared`.
5. **Any deviation** → is it a §4 locked decision? If so it is the Hub's call, not the implementer's.
6. **Any surprise** → does the plan's `## Current state` need correcting? Correct it **now, in the plan
   file** (§F).
7. **Deployed-environment smoke test at milestone boundaries** — against the environment the change
   actually ships to, not dev. Skip cleanly when the project has no deployed environment.

---

## §E — Hub techniques that actually catch things

### Re-running a gate *identically* is not independent verification

The Hub's rule is "re-derive, don't trust". Its sharpest limit: **re-deriving the same way
reproduces the implementer's blind spot instead of testing it.**

Worked example. A Hub accepted a milestone partly on *"gates genuinely ran — I re-ran the test
suite myself, 310 passed."* The very next deploy failed on that same suite. A dependency-injected
service built a database client **before request validation ran**, so an invalid query parameter
returned 500 instead of 422 — but *only on the CI runner*, because the local env file is
gitignored and every developer machine supplied it. Implementer green. Hub green. CI red.

> **The rule:** for any phase touching config, a data-store seam, or a dependency-injection
> boundary, re-run the gate under the *deprived* environment, not just again.
> `mv <env file> aside && <test command> && mv back` is a one-step runner reproduction.

Two corollaries, both earned:
- **A regression test for this class must not depend on ambient environment.** The test that broke
  CI was structurally incapable of catching its own bug locally. Its replacement monkeypatches the
  dependency to raise, so it bites everywhere.
- **Construct nothing expensive in a dependency provider or a service `__init__`.** A validation
  error must never need a database.

### Mutate the phase's riskiest DECISION, not just its named tests

A phase ran three mutations; one — swapping two deliberately-different windows for each other —
**broke nothing**, because every fixture was single-day so the two windows coincided. The suite
looked thorough and had a hole exactly where the phase's most consequential choice lived.

> When a phase's headline claim is *"these two things are deliberately different"*, mutate them
> into being the same and check that something fails.

### Mutate the GUARDRAIL, with evasion variants — not just the obvious violation

A security phase shipped a guard asserting a visibility-only permission could never become a real
gate. The Hub mutated it three ways:

| Variant | Caught? |
|---|---|
| `require("nav.x")` — the obvious one | yes |
| `require(SOME_CONST)` — indirection | yes, by a *different* test |
| `require("""nav.x""")` — **triple-quoted** | **no — full evasion** |

The third planted a live gate on an all-roles key and the entire suite plus both lint gates stayed
green. Root cause: the guard was a regex plus a substring scan, kept "two ways on purpose" — but
**both read the source as text, so they shared a blind spot rather than covering for each other.**

> **Two checks that can be fooled by the same trick are one check.** Parse the language, don't
> pattern-match its surface syntax — the parser hands back the *resolved* value, so every quoting
> style, including ones nobody has thought of, collapses into a single comparison.

Test a guardrail the way an adversary would, not the way its author imagined. On a phase whose
whole risk is "a gate that looks real and isn't", the guard against fake gates being itself fake is
the failure that matters most.

### A test asserting the OUTCOME does not pin the INVARIANT

Same phase. A documented invariant read *"break-glass admin resolves **before any database
lookup**"*. Two tests covered it — and both created the tables first, then asserted the returned
value. Moving the short-circuit *below* the query left every test green while destroying the
invariant outright.

> If the invariant is *"X happens without Y"*, the test must **withhold Y**. Asserting the result
> in a world where Y is present proves only that the result is reachable, not that it is
> independent. Here the fix was one test that never creates the tables — the omission *is* the test.

### A render/build check proves it mounted, not that it is right

A headless render returned `OK, 0 console errors` for a bar chart drawn upside down. Read the
screenshot, not the exit code.

### Mutation testing — the highest-value check the Hub does

**A test that passes but would not fail on the bug is worthless.** Reading a test tells you almost
nothing; breaking the code and watching the test fail tells you everything.

```
1. Back up the file the test claims to prove something about.
2. Remove exactly the behaviour under test — the smallest possible break
   (delete the branch, drop the argument, invert the condition).
3. Run the project's test command for that test file.  IT MUST FAIL.
4. Restore the file.
5. Re-run.  IT MUST PASS AGAIN.
```

Do this for **every** phase that adds a test claiming to prove a behaviour. It takes about a minute, and
it is the difference between "6 passed" and "6 tests that mean something." **Always restore and re-run —
never leave a mutation in the tree.** The specific trap worth naming: dropping an argument that has a
default silently changes behaviour *without erroring* — exactly what a mutation test catches and a code
read does not.

### Re-run the cross-review yourself

A report's own internal contradiction (CLEAN in one section, "pending" in another) is settled in one
command by just running it directly. **If a cross-review provider times out, try the other configured
provider before recording "inconclusive."** A single provider's outage is not grounds for skipping
independent review — on the reference run, the second provider found the real bug the first had missed.

### Read the copy, don't trust "verbatim copy"

When a phase claims to have copied a function/config/pattern verbatim, read it line by line against the
original. The easiest thing to drop silently is an argument with a default — dropping it changes
behaviour without erroring.

### Check the report against itself

Read the report once as a *document* before validating a single claim. Internal contradictions — a
verdict field disagreeing with a details field, a model name that doesn't match the claimed lane — have
found real problems as often as checking the code has.

---

## §F — Plan drift is the Hub's job

Nothing else in caddis owns *"the plan turned out to be wrong, correct it mid-flight."* The Hub is the
natural owner, and it is the step most likely to be skipped. Any SURPRISE that contradicts the plan's own
`## Current state` gets corrected **in the plan file, now** — not noted in the verdict for later, not
left for the next reader to reconcile.

---

