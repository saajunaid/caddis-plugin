# Skills Registry

> Bundle skill inventory generated from `SKILL.md` frontmatter for the shipped subset.
> Load a skill by reading its `SKILL.md`.

---

## Skills by Category

### Coding

| Skill | Path | When to Use |
|-------|------|-------------|
| Api Design | `api-design/` | REST and GraphQL API design: endpoints, resource schemas, versioning, pagination, error responses, OpenAPI. Use when designing or reviewing API contracts. |
| Backend Development | `backend-development/` | Backend API design, database schemas, microservices and TDD. Use for backend system architecture. |
| Code Review | `code-review/` | Automated code review for quality, security, performance and best practices. Use when reviewing code changes, PRs, or doing code audits. |
| Codebase Audit | `codebase-audit/` | Audit an unfamiliar codebase before architecture or implementation work. Use for a new codebase, pre-implementation audit, codebase review, technical due diligence or onboarding. Produces AUDIT-FINDINGS.md and QUESTIONS.md. |
| Dashboard Perf Sweep | `dashboard-perf-sweep/` | Re-measure dashboard/API endpoints for load-time regressions and decide by checklist if a slow one needs the rs-kit refresher, an index, keyset paging, gzip, or nothing. Use when the user says "sweep dashboard performance", "check if this app needs rs-kit", "re-measure the perf tracker", "is this endpoint a refresher candidate", or dashboard-performance-tracker.md is stale. Read-only. |
| Error Handling | `error-handling/` | Error handling for Python and TypeScript: error hierarchies, custom exceptions, result types, retries, circuit breakers, error boundaries, logging, user-facing messages. |
| Fastapi Dev | `fastapi-dev/` | Build FastAPI backends with standard patterns, error handling, and testing |
| Javascript Typescript | `javascript-typescript/` | JavaScript and TypeScript development with ES6+, Node.js, React, and modern web frameworks. Use for frontend, backend, or full-stack JavaScript/TypeScript projects. |
| Python Development | `python/` | Modern Python 3.12+ (Django, FastAPI, async) with production best practices. Use for Python projects, APIs, data processing or scripts. |
| Refactoring | `refactoring/` | Safely refactor code while maintaining behavior. Use when improving code structure, reducing duplication, extracting functions, or modernizing legacy code. |
| Security Review | `security-review/` | Security review workflow — OWASP, code scanning, cloud infrastructure |
| Sql | `sql/` | Write optimized, secure, readable SQL: performance, NULL handling, dialect-specific notes. |

### Data

| Skill | Path | When to Use |
|-------|------|-------------|
| Database Design | `database-design/` | Database schema design, migrations and query optimization for PostgreSQL, MySQL and NoSQL. |
| Db Diagram | `db-diagram/` | Diagram a SQL artifact (stored proc, view, query, .sql file, table) as Mermaid or Excalidraw. Use when the user says "diagram this query/proc/view/schema", "explain this SQL visually", "draw the ER diagram", "show me the data flow of this stored proc", "/mermaid-db", or "/excalidraw-db". Read-only. |

### Devops

| Skill | Path | When to Use |
|-------|------|-------------|
| Adopt App | `adopt-app/` | >- |
| Ci Cd Pipeline | `ci-cd-pipeline/` | CI/CD pipelines for GitHub Actions and Azure DevOps: build and deploy workflows, quality gates, environment promotion and release automation. |
| Gh Cli | `gh-cli/` | GitHub CLI operations — issues, PRs, releases, and repo management |
| Git Commit | `git-commit/` | Create well-structured conventional commit messages following Conventional Commits standard. Use when committing changes, preparing PRs, or generating changelogs. |
| Port To Github | `port-to-github/` | >- |
| Safe Cleanup | `safe-cleanup/` | Use BEFORE deleting a directory tree, scratchpad or git worktree, or "tidying up" generated folders, especially on Windows, where deleting through a junction or symlink destroys its target; and to verify a venv or node_modules survived. |
| Using Git Worktrees | `using-git-worktrees/` | Use when starting feature work that needs isolation from the current workspace, or before executing an implementation plan: creates an isolated git worktree safely. |
| Windows Deployment | `windows-deployment/` | Deploy FastAPI + React/Vite apps to Windows Server with NSSM services, IIS or nginx reverse proxy and git-pull. Use for Windows prod deploys, NSSM, reverse proxy setup, dev/prod config, or prod troubleshooting. |

### Docs

| Skill | Path | When to Use |
|-------|------|-------------|
| Code Documentation | `code-documentation/` | Write code documentation: API docs, README files, inline comments and developer guides. |
| Confluence Hla | `confluence-hla/` | High-Level Architecture (HLA) documents in Simplified Technical English as Confluence Storage Format XHTML with PlantUML. Use for Confluence architecture docs or converting markdown architecture. |
| Explainer Doc | `explainer-doc/` | Hand-off doc for a team that did NOT do the investigation (vendor, contractor, another team) — the "stranger must follow it alone" case. Use when the user says "write a spec for the X team", "document this for someone outside the team", "explainer doc", "implementation spec for a vendor", or "hand this off to Y". Not for readers with full context. |
| Tech Explainer | `tech-explainer/` | >- |
| Technical Writing | `technical-writing/` | Documentation best practices for READMEs, API docs, architecture docs, runbooks and developer guides. Use when writing or reviewing docs or setting documentation standards. |
| Writing Plans | `writing-plans/` | Use when you have a spec or requirements for a multi-step task, before touching code |

### Frontend

| Skill | Path | When to Use |
|-------|------|-------------|
| Css Architecture | `css-architecture/` | CSS architecture: design tokens, custom properties, Tailwind config, CSS Modules, container queries, dark mode, fluid typography, animation. Covers how to implement styling; frontend-design covers what to achieve. |
| Flow Studio | `flow-studio/` | Design an interactive flow, lifecycle or journey page (nodes, lanes, links, motion, inspector, notes) from a JSON model as a self-contained demo, then build it in an app. Use for lineage, pipelines, ticket or agent journeys. |
| Frontend Design | `frontend-design/` | Create distinctive, production-grade frontend interfaces that avoid generic AI aesthetics. Use when the user asks to build web components, pages, artifacts, posters or applications. |
| Mockup | `mockup/` | Create framework-aware UI mockups with feasibility checks. Prevents wasted effort by validating that proposed designs work within the target framework's constraints. |
| React Best Practices | `react-best-practices/` | Modern React development guidelines covering hooks, component patterns, state management, performance optimization, and TypeScript integration. |
| React Dev | `react-dev/` | Type-safe React 18-19 with TypeScript: components, generic components, hooks, events, Server Components, TanStack Router and React Router. Use when React TypeScript or React 19 is involved. |
| Ui Review | `ui-review/` | Review a UI against design requirements, WCAG 2.2 AA and brand guidelines. Use when validating UI before release. |
| Warm Editorial Ui | `warm-editorial-ui/` | Apply the "Warm Editorial Refinement" design system (warm cream/charcoal surfaces, Bahnschrift + Plus Jakarta Sans, layered shadows), the canonical template for new frontend builds. Use for apps, dashboards or UI in the abc-project style, or on "use our design system", "apply our template", "make it look like abc-project", "use the warm editorial style", "use our brand template", "add dark mode", or a new tool for XYZ Brand. |

### Media

| Skill | Path | When to Use |
|-------|------|-------------|
| Draw Io | `draw-io/` | draw.io diagram creation, editing, and review. Use for .drawio XML editing, PNG conversion, layout adjustment, and AWS icon usage. |
| Mermaid Diagrams | `mermaid-diagrams/` | Software diagrams in Mermaid: class, sequence, flowchart, ERD, C4, state, git graph, gantt. Use for domain models, API flows, processes and database schemas. |
| Particle Art | `particle-art/` | >- |

### Testing

| Skill | Path | When to Use |
|-------|------|-------------|
| Playwright | `playwright/` | Browser automation and testing with Playwright: auto-detects dev servers; tests pages, forms, logins, links, screenshots and responsive layouts. Use to test websites or automate any browser task. |
| Tdd Workflow | `tdd-workflow/` | Test-Driven Development workflow — red-green-refactor cycle |
| Test Strategy | `test-strategy/` | Plan what to test: test types, coverage goals, test pyramid, quality gates. Produces a prioritized TEST-STRATEGY.md for the Tester agent. |
| Webapp Testing | `webapp-testing/` | Test local web apps with Playwright: verify frontend behavior, debug UI, capture screenshots and browser logs. |

### Workflow

| Skill | Path | When to Use |
|-------|------|-------------|
| Advisory Hub | `advisory-hub/` | >- |
| Best Practices | `best-practices/` | >- |
| Brainstorming | `brainstorming/` | You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation. |
| Context Curator | `context-curator/` | Compress and prioritize codebase context before handing work to reasoning agents, minimizing token waste while preserving the required decision inputs. |
| Preflight | `preflight/` | Plan-vs-codebase validation — verifies API contracts, type names, field accuracy, dependencies, and paths before implementation begins |
| Skill Creator | `skill-creator/` | Create, edit and improve skills, run evals and benchmarks, and optimize a skill's description for triggering accuracy. |
