# Advisory Hub — the phase report contract — what an implementing session must file, verbatim

> **Loaded by:** `/caddis:implement`, in Advisory-Hub mode, at report-filing time
>
> Reference for `.github/skills/workflow/advisory-hub/SKILL.md`. The core card carries the
> model; this carries the detail for one moment of use. Every rule here was earned by a
> specific failure — the failure is stated alongside it, so a later reader can tell a hard-won
> rule from an opinion.

---

## §B — the phase report contract

Every implementation phase, in Advisory-Hub mode, ends by writing this block **to a file**
(`.caddis/advisory-hub-reports/phase-NN.report.md` — §H), never just to chat. **A report without re-derivable
evidence is not a report.**

```
=== PHASE REPORT FOR ADVISORY HUB ===
PLAN:          <path to the plan file>
ADVISORY CTX:  <path to <slug>-advisory-context.md>
PHASE:         <n> — <title>
MILESTONE:     <M<n>, or N/A>
MODEL/LANE:    <tier> / <lane>              (the model you ACTUALLY ran on)
DATE:          <ISO 8601 UTC>
STATUS:        COMPLETE | BLOCKED | PARTIAL

--- COMMITS ---
<sha> <subject>                             (one line per commit — including tooling,
                                              config, and non-source files)
FILES CHANGED: <n> (+<added>/-<removed>)

--- EXIT GATE: verbatim command + verbatim output ---
$ <the literal command the plan names>
<paste the real terminal output — do not summarise, retype, or tidy it>
RESULT: PASS | FAIL                          (repeat this triple per gate)

--- VALUE CHECK ---
CLAIM:                   <the number or behaviour this phase asserts>
RE-DERIVED BY:            <the exact independent query/command/script — copy-pasteable,
                          not a description of one>
RE-DERIVATION RETURNED:  <what it actually returned>
MATCH:                   YES | NO

--- PROJECT SAFETY RULES ---
RULES IN SCOPE: <rule ids from advisory-context §5, or NONE DECLARED>
RULE <id>:  APPLIES THIS PHASE: YES | NO — <why>
            EVIDENCE: <the check that was run + its output, or N/A>
            RESULT: PASS | FAIL | N/A          (repeat per rule)

--- CROSS-REVIEW ---
PROVIDER: <deepseek | glm | …>   VERDICT: CLEAN | ISSUES | NOT RUN (+ why)
ISSUES ADDRESSED: <list, or NONE>

--- DEVIATIONS FROM PLAN ---
<each deviation + why, or NONE>

--- SURPRISES / CONTRADICTIONS ---
<anything the real data or code contradicted in the plan's `## Current state`, or NONE>
<<< STOP CONDITION: if this section is non-empty, STOP after this phase.
    The Hub owns the plan correction — you do not. >>>

--- NOT DONE ---
<anything in the phase left undone + why, or NONE>

--- NEXT PHASE READY: YES | NO ---
=== END REPORT ===
```

### Non-negotiables for the report itself — each earned by a real failure

- **Verbatim means verbatim.** A phase once filed a fabricated framework stack-trace line — one that
  wasn't even valid syntax in that language — in the one section whose entire value is being trustworthy.
  Once output is reconstructed, the Hub has to re-run everything, which defeats the section's whole
  point. If output genuinely cannot be captured, **say so** — that is fine. Inventing it is not.
- **Reconcile the report against itself before filing.** One report's CROSS-REVIEW said `CLEAN` while its
  DEVIATIONS said "verdict pending" — both cannot be true. Read your own report once as a document before
  submitting it.
- **Report the model/lane you actually ran on.** One report named a first-party model for a session
  actually running on a third-party lane. The Hub uses this field to judge whether a lane is trustworthy
  for later phases; get it wrong here and the whole lane experiment is uninterpretable.
- **Report every commit**, including tooling, config, CI, and non-source files. A phase once shipped a
  deploy-pipeline change that never appeared in its own DEVIATIONS section.
- **Never edit the plan to make your own gate pass.** Run it, report the failure and why, and let the Hub
  fix the plan.
- **A re-derivation crib's numbers must match the final committed diff, not an earlier point in
  implementation.** One crib was true when written against a 6-test file, then stale by filing time
  because a late fix added 2 more tests — the same mutation against the final 8-test file gave a
  different result. The crib wasn't fabricated or self-contradictory (none of the other five rules would
  have caught it) — it was just stale. **If a late change touches what a crib measured, re-run the crib's
  own commands before filing.**

---

