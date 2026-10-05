# Scenario recipes

Each recipe says how to express a scenario in a flow-studio model. **Proven** means an example model passes the
check harness. **Candidate** means the recipe is written but not built yet: say so when you use it.
Version 0.1 draws left-to-right flows only (see `SKILL.md`); where a scenario needs a loop or a branch, the
recipe says what to do today.

Common states to start from (change the words to fit the scenario):

| State id | Word | tone | border | edge | motion | bucket |
|---|---|---|---|---|---|---|
| `ok` | OK | ok | solid | flow | flow | good |
| `planned` | PLANNED | muted | dashed | dash | flow-slow | neutral |
| `late` | LATE | warn | solid | flow | flow | neutral |
| `breached` | BREACHED | crit | solid | flow | flow | gap |
| `unknown` | NOT RECORDED | warn | dotted | dot | breathe | gap |

## 1. Data lineage and dependency impact (proven: `examples/lineage.json`)

- **Columns:** source, host, database, jobs, tables, refreshers, report tables, apps, pages.
- **Lanes:** one per app or system; a lane with no document gets `gap: true` and a note saying what is missing.
- **States:** measured, declared, inferred, not recorded. Views: Today (what is measured) and Complete (adds the
  declared layer).
- **Inspector:** Feeds this, Downstream, Pages (`filter: {col: <pages column>}`). **Action:** "Simulate: this stops
  updating".
- **Questions:** which layers matter, which sources are measured and which are declared, who owns each document.
- **Traps:** guessing a link (use a placeholder), counting a declared snapshot as current (carry its date).

## 2. Ticket, case or order lifecycle (candidate)

- **Columns:** the stages (New, Triage, In progress, Waiting, Resolved, Closed). **Lanes:** the owning team or
  system. **States:** on time, at risk, breached. **Nodes:** one card per stage and team; `weight` = open count.
- **Loops:** "reopened" and "back to triage" are loops: not drawn yet. Add a "Reopened" node in a later column.
- **Inspector:** Came from, Goes to, Closed. **Action:** "Simulate: SLA breach".
- **Traps:** drawing every status as a column when only some have owners.

## 3. Agent, user or customer journey (candidate)

- **Columns:** phases (Discover, Try, Buy, Use, Renew) or time steps. **Lanes:** actors (customer, agent, system).
  **Nodes:** touchpoints. **States:** smooth, friction, failure. **Metrics:** put the figure in `subtitle`.
- **Traps:** mixing actors in one lane; no states (a journey with no pain points hides the point).

## 4. Incident timeline and root cause (candidate)

- **Columns:** time buckets (T-30m, T-10m, T0, T+10m, T+1h). **Lanes:** systems. **Nodes:** events.
  **States:** normal, degraded, failed. **Action:** "Simulate: this failed" shows the blast radius.

## 5. CI/CD pipeline and release train (candidate)

- **Columns:** stages (commit, build, test, scan, deploy, verify). **Lanes:** environments or services.
  **States:** passed, running, failed, skipped. **Inspector:** Upstream, Downstream, Environments.

## 6. Approval or business process (candidate)

- **Columns:** steps; **lanes:** roles. Branches ("approved" and "rejected") are two nodes in the next column.
  Gateway diamonds are not drawn yet: use a card titled "Decision: ...".

## 7. Service or architecture dependency map (candidate)

- **Columns:** tiers (client, edge, service, data store). **Lanes:** domains. **States:** healthy, degraded, down.
  **Action:** "Simulate: this is down" ripples to the dependents.

## 8. State machine (candidate; needs loops)

- Not a good fit until loop-back links exist. Draw the forward path only and list the returns in the inspector
  (`members`).

## 9 to 16. Further candidates

Multi-agent or LLM orchestration trace, job schedule and batch dependency, decision tree or runbook, data model or
entity explorer, access and permission graph, supply chain, learning path or roadmap, network topology. Start from
recipe 1 or 5 and say they are unproven. When one passes the checks, add its model under `examples/` and change
"candidate" to "proven" here.

## Choosing the lanes (the usual mistake)

If every node sits in one lane, the page has no structure: a lane answers "who or what owns this row". If there
are more than about 10 lanes, group them (a lane per team, not per person). If a lane has no source of truth,
mark it `gap: true` so the gap is visible instead of looking like a forgotten node.
