---
name: confluence-hla
description: Author enterprise High-Level Architecture (HLA) documents in Simplified Technical English and generate Confluence Storage Format XHTML with self-contained PlantUML diagrams, wrapped tables, and zero AI fingerprints. Use when creating high-level architecture designs, architecture documentation for Confluence, or converting markdown architecture to Confluence storage format.
---

# Confluence High-Level Architecture (HLA) Authoring Skill

A cross-agent skill for **Claude Code**, **OpenAI Codex CLI**, and **Antigravity (`agy`)** to research systems, discover data pipelines, author enterprise-grade High-Level Architecture (HLA) documents, and export them directly into clean, self-contained **Confluence Storage Format XHTML** with native PlantUML macros.

---

## 1. Core Principles

1. **Simplified Technical English (ASD-STE100 Style):**
   - Short sentences (under 20 words where possible).
   - Active voice ("The worker queries telemetry" rather than "Telemetry is queried by the worker").
   - Clear, everyday technical words; one concept per sentence.
   - **CRITICAL:** Apply this style naturally. **NEVER** write notices, disclaimers, or metadata banners into the document stating that it was written in Simplified Technical English or ASD-STE100.
2. **Zero AI Fingerprints, Zero Em-Dashes & Anti-Slop Discipline:**
   - **NEVER use em-dashes (`—`) or en-dashes (`–`):** Em-dashes are the single most prominent dead giveaway of LLM-generated prose. Enterprise solutions architects do not write em-dashes. Use standard colons (`:`), hyphens (`-`), parentheses (`(...)`), or separate sentences instead.
     - *Banned:* `High-Level Architecture (HLA) — AppointmentAssist`
     - *Required:* `High-Level Architecture (HLA): AppointmentAssist`
     - *Banned:* `- **Cancel Appointment — Area Outage:** ...`
     - *Required:* `- **Cancel Appointment (Area Outage):** ...`
     - *Banned:* `The system — which runs on Windows Server — polls telemetry.`
     - *Required:* `The system runs on Windows Server. It polls telemetry.`
   - **Absolute Ban on AI Slop Buzzwords and Hyperbolic Clichés:**
     - *Banned verbs & nouns:* `delve`, `tapestry`, `plethora`, `beacon`, `game-changer`, `testament`, `revolutionize`, `cornerstone`, `leverage` (use `use`, `read`, or `query`), `foster`, `streamline`, `harnessing`, `embark`, `landscape` (in non-geographical contexts).
     - *Banned adjectives:* `pivotal`, `crucial`, `meticulous`, `seamless`, `holistic`, `robust`, `comprehensive`, `cutting-edge`, `paramount`, `vibrant`.
     - *Banned transitions & framing:* `Furthermore`, `Moreover`, `In conclusion`, `It is important to note`, `Let's explore`, `Here is a breakdown:`, `Key takeaways:`, `Summary:`.
   - **Clean ASCII Punctuation:**
     - Never use curly / smart quotes (`“`, `”`, `‘`, `’`) — always use straight ASCII quotes (`"`, `'`).
     - Never use unicode bullet symbols (`•`) — always use standard markdown hyphens (`-`).
     - Never use backtick formatting on ordinary English nouns.
   - **Zero Meta-Commentary & Self-Referential Announcements:**
     - Never write phrases announcing what the document is doing (e.g., "In this document we delve into...", "As requested by the user...").
     - Start immediately with the title, status, metadata block, and executive overview.
   - **Zero Tool / Agent / Assistant / Model Self-Attribution:**
     - The final Confluence export must **NEVER** contain YAML frontmatter, agent attribution tags, model names, preparation notices, or document references that expose internal repository paths or harness tooling (`caddis`, `claude code`, `codex`, `antigravity`, `asd-ste100`).
     - Note: Production application components (such as a local LLM daemon running on an on-premises GPU server) are documented as objective production system components, but the HLA itself must never attribute its own authorship to AI.
   - **Automated Converter Enforcement:**
     - The converter script (`convert_hla_to_confluence.py`) enforces this automatically by stripping all em-dashes, en-dashes, smart quotes, and AI buzzwords during HTML export.
3. **Confluence Native Compatibility (Self-Contained PlantUML):**
   - Uses native Confluence Storage Format XHTML.
   - All tables wrapped with `<table class="wrapped">` and explicit `<colgroup>`.
   - Table of contents generated via `<ac:structured-macro ac:name="toc" ac:schema-version="1"/>`.
   - **Pure PlantUML:** Diagrams are rendered natively via Confluence PlantUML macros. No image uploads, attachments, or base64 data URIs are required—the generated HTML is 100% self-contained and ready for a single copy-paste into the Confluence Source Editor.
   - Guaranteed 100% valid XML parseable by the Confluence Source Editor.
4. **Mermaid & PlantUML Full-Text Fidelity (Zero Truncation Rule):**
   - In Markdown (`.md`), always wrap Mermaid text lines using explicit `<br/>` tags (maximum ~35 to 45 characters per line) across actors, notes, messages, node labels, and edge transitions.
   - Never allow unwrapped single-line strings to blow out diagram dimensions (>1200px) or truncate text in Git viewers, VS Code, or Confluence viewports.
   - The converter (`convert_hla_to_confluence.py`) dynamically maps `<br/>` to `\n` in PlantUML so that both formats render complete, untruncated text cleanly.

---

## 2. Standard High-Level Architecture (HLA) Sections

When authoring an HLA, strictly adhere to the following 7-section structure:

```
1. Executive Summary
   1.1 Initiative Goal
   1.2 Solution Architecture Summary (Functional layers)
   1.3 Business Value & Operational Outcomes
2. Project Context and Scope
   2.1 Background
   2.2 Scope (In Scope / Out of Scope)
   2.3 Architecture Boundaries and Assumptions
3. Solution Approach and Workflow
   3.1 Operational Process Flow (Step-by-step numbers)
   3.2 End-to-End Sequence Diagram (PlantUML sequence diagram with autonumber)
4. Solution Architecture Landscape
   4.1 Solution Design and Architecture (Compact topology and system boundary diagram)
   4.2 Applications and Components Overview (Wrapped table: ID, Name, Function, Technology, Hosting)
   4.3 Telemetry and Health Information APIs (Apigee / REST / RPC interfaces with target systems)
   4.4 Multi-Stage Summarization and Recommendation Pipeline (PlantUML multi-track data flow)
   4.5 End-to-End Database and Data Processing Pipeline (Mandatory discovery: Source DB -> Staging -> Input -> LLM -> Recs -> UI -> RLHF)
   4.6 Screener Feedback Service and Continuous Learning (RLHF) (Capturing human decisions, notes, and ground truth)
5. Security Architecture and Controls
   5.1 Identity and Access Management (Authentication protocols, RBAC, loopback binding)
   5.2 Network Boundaries and Perimeter Controls (Internal subnets, API gateway mediation, service accounts)
   5.3 Data Protection and Privacy (TLS 1.2+ transit, TDE at rest, payload minimization)
   5.4 Auditability and Operational Visibility (Trace logging, read-back verification, health checks)
6. Target State Roadmap (Work In Progress)
   6.1 Identity Evolution (e.g. Migration from NTLM to SAML 2.0 / OIDC SSO)
   6.2 Compute / Intelligence Evolution (e.g. Cloud API to On-Premises GPU / Gemma model)
7. Appendix
   7.1 Terms and Definitions (Wrapped table: Term, Definition)
   [Note: 7.2 References is kept in working Markdown but STRICTLY OMITTED from Confluence HTML]
```

### Key Section Authoring Guidelines:
- **Section 3.1 Operational Process Flow:** Document the flow using clean, continuous numbered text steps (`1. **Step Name:** ...`). Completely omit ASCII, unicode, or plain-text drawing boxes, which break formatting in Confluence. The accompanying sequence diagram in 3.2 provides the visual workflow.
- **Section 3.2 End-to-End Sequence Diagram:** Autonumber all interactions. Apply corporate palette classes (`clientStyle`, `serverStyle`, `appStyle`, `dataStyle`, `extStyle`). Wrap all participant names, notes, and message labels under 45 characters using `<br/>`.
- **Section 4.1 Solution Design and Architecture:** The standardized title is `4.1 Solution Design and Architecture` (do NOT use "System Topology and Network Boundaries"). Provides the compact component topology and network boundary diagram.
- **Tables:** All tables must be authored cleanly and converted into `<table class="wrapped">` with wrapped headers (`<th><p>Header</p></th>`) and wrapped table cells (`<td><p>Value</p></td>`).

---

## 3. High-Level Database and Data Processing Pipeline Discovery

Every application in the fleet follows an end-to-end data processing pipeline connecting operational database systems to machine learning intelligence and human screener decisions.

### 3.1 Formal Database Asset & Lineage Hierarchy Notation

Do not reference database tables in isolation. In enterprise architectures, tables reside within database catalogs hosted on specific physical or virtual servers, and are transformed or moved by explicit stored procedures or ETL engines running on designated hosts.

Always identify data pipeline entities using the full hierarchy:

```
Host[Server] -> Database[DB] -> Schema.Table[Table/View]
```

Every lineage stage must explicitly specify:
1. **Host Server:** The physical server, cluster, or virtual machine hosting the database engine (e.g., `IEROXAPP2`, `DBUATL01`).
2. **Database Catalog:** The database name (e.g., `DERBY`, `Customer_FeedBack_JIT`).
3. **Schema & Table / View:** The object namespace and name (e.g., `dbo.CASE_FAULTS`, `dbo.AppScreen_Pending_Calls`).
4. **Population / Transformation Mechanism:** The exact script, worker process, SSIS package, or stored procedure (`sp_...`) that populates or updates the table.
5. **Executing Host:** The exact machine where the ETL process, worker loop, or stored procedure runs (e.g., on the source database server itself, on a dedicated ETL host, or on the application server).
6. **Trigger / Cadence:** The execution trigger (e.g., scheduled cron, continuous polling loop, SQL Agent job, or UI event).
7. **Operational Payload:** The specific attributes, signals, or features passed through the stage.
8. **Downstream Consumer:** The next service, worker, or human actor reading the entity.

---

### 3.2 Active Database Discovery Protocol (Do NOT Rely Solely on Documentation)

Architecture documents and blueprints frequently become outdated or retain deprecated table names. The authoring agent must **actively inspect live configuration, code implementations, and database metadata**:

1. **Configuration & Credential Discovery Protocol:**
   - Scan `.env.*`, `config/.env*`, settings files, and connection strings.
   - **Credential Priority:**
     - **Priority 1 (Standard Fleet User):** Check for database credentials in `.env*`. The default enterprise user across fleet applications is typically `LinkedUser` (extract user, password, and port from config).
     - **Priority 2 (Ambient Windows Auth Fallback):** If `LinkedUser` is absent or connection fails, use ambient Windows Integrated Authentication (`Trusted_Connection=yes;` with the executing user's ambient Windows context). Never hardcode or pin personal usernames so that all team members can execute the skill seamlessly.
   - **Table Exclusion Rule:** Never map backup (`_BU`), partition (`_P1`, `_P2`, `_P\d+`), or historical replica tables. Exclude these during catalog queries and pipeline lineage synthesis to prevent noise.
   - Extract primary database host (`DB_HOST`), secondary/telemetry host (`DERBY_SERVER`), database names (`DB_NAME`, `DERBY_DATABASE`), ODBC driver, and trust settings.
   - Inspect Linked Server definitions (`sys.servers`) on connected hosts to identify cross-database federations and distributed queries.

2. **Active Database Metadata Catalog Querying & Job Discovery:**
   - When database connectivity or credentials exist, query the live database catalog:
     - `INFORMATION_SCHEMA.TABLES` & `sys.tables`: Verify that referenced tables physically exist and identify current row counts and schemas. Distinguish active production tables from retired, backup, or partition tables.
     - `INFORMATION_SCHEMA.ROUTINES` & `sys.procedures`: Identify active stored procedures (e.g., `dbo.usp_LoadCustomerTimeline`, `dbo.usp_CustomerTimeline_ApplyStage`, `dbo.sp_CASE_FAULTS`) that load, clean, or move data.
     - `INFORMATION_SCHEMA.VIEWS`: Inspect view definitions (`OBJECT_DEFINITION` / `VIEW_DEFINITION`) to understand joined tables and upstream dependencies.
     - `msdb.dbo.sysjobs` & `sysjobsteps`: Query live SQL Server Agent jobs to uncover exact scheduled batch loaders, step execution commands, and pipeline schedules.
     - Linked Server Probes (`sys.servers`): Inspect remote data sources and linked gateways (e.g. `SNOWFLAKE_GENESYS`).

3. **Pipeline Worker & Codebase Usage Verification:**
   - Trace background batch scripts, CLI runners, and worker loops (e.g., `run_e2e_now.py`, `appscreen_diagnostics_processor.py`, `pipeline_service.py`, `Run_Genesys_Core_Daily.ps1`).
   - Identify SQL queries, ORM models, and YAML query definitions (`queries_insights.yaml`, etc.) to verify which tables are actually active in application code.
   - **Purge Unreferenced Tables:** Do NOT map tables that merely exist in the database catalog if code analysis shows they are unreferenced by the application (e.g., legacy order tables, obsolete staging tables, or test fixtures).

4. **External ETL Bridges & Cross-Host Script Mapping:**
   - If data originates from an external SaaS/Cloud datashare (e.g., Snowflake, Genesys Cloud, Salesforce) and traverses an ETL gateway server, document the exact bridge scripts (e.g. `C:\Scripts\Genesys\*.py`, `.ps1`), schedule triggers, and target upsert mechanisms.

5. **User Consultation Rule for Remaining Gaps:**
   - If an upstream ETL or batch trigger cannot be confirmed from code or live database catalogs, do not invent names.
   - Summarize the verified facts and ask the user targeted questions to confirm the remaining operational links.

---

### 3.3 Fluid & Dynamic Pipeline Architecture Across Fleet Applications

Pipeline stages are **fluid, adaptive, and application-specific**. The authoring agent must **NOT** hardcode or assume the stage names of AppointmentAssist ("Source Trouble Tickets", "Appointment Staging", "Diagnostic Enrichment") across other fleet repositories. 

The pipeline stage count typically varies between **3 and 8 stages**, depending on the operational archetype of the system:

1. **Decision Support & Triage Systems (e.g., AppointmentAssist):**
   ```
   [1. Source Trouble Tickets] -> [2. Appointment Staging] -> [3. Diagnostic Enrichment] -> [4. AI Model Inference] -> [5. Recommendation Storage] -> [6. Dispatcher Review Queue] -> [7. RLHF Feedback Capture]
   ```
2. **Entity Resolution & Customer Profile Systems (e.g., Customer Profile Service / Timeline Engine):**
   - Must trace: Raw Telephony / CRM Staging -> Staging Swap Jobs -> Canonical Event Table (`dbo.CustomerTimelineEvent` / `EventDigest`) -> LLM Context Assembly (`dbo.CustomerLLMContext`) -> Standalone Inference Engine (Ollama / Local GPU) -> Summary Persistence -> Application UI.
3. **Real-Time Telemetry & Probing Systems (e.g., Telemetry Monitor / Probe Service):**
   ```
   [1. Network Telemetry Probing] -> [2. Time-Series Raw DB] -> [3. Threshold Rule Engine] -> [4. Anomaly Prediction Model] -> [5. Incident Dispatch Queue] -> [6. Operator Acknowledgment]
   ```
4. **ELT Data Warehouses & Analytics Marts:**
   ```
   [1. Operational DB Replicas] -> [2. CDC Staging Tables] -> [3. Conformance & Cleaning Mart] -> [4. Dimensional & Fact Tables] -> [5. BI Reporting Views]
   ```
5. **Document & Audio AI Processing Systems:**
   ```
   [1. Multi-Channel Document Ingest] -> [2. Raw File Object Store] -> [3. OCR & Audio Transcription] -> [4. Entity & Feature Extraction] -> [5. LLM Synthesis Engine] -> [6. Verification UI] -> [7. Ground Truth Annotation Store]
   ```

---

### 3.4 Standard Lineage Documentation Format (Section 4.5)

Section 4.5 of the High-Level Architecture must include:
1. **Narrative Overview:** Explanation of the end-to-end data lifecycle from input inception to output consumption or model fine-tuning.
2. **Horizontal Stacked Lineage Diagram (STRICT MAX 4 LAYERS):**
   - Mermaid in `.md`, PlantUML in Confluence HTML, showing Host, DB, Table, and Execution context.
   - **CRITICAL READABILITY CONSTRAINT:** Do NOT stack 7 or 8 vertical layers. Group stages into **at most 4 logical layers** (e.g., Layer 1: Upstream Ingestion & Raw Staging, Layer 2: Canonical Event Spine & Context Assembly, Layer 3: AI Inference & Persistence, Layer 4: Application Presentation Layer).
   - In each layer, arrange components horizontally (`direction LR` in Mermaid, `-right->` in PlantUML).
   - Connect layers with clean orthogonal, 90-degree lines.
3. **Structured 7-Column Lineage Table:**
   While the stage count and names adapt fluidly to the application, the table schema strictly maintains all 7 standard columns:

| Stage | Host Server | Database | Schema & Table / Entity | Population / Transformation Mechanism & Executing Host | Trigger / Schedule Cadence | Operational Payload & Downstream Consumer |
|---|---|---|---|---|---|---|
| **1. <Fluid Stage Name>** | Discovered host (`DB_HOST` or source) | Discovered DB / Catalog | Discovered tables or entities (`dbo.TABLE_NAME`) | Stored Procedure `dbo.usp_...` or ETL worker with executing host | Execution trigger (Continuous, Batch, Polling, Event) | Business data payload and the downstream consumer. |
| **2. <Fluid Stage Name>** | Discovered host | Discovered DB | Discovered staging table or queue | Ingestion worker or service with executing host | Polling interval or event stream | Staged records awaiting enrichment or transformation. |
| **3. <Fluid Stage Name>** | Processing host | Processing DB | Discovered feature table or dataset | Background worker, rule engine, or ETL script | Continuous polling loop or worker batch | Enriched attributes, normalized features, telemetry signals. |
| **4. <Fluid Stage Name>** | Inference host | Model Runtime | AI model or scoring service | Scoring engine or LLM service with executing host | Pipeline batch or on-demand event | Input prompts / features, outputs scores or recommendations. |
| **5. <Fluid Stage Name>** | Storage host | Output DB | Discovered results table or data mart | Persistence worker or database write | Post-processing transactional write | Final predictions, calculated indicators, alert records. |
| **6. <Fluid Stage Name>** | App Host / Browser | UI / App DB | User dashboard or operational queue | Web dashboard and backend REST API | User interaction or session lifecycle | Interactive record presentation, claim locks, advisory state. |
| **7. <Fluid Stage Name>** | Storage host | Target DB | Audit table, feedback store, or ground truth | Feedback API or audit worker with executing host | User action or system audit event | Operational decisions, override justifications, RLHF ground truth. |

> **Critical Rule:** Never copy AppointmentAssist stage names or tables into an HLA for another application. Inspect the application's actual tables, stored procedures, worker scripts, and `.env*` configurations to formulate domain-accurate stages.

---

### 3.5 Standalone Database Lineage Discovery Tool & CLI Switches

When you need to discover, map, or render the database lineage without executing a full HLA document generation cycle, use the dedicated lineage switches:

1. **Automated Repository Lineage Discovery (`discover_db_lineage.py`):**
   ```powershell
   python scripts/discover_db_lineage.py --target-dir <path-to-repo> [--output <report.md>] [--format md|json]
   ```
   - Automatically parses `.env*` files in the target repository.
   - Connects using `LinkedUser` or Windows Auth fallback.
   - Queries `INFORMATION_SCHEMA`, `sys.procedures`, and `sys.servers`.
   - Analyzes local codebase ORM models and background worker scripts.
   - Outputs the standardized 7-column lineage table and Mermaid diagram.

2. **Standalone Lineage Confluence Export (`--lineage-only` switch):**
   ```powershell
   python scripts/convert_hla_to_confluence.py <path-to-hla.md> --lineage-only [--output <lineage.html>]
   ```
   - Extracts only Section 4.5 from the HLA markdown file.
   - Emits self-contained Confluence Storage Format XHTML with the horizontal stacked PlantUML diagram and wrapped 7-column table.
   - Ideal for pasting solely the database pipeline architecture into team documentation.

---

## 4. PlantUML Diagram Standards & Material Design Palette

Confluence natively renders PlantUML without external image dependencies. Follow these styling and layout rules:

### 4.1 Google Material Design Corporate Palette

Never use default bright or garish PlantUML colors. Use muted corporate Material tones:

| Layer / Role | Hex Stroke | Hex Fill | Hex Text | Skinparam Target |
|---|---|---|---|---|
| **Client / User Web Browser** | `#3949AB` | `#E8EAF6` | `#1A237E` | `skinparam rectangle<<user>>` / `skinparam actor` |
| **Web Server / Reverse Proxy** | `#455A64` | `#ECEFF1` | `#263238` | `skinparam rectangle<<proxy>>` |
| **App Services / Worker** | `#00695C` | `#E0F2F1` | `#004D40` | `skinparam rectangle<<service>>` |
| **API Gateway (Apigee)** | `#E65100` | `#FFF3E0` | `#BF360C` | `skinparam queue<<gateway>>` |
| **Databases / Staging Queues** | `#0277BD` | `#E1F5FE` | `#01579B` | `skinparam database<<db>>` |
| **External Core Telemetry APIs** | `#C2185B` | `#FCE4EC` | `#880E4F` | `skinparam rectangle<<telemetry>>` |
| **Artificial Intelligence / LLM** | `#6A1B9A` | `#F3E5F5` | `#4A148C` | `skinparam rectangle<<model>>` |
| **Feedback / RLHF Audit** | `#2E7D32` | `#E8F5E9` | `#1B5E20` | `skinparam database<<rlhf_db>>` |

### 4.2 Layout Rules: 90-Degree Orthogonal Routing & Horizontal Stacked Layers

1. **Mandate 90-Degree Orthogonal Connections (`skinparam linetype ortho`):**
   - Always include `skinparam linetype ortho` in structural PlantUML diagrams (Topology, DB Lineage, Summarization Pipeline).
   - Standard Graphviz splines create curved diagonal arcs that slice through package boundaries. Orthogonal routing forces clean Manhattan routing: all connections consist strictly of horizontal and vertical segments with 90° bends.
   - Do NOT use `skinparam handwritten false` (triggers an unwanted yellow warning banner in modern PlantUML).

2. **Horizontal Flow Stacked in Functional Layers (DB Lineage Pipeline):**
   - Do NOT draw the DB Lineage pipeline as a single, tall vertical strip.
   - Structure the pipeline as horizontal flows stacked in functional layers:
     - **Layer 1 (Upstream Ingestion & Telemetry Enrichment):** `SourceDB` -> `PendingDB` -> `InputDB` connected via `-right->`.
     - **Layer 2 (AI Summarization & Triage Inference):** `LLM` -> `RecDB` connected via `-right->`.
     - **Layer 3 (Screener Review & Continuous Learning / RLHF):** `UI` -> `FeedbackDB` connected via `-right->`.
     - Stack layers vertically using `L1 -[hidden]down- L2` and `L2 -[hidden]down- L3`.
     - Connect inter-layer steps vertically: `InputDB -down-> LLM : 3. Case Prompts` and `RecDB -down-> UI : 5. Present to Queue`.
     - Keep edge labels concise (`1. Extract`, `2. Ingest`, `4. Predict`, `6. Feedback`) with `skinparam nodesep 80` to prevent label collision with box borders.

3. **Horizontal Flow with Stacked Multi-Track Inputs (Summarization Pipeline):**
   - Do NOT draw summarization pipelines as single vertical columns.
   - Structure as a 3-stage left-to-right pipeline:
     - **Stage 1 (Left):** Multiple input tracks (e.g., Track A: Network Health, Track B: Case History, Track C: Account Profile) stacked vertically (`TrackA -[hidden]down- TrackB`), with each track flowing horizontally left-to-right (`N1 -right-> N2 -right-> NSum`).
     - **Stage 2 (Middle):** Language Model Synthesis Engine (`LLMEngine`), receiving 90-degree orthogonal connections from each track's summary node (`NSum -right-> LLMEngine`, etc.).
     - **Stage 3 (Right):** Action Recommendation & Justification (`RecOutput`), receiving a horizontal connection from `LLMEngine`.

4. **Component-to-Component Connections in Solution Design & Architecture:**
   - Connect internal component nodes directly (e.g., `Worker -down-> SQL`, `Worker -down-> Apigee`, `Worker -right-> LLM`).
   - Do NOT connect package boundaries (e.g., `HostLayer -down-> MidLayer`), which inflates diagram bounding boxes and distorts routing.
   - Use `skinparam nodesep 60` and `skinparam ranksep 50` for comfortable whitespace.

5. **Diagram Parity: Mermaid in Markdown, PlantUML in Confluence:**
   - Source `.md` documents MUST use standard Mermaid diagrams (`flowchart LR/TD`, `sequenceDiagram`) with subgraphs reflecting the horizontal/stacked layout so they render natively in Git repositories and Markdown viewers.
   - The conversion tool (`convert_hla_to_confluence.py`) translates the diagrams into native Confluence PlantUML macros with orthogonal routing.

6. **Mermaid Diagram Text Wrapping & Truncation Prevention in Markdown Documents:**
   - **The Problem:** Standard Markdown viewers (GitHub, Azure DevOps, GitLab, VS Code, browsers) do NOT automatically wrap text inside Mermaid SVG elements (nodes, participant boxes, sequence notes, or message arrows). Long unwrapped strings stretch the SVG viewport to over 1500px, causing the diagram to truncate, hide labels off-screen, or force horizontal scrollbars.
   - **The Rule:** In all Mermaid diagrams within `.md` documents, **always enforce explicit linebreaks using `<br/>`** to keep lines compact (maximum ~35 to 45 characters per line):
     - **Sequence Participants & Actors:** Wrap role and system names across lines:
       ```mermaid
       actor Agent as Contact Center<br/>Agent
       participant UI as React 19 UI<br/>(Port 5701)
       database DB as SQL Server<br/>(IEGEW3CCDR01)
       ```
     - **Sequence Notes:** Wrap multi-line explanations:
       ```mermaid
       Note over DB: UiPath bot inbox loads Pega & ServiceNow<br/>reports into dbo.L30D* tables
       ```
     - **Sequence Message Labels:** Break long method descriptions, endpoints, or query details:
       ```mermaid
       ETL->>SF: Query Genesys calls & NPS<br/>via SNOWFLAKE_GENESYS (06:00 UTC)
       ```
     - **Flowchart Node Labels:** Structure host, database, tables, and jobs onto distinct lines:
       ```mermaid
       PegaStaging["Pega & ServiceNow via UiPath Inbox<br/>DB: SERVSIGHT<br/>dbo.L30DInteractions, Cases,<br/>dbo.L30DSNOW, Webforms<br/>[SQL Agent: Daily_AI_*_L30D]"]:::srcStyle
       ```
     - **Flowchart Edge Labels:** Wrap action descriptions to avoid wide gaps and node label collisions:
       ```mermaid
       LLMContext -->|"5. Poll Queue &<br/>Context (TDS 1433)"| AISummaryGen
       ```
   - **Converter Parity:** The Confluence converter (`convert_hla_to_confluence.py`) dynamically translates `<br/>` and `<br>` into `\n` in PlantUML sequence notes, messages, nodes, and edge labels, guaranteeing that both Markdown and Confluence XHTML display full, untruncated text with zero literal `<br/>` syntax errors.

7. **Legacy PlantUML Engine Compatibility (Stereotypes After Aliases):**
   - **The Problem:** Enterprise Confluence installations commonly run older PlantUML plugin versions (such as PlantUML 1.2022.1). In these versions, placing stereotypes immediately after element types (e.g. `rectangle<<user_ui>> "Label" as Alias`) triggers a fatal `Syntax Error?` on render.
   - **The Rule:** In all generated PlantUML code, **always place the stereotype at the very end after the alias**:
     ```plantuml
     rectangle "Contact Center Agent Browser\n(Customer Care & Retention Teams)" as Browser <<user_ui>>
     database "SQL Server Database (SERVSIGHT)\nEvent Spine & Context Store" as ServSightDB <<staging_db>>
     queue "Linked Server Gateway\n(SNOWFLAKE_GENESYS / MSDASQL)" as LinkedServer <<gateway>>
     ```
8. **Anti-Slop and Em-Dash Prohibition in PlantUML and Text:**
   - **Zero Em-Dashes (`—`) or En-Dashes (`–`):** Never include em-dashes in sequence diagram step descriptions, participant names, note boxes, flowchart nodes, or edge labels. Use colons (`:`) or hyphens (`-`).
   - **Clean ASCII Strings:** Do not use unicode bullet points (`•`), curved apostrophes (`’`), or fancy quotation marks (`“”`). Use ASCII straight apostrophes and quotes.
   - **No Markdown Wildcard Collisions:** Protect code identifiers containing asterisks (`*`) so they do not collide with italic formatting during export.

---

## 5. End-to-End Execution Workflow

### Step 1: Research the Target Codebase
Inspect the target codebase across five dimensions:
1. **User Interface:** Framework (React, Vue, Vite), authentication flow, role capabilities.
2. **Backend Services & Gateways:** Endpoints, worker tasks, integration gateway (Apigee, reverse proxy, loopback ports).
3. **Data & Pipeline Layer:** Discover the 7-stage DB pipeline (Source Host.DB.Table -> Staging -> Feature Input -> LLM -> Recommendations -> UI -> Feedback/RLHF). If unverified, ask the user.
4. **Integration APIs:** Telemetry endpoints, external incident checkers, OAuth2 flows.
5. **Security & Perimeter:** Authentication mechanism, RBAC groups, network boundaries, data minimization.

### Step 2: Author Markdown HLA (`docs/hla/<slug>/<slug>-hla.md`)
- Write using the 7-section canonical structure in Simplified Technical English.
- Author PlantUML (or Mermaid) diagram blocks for:
  1. Sequence diagram
  2. Solution Design and Architecture diagram (compact topology)
  3. Multi-track summarization pipeline
  4. End-to-end database and processing pipeline (Section 4.5)
- Document the Screener Feedback Service and RLHF loop (Section 4.6).
- Maintain internal working references under section 7.2.
- **Do NOT add any Document Notice or STE preamble.**
- **Strictly eliminate all em-dashes (`—`), en-dashes (`–`), smart quotes, and AI buzzwords.**

### Step 3: Convert to Confluence XHTML (`docs/hla/<slug>/<slug>-hla.html`)
Run the bundled converter script:
```powershell
python scripts/convert_hla_to_confluence.py docs/hla/<slug>/<slug>-hla.md
```
Or execute the script from the skill directory:
```powershell
python <path-to-skill>/scripts/convert_hla_to_confluence.py docs/hla/<slug>/<slug>-hla.md
```

The converter automatically:
1. Strips YAML frontmatter completely.
2. Strips `7.2 Reference Documents` and any internal repository paths.
3. Purges all preparation notices, STE statements, and AI/agent metadata.
4. Escapes all XML entities (`&amp;`, `&lt;`, `&gt;`) inside table cells and text.
5. Replaces Markdown TOC with native `<ac:structured-macro ac:name="toc"/>`.
6. Wraps tables in `<table class="wrapped">` with explicit column specifications.
7. Translates diagrams into self-contained PlantUML macros with Google Material Design corporate styling.
8. Converts all em-dashes (`—`) and en-dashes (`–`) to colons (`:`) or hyphens (`-`).
9. Normalizes smart quotes (`“”‘’`) and unicode bullets (`•`) to clean ASCII.
10. Scrubs prohibited AI buzzwords, hyperbolic clichés, and meta-commentary.
11. Validates XML well-formedness before saving.

### Step 4: Verification and Confluence Import
1. Verify terminal reports: `XHTML validation successful: Content is well-formed XML.`
2. Copy the entire contents of the `.html` file.
3. Open Confluence, create or edit the target architecture page, open the **Confluence Source Editor** (`< >` icon), paste the XHTML, and click **Apply**.
4. The page immediately renders all tables and PlantUML diagrams natively—zero attachments or extra setup required.
