# Skills Registry

> Bundle skill inventory generated from `SKILL.md` frontmatter for the shipped subset.
> Load a skill by reading its `SKILL.md`.

---

## Skills by Category

### Coding

| Skill | Path | When to Use |
|-------|------|-------------|
| Api Design | `api-design/` | REST and GraphQL API design patterns. Use when designing new API endpoints, defining resource schemas, planning versioning strategies, or reviewing API contracts. Covers naming conventions, pagination, filtering, error responses, and OpenAPI documentation. |
| Backend Development | `backend-development/` | Backend API design, database architecture, microservices patterns, and test-driven development. Use for designing APIs, database schemas, or backend system architecture. |
| Code Review | `code-review/` | Automated code review for pull requests using specialized review patterns. Analyzes code for quality, security, performance, and best practices. Use when reviewing code changes, PRs, or doing code audits. |
| Codebase Audit | `codebase-audit/` | Systematic codebase audit methodology for unfamiliar codebases before architecture or implementation work. Use for new codebase, unfamiliar codebase, pre-implementation audit, codebase review, technical due diligence, or onboarding to an existing project. Produces AUDIT-FINDINGS.md and QUESTIONS.md. Routes to Architect, Planner, or Code Reviewer agents. |
| Error Handling | `error-handling/` | Error handling patterns for Python and TypeScript applications. Use when designing error hierarchies, implementing retry logic, building error boundaries, or establishing logging strategies. Covers custom exceptions, result types, circuit breakers, and user-facing error messages. |
| Fastapi Dev | `fastapi-dev/` | Build FastAPI backends with standard patterns, error handling, and testing |
| Javascript Typescript | `javascript-typescript/` | JavaScript and TypeScript development with ES6+, Node.js, React, and modern web frameworks. Use for frontend, backend, or full-stack JavaScript/TypeScript projects. |
| Python Development | `python/` | Modern Python development with Python 3.12+, Django, FastAPI, async patterns, and production best practices. Use for Python projects, APIs, data processing, or automation scripts. |
| Refactoring | `refactoring/` | Safely refactor code while maintaining behavior. Use when improving code structure, reducing duplication, extracting functions, or modernizing legacy code. |
| Security Review | `security-review/` | Security review workflow — OWASP, code scanning, cloud infrastructure |
| Sql | `sql/` | Write high-quality, optimized SQL with best practices for performance, NULL handling, security, and readability. Database-agnostic patterns with dialect-specific notes. |

### Data

| Skill | Path | When to Use |
|-------|------|-------------|
| Database Design | `database-design/` | Database schema design, optimization, and migration patterns for PostgreSQL, MySQL, and NoSQL databases. Use for designing schemas, writing migrations, or optimizing queries. |
| Db Diagram | `db-diagram/` | Turn a SQL artifact — a stored procedure, view, query, .sql file, or table name — into a diagram that explains it to a human. Use when the user says "diagram this query/proc/view/schema", "explain this SQL visually", "draw the ER diagram", "show me the data flow of this stored proc", "/mermaid-db", or "/excalidraw-db". Produces Mermaid (default, git-diffable) or Excalidraw (for design reviews). Read-only — never touches the database. |

### Devops

| Skill | Path | When to Use |
|-------|------|-------------|
| Ci Cd Pipeline | `ci-cd-pipeline/` | CI/CD pipeline design and implementation for GitHub Actions, Azure DevOps, and general pipeline architecture. Use when creating build pipelines, deployment workflows, quality gates, environment promotion strategies, or automating release processes. |
| Gh Cli | `gh-cli/` | GitHub CLI operations — issues, PRs, releases, and repo management |
| Git Commit | `git-commit/` | Create well-structured conventional commit messages following Conventional Commits standard. Use when committing changes, preparing PRs, or generating changelogs. |
| Using Git Worktrees | `using-git-worktrees/` | Use when starting feature work that needs isolation from current workspace or before executing implementation plans - creates isolated git worktrees with smart directory selection and safety verification |
| Windows Deployment | `windows-deployment/` | Deploy FastAPI + React/Vite apps to Windows Server with NSSM services, reverse proxy (IIS or nginx), and git-pull workflow. Use when deploying any web app to a Windows prod server, setting up NSSM services, configuring IIS or nginx reverse proxy, making code environment-aware for dev/prod, or troubleshooting prod deployment issues. |

### Docs

| Skill | Path | When to Use |
|-------|------|-------------|
| Code Documentation | `code-documentation/` | Writing effective code documentation - API docs, README files, inline comments, and technical guides. Use for documenting codebases, APIs, or writing developer guides. |
| Technical Writing | `technical-writing/` | Technical documentation best practices for READMEs, API docs, architecture docs, runbooks, and developer guides. Use when writing or reviewing documentation, creating onboarding guides, or establishing documentation standards. |
| Writing Plans | `writing-plans/` | Use when you have a spec or requirements for a multi-step task, before touching code |

### Frontend

| Skill | Path | When to Use |
|-------|------|-------------|
| Css Architecture | `css-architecture/` | CSS architecture, design token strategy, Tailwind conventions, CSS Modules, container queries, dark mode, responsive patterns, and animation architecture. Use for design token naming, CSS custom properties, Tailwind config, container queries, dark mode implementation, fluid typography, or CSS animation decisions. Complements frontend-design (what to achieve) with how to implement it. |
| Frontend Design | `frontend-design/` | Create distinctive, production-grade frontend interfaces with high design quality. Use this skill when the user asks to build web components, pages, artifacts, posters, or applications. Generates creative, polished code that avoids generic AI aesthetics while strictly adhering to the user's technical standards. |
| Mockup | `mockup/` | Create framework-aware UI mockups with feasibility checks. Prevents wasted effort by validating that proposed designs work within the target framework's constraints. |
| React Best Practices | `react-best-practices/` | Modern React development guidelines covering hooks, component patterns, state management, performance optimization, and TypeScript integration. |
| React Dev | `react-dev/` | This skill should be used when building React components with TypeScript, typing hooks, handling events, or when React TypeScript, React 19, Server Components are mentioned. Covers type-safe patterns for React 18-19 including generic components, proper event typing, and routing integration (TanStack Router, React Router). |
| Ui Review | `ui-review/` | Review UI implementations against design requirements, accessibility standards (WCAG 2.2 AA), and brand guidelines. Use when reviewing designs or validating UI before release. |
| Warm Editorial Ui | `warm-editorial-ui/` | Apply the "Warm Editorial Refinement" design system — a sophisticated, executive-grade aesthetic with warm cream surfaces (light mode) and warm charcoal surfaces (dark mode), Bahnschrift + Plus Jakarta Sans typography, generous rounded corners, multi-layer shadows, and a warm neutral palette. Supports both light and dark themes via CSS custom properties and the `.dark` class. Use this skill whenever the user wants to build an app, dashboard, component, or web UI using the abc-project visual style. Trigger on phrases like "use our design system", "apply our template", "make it look like abc-project", "use the warm editorial style", "use our brand template", "add dark mode", or any request to build a new tool/app/dashboard for XYZ Brand or similar contexts. This is the canonical design template for all new frontend builds. |

### Media

| Skill | Path | When to Use |
|-------|------|-------------|
| Draw Io | `draw-io/` | draw.io diagram creation, editing, and review. Use for .drawio XML editing, PNG conversion, layout adjustment, and AWS icon usage. |
| Mermaid Diagrams | `mermaid-diagrams/` | Create software diagrams using Mermaid text-based syntax. Use for class diagrams (domain modeling, OOP design), sequence diagrams (API flows, interactions), flowcharts (processes, algorithms, user journeys), ERD (database schemas), C4 architecture diagrams, state diagrams, git graphs, gantt charts, and data visualization. |
| Particle Art | `particle-art/` | Generate animated particle art React/Next.js components — zero dependencies, spring physics, CSS-variable theming, DPR-correct canvas, mouse interaction. Use when the user wants animated hero art, a living logo, a branded initial or monogram, a constellation background, or any "particles that form a shape". Triggers on "particle animation", "node network", "animated letter/logo/initials", "living letter", "morphing particles", "constellation", "neural net art", "dot field", "stipple portrait", "halftone animation", "ASCII art animation", "background art for my site", or "art that reacts to mouse". Covers — text/initials → spring-node letter; preset patterns (constellation, helix, spiral, DNA, hex-grid, wave, infinity); custom SVG paths; custom polygon points; Unicode halftone stipple; Gaussian dot field with sparks; SVG circuit traces; hybrid combos. Outputs a complete, self-contained, copy-paste-ready React component. Prefer this over p5.js (zero-dep, React-native, TypeScript), tsParticles (richer spring physics, CSS-var theming), Three.js (lightweight, no WebGL). |

### Testing

| Skill | Path | When to Use |
|-------|------|-------------|
| Playwright | `playwright/` | Complete browser automation with Playwright. Auto-detects dev servers, writes clean test scripts to /tmp. Test pages, fill forms, take screenshots, check responsive design, validate UX, test login flows, check links, automate any browser task. Use when user wants to test websites, automate browser interactions, validate web functionality, or perform any browser-based testing. |
| Tdd Workflow | `tdd-workflow/` | Test-Driven Development workflow — red-green-refactor cycle |
| Test Strategy | `test-strategy/` | Test planning and strategy for projects of any size. Use when defining what to test, choosing test types, setting coverage goals, building test pyramids, or planning quality gates. Produces TEST-STRATEGY.md with prioritized test plan. Routes to Tester agent for execution. |
| Webapp Testing | `webapp-testing/` | Toolkit for interacting with and testing local web applications using Playwright. Supports verifying frontend functionality, debugging UI behavior, capturing browser screenshots, and viewing browser logs. |

### Workflow

| Skill | Path | When to Use |
|-------|------|-------------|
| Best Practices | `best-practices/` | >- |
| Brainstorming | `brainstorming/` | You MUST use this before any creative work - creating features, building components, adding functionality, or modifying behavior. Explores user intent, requirements and design before implementation. |
| Context Curator | `context-curator/` | Compress and prioritize codebase context before handing work to reasoning agents, minimizing token waste while preserving the required decision inputs. |
| Golden Plan | `golden-plan/` | USE THIS SKILL whenever a user asks for a comprehensive implementation plan, a full-stack build plan, a UI+backend plan, or says 'create a plan for building X' where X spans multiple phases or systems. Also activate when the user says 'plan this project', 'I need a detailed plan', 'build plan', 'implementation plan', or attaches a mockup/wireframe and asks how to build it. Produces a zero-ambiguity, evidence-gated plan with self-contained per-phase prompts, exhaustive data binding tables, per-phase validation checklists, and a global quality gate. Evidence-gated: before writing phases, verify required artefacts (mockup, data sample, API contract, scaffold inventory); if any BLOCKER is missing, ask for it and wait before proceeding. Dual-mode: generic by default, junai-pipeline only when explicitly requested. Agent-agnostic - any agent with read/search/edit tools can use this skill. |
| Preflight | `preflight/` | Plan-vs-codebase validation — verifies API contracts, type names, field accuracy, dependencies, and paths before implementation begins |
| Skill Creator | `skill-creator/` | Create new skills, modify and improve existing skills, and measure skill performance. Use when users want to create a skill from scratch, edit, or optimize an existing skill, run evals to test a skill, benchmark skill performance with variance analysis, or optimize a skill's description for better triggering accuracy. |
