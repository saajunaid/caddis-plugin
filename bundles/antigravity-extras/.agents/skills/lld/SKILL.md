---
name: lld
description: Generates Lower-Level Design (LLD) Markdown documentation and converts to Confluence Storage Format XHTML with native PlantUML diagrams and auto-generated legends.
---

# Lower-Level Design (LLD) Authoring Skill

## Overview
This skill generates Lower-Level Design (LLD) documents for enterprise application fleet systems. It documents the complete internal engineering workings: hosts, services, internal API endpoints, physical database schemas, stored procedures, ETL batches, background worker threads, data contracts, and failure recovery modes. It converts documents to Confluence Storage Format XHTML using native PlantUML (`<ac:structured-macro ac:name="plantuml">`) diagrams with high contrast, crisp 200 DPI vector rendering, dynamic orientation, auto-wrapped labels, and clean embedded Creole legends.

## Mandatory Workflow Steps

### Step 1: Deep Codebase and Schema Dissection
Analyze the target codebase and underlying database environment to dissect:
- Physical hosting, processes, service managers (NSSM, systemd), ports, and thread loops.
- All ETL scripts, batch commands, cron/scheduler configurations, source/target tables, row volumes, and idempotency logic.
- Stored procedures: signatures, parameters, join logic, analytical thresholds, and exception outputs.
- Background workers, polling loops, watermark synchronization, and caching tiers.
- UI-to-SQL query lineage: map UI screens and routes to stable query identifiers (`QRY-*`) and database objects.

### Step 2: Component & Interface Classification Interview (Grill-Me)
**MANDATORY GATE:** Before generating architecture diagrams or drafting the LLD, the agent **MUST** present the discovered internal components (`SYS_Lxx`) and internal interfaces (`INT_Lxx`) to the user and interview them to confirm classifications:
1. **Internal Component Classification:**
   - Which internal components are **New / Impacted** (`Impacted = Yes`, red styling)?
   - Which components represent pre-existing external fleet databases or services (`Impacted = No`, blue styling)?
2. **Internal Interface Classification:**
   - Confirm which internal connections represent **New Connectivity** (`#DC2626` Red) vs **Existing Connectivity** (`#16A34A` Green).
3. Present clear recommendations based on codebase findings, allowing the user to confirm or adjust classifications in a single interactive turn.

### Step 3: Markdown Document Authoring
Draft the canonical LLD Markdown file following the standard 7-section structure. Adhere strictly to the engineering depth requirements below.

### Step 4: Confluence XHTML Conversion & Verification
Convert the Markdown to Confluence Storage Format XHTML using `scripts/convert_doc_to_confluence.py`. Verify well-formed XML and correct PlantUML macro rendering.

---

## Scope and Core Responsibilities (Detailed Engineering)

1. **Internal Architecture & Services:**
   - Host allocations, services, ports, execution threads, background loop intervals, and memory management.
   - Internal API route specifications, request/response models, middleware, and dependency injection.
2. **Exhaustive ETL & Ingestion Pipeline Dissection:**
   - Document every data pipeline script, source tables, destination staging tables, execution schedules (e.g. daily 06:00, monthly 20th), record volumes, idempotency patterns (e.g. delete-insert), and shared audit tables (e.g. `ETL_AUDIT_LOG`).
3. **Exhaustive Stored Procedure & Analytical Engine Dissection:**
   - Catalog all validation procedures / calculation engines.
   - For every stored procedure, specify: exact signature, input parameters, join/comparison logic, analytical tolerances/thresholds, discrepancy codes, and target tables written to.
4. **Continuous Summary Refresher & Watermark Synchronization:**
   - Document background polling workers, polling intervals (e.g. 300s), watermark queries (`SELECT MAX(run_id)...`), atomic summary rollups, watermark commits, and cache invalidation mechanisms.
5. **UI-to-SQL Query Lineage Specification:**
   - Exhaustive query lineage matrix mapping UI screens to stable query identifiers (`QRY-*`), API endpoints, repository methods, and source database tables.
6. **Mandatory Detailed Technical Sections (Non-Negotiable):**
   - **Operational Process Flow:** Multi-stage batch, validation, refresh, and serving pipeline with colorful Mermaid flowchart.
   - **End-to-End Operational Sequence Diagram:** Comprehensive technical sequence between Schedulers, Batch Runners, Databases, Secondary Systems, Background Refreshers, API Routers, and Frontends.
   - **Detailed Solution Architecture Landscape:** Internal subsystem architecture diagram with `SYS_Lxx` component IDs and `INT_Lxx` interface sequences, supported by Internal Applications Table and Internal Interfaces Table.
   - **End-to-End Database and Data Processing Pipeline:** Staging, validation, mart rollup, and API extraction data flow stages.
   - **End-to-End Database Lineage Specification:** Complete lineage matrix tracing Functional Domain -> Source Feeds -> Staging Tables -> Transformation Stored Procedures -> Destination Summary Tables -> API Endpoint Routes -> Primary UI Surfaces.
7. **Mermaid Diagram Standards (Expert Systems Architect & Mermaid Designer):**
   Render highly professional, visually balanced, and easily readable system architecture diagrams using Mermaid.js markdown blocks. Avoid cluttered, sprawling layouts by enforcing structural constraints and optimized styles.

   **🎨 Design & Styling Principles:**
   - **Color Palette & Semantic Styling (Standard/Impact/Existing):**
     - Use desaturated, modern executive colors. Do not use highly saturated primary colors.
     - Define exactly 3-4 standard semantic class styles at the top of every diagram:
       - `existingStyle`: Clean Blue (`fill:#EFF6FF,stroke:#2563EB,stroke-width:2px,color:#1E40AF`) for legacy/established components.
       - `newStyle`: Warm Red/Crimson (`fill:#FEF2F2,stroke:#DC2626,stroke-width:2px,color:#991B1B`) for greenfield/new components.
       - `impactedStyle`: Amber/Gold (`fill:#FFFBEB,stroke:#D97706,stroke-width:2px,color:#92400E`) for modified/impacted systems.
     - Apply classes consistently to the nodes using the triple colon notation (e.g., `NodeName:::newStyle`).
   - **Diagram Scalability Settings (Initialization Block):**
     - Always prepend diagrams with a configuration initialization block to control sizing and font scales:
       ```mermaid
       %%{init: { 
         'theme': 'default', 
         'themeVariables': { 'fontSize': '14px', 'subgraphTitleSize': '16px' }, 
         'flowchart': { 'useMaxWidth': false, 'htmlLabels': true, 'curve': 'basis' } 
       } }%%
       ```
   - **Readable Text Wrapping:**
     - Never let a single node have a long horizontal text block. Use `<br/>` tags to stack text vertically.
     - Format nodes with clear visual hierarchy: Use bolding for titles, bracket notation for IDs, and italics for status:
       `NodeName["📅 <b>Windows Scheduler</b><br/>[SYS_03]<br/><i>New Component</i>"]`

   **📐 Layout & Real Estate Rules:**
   - **The 3-Column Kanban Layout (Side-by-Side):**
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
   - **The Two-Line Grid Layout (Row Stacking):**
     - When a 3-pillar horizontal layout spans too wide, stack them into rows by setting the top-level structure to Top-to-Bottom (`flowchart TD`).
     - Group the lower pillars (Phase 2 and Phase 3) side-by-side inside a helper subgraph container that uses `direction LR`. This forces Phase 2 to wrap onto a new line directly below Phase 1.
   - **Component Types:**
     - Use standard flowchart shapes to represent structural entities:
       - `[(Database Node)]` for persistent storage, tables, or file outputs.
       - `["Application Node"]` for processing scripts, APIs, or services.
       - `["🖥️ UI Node"]` for user interfaces.
8. **Diagram Rendering and Styling (PlantUML Native Engine in Confluence):**
   - Confluence rendering uses native `<ac:structured-macro ac:name="plantuml">` blocks requiring zero page attachments.
   - Standard parameters: `scale 1.2` for flowcharts, `scale max 2000 width` for sequence diagrams, and `skinparam defaultFontSize 11` (no `skinparam dpi 200` to prevent image blowout) to guarantee crisp rendering, neat proportioning, and sharp text without oversized canvas stretching.
   - Spacing: `skinparam ranksep 28` and `skinparam nodesep 24`, package `Padding 10` for tight, balanced whitespace without excessive canvas stretching.
   - Natural curved splines: Do not force `skinparam linetype ortho` or `polyline` which distort canvases. Natural curved spline arrows route cleanly without box stretching.
   - Zero label clutter: Omit stereotypes (`<<impacted>>`, `<<service>>`, etc.) and verbose status annotations (`(New Component)`, `(Existing Platform)`, `[New]`, `[Existing]`) inside component boxes or on connection labels. Component status is communicated cleanly through color coding and the bottom legend.
   - Automatic edge label wrapping: Labels are wrapped at ~24 characters to prevent horizontal text collision with component bounding boxes.
   - Bold container headers: Package and cluster titles are rendered in bold font (`package "<b>Title</b>"`).
   - Component styling: Colored backgrounds and distinct borders with `skinparam rectangle { BorderThickness 1.5 }` and `skinparam database { BorderThickness 1.5 }`:
     - New / Impacted Components: `rectangle "<b>Title</b>\n[SYS_xx]" as Alias #FEF2F2;line:DC2626` (or `database ... #FEF2F2;line:DC2626`) for a crimson red border.
     - Existing Components: `rectangle "<b>Title</b>\n[SYS_xx]" as Alias #EFF6FF;line:2563EB` (or `database ... #EFF6FF;line:2563EB`) for a deep blue border.
   - Dynamic orientation: Let the model and skill decide whether Left-to-Right (`flowchart LR`) or Top-to-Bottom (`flowchart TD`) or mixed layout is best based on component count, layer depth, and readability. Avoid stretching wide multi-layer pipelines horizontally across thin ribbons.
   - Connectivity color coding:
     - New / Impacted connectivity: Solid Red (`#DC2626` / `━━━━▶`).
     - Existing connectivity: Solid Blue (`#2563EB` / `━━━━▶`).
     - Cross-package and feedback connectors: Append `norank` (`-[color,norank]right->`, `-[color,norank]up->`) to prevent vertical rank collapse in horizontal flows and tier scrambling in layered architectures.
   - Arrow sequence numbering: Place sequence numbers and interface IDs clearly on arrow labels (e.g. `SYS_L01 -->|"INT_L01 [1]: Pre-Flight Audit Query"| SYS_L02`).
   - Clean embedded Creole legend: Flowchart and architecture diagrams automatically include an embedded PlantUML Creole table legend explaining connection and component markers. Omit legend on sequence diagrams.
9. **Technical Metadata:**
   - Technical metadata (system name, engineering lead, target audience, version) is preserved in LLD documents.
10. **Dynamic Frontmatter Model:**
    - The Markdown frontmatter `Creating Model:` must dynamically capture whatever model is executing the task (e.g. `gemini-3.8-flash`), never hardcoded.

---

## Standard LLD Document Structure (Markdown)
Every LLD document must follow this standardized structure:

```markdown
---
type: design
status: current
feature: <app>-lld
creation-agent: caddis
Original Author: Platform Engineering
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <active model ID, e.g. gemini-3.8-flash>
---

# Lower-Level Design: <Application Name>

## Technical Metadata
- **System Name:** <Application Name> (Internal Engineering Specification)
- **Document Version:** 1.0.0
- **Document Status:** Current Engineering Specification
- **Engineering Lead:** Development & Platform Engineering Team
- **Target Audience:** Software Engineers, Database Administrators, Platform Reliability Engineers

---

## 1. System Components and Service Topology
- 1.1 Physical Hosting and Runtime Environment (Hostnames, IPs, OS, service manager like NSSM/systemd, ports)
- 1.2 Component Architecture and Process Model (Web server, async workers, refresher services, thread loops)

## 2. Operational Process Flow and Sequence Architecture
- 2.1 Operational Process Flow (Mermaid flowchart with classDef styling showing batch ingestion, validation, refresh, and serving stages)
- 2.2 End-to-End Operational Sequence Diagram (Mermaid sequence diagram detailing technical participants)

## 3. Detailed Solution Architecture Landscape
- 3.1 Solution Architecture Landscape (Mermaid topology diagram with internal SYS_Lxx nodes and INT_Lxx arrows)
- 3.2 Internal Applications and Subsystems Overview (Table: ID [SYS_Lxx], Application / Component, Application Type, Description, Impacted [Yes/No])
- 3.3 Internal Interfaces (Table: ID [INT_Lxx], Type / Protocol, From, To, Connectivity [Connectivity Exists / New Connectivity])

## 4. End-to-End Database and Data Processing Pipeline
- 4.1 Database Pipeline Architecture (Mermaid flowchart with classDef styling)
- 4.2 Ingestion & ETL Pipelines (Detailed breakdown of all ETL scripts, schedules, sources, staging tables, volumes, idempotency)
- 4.3 Stored Procedures and Analytical Logic Engine (Exhaustive catalog with parameters, join logic, tolerances, output tables)
- 4.4 Continuous Summary Refresher (Background loop, watermark polling, atomic rollups, cache invalidation)
- 4.5 End-to-End Database Lineage Specification (UI-to-SQL Query Matrix: Query ID [QRY-*], UI Screen, Route, Repo, Tables, Scope)

## 5. Physical Database Architecture
- 5.1 Host and Database Instances (Connection pools, drivers, timeouts, read/write segregation)
- 5.2 Schema and Table Definitions (Full physical tables, primary keys, indexes, foreign keys, partition strategy)

## 6. API Specifications and Internal Contracts
- 6.1 Backend Router Structure and Endpoint Inventory (Paths, HTTP methods, route handlers, middleware)
- 6.2 Data Transfer Objects (DTOs) and Validation Schemas (Pydantic models, request/response payloads)
- 6.3 Error Handling and Database Session Management

## 7. Reliability, Operational Runbooks, and Recovery
- 7.1 Health Checks and Diagnostic Endpoints
- 7.2 Failure Recovery and Re-run Idempotency
```

## Conversion Workflow
1. Write the canonical LLD Markdown file to `docs/<app>/<app>-lld.md`.
2. Run the conversion script:
   ```powershell
   python scripts/convert_doc_to_confluence.py docs/<app>/<app>-lld.md --output docs/<app>/<app>-lld.html --diagram-type plantuml
   ```
3. Verify that the output validates as well-formed XML and contains `<ac:structured-macro ac:name="plantuml">` blocks with crisp 200 DPI styling, 880px max width, centered alignment, wrapped edge labels, and embedded Creole legend.
