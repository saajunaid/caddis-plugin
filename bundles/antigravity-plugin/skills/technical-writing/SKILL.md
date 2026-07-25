---
name: technical-writing
context: fork
description: Technical documentation best practices for READMEs, API docs, architecture docs, runbooks, and developer guides. Use when writing or reviewing documentation, creating onboarding guides, or establishing documentation standards.
---

# Technical Writing Skill

Good documentation is the difference between a project that scales and one that stalls. Write for the reader who has zero context.

## 1. When to Apply This Skill

**Trigger conditions:**
- Writing or updating a README
- Creating API documentation
- Writing architecture decision records (ADRs)
- Building runbooks or incident playbooks
- Creating onboarding/developer guides
- Reviewing documentation for clarity

## 2. Document Types and Templates

### Document Provenance Frontmatter

All descriptive Markdown docs must follow `.github/instructions/document-frontmatter.instructions.md`.

- **New docs**: include `Original Author`, `Creation Date`, and `Creating Model` in YAML frontmatter.
- **Updated docs**: preserve those original fields and add or update `Last Author`, `Last Updated`, and `Last Model Used`.
- Use full ISO 8601 UTC timestamps for `Creation Date` and `Last Updated` values.
- Merge these fields into existing frontmatter instead of replacing document-specific metadata.

### README Structure

Every project README follows this order:

```markdown
# Project Name
One-sentence description of what this does and who it's for.

## Quick Start
Minimum steps to run the project locally (≤5 commands).

## Prerequisites
- Runtime versions (Python 3.12+, Node 22+)
- Required tools (Docker, pnpm)
- Required accounts/access

## Installation
Step-by-step setup with copy-pasteable commands.

## Usage
Common tasks with examples.

## Architecture
Brief overview with a diagram (link to detailed docs).

## Contributing
How to submit changes, run tests, and follow conventions.

## License
```

**Rules:**
- Quick Start must work on a fresh machine in under 5 minutes
- Every command must be copy-pasteable (no `<placeholder>` without explanation)
- Test the README by following it literally on a clean environment

### Architecture Decision Record (ADR)

```markdown
# ADR-{NNN}: {Decision Title}

## Status
Accepted | Superseded by ADR-{NNN} | Deprecated

## Context
What problem are we solving? What constraints exist?

## Decision
What did we decide and why?

## Alternatives Considered
| Option | Pros | Cons | Why Not |
|--------|------|------|---------|

## Consequences
What changes as a result? What new constraints are introduced?
```

### Runbook/Playbook

```markdown
# Runbook: {Incident Type}

## Symptoms
What does the user/monitor see?

## Impact
Who is affected? What's the blast radius?

## Diagnosis Steps
1. Check {metric/log/dashboard} — expected: {value}
2. Run `{command}` — look for {pattern}
3. ...

## Resolution Steps
1. {Step with exact command}
2. {Verification step}
3. ...

## Escalation
If not resolved in {time}, contact {team/person}.

## Post-Incident
- [ ] Update this runbook with new learnings
- [ ] File ticket for permanent fix
```

## 3. Writing Principles

### Know Your Reader

| Reader | Needs | Writing Style |
|--------|-------|--------------|
| **New developer** | Setup, concepts, where things are | Step-by-step, no assumptions |
| **Experienced dev** | API reference, edge cases, configuration | Concise, scannable, tables |
| **Ops/SRE** | Runbooks, monitoring, deployment | Commands, checklists, decision trees |
| **Stakeholder** | What it does, status, decisions | High-level, diagrams, outcomes |

### The Inverted Pyramid

Put the most important information first. Readers scan, they don't read.

```
┌─────────────────────────┐
│    What + Why (lead)    │  ← First paragraph answers the key question
├─────────────────────────┤
│  How (details)          │  ← Supporting details, steps, configuration
├─────────────────────────┤
│  Reference (appendix)   │  ← Edge cases, history, alternatives
└─────────────────────────┘
```

### Plain Language Rules

| Do | Don't |
|----|-------|
| "This function returns the user's name" | "This function facilitates the retrieval of the nomenclature associated with the user entity" |
| "Run `npm install`" | "Execute the package installation command" |
| "Fails if the file doesn't exist" | "In the event that the specified file is not present in the filesystem, the operation will not succeed" |
| Short sentences (< 25 words) | Run-on sentences with multiple clauses |
| Active voice | Passive voice |

## 4. Code Examples in Documentation

### Rules for Code Samples

```python
# ✅ GOOD: Complete, runnable example with imports
from datetime import datetime
from myapp.models import User

def create_user(name: str, email: str) -> User:
    """Create a user and return the saved instance."""
    user = User(name=name, email=email, created_at=datetime.now())
    user.save()
    return user

# Usage
user = create_user("Alice", "alice@example.com")
print(user.id)  # => "usr_abc123"
```

```python
# ❌ BAD: Incomplete snippet, no context
def create_user(name, email):
    user = User(name=name, email=email)  # What is User? Where is it imported?
    user.save()  # Does this return something?
```

**Rules:**
- Include imports
- Show expected output in comments
- Use realistic data (not "foo", "bar", "test")
- Every example must be copy-pasteable and runnable

## 5. Diagrams

Use diagrams for architecture, data flow, and sequences. Text alone fails for spatial relationships.

### When to Use Each Type

| Diagram | Use For |
|---------|---------|
| **Flowchart** | Decision trees, process flows |
| **Sequence** | API call chains, auth flows |
| **Architecture** | System overview, service boundaries |
| **ERD** | Database schema relationships |
| **State** | Lifecycle transitions (order, ticket) |

### Diagram Rules
- Label every arrow (what data flows, what triggers the transition)
- Include a legend if using color coding
- Keep to 7±2 elements — decompose larger diagrams
- Store diagrams as code (Mermaid, PlantUML) for version control

## 6. API Documentation

### Endpoint Documentation Template

```markdown
### `POST /api/v1/customers`

Create a new customer record.

**Auth:** Bearer token required

**Request Body:**
| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Customer full name (1-200 chars) |
| email | string | Yes | Valid email address |

**Response:** `201 Created`
```json
{
  "data": { "id": "cust_abc", "name": "Alice", "email": "alice@example.com" }
}
```

**Errors:**
| Code | When |
|------|------|
| 400 | Missing required field |
| 409 | Email already exists |
| 422 | Invalid email format |
```

## 7. Documentation Maintenance

### Keep Docs Near Code

```
src/
  auth/
    login.py
    README.md        ← Auth module docs live with auth code
docs/
  architecture.md    ← System-level docs in docs/
  runbooks/          ← Operational docs
```

### Freshness Rules

| Trigger | Action |
|---------|--------|
| API endpoint changed | Update API docs in same PR |
| New environment variable | Update README + .env.example |
| Architecture decision | Write or update ADR |
| Production incident | Update or create runbook |
| New developer onboarded | Test README, fix gaps found |

## 8. Review Checklist

When reviewing documentation:

- [ ] Answers "what does this do?" in the first paragraph
- [ ] Document frontmatter is present and current
- [ ] Code examples are complete and runnable
- [ ] Commands are copy-pasteable
- [ ] No stale references to old code, endpoints, or config
- [ ] Diagrams are up to date
- [ ] Written for the target audience (not the author)
- [ ] No jargon without definition
- [ ] Links work and point to current resources

## 9. Anti-Patterns

| Anti-Pattern | Problem | Fix |
|---|---|---|
| Docs written once, never updated | Stale docs are worse than no docs | Update in same PR as code changes |
| Wall of text | Nobody reads it | Use headings, tables, code blocks, diagrams |
| Documenting obvious code | Noise, maintenance burden | Document "why", not "what" |
| Screenshots of terminal output | Can't copy-paste, hard to update | Use code blocks with text output |
| "See the code for details" | Reader has to reverse-engineer | Write the explanation |
| Assuming reader context | "Just run the usual setup" | Spell out every step |
