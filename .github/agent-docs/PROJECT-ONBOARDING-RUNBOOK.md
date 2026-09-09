# Project Onboarding Runbook — End-to-End

> **Audience**: Developers starting a new project on the VMIE platform with the junai agent pipeline.
> **Last updated**: 2026-04-04

---

## Overview

This runbook covers the complete process from empty directory to a fully configured project with AI-assisted delivery. It integrates three systems:

| System | Repo | Responsibility |
|--------|------|----------------|
| **the infra repo** | `E:\Projects\the infra repo` | Project scaffolding, port allocation, Gitea CI, environment setup |
| **project-template** | `E:\Projects\project-template` | Golden skeleton — FastAPI backend, React 19 frontend, Alembic migrations |
| **junai extension** | VS Code Marketplace | Agent pool deployment — agents, skills, instructions, recipes, MCP config |

```
the infra repo                     junai extension
     │                                   │
     │ new-vmie-project.ps1              │ auto-deploy on workspace open
     │ (copies project-template)         │ (copies pool from extension bundle)
     ▼                                   ▼
┌─────────────────────────────────────────────┐
│              NEW PROJECT                     │
│  src/          ← from project-template       │
│  frontend/     ← from project-template       │
│  .github/                                    │
│    ├── agents/       ← from junai pool       │
│    ├── skills/       ← from junai pool       │
│    ├── recipes/      ← from junai pool       │
│    ├── instructions/ ← from junai pool       │
│    ├── project-config.md  (profile + recipe) │
│    └── copilot-instructions.md               │
│         ← user content preserved             │
│         ← junai managed section with recipe  │
│           discovery (inside sentinels)        │
│  .gitea/workflows/  ← from the infra repo    │
└─────────────────────────────────────────────┘
```

---

## Step 1: Bootstrap with the infra repo

Run the project generator from `the infra repo/bootstrap/`:

```powershell
cd E:\Projects\the infra repo

.\bootstrap\new-vmie-project.ps1 `
    -ProjectName "another fleet app" `
    -ProjectShort "apas" `
    -Description "Appointment management dashboard" `
    -Port 0
```

### Required Parameters

| Parameter | Description | Example |
|-----------|------------|---------|
| `-ProjectName` | Lowercase, hyphenated name | `another fleet app` |
| `-ProjectShort` | 3-8 char abbreviation | `apas` |
| `-Description` | One-line description | `Appointment management dashboard` |

### Optional Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `-Port` | `0` (auto) | Port offset — auto-selects next free slot from `port-registry.json` |
| `-NoFrontend` | off | Skip React frontend scaffold |
| `-NoWorker` | off | Skip background worker scaffold |
| `-NoAuth` | off | Skip JWT auth scaffold |
| `-SkipGitea` | off | Skip Gitea repo creation and push |
| `-Validate` | off | Dry-run — show pre-flight checks without executing |

### What It Does

1. **Pre-flight checks**: Validates port availability, template existence, Python/Node.js in PATH, Gitea connectivity
2. **Copy template**: Copies `E:\Projects\project-template` → `E:\Projects\another fleet app`
3. **Token replacement**: Replaces `{{PROJECT_NAME}}`, `{{PROJECT_SHORT}}`, `{{DESCRIPTION}}`, port placeholders across all files
4. **CI overlay**: Copies Gitea Actions workflows from `the infra repo/templates/workflows/` → `.gitea/workflows/`
5. **Environment setup**: Creates Python `.venv`, runs `pip install`, runs `npm install` for frontend
6. **Gitea**: Creates repo on Gitea, pushes initial commit
7. **Port registry**: Registers allocated ports in `the infra repo/infra-setup/port-registry.json`

### Validate First (Recommended)

```powershell
.\bootstrap\new-vmie-project.ps1 `
    -ProjectName "another fleet app" `
    -ProjectShort "apas" `
    -Description "Appointment management dashboard" `
    -Validate
```

This runs all pre-flight checks without creating anything. Fix any FAIL results before running for real.

---

## Step 2: Open in VS Code

```powershell
code E:\Projects\another fleet app
```

On workspace open, the **junai extension** fires automatically:

1. Detects no `agents/` directory → prompts: *"junai: Agent pipeline not yet set up. Run Initialize?"*
2. Click **"Initialize Now"** (or set `junai.autoInitializeOnActivation: "always"` for auto-init)
3. Extension runs `cmdInit`:
   - Copies pool (agents, skills, instructions, recipes, prompts, tools) from extension bundle → `.github/`
   - Writes Claude resources to `.claude/` and Codex resources to `.codex/`
   - Creates `pipeline-state.json` with default mode (`supervised`)
   - Writes sentinel-managed section in `copilot-instructions.md` (including recipe discovery)
   - Scaffolds `.vscode/mcp.json` with junai MCP server configuration

---

## Step 3: Select Profile + Recipe

After init, the extension prompts for profile and recipe selection:

### Profile Selection

A quick-pick dropdown appears with available profiles. Select the one matching your tech stack:

| Profile | Use Case |
|---------|----------|
| `react-fastapi-vite-mssql` | React + FastAPI + Vite + SQL Server — most enterprise dashboards |
| `streamlit-mssql-enterprise` | Streamlit + SQL Server — internal analytics tools |
| `telecom-appointment-intelligence` | Full-stack AI system with Redis + Ollama |
| `org1-telecom-ops` | Org-specific profile with brand colours |

### Recipe Selection

After profile, a second quick-pick appears for recipe:

| Recipe | Use Case |
|--------|----------|
| `enterprise-dashboard` | Data-to-UI dashboard delivery (9-phase pipeline) |
| `none` | No recipe — agents use built-in expertise only |

Both values are written to `.github/project-config.md`:

```markdown
| **profile** | `react-fastapi-vite-mssql` |
| **recipe**  | `enterprise-dashboard`     |
```

### Manual Override

You can always change these later by editing `project-config.md` directly, or by running:
- **Command Palette** → `junai: Select Project Profile`

---

## Step 4: Place Your Assets

### Data Files

Place source data files for the data pipeline:

```
scratch/data/
  ├── appointments.csv
  ├── customer-segments.json
  └── lookup-tables.xlsx
```

### HTML Mockups

Place reference mockups for the UI:

```
scratch/mockups/
  └── dashboard-mockup.html
```

The recipe's UI-DESIGN phase will use these for the Mockup-to-React Contract (5 annotation types: DATA-SOURCE, COMPONENT, IMPLEMENTATION NOTE, STYLE, IMPORT MAP).

---

## Step 5: Start the Pipeline

### Option A: Full Pipeline (Recommended)

Open Copilot Chat and invoke the Orchestrator:

```
@Orchestrator Start a new pipeline for another fleet app.
I have data files in scratch/data/ and an HTML mockup in scratch/mockups/.
Build an appointment management dashboard with light and dark mode support.
```

The pipeline runs through stages:
1. **PRD** → Product requirements
2. **Plan** → Implementation plan using recipe's 9-phase Delivery Pipeline
3. **Implement** → Code generation following recipe skills
4. **Test** → Automated verification
5. **Review** → Code quality check

### Option B: Standalone Mode (No Pipeline)

Use any AI tool (Copilot Chat, Claude Code, Cursor) and describe your task. The tool reads `copilot-instructions.md`, discovers the recipe, and follows its delivery phases:

```
Build the appointments dashboard. Follow the enterprise-dashboard recipe.
Data files are in scratch/data/ and mockup is in scratch/mockups/.
```

No MCP server, no pipeline state, no stage machine. The recipe still provides structure.

### Option C: Initialize Pipeline Manually

```
@Orchestrator Initialize pipeline for "another fleet app" feature "appointment-dashboard"
```

This creates a pipeline-state.json entry and begins the deterministic stage sequence.

---

## Step 6: Dark Mode Support

The project-template already includes CSS variable infrastructure for light/dark mode in `frontend/src/styles/globals.css`:

```css
@layer base {
  :root {
    /* Light mode variables */
    --background: 0 0% 100%;
    --foreground: 0 0% 3.9%;
    /* ... */
  }
  .dark {
    /* Dark mode variables */
    --background: 0 0% 3.9%;
    --foreground: 0 0% 98%;
    /* ... */
  }
}
```

During the **UI-DESIGN** phase, provide dark mode requirements:

- The `warm-editorial-ui` skill defines the light design system tokens
- For dark mode, specify a dark token set in the mockup annotations or as an explicit requirement
- shadcn/ui components automatically respect CSS variable theming

---

## Step 7: Ongoing Updates

### Pool Updates

When a new junai extension version is published:
1. VS Code auto-updates the extension
2. On workspace open, extension detects pool version mismatch
3. Auto-updates pool silently — commits changes to git

### Profile/Recipe Changes

Edit `.github/project-config.md` directly. Changes take effect on the next agent invocation.

### CI Pipeline

Gitea Actions workflows are in `.gitea/workflows/`:
- `ci.yml` — lint, test, build on every push
- `deploy-prod.yml` — production deployment
- `debug-pipeline.yml` — AI-assisted debugging
- `implement-fix.yml` — AI-assisted fix implementation

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Extension doesn't prompt on open | `junai.autoInitializeOnActivation` set to `never` | Change to `prompt` or run `junai: Initialize` from Command Palette |
| Recipe not firing | `recipe` field blank in project-config.md | Set it: `\| **recipe** \| \`enterprise-dashboard\` \|` |
| Stale agents/skills | Pool version behind extension | Run `junai: Update Agent Pool` from Command Palette |
| MCP server not connecting | `.vscode/mcp.json` missing or `uv` not installed | Run `junai: Initialize` to scaffold, ensure `uv` is installed globally |
| Port conflict at bootstrap | Port offset already allocated | Use `-Port 0` for auto-selection or check `port-registry.json` |

---

## Quick Reference

```powershell
# 1. Bootstrap
cd E:\Projects\the infra repo
.\bootstrap\new-vmie-project.ps1 -ProjectName "my-project" -ProjectShort "mypr" -Description "My project"

# 2. Open in VS Code (extension auto-initializes)
code E:\Projects\my-project

# 3. Verify project-config.md has profile + recipe set

# 4. Place data + mockups in scratch/

# 5. Start pipeline
# @Orchestrator Start pipeline for my-project ...
```
