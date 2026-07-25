# Skills Registry

> Bundle skill inventory generated from `SKILL.md` frontmatter for the shipped subset.
> Load a skill by reading its `SKILL.md`.

---

## Skills by Category

### Cloud

| Skill | Path | When to Use |
|-------|------|-------------|
| Aws Agentic Ai | `aws-agentic-ai/` | AWS Bedrock AgentCore comprehensive expert for deploying and managing all AgentCore services. Use when working with Gateway, Runtime, Memory, Identity, or any AgentCore component. Covers MCP target deployment, credential management, schema optimization, runtime configuration, memory management, and identity services. |
| Aws Cdk Development | `aws-cdk-development/` | AWS Cloud Development Kit (CDK) expert for building cloud infrastructure with TypeScript/Python. Use when creating CDK stacks, defining CDK constructs, implementing infrastructure as code, or when the user mentions CDK, CloudFormation, IaC, cdk synth, cdk deploy, or wants to define AWS infrastructure programmatically. Covers CDK app structure, construct patterns, stack composition, and deployment workflows. |
| Aws Cost Operations | `aws-cost-operations/` | This skill provides AWS cost optimization, monitoring, and operational best practices with integrated MCP servers for billing analysis, cost estimation, observability, and security assessment. |
| Aws Serverless Eda | `aws-serverless-eda/` | AWS serverless and event-driven architecture expert based on Well-Architected Framework. Use when building serverless APIs, Lambda functions, REST APIs, microservices, or async workflows. Covers Lambda with TypeScript/Python, API Gateway (REST/HTTP), DynamoDB, Step Functions, EventBridge, SQS, SNS, and serverless patterns. Essential when user mentions serverless, Lambda, API Gateway, event-driven, async processing, queues, pub/sub, or wants to build scalable serverless applications with AWS best practices. |
| Building Ai Agent On Cloudflare | `building-ai-agent-on-cloudflare/` | | |
| Building Mcp Server On Cloudflare | `building-mcp-server-on-cloudflare/` | | |

### Coding

| Skill | Path | When to Use |
|-------|------|-------------|
| Anchor Review | `anchor-review/` | Single-model adversarial review technique — 3-lens analysis with confidence scoring and self-challenge |
| Api Client Patterns | `api-client-patterns/` | Typed API client patterns for consuming REST APIs and tRPC. Use for typed fetch wrappers, zod response validation, API client factory, auth injection, TanStack Query (useQuery, useMutation, infinite queries, optimistic updates), tRPC end-to-end types, error handling with discriminated unions, OpenAPI client codegen, or pagination envelopes. Complements backend-development (server side) with client-side consumption patterns. |
| Architecture Design | `architecture-design/` | Design application architecture and system diagrams with layered patterns, Mermaid C4 diagrams, SQL Server data platform, and on-premise deployment considerations. |
| Backend To Frontend Handoff Docs | `backend-to-frontend-handoff/` | Create API handoff documentation for frontend developers. Use when backend work is complete and needs to be documented for frontend integration, or user says 'create handoff', 'document API', 'frontend handoff', or 'API documentation'. |
| Caching Patterns | `caching-patterns/` | Caching strategies for Streamlit and FastAPI applications |
| Code Explainer | `code-explainer/` | Explain code with visual diagrams, analogies, and step-by-step walkthroughs. Use when explaining how code works, teaching about a codebase, or answering "how does this work? |
| Cross Review | `cross-review/` | Cross-vendor code review — have a different vendor's model (DeepSeek/GLM/any OpenAI-compatible endpoint) review the current diff to catch bugs a same-vendor reviewer misses. Use after a phase is green and before commit/merge, or for a second opinion on a risky diff. |
| Llm Application Dev | `llm-application-dev/` | Building applications with Large Language Models - prompt engineering, RAG patterns, and LLM integration. Use for AI-powered features, chatbots, or LLM-based automation. |
| Mcp Builder | `mcp-builder/` | Guide for creating high-quality MCP (Model Context Protocol) servers that enable LLMs to interact with external services through well-designed tools. Use when building MCP servers to integrate external APIs or services, whether in Python (FastMCP) or Node/TypeScript (MCP SDK). |
| Observability | `observability/` | Structured logging, OpenTelemetry distributed tracing, metrics (RED method), health checks, and error tracking with Sentry. Use for structured logs, correlation IDs, PII redaction, OpenTelemetry setup, distributed tracing, metrics counters/histograms/gauges, SLO-based alerting, liveness/readiness probes, or Sentry integration. Dual Python/TypeScript examples throughout. |
| Understand Anything | `understand-anything/` | > |

### Data

| Skill | Path | When to Use |
|-------|------|-------------|
| Data Analysis | `data-analysis/` | Analyze datasets and generate insights with a systematic 5-phase workflow. Use when user provides data for analysis, asks about patterns, or needs visualizations. |
| Data Loader | `data-loader/` | Load data from files (Excel, JSON, CSV) into databases. Use when user needs to import data files into any database system. Database-agnostic - supports SQL Server, PostgreSQL, MySQL, SQLite, and others. |
| Data Validation | `data-validation/` | Data quality and validation patterns for ETL pipelines, API inputs, and data processing. Use when defining validation rules, building data quality checks, implementing schema validation, or designing data contracts. Covers Pydantic, Great Expectations patterns, and SQL-level constraints. |
| Db Testing | `db-testing/` | Test, debug, and validate database connectivity and queries. Use when diagnosing connection errors, testing configurations, or validating queries before deployment. |
| Schema Migration | `schema-migration/` | Migrate an application's data access layer from one database schema to another. Use when tables are renamed, consolidated, split, or columns change — and the app's queries, mappings, and abstraction layer must be updated without data loss. Read-only against the database. |

### Devops

| Skill | Path | When to Use |
|-------|------|-------------|
| Changelog Generator | `changelog-generator/` | Automatically creates user-facing changelogs from git commits by analyzing commit history, categorizing changes, and transforming technical commits into clear, customer-friendly release notes. Turns hours of manual changelog writing into minutes of automated generation. |
| Deploy Local | `deploy-local/` | End-to-end local deployment loop for Gitea-hosted projects. Use when the user wants to commit on dev, push to remote, monitor the golden CI/build/deploy workflow, validate prod on the configured prod host, and fix lint/test/pipeline failures until deployment is healthy. |
| Monorepo | `monorepo/` | Monorepo management with Turborepo and pnpm workspaces. Use for Turborepo setup, turbo.json task dependencies, remote caching, pnpm workspace protocol, shared packages (ui-library, config, types), affected-only CI/CD builds, or monorepo structure (apps/ vs packages/). Covers pitfalls like circular deps, version drift, and hoisting issues. |
| Update Readme | `update-readme/` | Detect feature commits and update README sections (Features, API, Usage) with accurate repo-aware changes, then stage only README for a docs commit. Use when users add features/routes/components and want README maintained automatically. |
| Windows Deployment | `windows-deployment/` | Deploy FastAPI + React/Vite apps to Windows Server with NSSM services, reverse proxy (IIS or nginx), and git-pull workflow. Use when deploying any web app to a Windows prod server, setting up NSSM services, configuring IIS or nginx reverse proxy, making code environment-aware for dev/prod, or troubleshooting prod deployment issues. |

### Docs

| Skill | Path | When to Use |
|-------|------|-------------|
| Architecture Document | `architecture-document/` | Generate professional enterprise-grade HLD and LLD documents from the living Architecture.md. Outputs DOCX (editable) or PPTX (executive summary) using existing document skills. |
| Doc Coauthoring | `doc-coauthoring/` | Guide users through a structured workflow for co-authoring documentation. Use when user wants to write documentation, proposals, technical specs, decision docs, or similar structured content. This workflow helps users efficiently transfer context, refine content through iteration, and verify the doc works for readers. Trigger when user mentions writing docs, creating proposals, drafting specs, or similar documentation tasks. |
| Documentation Analyzer | `documentation-analyzer/` | Analyze codebases, explain code functionality, and generate comprehensive documentation. Use when documenting a project, creating README files, or understanding complex code. |
| Naming Analyzer | `naming-analyzer/` | Suggest better variable, function, and class names based on context and conventions. |
| Prd To Code | `prd-to-code/` | Transform PRD documents into working application code using a systematic 6-phase methodology. Use when starting projects from requirements or converting specs to implementation. |

### Frontend

| Skill | Path | When to Use |
|-------|------|-------------|
| Algorithmic Art | `algorithmic-art/` | Create browser-based visual art using p5.js — generative art, interactive visualizations, animations, 3D scenes (WebGL), audio-reactive visuals, and data visualizations. 7 production modes with export to HTML, PNG, GIF, MP4, SVG. Use for generative art, algorithmic art, flow fields, particle systems, creative coding, or any p5.js visual. |
| Artifacts Builder | `artifacts-builder/` | Suite of tools for creating elaborate, multi-component claude.ai HTML artifacts using modern frontend web technologies (React, Tailwind CSS, shadcn/ui). Use for complex artifacts requiring state management, routing, or shadcn/ui components - not for simple single-file HTML/JSX artifacts. |
| Banner Design | `banner-design/` | Design banners for social media, ads, website heroes, and print. Multiple art direction options across 22 styles (minimalist, gradient, bold typography, glassmorphism, 3D, neon, etc.) for Facebook, Twitter/X, LinkedIn, YouTube, Instagram, Google Display, website hero, and print. |
| Brand Design | `brand-design/` | Comprehensive brand design: logo generation (55 styles), corporate identity program (50 deliverables, CIP mockups), icon design (15 styles, SVG), and social photos (HTML-to-screenshot, multi-platform). Use for logo, CIP, icon, or social media visual design tasks. |
| Brand Guidelines | `brand-guidelines/` | Apply brand colors and typography to artifacts. Use when brand colors, style guidelines, visual formatting, or company design standards apply. Ensures consistency across branded content. |
| Brand Voice | `brand-voice/` | Brand voice, visual identity, messaging frameworks, asset management, and brand consistency. Use for branded content, tone of voice, marketing assets, brand compliance, and style guide work. |
| Canvas Design | `canvas-design/` | Create beautiful visual art in .png and .pdf documents using design philosophy. Use when the user asks to create a poster, piece of art, design, or other static visual piece. Creates original visual designs. |
| Design Md | `design-md/` | Google's open DESIGN.md specification for describing visual identities to coding agents. YAML tokens + Markdown rationale + npx CLI for WCAG validation and W3C DTCG/Tailwind export. Use for formal, agent-consumable design system documentation. |
| Design System Tokens | `design-system-tokens/` | Token architecture and component specifications. Three-layer tokens (primitive → semantic → component), CSS variables, spacing/typography scales, and component state definitions. Use for design token creation and systematic design. |
| Enterprise Dashboard Aesthetic System | `enterprise-dashboard-aesthetic-system/` | Use when: upgrading React/Vite enterprise dashboards, harmonizing dashboard pages, improving executive analytics UI aesthetics, creating cohesive dashboard design systems, adding tasteful motion, or turning data-heavy pages into a polished narrative cockpit. Applies to RevSight-style FastAPI + React + Tailwind + shadcn dashboards. |
| Nextjs App Router | `nextjs-app-router/` | Next.js 13+ App Router conventions, Server vs Client Components, Server Actions, Middleware, data fetching, Metadata API, and route handlers. Use for Next.js App Router directory structure, Server Actions, SSR/RSC patterns, generateMetadata, layout/page/error/loading.tsx conventions, route groups, parallel routes, or hydration issues. Companion to react-dev and react-best-practices. |
| Popular Web Designs | `popular-web-designs/` | 54 real-world design systems (Stripe, Linear, Vercel, Supabase, Apple, Notion, Cursor, etc.) as ready-to-use HTML/CSS reference. Exact color palettes, typography hierarchies, component specs, spacing, shadow systems, and font substitutions. Use when building UI that should match a specific company's aesthetic. |
| React Useeffect | `react-useeffect/` | React useEffect best practices from official docs. Use when writing/reviewing useEffect, useState for derived values, data fetching, or state synchronization. Teaches when NOT to use Effect and better alternatives. |
| Responsive Mobile Native | `responsive-mobile-native/` | > |
| Shadcn Radix | `shadcn-radix/` | shadcn/ui component library, Radix UI primitives, theming with CSS variables, react-hook-form + zod forms, TanStack Table data tables, and cva variant composition. Use for shadcn setup, shadcn add, components.json, shadcn theming, Radix accessible components, shadcn form patterns, data tables, command palette, date picker, combobox, or drawer/sheet. References css-architecture for tokens and react-best-practices for structure. |
| Sketch | `sketch/` | Generate 2-3 interactive HTML design variants to explore UI directions side-by-side before committing to production code. Use for early-stage design exploration, comparing layout approaches, or when asked to "sketch this screen" or "show me variants". |
| Slides | `slides/` | Create strategic HTML presentations with Chart.js, design tokens, responsive layouts, copywriting formulas, and contextual slide strategies. |
| Streamlit Dev | `streamlit-dev/` | Build production-ready Streamlit dashboards with best-practice patterns, caching, components, and theming. Use when implementing any Streamlit page, component, chart, or UI feature. |
| Theme Factory | `theme-factory/` | Toolkit for styling artifacts with a theme. These artifacts can be slides, docs, reportings, HTML landing pages, etc. There are 10 pre-set themes with colors/fonts that you can apply to any artifact that has been creating, or can generate a new theme on-the-fly. |
| Ui Styling Patterns | `ui-styling-patterns/` | Create accessible user interfaces with shadcn/ui components (Radix UI + Tailwind), Tailwind CSS utility-first styling, and canvas-based visual designs. Use for responsive layouts, accessible components, theme customization, dark mode, and consistent styling patterns. |
| Ui Ux Intelligence | `ui-ux-intelligence/` | UI/UX design intelligence with CSV knowledge bases: 50+ styles, 161 color palettes, 57 font pairings, 161 product types, 99 UX guidelines, and 25 chart types. Use when making design decisions that need data-backed palettes, font pairing lookups, or style-specific implementation guidance. |
| Webapp Development | `webapp-development/` | End-to-end web application development workflow with brand theming and standard patterns |
| Word Cloud | `word-cloud/` | Generate beautiful word clouds — static or animated — from any input source. Handles text extraction from PDF, DOCX, XLSX, PPTX, HTML, CSV, TXT and produces production-ready components. Includes light/dark theming, sentiment/POS color coding, shape masking, and multiple animation modes. |

### Media

| Skill | Path | When to Use |
|-------|------|-------------|
| Architecture Diagram | `architecture-diagram/` | Generate dark-themed technical architecture diagrams as self-contained HTML/SVG files. No external libraries or render tools needed — just a browser. Use for software system architecture, cloud infrastructure, microservice topologies, and deployment diagrams. |
| Ascii Art | `ascii-art/` | Create text-based ASCII art using the right tool for the job — banners, borders, image conversion, pre-made art, and LLM-generated custom art. Decision-routing framework across pyfiglet, cowsay, TOIlet, boxes, and more. |
| Excalidraw | `excalidraw/` | Brand-themed Excalidraw diagrams for project documentation |
| Image Enhancer | `image-enhancer/` | Improves the quality of images, especially screenshots, by enhancing resolution, sharpness, and clarity. Perfect for preparing images for presentations, documentation, or social media posts. |
| Notebooklm | `notebooklm/` | Use this skill to query your Google NotebookLM notebooks directly from Claude Code for source-grounded, citation-backed answers from Gemini. Browser automation, library management, persistent auth. Drastically reduced hallucinations through document-only responses. |
| Plantuml | `plantuml/` | Brand-themed PlantUML diagrams for project documentation |
| Slack Gif Creator | `slack-gif-creator/` | Toolkit for creating animated GIFs optimized for Slack, with validators for size constraints and composable animation primitives. This skill applies when users request animated GIFs or emoji animations for Slack from descriptions like "make me a GIF for Slack of X doing Y". |
| Svg Create | `svg-create/` | Brand-themed SVG diagrams with consistent color palette and accessible design |
| Video Downloader | `video-downloader/` | Downloads videos from YouTube and other platforms for offline viewing, editing, or archival. Handles various formats and quality options. |
| Youtube Transcript | `youtube-transcript/` | Download YouTube video transcripts when user provides a YouTube URL or asks to download/get/fetch a transcript from YouTube. Also use when user wants to transcribe or get captions/subtitles from a YouTube video. |

### Productivity

| Skill | Path | When to Use |
|-------|------|-------------|
| Competitive Ads Extractor | `competitive-ads-extractor/` | Extracts and analyzes competitors' ads from ad libraries (Facebook, LinkedIn, etc.) to understand what messaging, problems, and creative approaches are working. Helps inspire and improve your own ad campaigns. |
| Content Research Writer | `content-research-writer/` | Assists in writing high-quality content by conducting research, adding citations, improving hooks, iterating on outlines, and providing real-time feedback on each section. Transforms your writing process from solo effort to collaborative partnership. |
| Domain Name Brainstormer | `domain-name-brainstormer/` | Generates creative domain name ideas for your project and checks availability across multiple TLDs (.com, .io, .dev, .ai, etc.). Saves hours of brainstorming and manual checking. |
| Github Issues | `github-issues/` | Create well-structured GitHub issues with proper labels, descriptions, and acceptance criteria. Use when creating bug reports, feature requests, or tracking tasks. |
| Humanizer | `humanizer/` | Identify and remove AI writing patterns from text to make it sound natural and human. Covers 29 documented LLM output patterns. Use when asked to humanize, de-AI, un-ChatGPT, or rewrite drafts (blogs, docs, emails, PRs, releases) to sound authentic. |
| Internal Comms | `internal-comms/` | Write internal communications using company formats. Use when writing status reports, leadership updates, company newsletters, FAQs, incident reports, project updates, or any internal communications. |
| Invoice Organizer | `invoice-organizer/` | Automatically organizes invoices and receipts for tax preparation by reading messy files, extracting key information, renaming them consistently, and sorting them into logical folders. Turns hours of manual bookkeeping into minutes of automated organization. |
| Jira Issues | `jira-issues/` | Create, update, and manage Jira issues from natural language. Use when the user wants to log bugs, create tickets, update issue status, or manage their Jira backlog. |
| Job Application | `job-application/` | Write tailored cover letters and job applications using a structured methodology. Analyzes job descriptions, maps experience, and generates personalized applications. |
| Lead Research Assistant | `lead-research-assistant/` | Identifies high-quality leads for your product or service by analyzing your business, searching for target companies, and providing actionable contact strategies. Perfect for sales, business development, and marketing professionals. |
| Meeting Insights Analyzer | `meeting-insights-analyzer/` | Analyzes meeting transcripts and recordings to uncover behavioral patterns, communication insights, and actionable feedback. Identifies when you avoid conflict, use filler words, dominate conversations, or miss opportunities to listen. Perfect for professionals seeking to improve their communication and leadership skills. |
| Raffle Winner Picker | `raffle-winner-picker/` | Picks random winners from lists, spreadsheets, or Google Sheets for giveaways, raffles, and contests. Ensures fair, unbiased selection with transparency. |

### Testing

| Skill | Path | When to Use |
|-------|------|-------------|
| Component Testing | `component-testing/` | React component testing with Vitest, Testing Library, MSW, and renderHook. Use for Vitest setup, jsdom/happy-dom config, Testing Library queries, userEvent, component unit tests, testing React hooks, MSW API mocking, snapshot testing, or testing loading/error states. Complements playwright (E2E) and tdd-workflow (methodology). |
| Performance Testing | `performance-testing/` | Performance testing, load testing, and benchmarking for APIs, databases, and web applications. Use when planning load tests, setting performance budgets, profiling bottlenecks, or validating scalability. Covers Locust, k6, pytest-benchmark, browser performance, and database query profiling. |
| Ui Testing | `ui-testing/` | Create automated UI tests using Playwright for Streamlit and web applications. Use when writing end-to-end tests, automating UI testing, or testing new features. |

### Workflow

| Skill | Path | When to Use |
|-------|------|-------------|
| Agent Md Refactor | `agent-md-refactor/` | Refactor bloated agent instruction files (AGENTS.md, .cursorrules, .github/ files, etc.) to follow progressive disclosure principles. Splits monolithic files into organized, linked documentation. |
| Agent Orchestration | `agent-orchestration/` | End-to-end blueprint for orchestrating the full agent pipeline — from spec intake through planning, implementation, testing, and debugging |
| Ask Questions If Underspecified | `asking-questions/` | Clarify requirements before implementing. Do not use automatically, only when invoked explicitly. |
| Data Contract Pipeline | `data-contract-pipeline/` | **WORKFLOW SKILL** - Build, audit, and validate data-to-UI contracts for apps. Use whenever the user mentions data mapping, UI lineage, DB-to-UI, DisplayDTOs, source-to-screen mapping, data contracts, schema drift, typed API responses, frontend type alignment, mockup grounding, requirements-to-UI mapping, or asks whether a UI is backed by real DB/file data. Works for DBs, JSON, Markdown, CSV, XLSX, YAML, APIs, and UI mockups. |
| Developer Growth Analysis | `developer-growth-analysis/` | Analyzes your recent Claude Code chat history to identify coding patterns, development gaps, and areas for improvement, curates relevant learning resources from HackerNews, and automatically sends a personalized growth report to your Slack DMs. |
| File Organizer | `file-organizer/` | Intelligently organizes your files and folders across your computer by understanding context, finding duplicates, suggesting better structures, and automating cleanup tasks. Reduces cognitive load and keeps your digital workspace tidy without manual effort. |
| Game Changing Features | `game-changing-features/` | Find 10x product opportunities and high-leverage improvements. Use when user wants strategic product thinking, mentions '10x', wants to find high-impact features, or says 'what would make this 10x better', 'product strategy', or 'what should we build next'. |
| Golden Nuggets | `golden-nuggets/` | Extract durable tribal knowledge ('gold nuggets') from a codebase or a set of changed files and route each to its correct destination - instruction file, runbook, hub, or (in CI capture mode) a review inbox. This SKILL.md is the single source of truth for nugget categories, routing rules, write rules, inbox format, and verification gates. It is read by the knowledge-transfer agent (pipeline mode), by the /golden-nuggets prompt (independent mode), and referenced by the CI extraction script (capture mode). Use when capturing what was learned after a feature, fix, sprint, incident, or release. |
| Intent Writer | `intent-writer/` | Structure freetext ideas, backlog items, or vague requirements into a formal Intent Document that preserves user intent across the entire agent pipeline chain. |
| Onboard Project | `onboard-project/` | Bootstrap a new project's AI configuration by generating copilot-instructions.md and populating project-config.md. Idempotent — safe to re-run on existing projects. |
| Pipeline State | `pipeline-state/` | Read and write `.github/pipeline-state.json` to track stage progress, artefacts, supervision gates, and handoff payloads in the agent pipeline. |
| Receiving Code Review | `receiving-code-review/` | Use when receiving code review feedback, before implementing suggestions, especially if feedback seems unclear or technically questionable - requires technical rigor and verification, not performative agreement or blind implementation |
| Relay | `relay/` | Create or update a root relay.md session-continuation document for any repository. Use this skill whenever the user asks to preserve project context, resume later, hand work to a future session, create a session relay, summarize current implementation state, or generate a reusable continuation prompt. The workflow is generic and must discover project structure at runtime. |
| Requesting Code Review | `requesting-code-review/` | Use when completing tasks, implementing major features, or before merging to verify work meets requirements |
| Setup Project Ai | `setup-project-ai/` | Install or refresh the agent-agnostic development harness in a project — an AGENTS.md-canonical rules hierarchy (root + per-folder) with a CLAUDE.md @import shim beside each, lean subagents, slash commands, settings.json, and the frontend/python test env. USE THIS SKILL when setting up AI resources on a new or existing project, bootstrapping the rules files (AGENTS.md/CLAUDE.md), adding subagents/commands, or when the user says 'set up the harness', 'setup-project-ai', 'generate CLAUDE.md', 'onboard this project to Claude Code / Codex / agy', or runs /setup-project-ai. Combines a deterministic generator (scripts/setup_project_ai.py) for the must-not-vary mechanics with an AI enrichment step that curates project-specific AGENTS.md content. |
| State Tracking | `state-tracking/` | USE THIS SKILL when an agent needs to maintain a living record of task progress across multiple sessions or hand-offs. Covers append-only audit logs, CURRENT_STATE head-of-line pattern, relay hand-off protocol, and recovery from mid-session interruptions. Works in both generic and junai-pipeline modes. |
| Verification Loop | `verification-loop/` | Systematic code change verification — lint, test, type-check, review |
