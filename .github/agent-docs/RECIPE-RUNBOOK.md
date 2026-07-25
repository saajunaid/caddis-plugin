# Recipe System — Runbook

> **Audience**: Developers and AI agents working with the caddis portable resource pool.
> **Last updated**: 2026-04-04

---

## 1. What Is a Recipe?

A **Project Recipe** is a thin composition manifest that defines a repeatable delivery workflow for a specific project archetype. It references existing skills (never duplicates them), sequences mandatory phases, and provides cross-skill conventions that no individual skill owns.

Recipes solve one problem: **agents forget to load the right skills at the right time**. Without a recipe, skill composition depends on the Planner embedding skills in the plan or mandatory triggers firing — both rely on human memory. A recipe makes the full skill chain automatic.

**Key properties:**
- ~200 lines — a routing table, not a content file
- References skills by path — content stays in skill files
- Conditional — only activates for matching task types (e.g., data-to-UI work)
- Additive — recipe skills are unioned with handoff + trigger skills, never replace them
- Optional — projects without a recipe work exactly as before

---

## 2. Available Recipes

| Recipe | File | Description | Target Profile |
|--------|------|-------------|----------------|
| `enterprise-dashboard` | `.github/recipes/enterprise-dashboard.recipe.md` | Data-to-UI dashboard delivery: intake → adapter → normalize → DTO → contract → API → mockup → implement → verify | `react-fastapi-vite-mssql` |

---

## 3. Scenarios

### 3a. Fresh Project (New Repo)

1. Run `new-vmie-project.ps1 -ProjectName "my-project"` from `platform-infra/bootstrap/` to scaffold the project from `project-template`
2. Open the project in VS Code — the junai extension auto-deploys the agent pool (agents, skills, instructions, recipes)
3. Extension prompts for **profile selection** → then **recipe selection**
4. Verify in `project-config.md`:
   - `profile` is set (e.g., `react-fastapi-vite-mssql`)
   - `recipe` is set (e.g., `enterprise-dashboard`)
5. Start building — agents automatically load recipe skills for data-to-UI tasks

```
platform-infra/bootstrap/ ──▶ new-project/          (from project-template)
                                 ├── src/             app scaffolding
                                 ├── frontend/        React scaffold
                                 └── .github/
                                      └── copilot-instructions.md  (sentinel markers)

junai extension (auto) ──▶ new-project/.github/
                                 ├── agents/
                                 ├── skills/
                                 ├── recipes/          ◀── recipe files
                                 ├── instructions/     ◀── instructions from pool
                                 └── project-config.md ◀── set profile + recipe
```

### 3b. Existing Project Mid-Flight

1. Run `caddis-pull` to get latest pool (including `recipes/` folder)
2. Edit `project-config.md` — add the `recipe` field to the Step 1 table:
   ```markdown
   | **recipe** | enterprise-dashboard |
   ```
3. Recipe takes effect on the **next agent invocation** — no restart needed
4. Existing plans, artifacts, and pipeline state are unaffected

### 3c. Project Without a Recipe

No action needed. When `project-config.md` has no `recipe` field (or it's blank):
- Agents skip all recipe loading logic
- Skill composition works exactly as before (handoff payload + mandatory triggers)
- No regression, no warnings, no behavior change

### 3d. Creating a New Recipe

When you have a **repeatable project archetype** that differs from existing recipes:

1. Create `.github/recipes/{name}.recipe.md` in `caddis`
2. Use `enterprise-dashboard.recipe.md` as a structural template
3. Define your delivery pipeline phases (can be fewer or more than 9)
4. Map each phase to existing skills in the Mandatory Skill Composition table
5. Add any cross-skill conventions unique to your archetype
6. Run `caddis-push` to commit to the pool
7. In target projects, set `recipe` in `project-config.md` to your recipe name

**When to create a new recipe vs. reuse existing:**
- Same tech stack, same delivery pattern → reuse existing recipe
- Same tech stack, different delivery pattern → new recipe
- Different tech stack entirely → new recipe + possibly new profile

---

## 4. How Agents Consume Recipes

The recipe loading chain has three sources. Agents take the **union** of all three:

```
┌─────────────────────────────┐
│  1. Handoff Skills          │  pipeline-state.json → handoff_payload.required_skills[]
│     (per-task, from plan)   │
├─────────────────────────────┤
│  2. Mandatory Triggers      │  Agent's own triggers (e.g., FastAPI skill for Python backend)
│     (per-agent, always)     │
├─────────────────────────────┤
│  3. Recipe Skills           │  project-config.md → recipe → .github/recipes/{recipe}.recipe.md
│     (per-project, auto)     │  → Mandatory Skill Composition for agent's phase
└─────────────────────────────┘
                │
                ▼
        Union (deduplicated)
                │
                ▼
        Agent loads & executes
```

**Loading sequence per agent:**
1. Read `pipeline-state.json` → load handoff skills
2. Fire mandatory triggers → load triggered skills
3. Read `project-config.md` → check `recipe` field
4. If recipe is set, read `.github/recipes/{recipe}.recipe.md`
5. Match current task to a recipe phase
6. Load recipe's mandatory skills for that phase (skip already-loaded)
7. Record loaded recipe skills with trigger `"recipe:{name}"`

**Which agents are recipe-aware:**

| Agent | Recipe Phases | Role |
|-------|--------------|------|
| Planner | All phases | Uses Delivery Pipeline as phase scaffold |
| Orchestrator | Current phase | Appends recipe skills to handoff payload |
| Frontend Developer | UI-DESIGN, IMPLEMENT | Loads mockup + UI skills from recipe |
| Implement | IMPLEMENT, VERIFY | Loads coding + testing skills from recipe |

---

## 5. Standalone Mode (No Pipeline)

Recipes work **without the junai MCP pipeline**. This is critical for teams using AI tools directly (VS Code Copilot Chat, Claude Code, Cursor, Windsurf, Codex) without the deterministic state machine.

### How It Works

The junai extension manages a sentinel-delimited section inside `copilot-instructions.md` (`<!-- junai:start -->` … `<!-- junai:end -->`). This managed section includes a "Recipe-Driven Delivery" block that tells ANY AI tool:

1. Check `project-config.md` for a `recipe` field
2. If set, read the recipe file
3. Follow its Delivery Pipeline and load its skills

This is the **universal entry point** — it fires regardless of which AI tool you use, whether the pipeline is running, or which agent file is active.

### Deployment Mechanism

The recipe discovery text is embedded in the extension's `junaiManagedSection()` function. When the extension runs `init` or `update`, it writes/refreshes this section inside the sentinel markers. User content outside the markers is never touched.

```
Extension update → junaiManagedSection() → copilot-instructions.md
                                              <!-- junai:start -->
                                              ## junai Agent Pipeline
                                              ...
                                              ## Recipe-Driven Delivery     ◀── universal trigger
                                              ...
                                              <!-- junai:end -->
```

**No separate file needed.** No manual copy. Every project gets recipe discovery automatically on extension install/update.

### Why This Is Reliable

```
┌──────────────────────────────────────────────────────────────┐
│  copilot-instructions.md                                     │
│  (read by ALL AI tools — Copilot, Claude, Cursor, Windsurf)  │
│                                                              │
│  "Check project-config.md for recipe…"                       │
│         │                                                    │
│         ▼                                                    │
│  project-config.md  →  recipe: enterprise-dashboard          │
│         │                                                    │
│         ▼                                                    │
│  recipes/enterprise-dashboard.recipe.md                      │
│  (Delivery Pipeline + Skills + Conventions)                  │
└──────────────────────────────────────────────────────────────┘
```

**No pipeline dependency.** No agent file dependency. One universal trigger.

### Pipeline Mode Adds Richness

When the full junai pipeline IS running, agents get additional recipe behavior:
- **Orchestrator** appends recipe skills to `handoff_payload.required_skills[]`
- **Planner** uses the recipe's Delivery Pipeline as a phase scaffold
- **Orchestrator** records recipe application in `_notes` for traceability

These are additive — they enhance but don't replace the universal discovery path.

---

## 6. FAQ

**Q: Can I override recipe skills in a plan?**
A: Yes. The Planner can add, reorder, or skip skills within a phase. The recipe provides the baseline; the plan refines it.

**Q: Does the recipe replace the data-contract-pipeline skill?**
A: No. The recipe *references* the data-contract-pipeline skill. Content stays in the skill file. The recipe just ensures it's loaded at the right phase.

**Q: Will the recipe fire for bug fixes?**
A: No. Recipe scaffolding is conditional — it only activates for data-to-UI delivery work (new features, new data sources, new dashboards). Bug fixes, refactors, and docs-only tasks skip recipe loading.

**Q: Do I need the full junai pipeline to use recipes?**
A: No. `copilot-instructions.md` contains recipe discovery instructions that ALL AI tools read automatically. The pipeline adds richer behavior (handoff augmentation, phase tracking in `_notes`), but the core recipe workflow works standalone.

**Q: What if a recipe references a skill that doesn't exist?**
A: The agent logs a warning and continues. Missing skills don't block execution — they just mean that phase won't have the cross-project baseline.

**Q: Can a project have multiple recipes?**
A: Not currently. The `recipe` field takes a single value. If you need to compose patterns, create a new recipe that references skills from both archetypes.

---

## 7. Architecture Diagram

See `.github/diagrams/recipe-system-architecture.drawio` for the full visual representation of the recipe system flow — from caddis source of truth through project bootstrap to agent execution.
