---
name: data-lineage
description: Generate End-to-End Data Lineage and Telemetry Specification Markdown and Confluence XHTML for fleet observability.
---

# /data-lineage Command

Run the End-to-End Data Lineage generation procedure:

1. **Target Architecture & Telemetry Discovery:**
   - Scan target application routes, pages, and controllers.
   - Trace API handlers down to physical tables, views, and columns.
   - Identify database server stored procedures, batch scripts, and scheduled SQL Agent jobs that populate each dataset.
   - Cross-reference estate configuration catalogs to identify hostnames, IPs, ports, and synthetic health probe endpoints.

2. **Author Canonical Markdown Document:**
   - Create document at `docs/<app>/<app>-data-lineage.md`.
   - Adhere strictly to the standard 5-section lineage structure:
     1. Physical Estate & Host Infrastructure (servers, IPs, ports, database instances, access methods).
     2. End-to-End Dependency & Impact Flowchart (vibrant Mermaid flowchart from feeds down to UI surfaces).
     3. Comprehensive 7-Column Lineage Matrix (`App`, `UI Page`, `API Route`, `Dataset`, `Producer`, `Database`, `Physical Host`).
     4. Stored Procedures & Producer Execution Catalog (schedules, triggers, parameters, source and target tables).
     5. Telemetry Ingestion Contract (machine-readable JSON target graph).
   - Use ASD-STE100 Simplified Technical English: active voice, short sentences, zero em-dashes.

3. **Convert to Confluence Storage Format XHTML:**
   - Run the PlantUML-enabled converter:
     ```powershell
     python scripts/convert_doc_to_confluence.py docs/<app>/<app>-data-lineage.md --output docs/<app>/<app>-data-lineage.html --diagram-type plantuml
     ```
   - Verify that all diagrams convert to native `<ac:structured-macro ac:name="plantuml">` blocks with scale 1.2, natural splines, auto-wrapped edge labels, crimson red borders on impacted components, and embedded Creole legends.
   - Verify that output validates as 100% well-formed XML.
