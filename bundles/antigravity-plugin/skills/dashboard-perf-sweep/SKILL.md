---
name: dashboard-perf-sweep
context: fork
description: Re-measure an app's dashboard/API endpoints for load-time regressions and decide, with a documented checklist (not a black-box verdict), whether a slow one is a candidate for the rs-kit summary-table refresher pattern — or needs an index, keyset paging, gzip, or nothing at all. Use when the user says "sweep dashboard performance", "check if this app needs rs-kit", "re-measure the perf tracker", "is this endpoint a refresher candidate", or when a dashboard-performance-tracker.md is stale and needs re-validating. Read-only by default (dev servers only; prod requires an explicit opt-in and human confirmation) and human-invoked, never scheduled -- it surfaces candidates, it does not enroll them.
---

# dashboard-perf-sweep — re-measure, then judge the shape, not just the time

Today an app "earns" the rs-kit refresher pattern only when someone happens to be doing unrelated
work on it, hits a slow page, and measures it properly. That worked for a couple of apps in the
fleet, but a snapshot measurement goes stale — a page added last month, or a table that crossed a
growth threshold since, has no mechanism to surface itself. This skill re-measures on demand.

**What already exists and must NOT be rebuilt:** every app in the fleet has its own
`.caddis/kb/dashboard-performance-tracker.md` with real baseline measurements. The gap this closes
is **re-measurement and re-judgment**, not first-time discovery.

## Explicit scope guardrails — do not relax without a new conversation

- **Read-only except the final tracker update.** No code changes, no schema changes, ever. The only
  write this skill makes is a diffable update to the target app's own `dashboard-performance-tracker.md`.
- **Dev by default.** Measuring against prod requires an explicit opt-in flag from the user AND, per
  this project's convention for risky/hard-to-reverse actions, confirmation before hitting a live
  service.
- **Human-invoked, not scheduled.** Run this when a person chooses to — never wire it into a cron job
  or background automation. It surfaces candidates; it does not enroll them.
- **rs-kit is one of several possible recommendations, never the only output.** The checklist below
  must be able to conclude "needs an index," "needs keyset paging," "needs gzip/trimmed fields,"
  "not currently a candidate" — recommending rs-kit only for the specific aggregation shape.

## The decision model — two gates, not one number

**Gate 1 — time (mechanical).** `DASHBOARD-PERFORMANCE-STANDARD.md` Rule 6: the first, uncached load
of any dashboard endpoint must finish in **under ~1 second**. The harness script below applies this
gate automatically per endpoint. Passing gate 1 does **not** mean rs-kit — it just means "look closer."

**Gate 2 — shape (judgment, applied by you the agent, never automated).** rs-kit fixes exactly one
shape: a query that recomputes `O(all rows ever stored)` per request, against data that keeps
growing. Time alone is not sufficient evidence — the fleet's own history proves it:

| App | Cold time | Root cause | rs-kit? |
|---|---|---|---|
| App A | worst >60s, 5 real breaches | recurring full-table aggregation | **YES** |
| App B (pre-fix) | 14s–60s+ across several endpoints | recurring full-table aggregation | **YES** |
| App C | 10.3s | a single ~158MB LOB payload on 9.1k rows, not aggregation | **NO** — SQL aggregate + gzip |
| App D | 1.9s | cold JSON parse, no DB at all in prod | **NO** — warm the provider |
| App E | 202ms | n/a — never crossed gate 1 | **NO** |

A naive "slow ⇒ recommend rs-kit" tool would have wrongly flagged App C and App D. That already
happened once before the shape distinction was made explicit — don't repeat it.

## Step 1 — build the endpoint list for this app

The tracker files are semi-structured (page names + backtick route fragments in a markdown table),
not a clean machine-parseable list — extract the list yourself, per app, each run:

1. Read the target app's `.caddis/kb/dashboard-performance-tracker.md` — pull every "Page / endpoint"
   entry, in particular anything marked ⏳ pending or not re-measured recently.
2. If the app has a `UI_PAGE_GUIDE.md` (check root and `docs/reference/`), cross-check it for pages
   **not yet in the tracker** — this is what catches drift, not just re-running the same old list. Not
   every app has one; if it's missing, say so explicitly rather than silently only using the tracker.
3. Write the result as a JSON file matching the harness's input shape:
   ```json
   [
     {"name": "Historical Trends chart", "method": "GET", "path": "/api/trends/daily"},
     {"name": "IW grid", "method": "POST", "path": "/raworkbench/investigation/query", "json": {}}
   ]
   ```
4. Confirm with the user (or the app's own `run`/`webapp-testing` conventions) how to reach the dev
   instance safely, and what auth the endpoints need (open / token / session cookie) — pass it via
   `--header`.

## Step 2 — start the dev server, then run the harness

Use the app's own `run` skill/convention to start it — this skill does not start dev servers itself,
only measures an already-reachable URL.

**Use `127.0.0.1`, never the hostname `localhost`, in `--base-url`.** On Windows, Python's `urllib`
resolves `localhost` dual-stack (tries IPv6 `::1` first) and can add a **spurious, rock-steady
~1000ms** to every single request — cold *and* warm, on every endpoint including the framework's own
static docs page. It looks exactly like a real, uniform perf problem (equal cold/warm, present on
trivial routes too) and is not one. This cost real time during this skill's own validation (§
Validating below) before `127.0.0.1` was substituted and the true numbers — sub-15ms — appeared. If a
sweep ever comes back with a suspiciously uniform floor across unrelated endpoints, first time a
`/docs` or `/openapi.json` route on the same base URL before trusting the data.

```bash
python <skill-dir>/scripts/perf_sweep.py --base-url http://127.0.0.1:<port> --endpoints endpoints.json
python <skill-dir>/scripts/perf_sweep.py --base-url http://127.0.0.1:<port> --endpoints endpoints.json \
  --header "Cookie: session=..." --output report.json
```

Cold = first request after the dev server's fresh start (or right after a cache-bust if it can't be
restarted cheaply); warm = the immediate second request. The report flags gate-1 breaches and prints
the cold/warm ratio — a big ratio with no cache in between already points at a query-shape problem,
not a cache-TTL one. **A page that errors or times out is a finding, not a script failure** — it's
printed as `[ERROR]`, never silently dropped.

## Step 3 — apply the gate-2 checklist to every gate-1 breach

Force these questions, in order, for each slow endpoint — don't skip to a verdict:

1. **Does response size explain most of the time** (large payload, not a slow query)? → not rs-kit;
   recommend trimming fields / gzip / virtualization.
2. **Is the slow part parsing/serialization, not the DB round-trip?** → not rs-kit; recommend
   caching/warming the parsed form (App D precedent).
3. **Does the query scale with total stored rows rather than the response size** — read the actual
   SQL/query plan, not just the timing — **and is the same aggregation recomputed per request on data
   that keeps growing?** → candidate for rs-kit.
4. **Is it slow only at deep pagination (OFFSET)?** → not rs-kit; recommend keyset paging
   (`exception_id`-style cursor, App B precedent).
5. **Is a specific WHERE clause unseekable** (function-wrapped column, NVARCHAR/VARCHAR param
   mismatch)? → not rs-kit; recommend an index or a param-type fix.

Link findings to real fleet precedent (the table above, the `nvarchar-param-varchar-column-scan`
pattern, the keyset-paging work) rather than describing fixes in the abstract — every category here
has already been solved once in this fleet.

## Step 4 — update the tracker, diffably

Update the target app's own `dashboard-performance-tracker.md` in place with the new measurements and
verdicts, so drift becomes visible over time in the diff. Never silently overwrite it without the user
being able to see a before/after. Print a summary alongside the file edit.

## Validating this skill against known ground truth

Before trusting a new app's output, or after changing the checklist, run the sweep against two
already-known apps in your fleet and confirm it reproduces the **already-established, human-verified**
conclusion for each: one that's genuinely fast (should conclude "not a candidate") and one with a
known aggregation breach (should conclude "aggregation-shaped, rs-kit candidate" for the pages
already identified). If the output disagrees with the known-good conclusion for either, that's a
checklist bug — fix the checklist, don't rationalize the disagreement away.
