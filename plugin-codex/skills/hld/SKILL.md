---
name: hld
description: Generate High-Level Design (HLD) Markdown documentation and Confluence XHTML with Draw.io diagrams.
---

# /hld Command

Run the High-Level Design (HLD) generation procedure:

1. **Research & Scope Analysis:**
   - Review target application architecture, user navigation surfaces, and primary databases.
   - Enforce HLD boundaries: exclude internal API routes, low-level stored procedures, and detailed ETL scripts.
   - Use high-level reporting summary tables and domain entities only.

2. **Author Canonical Markdown Document:**
   - Create document at `docs/<app>/<app>-hld.md`.
   - Adhere strictly to the standard 7-section HLD structure.
   - Ensure Mermaid diagrams depict automated schedulers as system participants, not human actors.
   - Use ASD-STE100 Simplified Technical English: active voice, short sentences, zero em-dashes.

3. **Convert to Confluence Storage Format XHTML:**
   - Run the Draw.io-enabled converter:
     ```bash
     python scripts/convert_doc_to_confluence.py docs/<app>/<app>-hld.md --output docs/<app>/<app>-hld.html
     ```
   - Verify that all diagrams are converted to native `<ac:structured-macro ac:name="drawio">` blocks.
   - Verify that output validates as well-formed XML.
