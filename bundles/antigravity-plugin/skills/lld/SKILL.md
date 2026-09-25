---
name: lld
description: Generate Lower-Level Design (LLD) Markdown documentation and Confluence XHTML with native PlantUML diagrams.
---

# /lld Command

Run the Lower-Level Design (LLD) generation procedure:

1. **Detailed Technical Discovery:**
   - Scan physical hosts, service managers (NSSM, systemd), environment configurations, and ports.
   - Extract internal API routes, controllers, middleware, and dependency injection patterns.
   - Inspect database schemas, tables, views, primary keys, and index configurations.
   - Catalog stored procedures (`usp_*`), parameter lists, analytical logic flows, and discrepancy output structures.
   - Map ETL scripts, daily/monthly cron schedules, record volumes, idempotency logic, and shared audit tables (e.g. `ETL_AUDIT_LOG`).
   - Map background refresher loops, polling intervals, watermark sync, and caching tiers.
   - Map UI screens to stable query IDs (`QRY-*`), API endpoints, repository methods, and source tables.

2. **Component & Interface Classification Interview (Grill-Me):**
   - **MANDATORY GATE:** Present discovered internal components (`SYS_Lxx`) and internal interfaces (`INT_Lxx`) to the user.
   - Ask the user to confirm/clarify:
     - Which internal components are New / Impacted (`Impacted = Yes`, Red `#DC2626`) vs Existing fleet databases/services (`Impacted = No`, Blue `#1D4ED8`)?
     - Which interfaces are Existing Connectivity (Green `#16A34A`) vs New Connectivity (Red `#DC2626`)?
   - Seek user sign-off in a single interactive turn before drafting diagrams.

3. **Author Canonical Markdown Document:**
   - Create document at `docs/<app>/<app>-lld.md`.
   - Adhere strictly to the standard LLD structure including the 5 mandatory technical sections:
     1. Operational Process Flow (multi-stage batch, validation, refresh, and serving pipeline)
     2. End-to-End Operational Sequence Diagram (technical interaction sequence)
     3. Detailed Solution Architecture Landscape (`SYS_Lxx` components, `INT_Lxx` interfaces, Applications and Interfaces tables)
     4. End-to-End Database and Data Processing Pipeline (staging, validation, mart rollup, API extraction)
     5. End-to-End Database Lineage Specification (complete domain -> source -> staging -> SP -> mart -> API -> UI matrix)
   - Dissect every ETL pipeline with schedules, row volumes, and idempotency.
   - Detail stored procedures catalog with parameters, join logic, and thresholds.
   - Use colorful, professional Mermaid diagrams with explicit `classDef` styling palettes (no raw yellow boxes).
   - Use ASD-STE100 Simplified Technical English: active voice, short sentences, zero em-dashes.

4. **Convert to Confluence Storage Format XHTML:**
   - Run the PlantUML-enabled converter:
     ```powershell
     python "${CLAUDE_PLUGIN_ROOT}/scripts/convert_doc_to_confluence.py" docs/<app>/<app>-lld.md --output docs/<app>/<app>-lld.html --diagram-type plantuml
     ```
   - Verify that all diagrams are converted to native `<ac:structured-macro ac:name="plantuml">` blocks with scale 1.2, natural splines, auto-wrapped edge labels, crimson red borders on impacted components, and embedded Creole legends.
   - Verify that output validates as well-formed XML.
