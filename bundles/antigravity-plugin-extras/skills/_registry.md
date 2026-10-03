# Skills Registry

> Bundle skill inventory generated from `SKILL.md` frontmatter for the shipped subset.
> Load a skill by reading its `SKILL.md`.

---

## Skills by Category

### Cloud

| Skill | Path | When to Use |
|-------|------|-------------|
| Aws Agentic Ai | `aws-agentic-ai/` | AWS Bedrock AgentCore expert: deploy and manage Gateway, Runtime, Memory, Identity, MCP targets and credentials. Use when working with any AgentCore component. |
| Aws Cdk Development | `aws-cdk-development/` | AWS CDK infrastructure as code in TypeScript/Python: stacks, constructs, deployment. Use when the user mentions CDK, CloudFormation, IaC, cdk synth, cdk deploy, or wants to define AWS infrastructure in code. |
| Aws Cost Operations | `aws-cost-operations/` | AWS cost optimization, monitoring and operations, with MCP servers for billing analysis, cost estimation, observability and security assessment. |
| Aws Serverless Eda | `aws-serverless-eda/` | AWS serverless and event-driven architecture. Use when the user mentions serverless, Lambda, API Gateway, DynamoDB, Step Functions, EventBridge, SQS, SNS, event-driven, async processing, queues or pub/sub. |
| Building Ai Agent On Cloudflare | `building-ai-agent-on-cloudflare/` | | |
| Building Mcp Server On Cloudflare | `building-mcp-server-on-cloudflare/` | | |

### Coding

| Skill | Path | When to Use |
|-------|------|-------------|
| Adopt Rbac | `adopt-rbac/` | >- |
| Anchor Review | `anchor-review/` | Single-model adversarial review technique — 3-lens analysis with confidence scoring and self-challenge |
| Api Client Patterns | `api-client-patterns/` | Typed client-side API consumption: fetch wrappers, zod validation, auth injection, TanStack Query (useQuery, useMutation, optimistic updates), tRPC, OpenAPI codegen, pagination. Use when consuming REST or tRPC APIs. |
| Architecture Design | `architecture-design/` | Design application architecture and system diagrams with layered patterns, Mermaid C4 diagrams, SQL Server data platform, and on-premise deployment considerations. |
| Backend To Frontend Handoff Docs | `backend-to-frontend-handoff/` | Document a finished backend API for frontend integration. Use when the user says 'create handoff', 'document API', 'frontend handoff', or 'API documentation'. |
| Caching Patterns | `caching-patterns/` | Caching strategies for Streamlit and FastAPI applications |
| Case Management | `case-management/` | >- |
| Code Explainer | `code-explainer/` | Explain code with diagrams, analogies and step-by-step walkthroughs. Use when teaching a codebase or answering "how does this work?" |
| Cross Review | `cross-review/` | Have a different vendor's model (DeepSeek, GLM, any OpenAI-compatible endpoint) review the current diff. Use after a phase is green and before commit/merge, or for a second opinion on a risky diff. |
| Llm Application Dev | `llm-application-dev/` | LLM applications: prompt engineering, RAG and LLM integration. Use for AI-powered features, chatbots or LLM automation. |
| Mcp Builder | `mcp-builder/` | Build high-quality MCP (Model Context Protocol) servers that let LLMs use external APIs and services, in Python (FastMCP) or Node/TypeScript (MCP SDK). |
| Observability | `observability/` | Structured logging, correlation IDs, PII redaction, OpenTelemetry tracing, metrics (RED), SLO alerting, health probes and Sentry, in Python and TypeScript. Use when adding logs, traces, metrics or error tracking. |
| Understand Anything | `understand-anything/` | > |

### Data

| Skill | Path | When to Use |
|-------|------|-------------|
| Data Analysis | `data-analysis/` | Analyze datasets and generate insights with a systematic 5-phase workflow. Use when user provides data for analysis, asks about patterns, or needs visualizations. |
| Data Loader | `data-loader/` | Load Excel, JSON or CSV files into any database (SQL Server, PostgreSQL, MySQL, SQLite and others). Use when importing data files into a database. |
| Data Validation | `data-validation/` | Data quality and validation for ETL, API inputs and pipelines: validation rules, schema validation, data contracts, Pydantic, Great Expectations, SQL constraints. |
| Db Testing | `db-testing/` | Test, debug, and validate database connectivity and queries. Use when diagnosing connection errors, testing configurations, or validating queries before deployment. |
| Schema Migration | `schema-migration/` | Migrate an app's data access layer when tables or columns are renamed, merged or split: update queries, mappings and abstractions without data loss. Read-only against the database. |

### Devops

| Skill | Path | When to Use |
|-------|------|-------------|
| Changelog Generator | `changelog-generator/` | Create user-facing changelogs and release notes from git commit history, grouping changes and rewriting technical commits in plain language. |
| Deploy Local | `deploy-local/` | Local deployment loop for Gitea-hosted projects: commit on dev, push, watch the golden CI/build/deploy workflow, check prod, and fix lint/test/pipeline failures until the deploy is healthy. |
| Monorepo | `monorepo/` | Turborepo and pnpm workspaces: turbo.json tasks, remote caching, shared packages, affected-only CI, apps/ vs packages/ layout, and pitfalls like circular deps, version drift and hoisting. |
| Safe Cleanup | `safe-cleanup/` | Use BEFORE deleting a directory tree, scratchpad or git worktree, or "tidying up" generated folders, especially on Windows, where deleting through a junction or symlink destroys its target; and to verify a venv or node_modules survived. |
| Update Readme | `update-readme/` | Detect feature commits and update README sections (Features, API, Usage) to match, then stage only the README. Use when features, routes or components were added. |

### Docs

| Skill | Path | When to Use |
|-------|------|-------------|
| Architecture Document | `architecture-document/` | Generate enterprise HLD and LLD documents from the living Architecture.md, as DOCX (editable) or PPTX (executive summary). |
| Data Lineage | `data-lineage/` | Generates End-to-End Data Lineage and Telemetry Specifications linking UI pages, API routes, database datasets, and ETL/SP producers for watch-sight observability. |
| Doc Coauthoring | `doc-coauthoring/` | Structured workflow for co-authoring documentation: transfer context, refine by iteration, test it on readers. Use when the user is writing docs, proposals, technical specs or decision docs. |
| Documentation Analyzer | `documentation-analyzer/` | Analyze a codebase, explain what the code does, and generate documentation such as README files. |
| Hld | `hld/` | Generate High-Level Design (HLD) Markdown and convert it to Confluence Storage Format XHTML with PlantUML diagrams and legends. |
| Lld | `lld/` | Generate Lower-Level Design (LLD) Markdown and convert it to Confluence Storage Format XHTML with PlantUML diagrams and legends. |
| Naming Analyzer | `naming-analyzer/` | Suggest better variable, function, and class names based on context and conventions. |
| Prd To Code | `prd-to-code/` | Turn a PRD into working application code with a 6-phase method. Use when starting a project from requirements or specs. |

### Frontend

| Skill | Path | When to Use |
|-------|------|-------------|
| Algorithmic Art | `algorithmic-art/` | Generative and algorithmic art with p5.js: flow fields, particle systems, animations, WebGL, audio-reactive visuals; exports HTML, PNG, GIF, MP4, SVG. Use for creative coding or any p5.js visual. |
| Artifacts Builder | `artifacts-builder/` | Build elaborate multi-component claude.ai HTML artifacts with React, Tailwind CSS and shadcn/ui. Use for complex artifacts with state or routing, not simple single-file HTML. |
| Banner Design | `banner-design/` | Design banners for social media, ads, website heroes and print, in 22 styles, sized for Facebook, X, LinkedIn, YouTube, Instagram and Google Display. |
| Brand Design | `brand-design/` | Brand design: logos, corporate identity (CIP) mockups, SVG icons and social media visuals. Use for logo, CIP, icon or social visual design tasks. |
| Brand Guidelines | `brand-guidelines/` | Apply brand colors and typography to artifacts. Use when brand colors, style guidelines or company design standards apply. |
| Brand Voice | `brand-voice/` | Brand voice, tone, messaging frameworks and brand consistency. Use for branded content, marketing assets, brand compliance and style guides. |
| Canvas Design | `canvas-design/` | Create original static visual art as .png or .pdf from a design philosophy. Use when the user asks for a poster, piece of art, design or other static visual. |
| Design Md | `design-md/` | Google's DESIGN.md spec for describing a visual identity to coding agents: YAML tokens, Markdown rationale, CLI for WCAG checks and DTCG/Tailwind export. Use for agent-readable design system docs. |
| Design System Tokens | `design-system-tokens/` | Design token architecture (primitive → semantic → component), CSS variables, spacing and type scales, component state specs. Use when creating design tokens. |
| Enterprise Dashboard Aesthetic System | `enterprise-dashboard-aesthetic-system/` | Use when upgrading or harmonizing React/Vite enterprise dashboards: executive analytics UI, cohesive dashboard design systems, tasteful motion, polished data-heavy pages (FastAPI + React + Tailwind + shadcn). |
| Nextjs App Router | `nextjs-app-router/` | Next.js App Router: Server vs Client Components, SSR/RSC, Server Actions, Middleware, data fetching, generateMetadata, route handlers, layout/page/error/loading.tsx, route groups, parallel routes, hydration issues. |
| Popular Web Designs | `popular-web-designs/` | 54 real-world design systems (Stripe, Linear, Vercel, Apple, Notion and more) as HTML/CSS reference: colors, type, components, spacing. Use when UI should match a specific company's look. |
| React Useeffect | `react-useeffect/` | React useEffect best practices from the official docs: when NOT to use an Effect, derived state, data fetching, synchronization. Use when writing or reviewing useEffect. |
| Responsive Mobile Native | `responsive-mobile-native/` | > |
| Shadcn Radix | `shadcn-radix/` | shadcn/ui and Radix UI: setup (shadcn add, components.json), theming, react-hook-form + zod forms, TanStack Table data tables, cva variants, command palette, date picker, combobox, drawer/sheet. |
| Sketch | `sketch/` | Generate 2-3 interactive HTML design variants to compare UI directions before production code. Use for early design exploration or when asked to "sketch this screen" or "show me variants". |
| Slides | `slides/` | Create strategic HTML presentations with Chart.js, design tokens, responsive layouts, copywriting formulas, and contextual slide strategies. |
| Streamlit Dev | `streamlit-dev/` | Build production Streamlit dashboards: caching, components, theming. Use for any Streamlit page, component, chart or UI feature. |
| Theme Factory | `theme-factory/` | Style artifacts (slides, docs, reports, HTML pages) with one of 10 preset themes or a newly generated theme. |
| Ui Styling Patterns | `ui-styling-patterns/` | Accessible UIs with shadcn/ui, Radix and Tailwind CSS: responsive layouts, theming, dark mode and consistent styling. |
| Ui Ux Intelligence | `ui-ux-intelligence/` | Data-backed UI/UX decisions from CSV knowledge bases: 50+ styles, 161 palettes, 57 font pairings, UX guidelines, chart types. Use to look up palettes, font pairs or style guidance. |
| Webapp Development | `webapp-development/` | End-to-end web application development workflow with brand theming and standard patterns |
| Word Cloud | `word-cloud/` | Generate static or animated word clouds from any text source (PDF, DOCX, XLSX, PPTX, HTML, CSV, TXT), with theming, sentiment coloring and shape masks. |

### Media

| Skill | Path | When to Use |
|-------|------|-------------|
| Architecture Diagram | `architecture-diagram/` | Dark-themed architecture diagrams as self-contained HTML/SVG, no external tools. Use for system, cloud, microservice and deployment diagrams. |
| Ascii Art | `ascii-art/` | Create ASCII art (banners, borders, image conversion, custom art), choosing between pyfiglet, cowsay, TOIlet, boxes and more. |
| Excalidraw | `excalidraw/` | Brand-themed Excalidraw diagrams for project documentation |
| Plantuml | `plantuml/` | Brand-themed PlantUML diagrams for project documentation |
| Svg Create | `svg-create/` | Brand-themed SVG diagrams with consistent color palette and accessible design |

### Productivity

| Skill | Path | When to Use |
|-------|------|-------------|
| Github Issues | `github-issues/` | Create well-structured GitHub issues with proper labels, descriptions, and acceptance criteria. Use when creating bug reports, feature requests, or tracking tasks. |
| Internal Comms | `internal-comms/` | Write internal communications in company formats: status reports, leadership updates, newsletters, FAQs, incident reports, project updates. |
| Jira Issues | `jira-issues/` | Create, update and manage Jira issues from natural language: log bugs, create tickets, update status, manage the backlog. |

### Testing

| Skill | Path | When to Use |
|-------|------|-------------|
| Component Testing | `component-testing/` | React component tests with Vitest, Testing Library, userEvent, renderHook and MSW: setup, queries, hooks, API mocking, snapshots, loading/error states. E2E is playwright; method is tdd-workflow. |
| Performance Testing | `performance-testing/` | Performance and load testing for APIs, databases and web apps: budgets, profiling, scalability, with Locust, k6 and pytest-benchmark. |
| Ui Testing | `ui-testing/` | Create automated UI tests using Playwright for Streamlit and web applications. Use when writing end-to-end tests, automating UI testing, or testing new features. |

### Workflow

| Skill | Path | When to Use |
|-------|------|-------------|
| Agent Md Refactor | `agent-md-refactor/` | Refactor bloated agent instruction files (AGENTS.md, .cursorrules, .github/ files) into linked, progressively disclosed docs. |
| Agent Orchestration | `agent-orchestration/` | Blueprint for orchestrating the agent pipeline from spec to planning, implementation, testing and debugging, plus when a second model is worth it, the intent→model map and cost guardrails. |
| Ask Questions If Underspecified | `asking-questions/` | Clarify requirements before implementing. Do not use automatically, only when invoked explicitly. |
| Data Contract Pipeline | `data-contract-pipeline/` | Build, audit and validate data-to-UI contracts. Use when the user mentions data mapping, UI lineage, DB-to-UI, DisplayDTOs, source-to-screen mapping, data contracts, schema drift, typed API responses, mockup grounding, or asks whether a UI is backed by real data. |
| Developer Growth Analysis | `developer-growth-analysis/` | Analyze recent Claude Code chat history for coding patterns and gaps, find learning resources on HackerNews, and send a growth report to Slack DMs. |
| File Organizer | `file-organizer/` | Organize files and folders by context: find duplicates, suggest better structures, automate cleanup. |
| Game Changing Features | `game-changing-features/` | Find 10x product opportunities and high-leverage features. Use when the user mentions '10x', says 'what would make this 10x better', 'product strategy', or 'what should we build next'. |
| Golden Nuggets | `golden-nuggets/` | Extract durable tribal knowledge ('gold nuggets') from a codebase or changed files and route each to an instruction file, runbook, hub or CI review inbox. Use after a feature, fix, sprint, incident or release. |
| Golden Plan | `golden-plan/` | Use when the user asks for a comprehensive multi-phase plan (full-stack, UI + backend), says 'create a plan for building X', 'plan this project', 'I need a detailed plan', 'build plan', 'implementation plan', or attaches a mockup and asks how to build it. Produces an evidence-gated plan with self-contained phase prompts and validation gates. |
| Intent Writer | `intent-writer/` | Structure freetext ideas, backlog items, or vague requirements into a formal Intent Document that preserves user intent across the entire agent pipeline chain. |
| Receiving Code Review | `receiving-code-review/` | Use when receiving code review feedback, before implementing it, especially if it seems unclear or wrong: verify with technical rigor, no performative agreement or blind implementation. |
| Setup Project Ai | `setup-project-ai/` | Install or refresh the agent-agnostic harness in a project: AGENTS.md rules with CLAUDE.md shims, subagents, commands and settings. Use when setting up AI resources on a project, or the user says 'set up the harness', 'setup-project-ai', 'generate CLAUDE.md', 'onboard this project to Claude Code / Codex / agy', or runs /setup-project-ai. |
| Verification Loop | `verification-loop/` | Systematic code change verification — lint, test, type-check, review |
