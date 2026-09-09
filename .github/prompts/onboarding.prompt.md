---
description: "Bootstrap AI configuration for a new project — generates copilot-instructions.md and populates project-config.md"
mode: agent
tools: ['codebase', 'editFiles']
---

# /onboarding — Set Up AI Resources for This Project

Run `/caddis:setup-project-ai` (the onboard-project skill was retired 2026-09-09 — it wrote `copilot-instructions.md`, which the AGENTS.md model replaced).

**Your task**: Bootstrap the AI configuration for this project.

1. Check what already exists (`project-config.md`, `copilot-instructions.md`, `.github/agent-docs/ARTIFACTS.md`)
2. Ask the user about their project (tech stack, branding, database, deployment, conventions)
3. Populate `project-config.md` with the project's profile and values
4. Create or update `copilot-instructions.md` (append missing sections only — never overwrite existing content; respect the `<!-- junai:start -->` … `<!-- junai:end -->` managed section)
5. Create `.github/agent-docs/ARTIFACTS.md` manifest if missing

**Important**: This is idempotent. If files already exist, only add what's missing. Never delete or rewrite existing content.
