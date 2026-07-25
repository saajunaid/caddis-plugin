# Instructions

This folder contains coding instructions and guidelines that AI assistants apply automatically based on file types.

## What are Instructions?

Instructions are context-specific guidelines that tell AI assistants how to write code for specific languages, frameworks, or situations. They're automatically applied based on file patterns.

## Available Instructions

### Language & Framework Instructions

| File | Applies To | Purpose |
|------|------------|---------|
| [python.instructions.md](python.instructions.md) | `**/*.py` | Python coding standards |
| [sql.instructions.md](sql.instructions.md) | `**/*.sql` | SQL Server guidelines |
| [streamlit.instructions.md](streamlit.instructions.md) | `**/app.py, **/pages/*.py` | Streamlit patterns |
| [fastapi.instructions.md](fastapi.instructions.md) | `**/api/**/*.py` | FastAPI patterns |
| [frontend.instructions.md](frontend.instructions.md) | `**/*.html, **/*.css` | Frontend styling, brand guidelines |
| [mobile-native-pwa.instructions.md](mobile-native-pwa.instructions.md) | `**/*.html, **/*.css, **/*.ts, **/*.tsx` | Mobile-native + PWA conversion playbook |
| [mcp-server.instructions.md](mcp-server.instructions.md) | `**/mcp-servers/**/*.py` | MCP server development |

### DevOps & Infrastructure Instructions

| File | Applies To | Purpose |
|------|------------|---------|
| [docker.instructions.md](docker.instructions.md) | `**/Dockerfile, **/docker-compose*.yml` | Docker best practices |
| [github-actions.instructions.md](github-actions.instructions.md) | `.github/workflows/*.yml` | CI/CD pipeline patterns |

### Testing & Quality Instructions

| File | Applies To | Purpose |
|------|------------|---------|
| [testing.instructions.md](testing.instructions.md) | `**/tests/**/*.py` | Testing patterns |
| [code-review.instructions.md](code-review.instructions.md) | `**/*` | Code review guidelines |
| [playwright.instructions.md](playwright.instructions.md) | `**/tests/**/*.ts, **/*.spec.ts` | E2E testing with Playwright |

### Security & Accessibility Instructions

| File | Applies To | Purpose |
|------|------------|---------|
| [security.instructions.md](security.instructions.md) | `**/*` | Security best practices |
| [accessibility.instructions.md](accessibility.instructions.md) | `**/*.html, **/*.py` | WCAG 2.2 compliance |

### Workflow & Execution Instructions

| File | Applies To | Purpose |
|------|------------|---------|
| [advisory-mode.instructions.md](advisory-mode.instructions.md) | `**` | Copilot advisory/planning chat boundaries |
| [plan-mode.instructions.md](plan-mode.instructions.md) | `**` | Requirements discovery before implementation |
| [large-task-fidelity.instructions.md](large-task-fidelity.instructions.md) | `**` | Execution discipline for large multi-phase outputs |
| [junai-system.instructions.md](junai-system.instructions.md) | `**` | junai agent pipeline system reference |

## How Instructions Work

Each instruction file has a YAML frontmatter:

```yaml
---
description: "What this instruction covers"
applyTo: "**/*.py"  # Glob pattern for matching files
---
```

When you open or create a file matching the pattern, the AI assistant automatically considers these guidelines.

## Project-Specific Adaptations

All instructions are tailored for the project's environment:
- Python 3.11+ syntax and features
- SQL Server database
- Brand integration
- Air-gapped production considerations
- Shared library usage (`<SHARED_LIBS>` shared libraries)

## Using Instructions

Instructions are **IDE-agnostic**. Use them in any tool that accepts file-based or pasted context:

| IDE / Tool | How to use |
|------------|------------|
| **GitHub Copilot** | Project-local `.github/` resources plus `copilot-instructions.md`. |
| **Cursor** | Add to `.cursorrules` or reference in chat; path-based rules can use the `applyTo` globs. |
| **VS Code (other extensions)** | Include in system/context via extension settings, or paste the relevant instruction when working on matching file types. |
| **Claude / other chat** | Use project-local `.claude/rules/` exports, or paste/attach the relevant instruction file when editing matching code. |

In caddis, `.github/` is the canonical source. Packaging/export then creates runtime-native project-local folders like `.claude/` and `.codex/` from that source.

## Portability & Precedence

When moving AI resources between projects or machines, use this model:

1. **Canonical source:** Keep shared behavior only in `.github/agents/`, `.github/skills/`, `.github/prompts/`, `.github/instructions/`, `.github/diagrams/`, `.github/tools/`.
2. **Project overlay:** Keep project-specific constraints in each project's `copilot-instructions.md`.
3. **Runtime exports:** Build project-local `.claude/` and `.codex/` folders from `.github/` rather than hand-authoring them independently.
4. **No user-level default:** Do not deploy equivalent instructions, agents, or skills to user-level folders by default; project-local resources take precedence and avoid duplicate loading.
5. **Sync direction:** Use `caddis-push` to publish canonical `.github/` updates from a project to `caddis-plugin`; use `caddis-pull` to bring latest canonical `.github/` source into another project.
6. **Important:** `caddis-pull`/`caddis-push` sync the canonical source, not generated runtime export folders and not project-local files like `copilot-instructions.md` or `.github/pipeline/*` unless your sync script is extended.
7. **First run on new machine:** clone/open project → load `sync.ps1` → run `caddis-pull` → run the runtime export step → verify expected `.github/`, `.claude/`, and `.codex/` folders are present for the target IDEs.

## Adding New Instructions

1. Create a new `.instructions.md` file
2. Add YAML frontmatter with `description` and `applyTo`
3. Write clear, actionable guidelines
4. Include code examples for best practices
