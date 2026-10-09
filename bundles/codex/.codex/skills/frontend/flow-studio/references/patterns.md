# Scenario recipes

Each recipe shows how to express a domain scenario in a flow-studio model.
All recipes listed below are **proven** and match an example file in `examples/`.

## Common states

You can start from these base states and adjust words to match your domain:

| State id | Word | Tone | Border | Edge | Motion | Bucket |
|---|---|---|---|---|---|---|
| `ok` | OK | ok | solid | flow | flow | good |
| `planned` | PLANNED | muted | dashed | dash | flow-slow | neutral |
| `late` | LATE | warn | solid | flow | flow | neutral |
| `breached` | BREACHED | crit | solid | flow | flow | gap |
| `unknown` | NOT RECORDED | warn | dotted | dot | breathe | gap |

---

## 1. Data lineage and dependency impact

- **Example file:** `examples/lineage.json`
- **Scenario:** Trace data assets from ingestion sources through storage, pipelines, transformations, to consuming dashboards and applications.
- **Typical columns:** Source, Host, Database, Pipeline, Tables, Refresher, Views, Dashboard. Do not add an App or Owner column: the lane is the app (ux-rules 11).
- **Typical lanes:** Customer Portal, Order Service, Data Warehouse, Reporting Platform. A lane without documentation uses `gap: true`.
- **Node count guideline:** 15 to 30 nodes.
- **Recommended inspector relations:**
  - Upstream (`dir: "up"`, label: "Upstream sources")
  - Downstream (`dir: "down"`, label: "Downstream consumers")
  - Pages (`dir: "down"`, label: "Affected pages", filter: `{ "kind": "card" }`)
- **Copy-paste skeleton:**

```json
{
  "version": 1,
  "meta": {
    "title": "Customer Data Lineage",
    "help": "Tracks customer record movement from OLTP to analytical reports.",
    "asOf": "2026-10-06",
    "source": "Data Governance Catalog"
  },
  "layout": "columns-lanes",
  "columns": [
    { "id": "src", "title": "Sources", "width": 180 },
    { "id": "ingest", "title": "Ingestion", "width": 180 },
    { "id": "wh", "title": "Warehouse", "width": 200 },
    { "id": "bi", "title": "Reporting", "width": 180 }
  ],
  "lanes": [
    { "id": "crm", "title": "CRM Core", "badge": "PROD", "badgeTone": "ok" },
    { "id": "analytics", "title": "Analytics Engine", "badge": "PROD", "badgeTone": "ok" }
  ],
  "states": {
    "ok": { "word": "LIVE", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" },
    "planned": { "word": "PLANNED", "tone": "muted", "border": "dashed", "edge": "dash", "motion": "flow-slow", "bucket": "neutral" }
  },
  "nodes": [
    { "id": "crm-db", "kind": "card", "lane": "crm", "col": 0, "row": 0, "state": "ok", "title": "CRM Postgres" },
    { "id": "cdc-pipe", "kind": "card", "lane": "crm", "col": 1, "row": 0, "state": "ok", "title": "CDC Stream" },
    { "id": "dim-cust", "kind": "card", "lane": "analytics", "col": 2, "row": 0, "state": "ok", "title": "dim_customer" },
    { "id": "dash-sales", "kind": "card", "lane": "analytics", "col": 3, "row": 0, "state": "ok", "title": "Sales Dashboard" }
  ],
  "links": [
    { "id": "l1", "from": "crm-db", "to": "cdc-pipe", "state": "ok" },
    { "id": "l2", "from": "cdc-pipe", "to": "dim-cust", "state": "ok" },
    { "id": "l3", "from": "dim-cust", "to": "dash-sales", "state": "ok" }
  ]
}
```

---

## 2. Ticket, case, or order lifecycle

- **Example file:** `examples/ticket-lifecycle.json`
- **Scenario:** Track service requests, customer tickets, or incident cases from creation to triage, engineering resolution, verification, and closure.
- **Typical columns:** New, Triage, In Progress, Review, Waiting, Resolved, Closed.
- **Typical lanes:** Tier 1 Support, Platform Engineering, Quality Assurance, Customer.
- **Node count guideline:** 8 to 20 nodes.
- **Recommended inspector relations:**
  - Previous step (`dir: "up"`, label: "Came from")
  - Next step (`dir: "down"`, label: "Goes to")
  - Escalations (`dir: "down"`, label: "Escalated to")
- **Copy-paste skeleton:**

```json
{
  "version": 1,
  "meta": {
    "title": "Support Ticket Journey",
    "help": "End-to-end support ticket triage and escalation workflow.",
    "asOf": "2026-10-06",
    "source": "HelpDesk Service API"
  },
  "layout": "columns-lanes",
  "columns": [
    { "id": "triage", "title": "Triage", "width": 160 },
    { "id": "dev", "title": "Engineering", "width": 180 },
    { "id": "qa", "title": "Verification", "width": 160 },
    { "id": "done", "title": "Resolved", "width": 160 }
  ],
  "lanes": [
    { "id": "support", "title": "Support Desk", "badge": "T1", "badgeTone": "ok" },
    { "id": "eng", "title": "Platform Team", "badge": "T2", "badgeTone": "ok" }
  ],
  "states": {
    "ontime": { "word": "ON TIME", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" },
    "risk": { "word": "AT RISK", "tone": "warn", "border": "dashed", "edge": "dash", "motion": "breathe", "bucket": "neutral" },
    "breach": { "word": "BREACHED", "tone": "crit", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "gap" }
  },
  "nodes": [
    { "id": "inbound", "kind": "card", "lane": "support", "col": 0, "row": 0, "state": "ontime", "title": "Inbound Case" },
    { "id": "diag", "kind": "card", "lane": "support", "col": 0, "row": 1, "state": "ontime", "title": "Initial Assessment" },
    { "id": "bugfix", "kind": "card", "lane": "eng", "col": 1, "row": 0, "state": "risk", "title": "Patch Defect", "sla": 3600 },
    { "id": "verify", "kind": "card", "lane": "support", "col": 2, "row": 0, "state": "ontime", "title": "Customer Verify" },
    { "id": "closed", "kind": "card", "lane": "support", "col": 3, "row": 0, "state": "ontime", "title": "Case Closed" }
  ],
  "links": [
    { "id": "l-triage", "from": "inbound", "to": "diag", "state": "ontime" },
    { "id": "l-escalate", "from": "diag", "to": "bugfix", "state": "risk" },
    { "id": "l-test", "from": "bugfix", "to": "verify", "state": "ontime" },
    { "id": "l-reopen", "from": "verify", "to": "bugfix", "state": "risk", "kind": "loop-back", "label": "Failed test" },
    { "id": "l-resolve", "from": "verify", "to": "closed", "state": "ontime" }
  ]
}
```

---

## 3. Agent and customer journey

- **Example file:** `examples/agent-journey.json`
- **Scenario:** Trace user prompts into an autonomous agent loop (receive, analyze, plan, tool execution, critique, response).
- **Typical columns:** Receive, Classify, Plan, Act, Validate, Respond.
- **Typical lanes:** User, Agent Core, Tool Worker, Human Reviewer.
- **Node count guideline:** 8 to 20 nodes.
- **Recommended inspector relations:**
  - Inputs (`dir: "up"`, label: "Context inputs")
  - Outputs (`dir: "down"`, label: "Generated steps")
  - Tool calls (`dir: "down"`, label: "External tools")
- **Copy-paste skeleton:**

```json
{
  "version": 1,
  "meta": {
    "title": "Autonomous Agent Loop",
    "help": "Execution loop of an LLM agent with tool calls and human verification.",
    "asOf": "2026-10-06",
    "source": "Agent Orchestrator"
  },
  "layout": "columns-lanes",
  "columns": [
    { "id": "input", "title": "Input", "width": 160 },
    { "id": "think", "title": "Reasoning", "width": 180 },
    { "id": "exec", "title": "Tool Execution", "width": 180 },
    { "id": "out", "title": "Response", "width": 160 }
  ],
  "lanes": [
    { "id": "client", "title": "User Session", "badge": "USER", "badgeTone": "muted" },
    { "id": "orchestrator", "title": "Agent Planner", "badge": "AI", "badgeTone": "ok" },
    { "id": "mcp", "title": "Tool Worker", "badge": "MCP", "badgeTone": "accent" }
  ],
  "states": {
    "ready": { "word": "READY", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" },
    "thinking": { "word": "ACTIVE", "tone": "accent", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "neutral" },
    "retry": { "word": "RETRY", "tone": "warn", "border": "dashed", "edge": "dash", "motion": "breathe", "bucket": "neutral" }
  },
  "nodes": [
    { "id": "prompt", "kind": "card", "lane": "client", "col": 0, "row": 0, "state": "ready", "title": "User Prompt" },
    { "id": "plan", "kind": "card", "lane": "orchestrator", "col": 1, "row": 0, "state": "thinking", "title": "Create Plan" },
    { "id": "call-api", "kind": "card", "lane": "mcp", "col": 2, "row": 0, "state": "ready", "title": "Execute Tool Call" },
    { "id": "answer", "kind": "card", "lane": "client", "col": 3, "row": 0, "state": "ready", "title": "Final Reply" }
  ],
  "links": [
    { "id": "l-in", "from": "prompt", "to": "plan", "state": "ready" },
    { "id": "l-call", "from": "plan", "to": "call-api", "state": "ready" },
    { "id": "l-back", "from": "call-api", "to": "plan", "state": "retry", "kind": "loop-back", "label": "Tool result" },
    { "id": "l-reply", "from": "plan", "to": "answer", "state": "ready" }
  ]
}
```

---

## 4. CI/CD pipeline and release train

- **Example file:** `examples/ci-cd-pipeline.json`
- **Scenario:** Trace code commit through automated build, testing, container scanning, staging validation, and canary production deployment.
- **Typical columns:** Commit, Build, Test, Security, Staging, Production.
- **Typical lanes:** Web Frontend, Core Service, Infrastructure as Code.
- **Node count guideline:** 10 to 25 nodes.
- **Recommended inspector relations:**
  - Upstream stages (`dir: "up"`, label: "Required steps")
  - Downstream gates (`dir: "down"`, label: "Dependent gates")
  - Artifacts (`dir: "down"`, label: "Published packages")
- **Copy-paste skeleton:**

```json
{
  "version": 1,
  "meta": {
    "title": "Release Train Pipeline",
    "help": "Continuous delivery pipeline with automated test gates and approval checks.",
    "asOf": "2026-10-06",
    "source": "GitHub Actions"
  },
  "layout": "columns-lanes",
  "columns": [
    { "id": "src", "title": "Source", "width": 150 },
    { "id": "ci", "title": "Build & Test", "width": 180 },
    { "id": "gate", "title": "Approval", "width": 160 },
    { "id": "deploy", "title": "Deployment", "width": 180 }
  ],
  "lanes": [
    { "id": "app", "title": "App Service", "badge": "CI/CD", "badgeTone": "ok" },
    { "id": "ops", "title": "Infrastructure", "badge": "PROD", "badgeTone": "warn" }
  ],
  "states": {
    "pass": { "word": "PASSED", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" },
    "running": { "word": "RUNNING", "tone": "accent", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "neutral" },
    "failed": { "word": "FAILED", "tone": "crit", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "gap" }
  },
  "nodes": [
    { "id": "push", "kind": "card", "lane": "app", "col": 0, "row": 0, "state": "pass", "title": "Git Commit" },
    { "id": "lint-test", "kind": "card", "lane": "app", "col": 1, "row": 0, "state": "pass", "title": "Unit & Integration" },
    { "id": "gate-check", "kind": "gateway", "lane": "ops", "col": 2, "row": 0, "state": "running", "title": "Sign-off OK?" },
    { "id": "prod-deploy", "kind": "card", "lane": "ops", "col": 3, "row": 0, "state": "pass", "title": "Canary Rollout" }
  ],
  "links": [
    { "id": "l-ci", "from": "push", "to": "lint-test", "state": "pass" },
    { "id": "l-gate", "from": "lint-test", "to": "gate-check", "state": "pass" },
    { "id": "l-ok", "from": "gate-check", "to": "prod-deploy", "state": "pass", "label": "Approved" },
    { "id": "l-fail", "from": "gate-check", "to": "push", "state": "failed", "kind": "loop-back", "label": "Rejected" }
  ]
}
```

---

## 5. Approval or business process

- **Example file:** `examples/approval-flow.json`
- **Scenario:** Multi-tiered approval workflow for expense requests, contract reviews, or capital expenditure.
- **Typical columns:** Submission, Initial Review, Dept Approval, Executive Signoff, Fulfillment.
- **Typical lanes:** Employee, Line Manager, Finance Officer, VP / Executive.
- **Node count guideline:** 8 to 22 nodes.
- **Recommended inspector relations:**
  - Prior reviews (`dir: "up"`, label: "Previous decisions")
  - Next approvals (`dir: "down"`, label: "Next reviews")
  - Audit trail (`dir: "down"`, label: "Audit records")
- **Copy-paste skeleton:**

```json
{
  "version": 1,
  "meta": {
    "title": "Expense Approval Flow",
    "help": "Multi-tier corporate expense authorization workflow.",
    "asOf": "2026-10-06",
    "source": "ERP Workflow Engine"
  },
  "layout": "auto",
  "columns": [
    { "id": "start", "title": "Request", "width": 160 },
    { "id": "review", "title": "Review", "width": 180 },
    { "id": "finance", "title": "Finance", "width": 180 },
    { "id": "done", "title": "Pmt", "width": 160 }
  ],
  "lanes": [
    { "id": "staff", "title": "Requester", "badge": "STAFF", "badgeTone": "muted" },
    { "id": "mgr", "title": "Line Manager", "badge": "MGR", "badgeTone": "ok" },
    { "id": "acct", "title": "Finance Dept", "badge": "ACCT", "badgeTone": "warn" }
  ],
  "states": {
    "approved": { "word": "APPROVED", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" },
    "pending": { "word": "PENDING", "tone": "warn", "border": "dashed", "edge": "dash", "motion": "breathe", "bucket": "neutral" },
    "rejected": { "word": "REJECTED", "tone": "crit", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "gap" }
  },
  "nodes": [
    { "id": "submit", "kind": "card", "lane": "staff", "state": "approved", "title": "Submit Invoice" },
    { "id": "mgr-gate", "kind": "gateway", "lane": "mgr", "state": "pending", "title": "Within Budget?" },
    { "id": "finance-audit", "kind": "card", "lane": "acct", "state": "pending", "title": "Tax Compliance" },
    { "id": "payout", "kind": "card", "lane": "acct", "state": "approved", "title": "Disburse Funds" }
  ],
  "links": [
    { "id": "l-sub", "from": "submit", "to": "mgr-gate", "state": "approved" },
    { "id": "l-app", "from": "mgr-gate", "to": "finance-audit", "state": "approved", "label": "Yes" },
    { "id": "l-rej", "from": "mgr-gate", "to": "submit", "state": "rejected", "kind": "loop-back", "label": "Revise" },
    { "id": "l-pay", "from": "finance-audit", "to": "payout", "state": "approved" }
  ]
}
```

---

## 6. Incident timeline and root cause

- **Example file:** `examples/incident-timeline.json`
- **Scenario:** Trace outage timeline from initial alert to blast radius detection, containment action, patch rollout, and post-incident review.
- **Typical columns:** Detection, Triage, Containment, Patch, Verification, Recovered.
- **Typical lanes:** API Gateway, Orders Service, Database, On-Call Operations.
- **Node count guideline:** 10 to 24 nodes.
- **Recommended inspector relations:**
  - Root causes (`dir: "up"`, label: "Root causes")
  - Impacted components (`dir: "down"`, label: "Blast radius")
  - Incident actions (`dir: "down"`, label: "Remediation tasks")
- **Copy-paste skeleton:**

```json
{
  "version": 1,
  "meta": {
    "title": "Production Outage Timeline",
    "help": "Post-incident analysis of connection pool exhaustion.",
    "asOf": "2026-10-06",
    "source": "Incident Response Log"
  },
  "layout": "columns-lanes",
  "columns": [
    { "id": "t0", "title": "10:00 Alert", "width": 160 },
    { "id": "t1", "title": "10:15 Triage", "width": 180 },
    { "id": "t2", "title": "10:30 Mitigation", "width": 180 },
    { "id": "t3", "title": "11:00 Recovered", "width": 160 }
  ],
  "lanes": [
    { "id": "gw", "title": "API Gateway", "badge": "EDGE", "badgeTone": "warn" },
    { "id": "db", "title": "Database Cluster", "badge": "STORAGE", "badgeTone": "crit" }
  ],
  "states": {
    "healthy": { "word": "HEALTHY", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" },
    "failing": { "word": "FAILED", "tone": "crit", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "gap" },
    "fixed": { "word": "RESTORED", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" }
  },
  "nodes": [
    { "id": "alert", "kind": "card", "lane": "gw", "col": 0, "row": 0, "state": "failing", "title": "504 Gateway Timeout" },
    { "id": "pool-exhaust", "kind": "card", "lane": "db", "col": 1, "row": 0, "state": "failing", "title": "Pool Depleted" },
    { "id": "restart-nodes", "kind": "card", "lane": "db", "col": 2, "row": 0, "state": "healthy", "title": "Scale Connections" },
    { "id": "traffic-restored", "kind": "card", "lane": "gw", "col": 3, "row": 0, "state": "fixed", "title": "Normal Latency" }
  ],
  "links": [
    { "id": "l-root", "from": "alert", "to": "pool-exhaust", "state": "failing" },
    { "id": "l-fix", "from": "pool-exhaust", "to": "restart-nodes", "state": "healthy" },
    { "id": "l-back-online", "from": "restart-nodes", "to": "traffic-restored", "state": "fixed" }
  ],
  "inspector": {
    "actions": [
      { "id": "sim-fail", "label": "Simulate: DB Failure", "dir": "down", "staleText": "Cascade to edge clients" }
    ]
  }
}
```

---

## 7. Service or architecture dependency map

- **Example file:** `examples/service-map.json`
- **Scenario:** Map microservices, API gateways, cache layers, message brokers, and persistent datastores across functional domains.
- **Typical columns:** Edge Gateway, Auth, Commerce API, Background Workers, Persistence.
- **Typical lanes:** Public Domain, Core Domain, Data Infrastructure.
- **Node count guideline:** 12 to 28 nodes.
- **Recommended inspector relations:**
  - Upstream callers (`dir: "up"`, label: "Direct clients")
  - Downstream services (`dir: "down"`, label: "Downstream dependencies")
  - Shared storage (`dir: "down"`, label: "Datastores used")
- **Copy-paste skeleton:**

```json
{
  "version": 1,
  "meta": {
    "title": "Microservice Architecture Map",
    "help": "Service dependency topology with traffic volume and latency metrics.",
    "asOf": "2026-10-06",
    "source": "Service Mesh Telemetry"
  },
  "layout": "auto",
  "columns": [
    { "id": "edge", "title": "Edge", "width": 160 },
    { "id": "svc", "title": "Services", "width": 200 },
    { "id": "data", "title": "Datastores", "width": 180 }
  ],
  "lanes": [
    { "id": "ingress", "title": "Ingress Tier", "badge": "NET", "badgeTone": "ok" },
    { "id": "app", "title": "Application Tier", "badge": "SVC", "badgeTone": "ok" },
    { "id": "storage", "title": "Persistence Tier", "badge": "DB", "badgeTone": "ok" }
  ],
  "states": {
    "nominal": { "word": "HEALTHY", "tone": "ok", "border": "solid", "edge": "flow", "motion": "flow", "bucket": "good" },
    "warn": { "word": "DEGRADED", "tone": "warn", "border": "dashed", "edge": "dash", "motion": "breathe", "bucket": "neutral" }
  },
  "nodes": [
    { "id": "api-gw", "kind": "card", "lane": "ingress", "state": "nominal", "title": "Kong Gateway" },
    { "id": "order-svc", "kind": "card", "lane": "app", "state": "nominal", "title": "Order Service", "metrics": { "value": 420, "unit": "rps", "label": "Throughput" } },
    { "id": "db-cluster", "kind": "group", "lane": "storage", "state": "nominal", "title": "Postgres Cluster", "contains": ["pg-primary", "pg-replica"], "collapsed": true },
    { "id": "pg-primary", "kind": "card", "lane": "storage", "state": "nominal", "title": "PG Primary" },
    { "id": "pg-replica", "kind": "card", "lane": "storage", "state": "nominal", "title": "PG Read Replica" }
  ],
  "links": [
    { "id": "l-edge-order", "from": "api-gw", "to": "order-svc", "state": "nominal" },
    { "id": "l-order-pg", "from": "order-svc", "to": "pg-primary", "state": "nominal" }
  ]
}
```

---

## Lane structure guidance

A lane answers: "who or what owns this row?".
- Group lanes by owning team, service domain, or architecture tier.
- Avoid placing all nodes into a single lane; that destroys visual structure.
- Avoid using more than 10 lanes; group related sub-services instead.
- If a system has no verifiable document or owner, mark the lane `gap: true` with an explanatory note.
