---
description: Generate High-Level Design (HLD) Markdown documentation and Confluence XHTML with native PlantUML diagrams.
stage: plan
---

# /hld Command

Run the High-Level Design (HLD) generation procedure:

1. **Research & Scope Analysis:**
   - Review target application architecture, user navigation surfaces, and primary databases.
   - Enforce HLD boundaries: exclude internal API routes, low-level stored procedures, and detailed ETL scripts.
   - Use high-level reporting summary tables and domain entities only.

2. **Component & Interface Classification Interview (Grill-Me):**
   - **MANDATORY GATE:** Present discovered systems (`SYS_xx`) and interfaces (`INT_xx`) to the user.
   - Ask the user to confirm/clarify:
     - Which systems/components are Existing fleet infrastructure (`Impacted = No`, Blue `#1D4ED8`) vs New / Impacted (`Impacted = Yes`, Red `#DC2626`)?
     - Which interfaces are Existing Connectivity (Green `#16A34A`) vs New Connectivity (Red `#DC2626`)?
   - Formulate recommendations from codebase discovery and seek user sign-off in a single interactive turn.

3. **Author Canonical Markdown Document:**
   - Create document at `docs/<app>/<app>-hld.md`.
   - Adhere strictly to the standard HLD structure.
   - **Do not synthesize or fabricate "Target Architecture", "Target State Roadmap", or "Security Topology" sections/diagrams** when there are no notes mentioning future architecture and the user does not request them. Only include them when explicitly requested by the user or specified in existing project notes as future work.
   - Place the core architecture diagram in Section 4 titled `### 4.1 Solution Design and Architecture` under `## 4. Solution Architecture Landscape`. Do not use `System Topology Architecture Diagram` or place it in Section 2.
   - Represent domain data models in Section 5 (`### 5.2 Domain Entity Model`) using Mermaid `classDiagram` or `erDiagram` syntax, converted natively to PlantUML.
   - Ensure Mermaid diagrams depict automated schedulers as system participants, not human actors.
   - Use colorful, professional Mermaid diagrams with explicit `classDef` styling palettes (no raw yellow boxes).
   - Use ASD-STE100 Simplified Technical English: active voice, short sentences, zero em-dashes.

4. **Convert to Confluence Storage Format XHTML:**
   - Run the PlantUML-enabled converter:
     ```powershell
     python scripts/convert_doc_to_confluence.py docs/<app>/<app>-hld.md --output docs/<app>/<app>-hld.html --diagram-type plantuml
     ```
   - Verify that all diagrams are converted to native `<ac:structured-macro ac:name="plantuml">` blocks with scale 1.2, natural splines, auto-wrapped edge labels, crimson red borders on impacted components, and embedded Creole legends.
   - Ensure multi-stage operational flows use horizontal side-by-side stages (`flowchart LR`) and architecture topologies follow clean 3-tier hierarchies (`flowchart TD`).
   - Verify that output validates as well-formed XML.
