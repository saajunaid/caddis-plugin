---
description: Generate Lower-Level Design (LLD) Markdown documentation and Confluence XHTML with Draw.io diagrams.
stage: plan
---

# /lld Command

Run the Lower-Level Design (LLD) generation procedure:

1. **Detailed Technical Discovery:**
   - Scan physical hosts, service managers (NSSM, systemd), environment configurations, and ports.
   - Extract internal API routes, controllers, middleware, and dependency injection patterns.
   - Inspect database schemas, tables, views, primary keys, and index configurations.
   - Catalog stored procedures (`usp_*`), parameter lists, business logic flows, and return codes.
   - Map batch ingestion scripts, command-line arguments, and background refresher polling loops.

2. **Author Canonical Markdown Document:**
   - Create document at `docs/<app>/<app>-lld.md`.
   - Adhere strictly to the standard 7-section LLD structure.
   - Detail every stored procedure, table, ETL job, and endpoint contract.
   - Include detailed Mermaid sequence, flowchart, and component interaction diagrams.
   - Use ASD-STE100 Simplified Technical English: active voice, short sentences, zero em-dashes.

3. **Convert to Confluence Storage Format XHTML:**
   - Run the Draw.io-enabled converter:
     ```bash
     python scripts/convert_doc_to_confluence.py docs/<app>/<app>-lld.md --output docs/<app>/<app>-lld.html
     ```
   - Verify that all diagrams are converted to native `<ac:structured-macro ac:name="drawio">` blocks.
   - Verify that output validates as well-formed XML.
