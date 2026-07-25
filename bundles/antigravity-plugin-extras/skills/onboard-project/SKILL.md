---
name: onboard-project
context: fork
description: Bootstrap a new project's AI configuration by generating copilot-instructions.md and populating project-config.md. Idempotent — safe to re-run on existing projects.
---

# Onboard Project Skill

## Purpose

Entry point for the portable AI resources pool. When copied to a new project, this skill bootstraps the project-specific configuration that agents need to function correctly.

**What it produces:**
1. `copilot-instructions.md` — project-specific context for the AI assistant
2. `project-config.md` — populated with project values (profile + placeholders)
3. `agent-docs/ARTIFACTS.md` — artifact manifest (if missing)

---

## When to Use

- Setting up AI resources on a **new project** for the first time
- After copying the `.github/` (or `.cursor/`) portable pool to a new repo
- When `project-config.md` has a blank profile and empty placeholder values
- To add missing sections to an existing `copilot-instructions.md`

---

## Behavior: Idempotent & Non-Destructive

> **CRITICAL**: This skill NEVER overwrites or degrades existing content.

| Scenario | Behavior |
|----------|----------|
| `copilot-instructions.md` does not exist | Create from template, populate from user Q&A |
| `copilot-instructions.md` exists | Read it, compare sections vs. template, append ONLY missing sections with `<!-- Added by onboard-project -->` marker |
| `project-config.md` has blank profile | Ask user for values, populate |
| `project-config.md` has profile set | Skip — already configured |
| `agent-docs/ARTIFACTS.md` missing | Create from template |
| `agent-docs/ARTIFACTS.md` exists | Skip — already configured |

**Conflict resolution**: If existing content contradicts template defaults, **keep the user's version**. It's more battle-tested.

---

## Steps

### Step 1: Check Current State

Read the following files (if they exist):
1. `project-config.md` — check if profile is set, if placeholders are filled
2. `copilot-instructions.md` — check which sections already exist
3. `agent-docs/ARTIFACTS.md` — check if manifest exists

Report what exists and what's missing before proceeding.

### Step 2: Gather Project Information

Ask the user for information needed to populate the configuration. Skip questions where answers can be inferred from existing files.

**Required information:**

| Category | Questions |
|----------|-----------|
| **Identity** | Project name? Organization name? One-line description? |
| **Tech Stack** | Language(s)? Frontend framework? Backend framework? Database type? |
| **Branding** | Primary brand color (hex)? Dark color? Light color? Additional brand colors? |
| **Infrastructure** | Deployment environment (cloud/on-premise/hybrid)? Air-gapped? Authentication method? |
| **Logging** | Logging library? (loguru, logging, structlog, etc.) |
| **Shared Libraries** | Any shared/internal libraries? Paths? |
| **Project Structure** | Entry point file? Source root? Key directories? |
| **Data Sources** | Database name(s)? Connection method? Key tables? |
| **Key Conventions** | Query externalization? Path resolution patterns? CSS scoping method? Component reuse patterns? |
| **Commands** | How to run the app? Run tests? Lint? Build? |
| **Recipe** | Delivery workflow pattern? (`enterprise-dashboard` for data-to-UI dashboards, or blank for generic projects) |

### Step 3: Populate project-config.md

1. Set the `profile` field (use org name slug, e.g., `acme`, `myorg`, or leave blank if no profile needed)
2. If using a profile, create a Profile Definition section with:
   - Core Placeholders table (`<ORG_NAME>`, `<BRAND_PRIMARY>`, `<BRAND_DARK>`, `<BRAND_LIGHT>`, `<DB_TYPE>`, `<DEPLOY_ENV>`, `<LOGGING_LIB>`, `<SHARED_LIBS>`)
   - Brand Color Palette table (if provided)
   - Tech Stack table
   - Data Sources table
   - Project Structure block
   - Key Conventions list
3. If not using a profile, fill in the "Step 2: Project Values" table directly
4. If user specified a recipe:
   - Verify `.github/recipes/{recipe}.recipe.md` exists in the pool
   - Set the `recipe` field in the Step 1 table: `| **recipe** | {recipe} |`
   - If recipe file is missing, warn but continue — recipe is optional

### Step 4: Create or Update copilot-instructions.md

**Template sections** (check each — add only what's missing):

```markdown
# {Project Name} — AI Assistant Context

## Project Overview
{One paragraph: what the project does, who it's for, key goals}

## Architecture
{High-level architecture: components, data flow, key patterns}

## Tech Stack
{Table: Layer → Technology}

## Data Sources
{Table: Source → Table/Collection → Description}

## Key Patterns & Conventions
{Bullet list of project-specific patterns the AI must follow}

## Database Access
{Connection method, query patterns, ORM/raw SQL, caching}

## Project Structure
{Directory tree of key folders}

## Deployment
{How the app is deployed, environment specifics}

## Key Commands
{Run, test, lint, build commands}
```

**Merge logic for existing files:**
1. Parse existing `copilot-instructions.md` into sections (by `##` headings)
2. If the file contains `<!-- junai:start -->` … `<!-- junai:end -->` sentinel markers, leave that block untouched — it is managed by the junai extension
3. For each template section, check if an equivalent heading exists outside the managed block (fuzzy match — "Tech Stack" matches "Technology Stack", "Stack", etc.)
4. If section exists → **skip it** (preserve user's content entirely)
5. If section is missing → **append it** before the managed section (or at the end if no managed section) with marker:
   ```markdown
   <!-- Added by onboard-project — review and customize -->
   ## {Section Title}
   {Template content populated with project values}
   ```
5. Never reorder, rewrite, or delete existing sections

### Step 5: Create agent-docs/ARTIFACTS.md (if missing)

If `agent-docs/ARTIFACTS.md` does not exist, create it using the standard template:

```markdown
# Agent Artifacts

> **For agents**: Only read artifacts with status `current`. Ignore `superseded` and `archived`.
> **For humans**: This is a working directory for inter-agent communication. Do not include in project documentation.

## How to Read This Manifest

- **chain_id**: Links all artifacts in a feature chain (format: `FEAT-YYYY-MMDD-{slug}`)
- **status**: `current` (active) | `superseded` (replaced) | `archived` (historical) | `completed` (done)
- **approval**: `pending` (awaiting review) | `approved` (proceed) | `revision-requested` (needs changes)

## Artifacts

| Date | Agent | Type | Description | Path | Status | Approval | Chain ID |
|------|-------|------|-------------|------|--------|----------|----------|
| | | | | | | | |
```

Also create the subfolder structure if missing:
- `agent-docs/intents/`
- `agent-docs/escalations/`
- `agent-docs/prd/`
- `agent-docs/architecture/`
- `agent-docs/ux/mockups/`
- `agent-docs/ux/reviews/`
- `agent-docs/security/`
- `agent-docs/reviews/`
- `agent-docs/debug/`
- `agent-docs/testing/`
- `agent-docs/.archive/`

### Step 6: Summary

Report what was done:
- Files created vs. updated
- Sections added to existing `copilot-instructions.md` (if any)
- Profile set in `project-config.md`
- Next steps (e.g., "Review the added sections and customize them")

---

## Important Notes

- All paths in this skill are relative. The skill works regardless of whether the AI resources folder is at `.github/`, `.cursor/`, or any other location.
- The `copilot-instructions.md` file is project-specific and should NOT be committed to the portable pool. It stays in the project repo. The junai extension manages only a sentinel-delimited `<!-- junai:start -->` … `<!-- junai:end -->` section — never edit content inside those markers (it will be refreshed on the next Update). Add your project content outside the markers.
- `project-config.md` IS part of the portable pool as a template. When the profile section is filled in, it becomes project-specific.
- The `recipe` field in `project-config.md` is optional. Projects without a recipe work exactly as before — agents use their built-in expertise and plan-embedded skills. Recipes add automatic cross-project baseline loading for repeatable delivery patterns.
