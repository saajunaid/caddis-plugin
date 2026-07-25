---
name: architecture-document
context: fork
description: Generate professional enterprise-grade HLD and LLD documents from the living Architecture.md. Outputs DOCX (editable) or PPTX (executive summary) using existing document skills.
---

# Architecture Document Generator

Produce formal **High-Level Design (HLD)** and **Low-Level Design (LLD)** documents from the project's living `docs/Architecture.md` and codebase.

> **Project Context** — Read `project-config.md` for brand tokens, org name, tech stack, and project metadata used in document headers.
> **Document metadata** — Any Markdown companion doc or source doc created or updated in this workflow must follow `.github/instructions/document-frontmatter.instructions.md`. For DOCX/PPTX deliverables, mirror the same author/date/model fields on the cover page or revision history.

## When to Load This Skill

- Stakeholder requests a formal architecture deliverable
- Audit or compliance review requires documented HLD/LLD
- Onboarding pack for new team members
- Architecture review board submission
- Project milestone that requires design documentation

## Prerequisites

Before generating, ensure:
1. `docs/Architecture.md` exists and is current (the `@architect` agent maintains this)
2. Architecture diagrams exist in `docs/architecture/*.drawio` (or `.png` exports)
3. `project-config.md` has a profile set (for org name, tech stack, branding)

## Output Formats

| Format | Skill to Load | Best For |
|--------|---------------|----------|
| **DOCX** (recommended) | `.github/skills/document-skills/docx/SKILL.md` | Full HLD/LLD — editable, ToC, numbered sections |
| **PPTX** | `.github/skills/document-skills/pptx/SKILL.md` | Executive summary / architecture overview deck |
| **PDF** | `.github/skills/document-skills/pdf/SKILL.md` | Final read-only distribution (generate from DOCX) |

---

## HLD — High-Level Design

### Document Structure

```
COVER PAGE
    Project: <APP_TITLE>
    Organization: <ORG_NAME>
    Document Type: High-Level Design (HLD)
    Version: {from Architecture.md front-matter or git tag}
    Date: {current date}
    Author: {architect or team}
    Status: Draft | Under Review | Approved
    Classification: Internal | Confidential

REVISION HISTORY
    | Version | Date | Author | Changes |

APPROVAL TABLE
    | Role | Name | Signature | Date |

TABLE OF CONTENTS (auto-generated)

§1  INTRODUCTION
    §1.1  Purpose
    §1.2  Scope
    §1.3  Audience
    §1.4  References & Related Documents
    §1.5  Glossary & Abbreviations

§2  EXECUTIVE SUMMARY
    - Business context (1-2 paragraphs)
    - Solution overview (1-2 paragraphs)
    - Key architectural decisions summary

§3  SYSTEM CONTEXT
    §3.1  System Context Diagram (C4 Level 1)
    §3.2  External Systems & Interfaces
    §3.3  User Roles & Access Patterns
    §3.4  Data Sources

§4  ARCHITECTURE OVERVIEW
    §4.1  Architecture Style & Patterns
    §4.2  Component Architecture Diagram (C4 Level 2)
    §4.3  Component Descriptions
          (table: Component | Responsibility | Technology | Interfaces)
    §4.4  Technology Stack Summary

§5  DATA ARCHITECTURE
    §5.1  Data Flow Diagram
    §5.2  Data Sources & Stores
    §5.3  Data Integration Patterns
    §5.4  Data Retention & Archival

§6  INTEGRATION ARCHITECTURE
    §6.1  Integration Patterns (sync/async, push/pull)
    §6.2  API Overview (endpoints, protocols)
    §6.3  External System Interfaces
    §6.4  Message Flows / Event Flows

§7  DEPLOYMENT ARCHITECTURE
    §7.1  Deployment Diagram
    §7.2  Infrastructure Components
    §7.3  Environment Strategy (Dev/UAT/Prod)
    §7.4  Scaling & High Availability

§8  SECURITY ARCHITECTURE
    §8.1  Authentication & Authorization
    §8.2  Data Protection (at rest, in transit)
    §8.3  Network Security
    §8.4  Compliance Requirements

§9  NON-FUNCTIONAL REQUIREMENTS
    §9.1  Performance Targets
    §9.2  Availability & Reliability
    §9.3  Scalability
    §9.4  Maintainability
    §9.5  Observability (logging, monitoring, alerting)

§10  ARCHITECTURAL DECISIONS
    §10.1  Key Decisions Log (ADR summary table)
    §10.2  Alternatives Considered
    §10.3  Constraints & Trade-offs

§11  RISKS & MITIGATIONS
    (table: Risk | Likelihood | Impact | Mitigation)

§12  APPENDICES
    §A  Full Diagram Index
    §B  Glossary
    §C  Referenced Documents
```

### Content Sourcing

| HLD Section | Source |
|-------------|--------|
| §1 Introduction | `project-config.md` (org, tech stack) + `README.md` |
| §2 Executive Summary | `docs/Architecture.md` introduction/overview |
| §3 System Context | `docs/Architecture.md` context sections + `docs/architecture/system-context.drawio` |
| §4 Architecture Overview | `docs/Architecture.md` component sections + diagrams |
| §5 Data Architecture | `docs/Architecture.md` data sections + `project-config.md` data sources |
| §6 Integration | `docs/Architecture.md` API/integration sections |
| §7 Deployment | `docs/Architecture.md` deployment sections + `project-config.md` deploy env |
| §8 Security | `docs/Architecture.md` security sections + `project-config.md` compliance |
| §9 NFRs | `docs/Architecture.md` NFR sections |
| §10 Decisions | `docs/architecture/` ADR files or decisions section |
| §11 Risks | `docs/Architecture.md` risks section (or flag if missing) |

---

## LLD — Low-Level Design

### Document Structure

```
COVER PAGE (same format as HLD, Document Type: Low-Level Design)
REVISION HISTORY
APPROVAL TABLE
TABLE OF CONTENTS

§1  INTRODUCTION
    §1.1  Purpose
    §1.2  Scope (which HLD components this LLD covers)
    §1.3  HLD Reference (link to HLD document + version)

§2  MODULE DESIGN
    §2.1  Module Overview Diagram
    §2.2  Module Descriptions
          For each module:
          - Responsibility
          - Public interface (functions/methods/endpoints)
          - Dependencies (internal + external)
          - Configuration

§3  DATA MODEL
    §3.1  Entity Relationship Diagram
    §3.2  Table Definitions
          (table: Table | Columns | Types | Constraints | Indexes)
    §3.3  Data Validation Rules
    §3.4  Migration Strategy

§4  API DESIGN
    §4.1  API Endpoints
          (table: Method | Path | Request | Response | Auth | Rate Limit)
    §4.2  Request/Response Schemas (with examples)
    §4.3  Error Codes & Handling
    §4.4  Versioning Strategy

§5  SEQUENCE DIAGRAMS
    §5.1  Key User Flows
          (one sequence diagram per critical flow)
    §5.2  Error / Edge Case Flows
    §5.3  Background Process Flows

§6  CLASS / MODULE STRUCTURE
    §6.1  Package/Module Hierarchy
    §6.2  Key Classes & Responsibilities
    §6.3  Design Patterns Used
    §6.4  Dependency Injection / Configuration

§7  CACHING & STATE MANAGEMENT
    §7.1  Caching Strategy
          (table: Layer | Object | Strategy | TTL | Invalidation)
    §7.2  Session State Management
    §7.3  Serialization Constraints

§8  ERROR HANDLING & RESILIENCE
    §8.1  Error Classification
    §8.2  Retry Strategies
    §8.3  Circuit Breaker Patterns
    §8.4  Logging & Observability

§9  CONFIGURATION & ENVIRONMENT
    §9.1  Environment Variables
    §9.2  Feature Flags
    §9.3  Configuration Files
    §9.4  Secrets Management

§10  TESTING STRATEGY
    §10.1  Unit Test Approach
    §10.2  Integration Test Approach
    §10.3  E2E Test Scenarios
    §10.4  Performance Test Plan

§11  APPENDICES
    §A  Full Class Diagram
    §B  Database Schema DDL
    §C  Sample API Payloads
```

### Content Sourcing

| LLD Section | Source |
|-------------|--------|
| §2 Module Design | Codebase scan (`src/` structure) + `docs/Architecture.md` |
| §3 Data Model | Database schema + `project-config.md` data sources |
| §4 API Design | FastAPI route inspection or API docs |
| §5 Sequence Diagrams | Generate from codebase call flows |
| §6 Class Structure | Codebase scan (imports, classes, modules) |
| §7 Caching | `docs/Architecture.md` caching sections + codebase |
| §8 Error Handling | Codebase patterns (try/catch, error types) |
| §9 Configuration | `.env.example`, `config.py`, `project-config.md` |
| §10 Testing | Test files + `docs/Architecture.md` testing strategy |

---

## Generation Workflow

### Step 1: Gather Sources

```
1. Read docs/Architecture.md (full content)
2. Read project-config.md (profile, tech stack, org name)
3. List docs/architecture/*.drawio and *.png (diagram inventory)
4. If LLD: scan src/ for module structure, key classes, API routes
```

### Step 2: Determine Scope

Ask the user:
- **HLD, LLD, or both?**
- **Output format?** DOCX (recommended), PPTX (exec summary), or both?
- **Which components?** Full system or specific subsystem?

### Step 3: Assemble Content

Map each section to its source (see Content Sourcing tables above). For each section:
- If source content exists → extract and format
- If source is thin → flag with `[TODO: Expand — insufficient detail in Architecture.md]`
- If source is missing → flag with `[MISSING: No content found — update Architecture.md first]`

### Step 4: Generate Document

Load the appropriate document skill:
- **DOCX**: Load `.github/skills/document-skills/docx/SKILL.md` — use OOXML for professional formatting
- **PPTX**: Load `.github/skills/document-skills/pptx/SKILL.md` — use html2pptx workflow

### Step 5: Output

Save to:
- `docs/deliverables/HLD-{project-name}-v{version}.docx`
- `docs/deliverables/LLD-{project-name}-v{version}.docx`
- `docs/deliverables/Architecture-Overview-{project-name}-v{version}.pptx`

---

## Formatting Standards

### Enterprise Document Conventions

- **Font**: Arial or Calibri, 11pt body, 14pt headings
- **Section numbering**: §1, §1.1, §1.1.1 (three levels max)
- **Tables**: Bordered, header row shaded with brand primary color
- **Diagrams**: Captioned ("Figure N: Description"), referenced in text
- **Page headers**: Project name + Document type + "CONFIDENTIAL" (if applicable)
- **Page footers**: Page N of M + Version + Date
- **Line spacing**: 1.15 for body text
- **Margins**: 2.5cm all sides

### Diagram Embedding

For DOCX:
- Embed `.png` exports of `.drawio` diagrams
- Caption each figure: "Figure {N}: {Description}"
- Reference in text: "See Figure {N}"

For PPTX:
- One diagram per slide (full-width)
- Slide title = diagram caption
- Speaker notes = brief description

### Quality Checklist

Before delivering:
- [ ] Every section has content or explicit `[TODO]` marker
- [ ] All diagrams embedded and captioned
- [ ] Table of Contents generated and correct
- [ ] Revision history has current entry
- [ ] Cover page has correct project name, org, date
- [ ] No placeholder tokens (`<ORG_NAME>` etc.) remain — all resolved from project-config.md
- [ ] Section numbering is consistent and sequential
- [ ] Cross-references (e.g., "See §4.2") point to correct sections
