---
name: hld
description: Generates High-Level Design (HLD) Markdown documentation and converts to Confluence Storage Format XHTML with native PlantUML diagrams and auto-generated legends.
---

# High-Level Design (HLD) Authoring Skill

## Overview
This skill generates High-Level Design (HLD) documents for enterprise application fleet systems. It produces human-readable, professional architectural documentation and converts them to Confluence Storage Format XHTML using native PlantUML (`<ac:structured-macro ac:name="plantuml">`) diagrams with high contrast, crisp 200 DPI vector rendering, dynamic orientation, auto-wrapped labels, and clean embedded Creole legends.

## Mandatory Workflow Steps

### Step 1: Deep Codebase and Architectural Discovery
Analyze the target codebase, configuration files, deployment scripts, database schemas, and external integrations to discover:
- Business initiative objectives and high-level workflows.
- Physical hosting environments, virtual machines, databases, and client surfaces.
- All interconnected systems, platforms, and third-party gateways.
- External network connectivity, protocols, ports, and batch schedules.

### Step 2: Component & Interface Classification Interview (Grill-Me)
**MANDATORY GATE:** Before generating diagrams or drafting documentation, the agent **MUST** present the discovered components and interfaces to the user and interview them to confirm lifecycle classifications:
1. **Component Classification:**
   - Which systems/components are **Existing** pre-production fleet infrastructure (`Impacted = No`)?
   - Which systems/components are **New** or **Impacted** by this solution (`Impacted = Yes`)?
2. **Interface Classification:**
   - Which interfaces are **Existing Connectivity** (pre-existing enterprise links, rendered in Green `#16A34A`)?
   - Which interfaces are **New Connectivity** (links created or modified for this initiative, rendered in Red `#DC2626`)?
3. Present clear recommendations based on codebase findings, allowing the user to confirm or adjust classifications in a single interactive turn.

### Step 3: Markdown Document Authoring
Draft the canonical HLD Markdown file following the standard 7-section structure. Adhere strictly to the scope rules below.

### Step 4: Confluence XHTML Conversion & Verification
Convert the Markdown to Confluence Storage Format XHTML using `scripts/convert_doc_to_confluence.py`. Verify well-formed XML and correct PlantUML macro rendering.

---

## Scope and Boundary Principles (Strict)

1. **High-Level Design Only:**
   - **Include:** Business initiative goals, high-level architecture topology, user surfaces, high-level database references, and security/privacy controls.
   - **DO NOT INCLUDE:**
     - Physical code repository locations, local filesystem folder paths (e.g. `E:\Projects\...`), or git repository URLs. HLD focuses strictly on logical solution architecture, business functions, and system interactions.
     - Internal application API routes or controller implementation details.
     - Stored procedure names, parameter lists, or SQL code.
     - Low-level ETL batch scripts, job schedules, or internal script arguments.
     - Low-level table schemas or physical column definitions.
2. **Strict Grounding - No Synthetic Target Architecture or Security Topology:**
   - **DO NOT synthesize or fabricate "Target Architecture", "Target State Roadmap", or "Security Topology" sections/diagrams** when there are no notes, documentation, or backlog items mentioning future architecture, and when the user has not explicitly requested them.
   - **Condition for Inclusion:** Only include a Target Architecture, Target State Roadmap, or future security topology section/diagram when:
     1. The user explicitly requests it, OR
     2. Existing repository documentation, PRDs, ADRs, or notes explicitly specify something to be done in the future.
   - When neither condition is met, omit these sections entirely. Do not invent speculative enterprise identity evolutions, automated operational integrations, or synthetic filesystem/host boundary diagrams. Document only the authenticated, current-state solution architecture and established security posture.
3. **Database Representation:**
   - Mention the physical database host and database name.
   - List high-level reporting summary tables or key domain mart entities only.
   - Low-level staging tables and stored procedures belong strictly in the Lower-Level Design (LLD).
4. **Sequence Diagrams:**
   - Automated schedulers (such as Windows Task Scheduler or cron) must be depicted as system components or lifeline participants, **NEVER** as human actors.
5. **Mermaid Diagram Standards (Expert Systems Architect & Mermaid Designer):**
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
6. **Diagram Rendering and Styling (PlantUML Native Engine in Confluence):**
   - Confluence rendering uses native `<ac:structured-macro ac:name="plantuml">` blocks requiring zero page attachments.
   - Standard parameters: `scale 1.2` for flowcharts, `scale max 2000 width` for sequence diagrams, and `skinparam defaultFontSize 11` (no `skinparam dpi 200` to prevent image blowout) to guarantee crisp rendering, neat proportioning, and sharp text without oversized canvas stretching.
   - Spacing: `skinparam ranksep 28` and `skinparam nodesep 24`, package `Padding 10` for tight, balanced whitespace without excessive canvas stretching.
   - Natural curved splines: Do not force `skinparam linetype ortho` or `polyline` which distort canvases. Natural curved spline arrows route cleanly without unnatural box stretching.
   - Zero label clutter: Omit stereotypes (`<<impacted>>`, `<<service>>`, etc.) and verbose status annotations (`(New Component)`, `(Existing Platform)`, `[New]`, `[Existing]`) inside component boxes or on connection labels. Component status is communicated cleanly through color coding and the bottom legend.
   - Automatic edge label wrapping: Labels are wrapped at ~24 characters to prevent horizontal text collision with component bounding boxes.
   - Bold container headers: Package and cluster titles are rendered in bold font (`package "<b>Title</b>"`).
   - Component styling: Colored backgrounds and distinct borders with `skinparam rectangle { BorderThickness 1.5 }` and `skinparam database { BorderThickness 1.5 }`:
     - New / Impacted Components: `rectangle "<b>Title</b>\n[SYS_xx]" as Alias #FEF2F2;line:DC2626` (or `database ... #FEF2F2;line:DC2626`) for a crimson red border.
     - Existing Components: `rectangle "<b>Title</b>\n[SYS_xx]" as Alias #EFF6FF;line:2563EB` (or `database ... #EFF6FF;line:2563EB`) for a deep blue border.
   - Connectivity color coding:
     - New / Impacted connectivity: Solid Red (`#DC2626` / `━━━━▶`).
     - Existing connectivity: Solid Blue (`#2563EB` / `━━━━▶`).
     - Cross-package and feedback connectors: Append `norank` (`-[color,norank]right->`, `-[color,norank]up->`) to prevent vertical rank collapse in horizontal flows and tier scrambling in layered architectures.
   - Dynamic layout heuristics:
     - **Operational Process / Lifecycle Flows**: Must use Left-to-Right (`flowchart LR`) layout organized into sequential multi-stage columns (`subgraph` packages with internal `direction TB`). Inter-stage transitions link horizontally across stages without pushing downstream packages downward (`norank` ranking in PlantUML). This creates a clean side-by-side kanban/phase layout that stays compact vertically.
     - **Solution Landscapes / Architecture Diagrams**: Must follow a clean 3-Tier Layered Hierarchy (`flowchart TD`) ordered along the natural dataflow:
       1. Top Tier: Presentation & Application Tier (Dashboards, APIs, Web UI - `direction LR`)
       2. Middle Tier: Automation & Enterprise Integration Tier (Orchestrators, Pipelines, Gateways, Core Services - `direction LR`)
       3. Bottom Tier: Core Data & Intelligence Platform (Databases, Marts, AI Reasoning Engines - `direction LR`)
       Arranging layers along this hierarchical flow ensures all downward dependency arrows travel cleanly and eliminates criss-crossing diagonal lines or backwards-pointing loops.
   - Arrow sequence numbering: Place sequence numbers and interface IDs clearly on arrow labels (e.g. `SYS_01 -->|"INT_01 [1]: SFTP Batch Transfer"| SYS_04`).
   - Clean embedded Creole legend: Flowchart and architecture diagrams automatically include an embedded PlantUML Creole table legend explaining connection and component markers. Omit legend on sequence diagrams and entity/class domain models.
   - **Entity-Relationship and Domain Class Models:** Use Mermaid `classDiagram` or `erDiagram` syntax under Section 5 (e.g. `### 5.2 Domain Entity Model`). The converter automatically transforms these into native PlantUML `@startuml ... class / entity ... @enduml` macros with scale 1.2, crisp borders, and full attribute rendering.
   - **Diagram Title & Section Placement:** The core solution architecture diagram must ALWAYS be titled `### 4.1 Solution Design and Architecture` under `## 4. Solution Architecture Landscape`. Never title it `System Topology Architecture Diagram` or place it in Section 2.
7. **No AI Traces and Clean STE:**
   - The HLD must contain zero hints or traces of AI generation (no model names, tool mentions, or meta-notices in the Confluence HTML).
   - Write in Simplified Technical English (ASD-STE100): short sentences, active voice, and clear technical descriptions.
   - Executive Metadata is omitted from the Confluence HTML view (metadata belongs in LLD).
8. **Dynamic Frontmatter Model:**
   - The Markdown frontmatter `Creating Model:` must dynamically capture whatever model is executing the task (e.g. `gemini-3.8-flash`), never hardcoded.

---

## Standard HLD Document Structure (Markdown)
Every HLD document must follow this standardized 8-section structure (exemplified by the gold standard reference implementation [`references/gold-standard-hld.md`](references/gold-standard-hld.md), shipped with this skill; read it before writing and match its structure, diagram styling, ID schemes and table columns):

```markdown
---
type: design
status: current
feature: <app>-hld
creation-agent: caddis
Original Author: Solutions Architecture
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: <active model ID, e.g. gemini-3.8-flash>
---

# High-Level Architecture (HLA): <Application Name>

## Document Information

### Version History
| Version | Date | Author | Description |
|---|---|---|---|
| 1.0 | <YYYY-MM-DD> | Solutions Architecture | Initial High-Level Architecture Draft |

---

## 1. Executive Summary
- 1.1 Initiative Goal
- 1.2 Solution Architecture Summary
- 1.3 Business Value & Operational Outcomes

## 2. Project Context and Scope
- 2.1 Background
- 2.2 Scope (In Scope / Out of Scope)
- 2.3 Architecture Boundaries and Key Assumptions

## 3. Solution Approach and Workflow
- 3.1 Operational Process Flow (Mermaid flowchart with classDef styles)
- 3.2 End-to-End Operational Sequence Diagram (Mermaid sequence diagram with system scheduler participant)

## 4. Solution Architecture Landscape
- 4.1 Solution Design and Architecture (Mermaid topology diagram with SYS_xx nodes and INT_xx arrows)
- 4.2 Applications and Components Overview
  - Summary Table columns: ID (SYS_xx), Application / Component, Application Type, Description, Impacted (Yes/No)
  - Detailed subsections for each component (4.2.1 .. 4.2.N)
- 4.3 Interfaces
  - Summary Table columns: ID (INT_xx), Type / Protocol, From, To, Connectivity (Connectivity Exists / New Connectivity)
  - Detailed subsections for each interface (4.3.1 .. 4.3.N)
- 4.4 Primary Production Navigation Surfaces (Operational domains and core views)
- 4.5 Auxiliary and Direct-URL Surfaces (Health, export, documentation endpoints)

## 5. High-Level Data and Storage Architecture
- 5.1 Host and Database/Storage Topology (Database instances, working storage layout)
- 5.2 Domain Entity Model (Mermaid classDiagram or erDiagram rendered as native PlantUML)
- 5.3 Output Channels, Summary Mart, or Caching Strategy (As applicable to the application architecture)

## 6. Security Architecture and Controls
- 6.1 Identity and Access Management (Authentication seams, roles, authorization boundaries)
- 6.2 Network Boundaries and Perimeter Controls (Subnets, ports, host environments)
- 6.3 Data Protection and Privacy (Encryption, sensitive data handling)
- 6.4 Auditability and Governance

## 7. Architecture Traceability Matrix
- 7.1 Initiative Requirements & Traceability (DO NOT include section 7.2 or any target roadmap unless explicitly requested by user or documented in notes)

## 8. Appendix
- 8.1 Terms and Definitions
- 8.2 Reference Documents
```

## Conversion Workflow
1. Write the canonical HLD Markdown file to `docs/<app>/<app>-hld.md`.
2. Run the conversion script:
   ```powershell
   python scripts/convert_doc_to_confluence.py docs/<app>/<app>-hld.md --output docs/<app>/<app>-hld.html --diagram-type plantuml
   ```
3. Verify that the output validates as well-formed XML and contains `<ac:structured-macro ac:name="plantuml">` blocks with scale 1.2 vector styling, centered alignment, wrapped edge labels, and embedded Creole legend.
