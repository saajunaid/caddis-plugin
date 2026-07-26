---
Original Author: Claude Code
Creation Date: 2026-06-08
---

# Agent Eval — Phase 7

Lightweight calibration loop for the 11 harness subagents. NOT a framework. No web UI, no DB,
no persistent telemetry server. Three signals; one command.

## Why eval and why light

Subagents are (tool-allowlist + method + return-format contract). A stronger model is *focused*,
not limited, by the contract. What goes stale:
- **Method detail** — specific OWASP categories, debug heuristics, hardcoded framework gotchas
- **Model tiers** — a smarter haiku may now cover what sonnet did; a local coder may need more scaffolding

The right amount of scaffolding is a function of model capability. Running heterogeneous tiers
(planner = frontier, coder = local) means subagents may need tier-aware verbosity.

## Three signals (in priority order)

### Signal 1 — agent-log.jsonl (runtime, always-on)
The `.caddis/agent-log.jsonl` written by the SubagentStop hook
(`claude-harness/hooks/agent_log.py`, wired 2026-07-20 — one JSONL line per subagent
dispatch: ts, agent, best-effort verdict, session id) is the primary live signal.
Watch verdict distribution per agent over time:

| Pattern | Interpretation |
|---|---|
| `approved` 100% of the time | May be rubber-stamping — subagent possibly redundant or too lenient |
| `FAIL` / `changes-requested` > 60% | Miscalibrated method or wrong scope; too strict or too noisy |
| Missing runs for weeks | Subagent not being dispatched — trigger condition needs checking |

**How to read:** `cat .caddis/agent-log.jsonl | python -c "import sys,json; [print(r['agent'],r['verdict']) for r in (json.loads(l) for l in sys.stdin)]"`

### Signal 2 — golden task set (per-subagent, 3–5 tasks each)
A small set of representative inputs stored in `.github/agent-docs/eval/tasks/<agent>/`.
Each task file:
- A realistic input (diff, PR description, plan, schema, bug report, codebase snippet)
- Expected verdict + key findings that a correct run must include
- A "baseline" transcript (first time a frontier model ran it — reference output)

Run a task manually: dispatch the subagent with the task input and compare output against
the expected findings. Takes ~2 min per agent. No automation required; this is a bake-off, not CI.

**Golden task coverage per agent (initial set):**

| Agent | Task examples |
|---|---|
| `tester` | FastAPI route with missing edge case; React hook with stale closure |
| `code-reviewer` | PR adding auth middleware (catch missing test); SQL query (catch injection) |
| `preflight` | Plan with wrong file path; plan with correct assumptions |
| `security-analyst` | FastAPI with hardcoded secret; parameterized queries (should pass) |
| `debug` | 500 from DB connection pool exhaustion; React hydration mismatch |
| `anchor` | Working implementation (should pass); subtle off-by-one (should flag) |
| `data-engineer` | DataFrame with join producing duplicates; clean transform (should pass) |
| `sql-expert` | Slow query missing index; correct query (should pass) |
| `codebase-audit` | Repo with circular import and dead code; clean repo |
| `knowledge-transfer` | Outdated CLAUDE.md fragment; correct fragment |
| `ui-design-reviewer` | (URL-based) Local app with WCAG contrast failure; clean app |

### Signal 3 — new-model bake-off (triggered, not scheduled)
When a new Claude model drops or you change tier assignments (there is no `model-aliases.json` — a
tier is the `model:` frontmatter field in each `claude-harness/agents/<name>.md`; see `LOCAL-MODELS.md`
for the tier→model mapping the gateway resolves it against):
1. Pick 1 golden task per agent (the hardest one).
2. Run it with the current model AND the new model.
3. If the new model returns the same or better verdict with fewer tokens → update the tier.
4. If a subagent now beats the unconstrained baseline → it earns its keep. If not → simplify or retire.

## Running an eval session (manual, ~30 min for all 11 agents)

```
1. Open agent-log.jsonl — scan verdicts from last 2 weeks.
   Flag any agent with 0 runs (not dispatched) or >60% FAIL.

2. For each flagged agent, run 1–2 golden tasks.
   Compare output to baseline transcript in eval/tasks/<agent>/.

3. Check for `model:` frontmatter changes across `claude-harness/agents/*.md` (or a gateway
   tier→model remap in `LOCAL-MODELS.md`) — if any model was upgraded, run the bake-off for agents
   on that tier.

4. Update this file with findings:
   - method-detail staleness (specific OWASP categories, framework versions)
   - tier changes (haiku can now cover X)
   - retirements (never dispatched AND golden task shows no win over baseline)
```

## File layout

```
.github/agent-docs/
  agent-eval.md              ← this file (design + runbook)
  eval/
    tasks/
      code-reviewer/
        01-auth-middleware-missing-test.md     ← input + expected findings
        02-sql-injection-catch.md
      tester/
        01-missing-edge-case.md
      preflight/
        01-wrong-file-path.md
        02-correct-plan-pass.md
      ... (one folder per agent)
    baselines/
      code-reviewer-01-baseline.md            ← reference output (frontier model)
      ...
```

## Retirement criteria

Retire a subagent if ALL three are true:
1. agent-log shows <5 dispatches in the last 60 days
2. Golden task: the subagent output is not meaningfully better than the unconstrained baseline
3. Its capability is fully covered by the main-thread model or another subagent

Retiring = deleting the `.md` file from `claude-harness/agents/` and removing from `stack-map.json`.
Do not keep zombie subagents "just in case."

## Staleness triggers (run eval when any of these fires)

- New Claude model family released (tier recalibration)
- A framework version in method-detail is >1 major behind (e.g., React 20 ships, react-dev still says React 19)
- agent-log shows a subagent verdict pattern that looks wrong (see Signal 1 table)
- A subagent returns a verdict that surprises you in a real project run

## Non-goals

- No CI job — eval is a deliberate human-in-the-loop session, not automated gate
- No web dashboard / database / telemetry server — agent-log.jsonl + files is sufficient
- No A/B testing framework — bake-off is manual (2 runs, read the output)
- No "eval score" number — verdict distribution + key-finding match is the signal
