---
name: lld
description: Generates Lower-Level Design (LLD) Markdown documentation and converts to Confluence Storage Format XHTML with inline PlantUML macros.
---

# Lower-Level Design (LLD) Authoring Skill

## Overview
This skill generates Lower-Level Design (LLD) documents for enterprise application fleet systems. It documents the complete internal engineering workings: hosts, services, internal API endpoints, database schemas, stored procedures, ETL batches, background worker threads, data contracts, and failure recovery modes. It converts documents to Confluence Storage Format XHTML with inline PlantUML (`<ac:structured-macro ac:name="plantuml">`) diagrams.

## Scope and Core Responsibilities (Detailed Engineering)
1. **Internal Architecture & Services:**
   - Host allocations, services, ports, execution threads, background loop intervals, and memory management.
   - Internal API route specifications, request/response models, middleware, and dependency injection.
2. **Database Engine & Physical Data Model:**
   - Database server names, schemas, physical table structures, columns, data types, primary keys, and indexes.
   - Comprehensive stored procedure inventory: input parameters, output datasets, business logic flows, and return codes.
3. **ETL & Batch Processing Pipelines:**
   - Staging scripts, pre-flight checks, batch orchestration commands (e.g., Windows Task Scheduler, cron, Airflow).
   - Validation pillars/rules breakdown with exact execution parameters, thresholds, and exception output structures.
4. **Diagram Rendering and Orthogonal Connectors:**
   - Diagrams are converted to native Confluence PlantUML macros (`<ac:structured-macro ac:name="plantuml">`) using `skinparam linetype ortho`.
   - `skinparam linetype ortho` ensures that all arrows connecting boxes are strictly orthogonal (90-degree right angles).
   - PlantUML renders inline upon copy-paste into Confluence with zero attachment access errors.
5. **Technical Metadata:**
   - Technical metadata (system name, engineering lead, target audience, version) is preserved in LLD documents.

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
Creating Model: gemini-3.5-flash
---

# Lower-Level Design: <Application Name>

## Technical Metadata
- **System Name:** <Application Name> (Internal Engineering Specification)
- **Document Version:** 1.0.0
- **Document Status:** Draft for Review
- **Engineering Lead:** Development & Platform Engineering Team
- **Target Audience:** Software Engineers, Database Administrators, Platform Reliability Engineers

---

## 1. System Components and Service Topology
- 1.1 Physical Hosting and Runtime Environment (Hostnames, IPs, OS, service manager like NSSM/systemd, ports)
- 1.2 Component Architecture and Process Model (Web server, async workers, refresher services, thread loops)
- 1.3 Detailed Service Interaction Diagram (Mermaid component flow)

## 2. API Specifications and Internal Contracts
- 2.1 Backend Router Structure and Endpoint Inventory (Paths, HTTP methods, route handlers, middleware)
- 2.2 Data Transfer Objects (DTOs) and Validation Schemas (Pydantic models, JSON contracts)
- 2.3 Error Handling, HTTP Status Codes, and Logging Protocols

## 3. Physical Database Architecture
- 3.1 Host and Database Instances (Connection pools, drivers, timeouts, read/write segregation)
- 3.2 Schema and Table Definitions (Full physical tables, primary keys, indexes, foreign keys, partition strategy)
- 3.3 Database Views and Materialized Query Structures

## 4. Stored Procedures and Analytical Logic Engine
- 4.1 Stored Procedure Catalog (Full list of procedures, executing hosts, input/output parameters)
- 4.2 Analytical Rules and Exception Detection Logic (Pillars / Rules mapping, rating formulas, tolerances)
- 4.3 Stored Procedure Execution Workflow (Mermaid execution flowchart)

## 5. ETL, Batch Jobs, and Refresher Pipeline
- 5.1 Batch Ingestion and Staging Scripts (Command-line triggers, script paths, pre-flight checks)
- 5.2 Background Refresher Service Loop (Watermark polling logic, cadence, transaction locks)
- 5.3 Exception Logging, State Registers, and KPI Calculation

## 6. Integration Endpoints and External Services
- 6.1 Downstream Systems and Gateways (OAuth2 tokens, headers, payload structures)
- 6.2 External Data Feeds and Clearing House File Formats

## 7. Reliability, Operational Runbooks, and Recovery
- 7.1 Health Checks, Heartbeat Probes, and Diagnostic Endpoints
- 7.2 Failure Modes, Recovery Procedures, and Re-run Idempotency
- 7.3 Operational Runbooks and Diagnostic Commands
```

## Conversion Workflow
1. Write the canonical LLD Markdown file to `docs/<app>/<app>-lld.md`.
2. Run the conversion script:
   ```bash
   python scripts/convert_doc_to_confluence.py docs/<app>/<app>-lld.md --output docs/<app>/<app>-lld.html
   ```
3. Verify that the output validates as well-formed XML and contains `<ac:structured-macro ac:name="plantuml">` blocks with `skinparam linetype ortho`.
