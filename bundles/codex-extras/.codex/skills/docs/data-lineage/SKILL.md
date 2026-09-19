---
name: data-lineage
description: Generates End-to-End Data Lineage and Telemetry Specifications linking UI pages, API routes, database datasets, and ETL/SP producers for watch-sight observability.
---

# Data Lineage Skill

This skill generates End-to-End Data Lineage and Telemetry Specifications for enterprise applications. It bridges the gap between frontend user surfaces, backend API routes, relational database objects, and upstream data producers (ETLs, Stored Procedures, and SQL Agent jobs).

The resulting specifications serve as the ground truth for estate-wide observability in **watch-sight** to enable automated dependency graphs, health probing, and blast-radius impact analysis.

---

## Mandatory Workflow Steps

### Step 1: Codebase & Infrastructure Discovery
Conduct targeted research across the target application and observability repositories:
1. **Frontend Surfaces:** Inspect `frontend/src/routes/` or router configurations to identify all user-facing pages, views, and navigation tabs.
2. **API Routes:** Inspect `src/api/routes/` or API routers to map every HTTP endpoint invoked by each frontend page.
3. **Database Repositories & SQL Queries:** Trace API controllers into data services and repositories to identify exact SQL tables, views, and columns accessed.
4. **Data Producers & Execution Timings (DB Server SPs & ETLs):** Identify the scheduled jobs, batch Python scripts, and SQL Server Stored Procedures that populate, calculate, or refresh each dataset. Discover their exact execution timings, run frequencies, and triggers (e.g. SQL Server Agent schedules, Windows Task Scheduler jobs, cron expressions, email triggers, or polling loops from runbooks and pipeline schedule references).
5. **Physical Estate Host Resolution:** Query `E:\Projects\watch-sight\config\monitor-targets.json` and `docs/runbooks/estate-pipelines/` to resolve physical server hostnames, IP addresses, ports, database instances, and service accounts.

### Step 2: Markdown Document Authoring
Draft the canonical Data Lineage Markdown file:
`docs/<app>/<app>-data-lineage.md`

Follow the standard 5-section lineage structure detailed below.

### Step 3: Confluence XHTML Compilation & Verification
Compile the Markdown document into Confluence Storage Format XHTML using:
```powershell
python scripts/convert_doc_to_confluence.py docs/<app>/<app>-data-lineage.md --output docs/<app>/<app>-data-lineage.html --diagram-type plantuml
```
Verify that the output compiles as well-formed XML without errors.

---

## Standard Lineage Document Structure (Markdown)

Every lineage document must follow this standardized 5-section structure:

```markdown
---
type: lineage
status: current
feature: <app>-data-lineage
creation-agent: caddis
Creating Model: <active model ID, e.g. gemini-3.8-flash>
---

# <App Title> — End-to-End Data Lineage & Telemetry Specification

## 1. Physical Estate & Host Infrastructure
Detail the physical hosts, IP addresses, ports, database instances, and network access paths:
- Application Host (Web server, reverse proxy, ports)
- Primary Database Host (SQL Server, database instance, port, auth mechanism)
- Ingestion & Staging Host (Batch runner, scheduled jobs, agent services)
- External Feeds & Gateways (SFTP drops, upstream BSS/mediation systems)

## 2. End-to-End Dependency & Impact Flowchart
Provide a colorful, professional Mermaid diagram (`flowchart TD` or `flowchart LR`) illustrating the 5-tier dependency pipeline:
Upstream Ingestion -> Processing / DB Stored Procedures -> Database Tables/Views -> API Routes -> Frontend UI Pages.
- Use explicit classDef pastel styles (never raw yellow boxes).
- Group layers into clear subgraphs.

## 3. Comprehensive Database Lineage Matrix
A comprehensive table specifying the complete end-to-end data lineage across the following mandatory columns:
| App | UI Page | API Route | Dataset (Tables / Views) | Producer (ETL / SP / Job) | Execution Timing / Trigger | Database | Physical Host |
|---|---|---|---|---|---|---|---|
| ... | ... | ... | ... | ... | ... | ... | ... |

Column specifications:
- **App:** Application identifier (e.g. `rev-sight`).
- **UI Page:** User interface page path and title (e.g. `/runs (Run Monitor)`).
- **API Route:** HTTP method and endpoint (e.g. `GET /api/runs`).
- **Dataset:** Schema-qualified tables or views read (e.g. `[dbo].[CDR_RUN_LOG]`).
- **Producer:** Exact SQL Agent job name, batch ETL script, or DB Stored Procedure that populates or refreshes the dataset.
- **Execution Timing / Trigger:** Exact schedule, frequency, and trigger mechanism (e.g. `Daily 07:00 UTC (SQL Agent)`, `Nightly 08:00 UTC (Task Scheduler)`, `Every 5 min polling (Background Service)`).
- **Database:** Target database name (e.g. `CDR`, `CERILLION`).
- **Physical Host:** Hostname and IP (e.g. `iegew3ccdr01 (100.126.185.4)`).

## 4. Stored Procedures & Producer Execution Catalog
Catalog the database server stored procedures and scheduled jobs that populate the datamart:
- Sequential execution order reference table detailing every job in execution order, execution time, host machine, scheduler, and dependencies.
- Detailed procedure profiles: Procedure Name, database instance, trigger mechanism, exact schedule, parameters, source tables read, and target tables written.

## 5. watch-sight Telemetry Ingestion Contract
Provide a machine-readable JSON specification block aligned with `watch-sight/config/monitor-targets.json` implementing the **Three-Tier Real-Time Schedule Discovery Hierarchy**:
- **All Producers Represented:** Every single producer (ETL script, SQL Agent job, Stored Procedure) cataloged in Section 4 must be represented in the telemetry contract.
- **Tier 1 (Live Scheduler Discovery):** Define authoritative real-time queries against OS and DB schedulers (`msdb.dbo.sysschedules` / `msdb.dbo.sysjobschedules` for SQL Agent jobs; PowerShell `Get-ScheduledTaskInfo` for Windows Task Scheduler) so monitoring automatically tracks schedule changes made by operators in real time without documentation drift.
- **Tier 2 (Execution Audit Telemetry):** Define queries against application execution audit tables where available (`[dbo].[ETL_AUDIT_LOG]`, `[dbo].[CDR_LOAD_LOG]`, `[dbo].[cdr_validation_run]`, `msdb.dbo.sysjobhistory`) for actual runtime watermarks, durations, and status. If an application lacks audit tables, Tier 2 is omitted and Tier 1 scheduler status is used.
- **Tier 3 (Static Baseline Fallback):** Define static baseline fallback schedules and maximum allowable runtimes as a safety guardrail when live probes are momentarily unreachable.
- `hosts` & `db_ping_targets`
- `pipeline_producers` (with Tier 1, Tier 2, and Tier 3 blocks)
- `continuous_services`
- `application_components`
- `blast_radius_rules`
```

---

## Diagram and Conversion Standards (Expert Systems Architect & Mermaid Designer)

### 🎨 Design & Styling Principles
1. **Color Palette & Semantic Styling (Standard/Impact/Existing):**
   - Use desaturated, modern executive colors. Do not use highly saturated primary colors.
   - Define exactly 3-4 standard semantic class styles at the top of every diagram:
     - `existingStyle`: Clean Blue (`fill:#EFF6FF,stroke:#2563EB,stroke-width:2px,color:#1E40AF`) for legacy/established components.
     - `newStyle`: Warm Red/Crimson (`fill:#FEF2F2,stroke:#DC2626,stroke-width:2px,color:#991B1B`) for greenfield/new components.
     - `impactedStyle`: Amber/Gold (`fill:#FFFBEB,stroke:#D97706,stroke-width:2px,color:#92400E`) for modified/impacted systems.
   - Apply classes consistently to the nodes using the triple colon notation (e.g., `NodeName:::newStyle`).
2. **Diagram Scalability Settings (Initialization Block):**
   - Always prepend diagrams with a configuration initialization block to control sizing and font scales:
     ```mermaid
     %%{init: { 
       'theme': 'default', 
       'themeVariables': { 'fontSize': '14px', 'subgraphTitleSize': '16px' }, 
       'flowchart': { 'useMaxWidth': false, 'htmlLabels': true, 'curve': 'basis' } 
     } }%%
     ```
3. **Readable Text Wrapping:**
   - Never let a single node have a long horizontal text block. Use `<br/>` tags to stack text vertically.
   - Format nodes with clear visual hierarchy: Use bolding for titles, bracket notation for IDs, and italics for status:
     `NodeName["📅 <b>Windows Scheduler</b><br/>[SYS_03]<br/><i>New Component</i>"]`

### 📐 Layout & Real Estate Rules
1. **The 3-Column Kanban Layout (Side-by-Side):**
   - When sequential phases are required (e.g., Phase 1 | Phase 2 | Phase 3) but need to prevent horizontal text compression, utilize a "Hybrid Columnar Layout".
   - **Rule:** Set the top-level flow to Left-to-Right (`flowchart LR`) to align parent containers horizontally, but enforce vertical stacking (`direction TB`) *inside* each subgraph container.
   - **Example Structure:**
     ```mermaid
     flowchart LR
         subgraph Phase1["Phase 1"]
             direction TB
             A --> B --> C
         end
         subgraph Phase2["Phase 2"]
             direction TB
             D --> E --> F
         end
         Phase1 --> Phase2
     ```
2. **The Two-Line Grid Layout (Row Stacking):**
   - When a 3-pillar horizontal layout spans too wide, stack them into rows by setting the top-level structure to Top-to-Bottom (`flowchart TD`).
   - Group the lower pillars (Phase 2 and Phase 3) side-by-side inside a helper subgraph container that uses `direction LR`. This forces Phase 2 to wrap onto a new line directly below Phase 1.
3. **Component Types:**
   - Use standard flowchart shapes to represent structural entities:
     - `[(Database Node)]` for persistent storage, tables, or file outputs.
     - `["Application Node"]` for processing scripts, APIs, or services.
     - `["🖥️ UI Node"]` for user interfaces.
4. **Dynamic Layout & Sizing:** Do not fix exclusively to Left-to-Right (`flowchart LR`) or Top-to-Bottom (`flowchart TD`). Choose the layout dynamically based on component count and readability:
   - Use `flowchart LR` for simple linear flows with few components.
   - Use `flowchart TD` or mixed subgraphs when there are many layers or components to prevent excessive horizontal stretching.
5. **PlantUML Engine & Crisp Proportioning:** Diagrams convert via `convert_doc_to_confluence.py` using `scale 1.2` for flowcharts, `scale max 2000 width` for sequence diagrams, `skinparam defaultFontSize 11` (no `skinparam dpi 200` to prevent blowout), natural curved splines (omit `polyline` / `ortho`), tightened whitespace (`nodesep 24`, `ranksep 28`, package `Padding 10`), distinct 1.5px border outlines (`#FEF2F2;line:DC2626` for crimson red impacted borders, `#EFF6FF;line:2563EB` for deep blue existing borders), and cross-package `norank` connectors to guarantee sharp, readable, properly proportioned text in Confluence.
6. **No Cluttered Labels or Overlapping Text:** Omit stereotypes (`<<impacted>>`, `<<service>>`) and status tags (`(New Component)`, `(Existing Platform)`) from component boxes and arrow labels. Multi-line edge labels must be wrapped at ~24 characters.
7. **No Leaked Tags:** Never emit `<#ghost>` or unsupported formatting tags into Confluence macros. Component and connection classification is handled by the bottom legend.
8. **Simplified Technical English (ASD-STE100):** Short sentences, active voice, and clear technical descriptions.
