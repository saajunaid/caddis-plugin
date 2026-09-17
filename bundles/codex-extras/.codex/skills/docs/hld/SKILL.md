---
name: hld
description: Generates High-Level Design (HLD) Markdown documentation and converts to Confluence Storage Format XHTML with inline PlantUML macros.
---

# High-Level Design (HLD) Authoring Skill

## Overview
This skill generates High-Level Design (HLD) documents for enterprise application fleet systems and converts them to Confluence Storage Format XHTML with self-contained, inline PlantUML (`<ac:structured-macro ac:name="plantuml">`) diagrams.

## Scope and Boundary Principles (Strict)
1. **High-Level Design Only:**
   - Include: Business initiative goals, high-level architecture topology, user surfaces, high-level database references, security & network boundaries, and target state roadmap.
   - **DO NOT INCLUDE:**
     - Internal application API routes or controller implementation details.
     - Stored procedure names, parameter lists, or SQL code.
     - Low-level ETL batch scripts, job schedules, or internal script arguments.
     - Low-level table schemas or physical column definitions.
2. **Database Representation:**
   - Mention the physical database host and database name.
   - List high-level reporting summary tables or key domain mart entities only.
   - Low-level tables and stored procedures belong strictly in the Lower-Level Design (LLD).
3. **Sequence Diagrams:**
   - Automated schedulers (such as Windows Task Scheduler or cron) must be depicted as system components or lifeline participants, **NEVER** as human actors.
4. **Diagram Rendering and Orthogonal Connectors:**
   - Diagrams are converted to native Confluence PlantUML macros (`<ac:structured-macro ac:name="plantuml">`) using `skinparam linetype ortho`.
   - `skinparam linetype ortho` ensures that all arrows connecting boxes are strictly orthogonal (90-degree right angles, zero diagonal slants).
   - PlantUML renders inline upon copy-paste into Confluence with zero attachment access errors.
5. **No AI Traces and Clean STE:**
   - The HLD must contain zero hints or traces of AI generation (no model names, tool mentions, or meta-notices in the Confluence HTML).
   - Write in Simplified Technical English (ASD-STE100): short sentences, active voice, and clear technical descriptions.
   - Executive Metadata is omitted from the Confluence HTML view (metadata belongs in LLD).

## Standard HLD Document Structure (Markdown)
Every HLD document must follow this standardized 7-section structure:

```markdown
---
type: design
status: current
feature: <app>-hld
creation-agent: caddis
Original Author: Solutions Architecture
Creation Date: <YYYY-MM-DDTHH:MM:SSZ>
Creating Model: gemini-3.5-flash
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
- 3.1 Operational Process Flow (Mermaid flowchart)
- 3.2 End-to-End Operational Sequence Diagram (Mermaid sequence diagram with system scheduler participant)

## 4. Solution Architecture Landscape
- 4.1 Solution Design and Architecture (Mermaid topology diagram)
- 4.2 User Surfaces and Capabilities Overview (Summary table of primary operational interfaces)
- 4.3 High-Level Data Model and Summary Mart (High-level summary entities only, no stored procedures or DDL)
- 4.4 High-Level Data Flow and Integration (Mermaid data lineage flow)

## 5. Security Architecture and Controls
- 5.1 Identity and Access Management (Authentication seams, roles, authorization boundaries)
- 5.2 Network Boundaries and Perimeter Controls (Subnets, ports, host environments)
- 5.3 Data Protection and Privacy (Encryption, sensitive data handling)
- 5.4 Auditability and Governance

## 6. Target State Roadmap (Work In Progress)
- 6.1 Enterprise Identity Evolution
- 6.2 Automated Operational Integration

## 7. Appendix
- 7.1 Terms and Definitions
- 7.2 Reference Documents
```

## Conversion Workflow
1. Write the canonical HLD Markdown file to `docs/<app>/<app>-hld.md`.
2. Run the conversion script:
   ```bash
   python scripts/convert_doc_to_confluence.py docs/<app>/<app>-hld.md --output docs/<app>/<app>-hld.html
   ```
3. Verify that the output validates as well-formed XML and contains `<ac:structured-macro ac:name="plantuml">` blocks with `skinparam linetype ortho`.
