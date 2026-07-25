# Sub-Command Instructions

All commands below require `.understand-anything/knowledge-graph.json` to exist.
If it doesn't, tell the user to run `/understand` first.

## Efficient Graph Reading (All Commands)

- **Never dump the full graph into context** — always search first
- Use `grep -i "<term>"` in the graph file to find relevant entries
- Read only sections you need: project metadata, matched nodes, connected edges, relevant layers
- Node `summary` and `name` are the most useful fields for understanding
- Edges reveal how components connect — follow `imports` and `calls` for dependency chains

---

<a name="chat"></a>
## /understand-chat — Q&A About Codebase

Answer questions about the codebase using the knowledge graph.

**Steps:**
1. Read project metadata only — grep or read the top few lines for `"project"` section
2. Search for relevant nodes matching the user's query keywords:
   - Search `"name"` fields: `grep -i "<keyword>" knowledge-graph.json`
   - Search `"summary"` fields for semantic matches
   - Search `"tags"` arrays for topic matches
   - Note the `id` values of all matching nodes
3. Find connected edges for each matched node ID:
   - Grep for the ID to find outgoing (`"source"`) and incoming (`"target"`) edges
   - This gives the 1-hop subgraph around the query
4. Read layer context — grep for the matched node IDs in `"layers"` to find architectural context
5. Answer using only the relevant subgraph:
   - Reference specific files, functions, and relationships from the graph
   - Explain which layers are relevant and why
   - If query matches nothing, say so and suggest related terms from the graph

---

<a name="dashboard"></a>
## /understand-dashboard — Launch Interactive Dashboard

Start the interactive web dashboard for the knowledge graph.

**Steps:**
1. Resolve project directory from `$ARGUMENTS` (if provided) or use CWD
2. Verify `$PROJECT_ROOT/.understand-anything/knowledge-graph.json` exists
3. Resolve plugin root (same logic as main SKILL.md plugin detection)
4. Start the dashboard:

   **Scripted mode:**
   ```bash
   # Find dashboard server in plugin packages
   DASHBOARD_DIST="$PLUGIN_ROOT/packages/dashboard/dist"
   if [ ! -d "$DASHBOARD_DIST" ]; then
     cd "$PLUGIN_ROOT" && pnpm --filter @understand-anything/dashboard build
   fi
   node "$PLUGIN_ROOT/packages/dashboard-server/bin/serve.js" \
     --graph "$PROJECT_ROOT/.understand-anything/knowledge-graph.json" \
     --port 8080
   ```
   Report: `Dashboard running at http://localhost:8080`

   **LLM-native mode:** Report that the dashboard requires the plugin to be installed:
   > The interactive dashboard requires the Understand Anything plugin.
   > Install with: `curl -fsSL https://raw.githubusercontent.com/Lum1104/Understand-Anything/main/install.sh | bash -s vscode`
   > Then re-run `/understand-dashboard`.
   > Alternatively, I can provide a text-based summary of the graph using `/understand-chat`.

---

<a name="diff"></a>
## /understand-diff — Analyze Git Diff / PR Impact

Analyze code changes against the knowledge graph to surface affected components and risk.

**Steps:**
1. Read project metadata (grep `"project"` section)
2. Get changed files:
   - Uncommitted changes: `git diff --name-only`
   - Feature branch vs base: `git diff main...HEAD --name-only`
   - User specifies branch or PR: use that
3. Find nodes for each changed file — grep for `"filePath"` matching each changed path
   - Captures file-level nodes AND function/class nodes defined in those files
   - Note all matched node IDs as `$CHANGED_NODE_IDS`
4. Find 1-hop connected nodes (affected components):
   - For each changed node ID, grep for that ID in `"edges"` section
   - Upstream: nodes where changed ID appears as `"target"` (they depend on it)
   - Downstream: nodes where changed ID appears as `"source"` (it depends on them)
   - Record as `$AFFECTED_NODE_IDS` (exclude `$CHANGED_NODE_IDS`)
5. Identify affected layers — grep for matched IDs in `"layers"`
6. Produce structured analysis:
   - **Changed Components**: directly modified (with summaries from matched nodes)
   - **Affected Components**: potentially impacted (from 1-hop edges), with relationship explanation
   - **Affected Layers**: which architectural layers are touched, cross-layer concerns
   - **Risk Assessment**: based on node `complexity`, number of cross-layer edges, blast radius
   - Suggest what to review carefully; flag high-complexity affected nodes
7. Write diff overlay (enables dashboard visualization):
   ```json
   // .understand-anything/diff-overlay.json
   {
     "version": "1.0.0",
     "baseBranch": "<base>",
     "generatedAt": "<ISO timestamp>",
     "changedFiles": ["<paths>"],
     "changedNodeIds": ["<ids>"],
     "affectedNodeIds": ["<ids>"]
   }
   ```
   Tell user they can run `/understand-dashboard` to see the overlay visually.

---

<a name="domain"></a>
## /understand-domain — Extract Business Domain Flows

Extract business domains, flows, and process steps from the codebase and add them to the graph.

**When to derive from existing graph** (default): read `knowledge-graph.json`, extract domain concepts from node summaries and tags
**When to do lightweight scan** (`--full` flag or no graph exists): file tree + entry point detection + sampled files

**Steps:**
1. Resolve `PROJECT_ROOT` (same logic as main skill)
2. Check for `--full` flag or absence of `knowledge-graph.json`

   **From existing graph** (fast path):
   - Read nodes and their summaries, tags, and layer assignments
   - Identify business domains by clustering nodes with related tags and summaries
   - Extract flows: sequences of operations that accomplish a business goal
   - Map each flow to its constituent nodes

   **Lightweight scan** (`--full` or no graph):
   - Run file discovery (reduced Phase 1): detect entry points, key files
   - Sample representative files from each directory
   - Analyze sampled files for business logic patterns

3. For each domain/flow identified, dispatch `domain-analyzer` subagent (scripted) or analyze inline (LLM-native)

4. Produce domain nodes:
   - `domain` nodes: high-level business areas (e.g., `domain:authentication`, `domain:billing`)
   - `flow` nodes: business processes (e.g., `flow:user-registration`)
   - `step` nodes: individual steps within a flow (e.g., `step:validate-email`)

5. Produce domain edges:
   - `contains_flow`: domain → flow
   - `flow_step`: flow → step (ordered)
   - `related`: step → existing graph nodes that implement the step

6. Merge domain nodes/edges into `knowledge-graph.json` (append, preserving existing nodes/edges)
7. Report: domains found, flows extracted, steps mapped

---

<a name="explain"></a>
## /understand-explain — Deep-Dive Explanation of a Component

Provide a thorough explanation of a specific file, function, class, or module.

**Steps:**
1. Find the target node — grep `knowledge-graph.json` for `$ARGUMENTS` (path or name):
   - File path match: search `"filePath"` fields
   - Function notation (`file.ts:functionName`): search `"name"` filtered by file path
   - Partial name: search `"name"` fields broadly
   - Note the exact `id`, `type`, `summary`, `tags`, `complexity`
2. Find all connected edges for the target node ID:
   - Outgoing (`"source"` matches): what this node calls/imports/depends on
   - Incoming (`"target"` matches): what calls/imports/depends on this node
   - Note connected node IDs and edge types
3. Read connected nodes (names, summaries, types) to build the component's neighborhood
4. Identify the layer — grep target ID in `"layers"`
5. Read the actual source file at the node's `filePath`
6. Produce explanation:
   - **Role in architecture**: which layer, why it exists, what problem it solves
   - **Internal structure**: contained functions/classes (from `contains` edges)
   - **External connections**: what it imports, what calls it, what it depends on
   - **Data flow**: inputs → processing → outputs (from source code)
   - **Patterns and complexity**: idioms, design patterns, areas worth careful attention
   - Assume the reader may not know the programming language deeply

---

<a name="knowledge"></a>
## /understand-knowledge — Analyze LLM Wiki Knowledge Base

Analyze a Karpathy-pattern LLM wiki and produce a knowledge graph of entities, relationships, and topics.

**Detection signals** (all should be present):
- `index.md` exists with category structure
- Multiple `.md` files with `[[wikilink]]` syntax
- Optional: `raw/` directory with source documents
- Optional: `log.md` chronological operation log
- Optional: `CLAUDE.md`, `AGENTS.md`, or similar schema file

**Steps:**
1. Resolve wiki directory from `$ARGUMENTS` or CWD
2. Detect the wiki structure:
   - Parse `index.md` for categories and wikilink references
   - Enumerate all `.md` files in the wiki
   - Check for `raw/` directory (source documents)
   - Read schema/config file if present

3. **Phase: Deterministic extraction**
   - Extract all explicit wikilinks from each wiki file: `[[target]]` → `related` edge
   - Extract categories from `index.md`
   - Build initial node list: one node per wiki file

4. **Phase: LLM enrichment** (dispatch `article-analyzer` subagent or analyze inline)
   For each wiki article:
   - Extract named entities (people, places, concepts, technologies)
   - Identify implicit relationships not captured by wikilinks
   - Extract claims and their source references
   - Identify topic clusters

5. Produce knowledge graph nodes:
   - `article` nodes: one per wiki file
   - `entity` nodes: extracted named entities
   - `topic` nodes: thematic clusters
   - `claim` nodes: key assertions in the wiki
   - `source` nodes: raw source documents (if `raw/` exists)

6. Produce knowledge graph edges:
   - `related`: wikilinks and implicit relationships
   - `cites`: claim → source document
   - `contains`: topic → article/entity

7. Write `knowledge-graph.json` with full KnowledgeGraph structure
8. Launch dashboard (if scripted mode available)

---

<a name="onboard"></a>
## /understand-onboard — Generate Onboarding Guide

Generate a comprehensive onboarding guide from the project's knowledge graph.

**Steps:**
1. Read project metadata (grep `"project"` section: name, description, languages, frameworks)
2. Read layers — grep for `"layers"` to get full layer array with names and descriptions
3. Read tour — grep for `"tour"` to get the ordered guided walkthrough steps
4. Read file-level structural nodes only (skip function/class nodes for high-level guide):
   - Types: `file`, `config`, `document`, `service`, `pipeline`, `table`, `schema`, `resource`, `endpoint`
   - Extract `name`, `filePath`, `summary`, `complexity` for each
5. Identify complexity hotspots — nodes with `complexity: "complex"` or `"high"`
6. Generate onboarding guide as markdown with these sections:
   - **Project Overview**: name, languages, frameworks, description
   - **Architecture**: each layer's name, description, and key files
   - **Key Concepts**: important patterns and design decisions (from node summaries and tags)
   - **Guided Tour**: step-by-step walkthrough (from the `tour` section, ordered by `order`)
   - **File Map**: what each key file does, organized by layer
   - **Complexity Hotspots**: areas to approach carefully (from complexity values)
   - **Getting Started**: how to run, configure, and contribute (from config/pipeline nodes)
7. Offer to save as `docs/ONBOARDING.md` in the project
8. Suggest committing it so the team benefits from it
