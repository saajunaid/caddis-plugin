# Skills Registry

> Public skill inventory generated from `SKILL.md` frontmatter. Private material and denylist-exception paths are excluded from this registry.
> Load a skill by reading its `SKILL.md`. See `project-config.md` for project-specific placeholder values.

---

## Skills by Category

### Cloud

| Skill | Path | When to Use |
|-------|------|-------------|
| AWS Agentic AI | `cloud/aws-agentic-ai/` | AWS Bedrock AgentCore expert: deploy and manage Gateway, Runtime, Memory, Identity, MCP targets and credentials. Use when working with any AgentCore component. |
| AWS CDK Development | `cloud/aws-cdk-development/` | AWS CDK infrastructure as code in TypeScript/Python: stacks, constructs, deployment. Use when the user mentions CDK, CloudFormation, IaC, cdk synth, cdk deploy, or wants to define AWS infrastructure in code. |
| AWS Cost Operations | `cloud/aws-cost-operations/` | AWS cost optimization, monitoring and operations, with MCP servers for billing analysis, cost estimation, observability and security assessment. |
| AWS Serverless EDA | `cloud/aws-serverless-eda/` | AWS serverless and event-driven architecture. Use when the user mentions serverless, Lambda, API Gateway, DynamoDB, Step Functions, EventBridge, SQS, SNS, event-driven, async processing, queues or pub/sub. |
| Building AI Agent On Cloudflare | `cloud/building-ai-agent-on-cloudflare/` | Builds stateful AI agents on Cloudflare Workers with the Agents SDK. Use when the user wants to "build an agent", "stateful agent", "WebSocket AI", or mentions "Agents SDK". |
| Building MCP Server On Cloudflare | `cloud/building-mcp-server-on-cloudflare/` | Builds and deploys remote MCP servers on Cloudflare Workers with tools and OAuth. Use when the user wants to "build MCP server", "remote MCP", "deploy MCP", or add "OAuth to MCP". |

### Coding

| Skill | Path | When to Use |
|-------|------|-------------|
| Adopt Rbac | `coding/adopt-rbac/` | Pointer to the org's RBAC adoption skill. Use for "add RBAC to this app" or "adopt rbac-kit". |
| Anchor Review | `coding/anchor-review/` | Single-model adversarial review technique — 3-lens analysis with confidence scoring and self-challenge |
| API Client Patterns | `coding/api-client-patterns/` | Typed client-side API consumption: fetch wrappers, zod validation, auth injection, TanStack Query (useQuery, useMutation, optimistic updates), tRPC, OpenAPI codegen, pagination. Use when consuming REST or tRPC APIs. |
| API Design | `coding/api-design/` | REST and GraphQL API design: endpoints, resource schemas, versioning, pagination, error responses, OpenAPI. Use when designing or reviewing API contracts. |
| Architecture Design | `coding/architecture-design/` | Design application architecture and system diagrams with layered patterns, Mermaid C4 diagrams, SQL Server data platform, and on-premise deployment considerations. |
| Backend Development | `coding/backend-development/` | Backend API design, database schemas, microservices and TDD. Use for backend system architecture. |
| Backend To Frontend Handoff Docs | `coding/backend-to-frontend-handoff/` | Document a finished backend API for frontend integration. Use when the user says 'create handoff', 'document API', 'frontend handoff', or 'API documentation'. |
| Caching Patterns | `coding/caching-patterns/` | Caching strategies for Streamlit and FastAPI applications |
| Case Management | `coding/case-management/` | Pointer to the org's case-management blueprint. Use for "add case management". |
| Code Explainer | `coding/code-explainer/` | Explain code with diagrams, analogies and step-by-step walkthroughs. Use when teaching a codebase or answering "how does this work?" |
| Code Review | `coding/code-review/` | Automated code review for quality, security, performance and best practices. Use when reviewing code changes, PRs, or doing code audits. |
| Codebase Audit | `coding/codebase-audit/` | Audit an unfamiliar codebase before architecture or implementation work. Use for a new codebase, pre-implementation audit, codebase review, technical due diligence or onboarding. Produces AUDIT-FINDINGS.md and QUESTIONS.md. |
| Cross Review | `coding/cross-review/` | Have a different vendor's model (agy Carbon by default; DeepSeek, GLM, any OpenAI-compatible endpoint) review the current diff. Use after a phase is green and before commit/merge, or for a second opinion on a risky diff. |
| Dashboard Perf Sweep | `coding/dashboard-perf-sweep/` | Re-measure dashboard/API endpoints for load-time regressions. Use when the user says "sweep dashboard performance", "check if this app needs rs-kit", or "re-measure the perf tracker". |
| Error Handling | `coding/error-handling/` | Error handling for Python and TypeScript: error hierarchies, custom exceptions, result types, retries, circuit breakers, error boundaries, logging, user-facing messages. |
| FastAPI Dev | `coding/fastapi-dev/` | Build FastAPI backends with standard patterns, error handling, and testing |
| Javascript Typescript | `coding/javascript-typescript/` | JavaScript and TypeScript development with ES6+, Node.js, React, and modern web frameworks. Use for frontend, backend, or full-stack JavaScript/TypeScript projects. |
| LLM Application Dev | `coding/llm-application-dev/` | LLM applications: prompt engineering, RAG and LLM integration. Use for AI-powered features, chatbots or LLM automation. |
| MCP Builder | `coding/mcp-builder/` | Build high-quality MCP (Model Context Protocol) servers that let LLMs use external APIs and services, in Python (FastMCP) or Node/TypeScript (MCP SDK). |
| Observability | `coding/observability/` | Structured logging, correlation IDs, PII redaction, OpenTelemetry tracing, metrics (RED), SLO alerting, health probes and Sentry, in Python and TypeScript. Use when adding logs, traces, metrics or error tracking. |
| Python Development | `coding/python/` | Modern Python 3.12+ (Django, FastAPI, async) with production best practices. Use for Python projects, APIs, data processing or scripts. |
| Refactoring | `coding/refactoring/` | Safely refactor code while maintaining behavior. Use when improving code structure, reducing duplication, extracting functions, or modernizing legacy code. |
| Security Review | `coding/security-review/` | Security review workflow — OWASP, code scanning, cloud infrastructure |
| SQL | `coding/sql/` | Write optimized, secure, readable SQL: performance, NULL handling, dialect-specific notes. |
| Understand Anything | `coding/understand-anything/` | Turn a codebase into an interactive knowledge graph. Use for /understand* commands, or when the user says "map out the codebase", "how does this project work", or "knowledge graph". |

### Data

| Skill | Path | When to Use |
|-------|------|-------------|
| Data Analysis | `data/data-analysis/` | Analyze datasets and generate insights with a systematic 5-phase workflow. Use when user provides data for analysis, asks about patterns, or needs visualizations. |
| Data Loader | `data/data-loader/` | Load Excel, JSON or CSV files into any database (SQL Server, PostgreSQL, MySQL, SQLite and others). Use when importing data files into a database. |
| Data Validation | `data/data-validation/` | Data quality and validation for ETL, API inputs and pipelines: validation rules, schema validation, data contracts, Pydantic, Great Expectations, SQL constraints. |
| Database Design | `data/database-design/` | Database schema design, migrations and query optimization for PostgreSQL, MySQL and NoSQL. |
| DB Diagram | `data/db-diagram/` | Diagram SQL artifacts (procs, views, queries, tables) as Mermaid or Excalidraw. Use when the user says "diagram this SQL", "draw the ER diagram", "/mermaid-db", or "/excalidraw-db". |
| DB Testing | `data/db-testing/` | Test, debug, and validate database connectivity and queries. Use when diagnosing connection errors, testing configurations, or validating queries before deployment. |
| Schema Migration | `data/schema-migration/` | Migrate an app's data access layer when tables or columns are renamed, merged or split: update queries, mappings and abstractions without data loss. Read-only against the database. |

### DevOps

| Skill | Path | When to Use |
|-------|------|-------------|
| Adopt App | `devops/adopt-app/` | Inventory an unscaffolded app or POC read-only and produce an adoption plan. Use when the user says "adopt this POC", "onboard this app", "never set up properly", or "get this into CI". |
| Changelog Generator | `devops/changelog-generator/` | Create user-facing changelogs and release notes from git commit history, grouping changes and rewriting technical commits in plain language. |
| CI Cd Pipeline | `devops/ci-cd-pipeline/` | CI/CD pipelines for GitHub Actions and Azure DevOps: build and deploy workflows, quality gates, environment promotion and release automation. |
| Deploy Local | `devops/deploy-local/` | Local deployment loop for Gitea-hosted projects: commit on dev, push, watch the golden CI/build/deploy workflow, check prod, and fix lint/test/pipeline failures until the deploy is healthy. |
| Gh CLI | `devops/gh-cli/` | GitHub CLI operations — issues, PRs, releases, and repo management |
| Git Commit | `devops/git-commit/` | Create well-structured conventional commit messages following Conventional Commits standard. Use when committing changes, preparing PRs, or generating changelogs. |
| Monorepo | `devops/monorepo/` | Turborepo and pnpm workspaces: turbo.json tasks, remote caching, shared packages, affected-only CI, apps/ vs packages/ layout, and pitfalls like circular deps, version drift and hoisting. |
| Port To GitHub | `devops/port-to-github/` | Port an app or repo to GitHub with verified history, CI translation, and deploy cutover. Use when the user says "move this app to GitHub", "port X to GitHub", or "migrate from Gitea". |
| Runner Move | `devops/runner-move/` | Move GitHub Actions jobs from self-hosted to GitHub-hosted runners. Use when the user says "move CI to GitHub-hosted runners", "stop using self-hosted runners", or "runner migration". |
| Safe Cleanup | `devops/safe-cleanup/` | Use BEFORE deleting a directory tree, scratchpad or git worktree, or "tidying up" generated folders, especially on Windows, where deleting through a junction or symlink destroys its target; and to verify a venv or node_modules survived. |
| Send Email | `devops/send-email/` | Email a Markdown file via Microsoft Graph or SMTP. Use to email a draft or note. |
| Update README | `devops/update-readme/` | Detect feature commits and update README sections (Features, API, Usage) to match, then stage only the README. Use when features, routes or components were added. |
| Using Git Worktrees | `devops/using-git-worktrees/` | Use when starting feature work that needs isolation from the current workspace, or before executing an implementation plan: creates an isolated git worktree safely. |
| Windows Deployment | `devops/windows-deployment/` | Deploy FastAPI + React/Vite apps to Windows Server with NSSM services, IIS or nginx reverse proxy and git-pull. Use for Windows prod deploys, NSSM, reverse proxy setup, dev/prod config, or prod troubleshooting. |

### Docs

| Skill | Path | When to Use |
|-------|------|-------------|
| Architecture Document | `docs/architecture-document/` | Generate enterprise HLD and LLD documents from the living Architecture.md, as DOCX (editable) or PPTX (executive summary). |
| Code Documentation | `docs/code-documentation/` | Write code documentation: API docs, README files, inline comments and developer guides. |
| Confluence Hla | `docs/confluence-hla/` | High-Level Architecture (HLA) documents in Simplified Technical English as Confluence Storage Format XHTML with PlantUML. Use for Confluence architecture docs or converting markdown architecture. |
| Doc Coauthoring | `docs/doc-coauthoring/` | Structured workflow for co-authoring documentation: transfer context, refine by iteration, test it on readers. Use when the user is writing docs, proposals, technical specs or decision docs. |
| Documentation Analyzer | `docs/documentation-analyzer/` | Analyze a codebase, explain what the code does, and generate documentation such as README files. |
| Explainer Doc | `docs/explainer-doc/` | Write a self-contained hand-off spec for an external team or vendor. Use when the user says "write a spec for the X team", "explainer doc", "spec for a vendor", or "hand this off to Y". |
| HLD | `docs/hld/` | Generate High-Level Design (HLD) Markdown and convert it to Confluence Storage Format XHTML with PlantUML diagrams and legends. |
| LLD | `docs/lld/` | Generate Lower-Level Design (LLD) Markdown and convert it to Confluence Storage Format XHTML with PlantUML diagrams and legends. |
| Naming Analyzer | `docs/naming-analyzer/` | Suggest better variable, function, and class names based on context and conventions. |
| Office Documents Official | `docs/office-documents-official/` | Hint for Office and PDF file work. Use when the user asks to create, edit, read or convert a Word .docx, PDF, PowerPoint .pptx or Excel .xlsx file. caddis does not ship these skills; points to Anthropic's official document-skills plugin. |
| PRD To Code | `docs/prd-to-code/` | Turn a PRD into working application code with a 6-phase method. Use when starting a project from requirements or specs. |
| Tech Explainer | `docs/tech-explainer/` | Plain-language explainer with Mermaid diagrams and STE for stakeholders. Use when the user says "explain this to X", "plain English", "STE", or "explain our findings". |
| Technical Writing | `docs/technical-writing/` | Documentation best practices for READMEs, API docs, architecture docs, runbooks and developer guides. Use when writing or reviewing docs or setting documentation standards. |
| Writing Plans | `docs/writing-plans/` | Use when you have a spec or requirements for a multi-step task, before touching code. In caddis, plans are written with /caddis:feature-plan, the only plan writer; this skill sends you there. |

### Frontend

| Skill | Path | When to Use |
|-------|------|-------------|
| Algorithmic Art | `frontend/algorithmic-art/` | Generative and algorithmic art with p5.js: flow fields, particle systems, animations, WebGL, audio-reactive visuals; exports HTML, PNG, GIF, MP4, SVG. Use for creative coding or any p5.js visual. |
| Artifacts Builder | `frontend/artifacts-builder/` | Build elaborate multi-component claude.ai HTML artifacts with React, Tailwind CSS and shadcn/ui. Use for complex artifacts with state or routing, not simple single-file HTML. |
| Banner Design | `frontend/banner-design/` | Design banners for social media, ads, website heroes and print, in 22 styles, sized for Facebook, X, LinkedIn, YouTube, Instagram and Google Display. |
| Brand Design | `frontend/brand-design/` | Brand design: logos, corporate identity (CIP) mockups, SVG icons and social media visuals. Use for logo, CIP, icon or social visual design tasks. |
| Brand Guidelines | `frontend/brand-guidelines/` | Apply brand colors and typography to artifacts. Use when brand colors, style guidelines or company design standards apply. |
| Brand Voice | `frontend/brand-voice/` | Brand voice, tone, messaging frameworks and brand consistency. Use for branded content, marketing assets, brand compliance and style guides. |
| Canvas Design | `frontend/canvas-design/` | Create original static visual art as .png or .pdf from a design philosophy. Use when the user asks for a poster, piece of art, design or other static visual. |
| CSS Architecture | `frontend/css-architecture/` | CSS architecture: design tokens, custom properties, Tailwind config, CSS Modules, container queries, dark mode, fluid typography, animation. Covers how to implement styling; frontend-design covers what to achieve. |
| Design Md | `frontend/design-md/` | Google's DESIGN.md spec for describing a visual identity to coding agents: YAML tokens, Markdown rationale, CLI for WCAG checks and DTCG/Tailwind export. Use for agent-readable design system docs. |
| Design System Tokens | `frontend/design-system-tokens/` | Design token architecture (primitive → semantic → component), CSS variables, spacing and type scales, component state specs. Use when creating design tokens. |
| Enterprise Dashboard Aesthetic System | `frontend/enterprise-dashboard-aesthetic-system/` | Use when upgrading or harmonizing React/Vite enterprise dashboards: executive analytics UI, cohesive dashboard design systems, tasteful motion, polished data-heavy pages (FastAPI + React + Tailwind + shadcn). |
| Flow Studio | `frontend/flow-studio/` | Design an interactive flow, lifecycle or journey page (nodes, lanes, links, motion, inspector, notes) from a JSON model as a self-contained demo, then build it in an app. Use for lineage, pipelines, ticket or agent journeys. |
| Frontend Design | `frontend/frontend-design/` | Create distinctive, production-grade frontend interfaces that avoid generic AI aesthetics. Use when the user asks to build web components, pages, artifacts, posters or applications. |
| Mockup | `frontend/mockup/` | Create framework-aware UI mockups with feasibility checks. Prevents wasted effort by validating that proposed designs work within the target framework's constraints. |
| Next.js App Router | `frontend/nextjs-app-router/` | Next.js App Router: Server vs Client Components, SSR/RSC, Server Actions, Middleware, data fetching, generateMetadata, route handlers, layout/page/error/loading.tsx, route groups, parallel routes, hydration issues. |
| Popular Web Designs | `frontend/popular-web-designs/` | 54 real-world design systems (Stripe, Linear, Vercel, Apple, Notion and more) as HTML/CSS reference: colors, type, components, spacing. Use when UI should match a specific company's look. |
| React Best Practices | `frontend/react-best-practices/` | Modern React development guidelines covering hooks, component patterns, state management, performance optimization, and TypeScript integration. |
| React Dev | `frontend/react-dev/` | Type-safe React 18-19 with TypeScript: components, generic components, hooks, events, Server Components, TanStack Router and React Router. Use when React TypeScript or React 19 is involved. |
| React Useeffect | `frontend/react-useeffect/` | React useEffect best practices from the official docs: when NOT to use an Effect, derived state, data fetching, synchronization. Use when writing or reviewing useEffect. |
| Responsive Mobile Native | `frontend/responsive-mobile-native/` | Adapt desktop-first web apps into responsive, mobile-native PWAs from one codebase. Use when the user says "make this PWA", "mobile-friendly", "tablet layout", or "responsive design". |
| Shadcn Radix | `frontend/shadcn-radix/` | shadcn/ui and Radix UI: setup (shadcn add, components.json), theming, react-hook-form + zod forms, TanStack Table data tables, cva variants, command palette, date picker, combobox, drawer/sheet. |
| Sketch | `frontend/sketch/` | Generate 2-3 interactive HTML design variants to compare UI directions before production code. Use for early design exploration or when asked to "sketch this screen" or "show me variants". |
| Slides | `frontend/slides/` | Create strategic HTML presentations with Chart.js, design tokens, responsive layouts, copywriting formulas, and contextual slide strategies. |
| Streamlit Dev | `frontend/streamlit-dev/` | Build production Streamlit dashboards: caching, components, theming. Use for any Streamlit page, component, chart or UI feature. |
| Theme Factory | `frontend/theme-factory/` | Style artifacts (slides, docs, reports, HTML pages) with one of 10 preset themes or a newly generated theme. |
| UI Review | `frontend/ui-review/` | Review a UI against design requirements, WCAG 2.2 AA and brand guidelines. Use when validating UI before release. |
| UI Styling Patterns | `frontend/ui-styling-patterns/` | Accessible UIs with shadcn/ui, Radix and Tailwind CSS: responsive layouts, theming, dark mode and consistent styling. |
| UI UX Intelligence | `frontend/ui-ux-intelligence/` | Data-backed UI/UX decisions from CSV knowledge bases: 50+ styles, 161 palettes, 57 font pairings, UX guidelines, chart types. Use to look up palettes, font pairs or style guidance. |
| Warm Editorial UI | `frontend/warm-editorial-ui/` | Apply the Warm Editorial Refinement design system. Use when the user says "use our design system", "warm editorial style", "apply our template", or "make it look like abc-project". |
| Webapp Development | `frontend/webapp-development/` | End-to-end web application development workflow with brand theming and standard patterns |
| Word Cloud | `frontend/word-cloud/` | Generate static or animated word clouds from any text source (PDF, DOCX, XLSX, PPTX, HTML, CSV, TXT), with theming, sentiment coloring and shape masks. |

### Testing

| Skill | Path | When to Use |
|-------|------|-------------|
| Component Testing | `testing/component-testing/` | React component tests with Vitest, Testing Library, userEvent, renderHook and MSW: setup, queries, hooks, API mocking, snapshots, loading/error states. E2E is playwright; method is tdd-workflow. |
| Performance Testing | `testing/performance-testing/` | Performance and load testing for APIs, databases and web apps: budgets, profiling, scalability, with Locust, k6 and pytest-benchmark. |
| Playwright | `testing/playwright/` | Browser automation and testing with Playwright: auto-detects dev servers; tests pages, forms, logins, links, screenshots and responsive layouts. Use to test websites or automate any browser task. |
| Tdd Workflow | `testing/tdd-workflow/` | Test-Driven Development workflow — red-green-refactor cycle |
| Test Strategy | `testing/test-strategy/` | Plan what to test: test types, coverage goals, test pyramid, quality gates. Produces a prioritized TEST-STRATEGY.md for the Tester agent. |
| UI Testing | `testing/ui-testing/` | Create automated UI tests using Playwright for Streamlit and web applications. Use when writing end-to-end tests, automating UI testing, or testing new features. |
| Webapp Testing | `testing/webapp-testing/` | Test local web apps with Playwright: verify frontend behavior, debug UI, capture screenshots and browser logs. |

### Workflow

| Skill | Path | When to Use |
|-------|------|-------------|
| Agent Md Refactor | `workflow/agent-md-refactor/` | Refactor bloated agent instruction files (AGENTS.md, .cursorrules, .github/ files) into linked, progressively disclosed docs. |
| Agent Orchestration | `workflow/agent-orchestration/` | Blueprint for orchestrating the agent pipeline from spec to planning, implementation, testing and debugging, plus when a second model is worth it, the intent→model map and cost guardrails. |
| Ask Questions If Underspecified | `workflow/asking-questions/` | Clarify requirements before implementing. Do not use automatically, only when invoked explicitly. |
| Best Practices | `workflow/best-practices/` | Transforms vague prompts into optimized Claude Code prompts. Adds verification, specific context, constraints, and proper phasing. Invoke with /best-practices. |
| Brainstorming | `workflow/brainstorming/` | Use before any creative work: new features, components or behavior changes, or planning anything new. Finds what the user wants first. |
| Context Curator | `workflow/context-curator/` | Compress and prioritize codebase context before handing work to reasoning agents, minimizing token waste while preserving the required decision inputs. |
| Data Contract Pipeline | `workflow/data-contract-pipeline/` | Build, audit, and validate DB-to-UI data contracts. Use when the user mentions data mapping, UI lineage, DisplayDTOs, source-to-screen mapping, or asks if a UI is backed by real data. |
| Developer Growth Analysis | `workflow/developer-growth-analysis/` | Analyze recent Claude Code chat history for coding patterns and gaps, find learning resources on HackerNews, and send a growth report to Slack DMs. |
| File Organizer | `workflow/file-organizer/` | Organize files and folders by context: find duplicates, suggest better structures, automate cleanup. |
| Game Changing Features | `workflow/game-changing-features/` | Find 10x product opportunities and high-leverage features. Use when the user mentions '10x', says 'what would make this 10x better', 'product strategy', or 'what should we build next'. |
| Golden Nuggets | `workflow/golden-nuggets/` | Extract durable tribal knowledge ('gold nuggets') from a codebase or changed files and route each to an instruction file, runbook, hub or CI review inbox. Use after a feature, fix, sprint, incident or release. |
| Intent Writer | `workflow/intent-writer/` | Structure freetext ideas, backlog items, or vague requirements into a formal Intent Document that preserves user intent across the entire agent pipeline chain. |
| Preflight | `workflow/preflight/` | Plan-vs-codebase validation — verifies API contracts, type names, field accuracy, dependencies, and paths before implementation begins |
| Receiving Code Review | `workflow/receiving-code-review/` | Use when receiving code review feedback, before implementing it, especially if it seems unclear or wrong: verify with technical rigor, no performative agreement or blind implementation. |
| Roadmap | `workflow/roadmap/` | Track milestones across plans in .caddis/roadmaps/<slug>/: next batch, typed blockers, rollup. Every change is a docs PR via caddis_roadmap.py. |
| Setup Project AI | `workflow/setup-project-ai/` | Install or refresh the project AI harness: AGENTS.md, CLAUDE.md shims, agents, settings. Use when the user says 'set up the harness', 'generate CLAUDE.md', or runs /setup-project-ai. |
| Skill Creator | `workflow/skill-creator/` | Create, edit and improve skills, run evals and benchmarks, and optimize a skill's description for triggering accuracy. |
| Verification Loop | `workflow/verification-loop/` | Systematic code change verification — lint, test, type-check, review |

### Media

| Skill | Path | When to Use |
|-------|------|-------------|
| Architecture Diagram | `media/architecture-diagram/` | Dark-themed architecture diagrams as self-contained HTML/SVG, no external tools. Use for system, cloud, microservice and deployment diagrams. |
| Ascii Art | `media/ascii-art/` | Create ASCII art (banners, borders, image conversion, custom art), choosing between pyfiglet, cowsay, TOIlet, boxes and more. |
| Draw Io | `media/draw-io/` | draw.io diagram creation, editing, and review. Use for .drawio XML editing, PNG conversion, layout adjustment, and AWS icon usage. |
| Excalidraw | `media/excalidraw/` | Brand-themed Excalidraw diagrams for project documentation |
| Flow Chart From Counts | `media/flow-chart-from-counts/` | Turn a from-to-count edge list into a zoomable Mermaid flow chart page with counts, a legend and a render check. |
| Mermaid Diagrams | `media/mermaid-diagrams/` | Software diagrams in Mermaid: class, sequence, flowchart, ERD, C4, state, git graph, gantt. Use for domain models, API flows, processes and database schemas. |
| Particle Art | `media/particle-art/` | Zero-dependency animated particle art as a React/Next.js component (spring physics, CSS-variable theming, mouse interaction). Use for animated hero art or a living logo, or on "particle animation", "animated letter/logo/initials" or "morphing particles". |
| Plantuml | `media/plantuml/` | Brand-themed PlantUML diagrams for project documentation |
| SVG Create | `media/svg-create/` | Brand-themed SVG diagrams with consistent color palette and accessible design |

### Productivity

| Skill | Path | When to Use |
|-------|------|-------------|
| GitHub Issues | `productivity/github-issues/` | Create well-structured GitHub issues with proper labels, descriptions, and acceptance criteria. Use when creating bug reports, feature requests, or tracking tasks. |
| Internal Comms | `productivity/internal-comms/` | Write internal communications in company formats: status reports, leadership updates, newsletters, FAQs, incident reports, project updates. |
| Jira Issues | `productivity/jira-issues/` | Create, update and manage Jira issues from natural language: log bugs, create tickets, update status, manage the backlog. |
