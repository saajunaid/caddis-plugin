# /understand Pipeline — Full Phase Specifications

## Phase 0 — Pre-flight

### Resolve PROJECT_ROOT
Parse `$ARGUMENTS` for a non-flag token (no leading `--`). If found, treat as target directory:
- Resolve relative paths against CWD
- Verify: `test -d <path>` — abort with error if not a directory
- Set `PROJECT_ROOT` to the resolved absolute path
- If no path argument, `PROJECT_ROOT = CWD`

### Worktree Redirect
If running inside a git worktree, redirect output to the main repo root to prevent ephemeral data loss:
```bash
COMMON_DIR=$(git -C "$PROJECT_ROOT" rev-parse --git-common-dir 2>/dev/null)
GIT_DIR=$(git -C "$PROJECT_ROOT" rev-parse --git-dir 2>/dev/null)
# If COMMON_DIR != GIT_DIR, we're in a worktree; main root = dirname(COMMON_DIR)
```
Skip redirect if `UNDERSTAND_NO_WORKTREE_REDIRECT=1`.

### Config Flags
- `--auto-update` in `$ARGUMENTS` → write `{"autoUpdate": true}` to `$PROJECT_ROOT/.understand-anything/config.json`
- `--no-auto-update` → write `{"autoUpdate": false}`
- `--language <code>` → normalize code (friendly names → ISO: `chinese` → `zh`, etc.) and write `{"outputLanguage": "<code>"}` to config. Store as `$OUTPUT_LANGUAGE`. Build `$LANGUAGE_DIRECTIVE`:
  > **Language directive**: Generate all textual content (summaries, descriptions, tags, titles, languageNotes, languageLesson) in **{language}**. Maintain technical accuracy while using natural, native-level phrasing. Keep technical terms in English when no standard translation exists (e.g., "middleware", "hook", "barrel").
- If no `--language` flag, read `outputLanguage` from config.json; default to `en`.

### Incremental vs Full Decision
1. Get current commit: `git rev-parse HEAD`
2. Create dirs: `mkdir -p $PROJECT_ROOT/.understand-anything/intermediate $PROJECT_ROOT/.understand-anything/tmp`
3. Check for existing `knowledge-graph.json` and `meta.json` (read `gitCommitHash` from meta).

| Condition | Action |
|---|---|
| `--full` flag | Full analysis (all phases) |
| No existing graph or meta | Full analysis |
| `--review` + existing graph + unchanged commit | Skip to Phase 6 (copy existing graph to `intermediate/assembled-graph.json`) |
| Existing graph + unchanged commit | Ask user: (a) full rebuild, (b) LLM review, (c) do nothing |
| Existing graph + changed files | Incremental update |

### Project Context Collection
Read these for subagent injection:
- `$README_CONTENT` — first 3000 chars of `README.md` (or `.rst`, `.md` variants)
- `$MANIFEST_CONTENT` — first manifest found: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `pom.xml`
- `$DIR_TREE` — `find $PROJECT_ROOT -maxdepth 2 -type f -not -path '*/node_modules/*' -not -path '*/.git/*' -not -path '*/dist/*' | head -100`
- `$ENTRY_POINT` — first match from: `src/index.ts`, `src/main.ts`, `src/App.tsx`, `index.js`, `main.py`, `manage.py`, `app.py`, `main.go`, `src/main.rs`, `Program.cs`, `index.php`

---

## Phase 0.5 — Ignore Configuration

1. Check if `$PROJECT_ROOT/.understand-anything/.understandignore` exists.
2. **If missing**: Generate a starter `.understandignore` that:
   - Excludes built-in defaults: `node_modules/`, `.git/`, `vendor/`, `dist/`, `build/`, `*.lock`, `*.min.js`, image files, etc.
   - Reads `.gitignore` and comments out its entries as suggestions
   - Lists detected directories (`test/`, `tests/`, `fixtures/`, `docs/`, `migrations/`, `.storybook/`) as commented suggestions
   - **In scripted mode**: run the bundled Node.js generator from `$PLUGIN_ROOT/understand-anything-plugin/skills/understand/`
   - **In LLM-native mode**: construct the file manually from the defaults above

   Report to user and **wait for confirmation** before proceeding.
3. **If exists**: Report found, **wait for confirmation** before proceeding.

---

## Phase 1 — SCAN

`[Phase 1/7] Scanning project files...`

**Scripted mode**: Dispatch `project-scanner` subagent (definition at `agents/project-scanner.md` in plugin root). Inject `$README_CONTENT`, `$MANIFEST_CONTENT`, and `$LANGUAGE_DIRECTIVE`.
Output: `$PROJECT_ROOT/.understand-anything/intermediate/scan-result.json`

**LLM-native mode**: Perform scanning directly:
1. Recursively list all files respecting `.understandignore` patterns
2. Detect languages by extension, frameworks by manifest/config file patterns
3. Build `scan-result.json` with:
   - `projectName`, `projectDescription` (from README/manifest)
   - `languages[]`, `frameworks[]`
   - `files[]`: `{ path, sizeLines, language, fileCategory }` where `fileCategory` is one of: `code`, `config`, `docs`, `infra`, `data`, `script`, `markup`
   - `importMap`: `{ [filePath]: string[] }` — project-internal imports per file (empty array for non-code)

Read result and store `$FILE_LIST` (with fileCategory metadata) and `$IMPORT_MAP`.

**Gate**: If >100 files, inform user and suggest scoping with a subdirectory argument. Proceed only if user confirms.

If `filteredByIgnore > 0`, report: `Excluded {N} files via .understandignore.`

---

## Phase 1.5 — BATCH *(Scripted mode only — skip in LLM-native)*

`[Phase 1.5/7] Computing semantic batches...`

```bash
node <SKILL_DIR>/compute-batches.mjs $PROJECT_ROOT
```

Reads `scan-result.json`, writes `intermediate/batches.json`.
- Append any `Warning:` lines from stderr to `$PHASE_WARNINGS`
- Non-zero exit = fatal — relay full stderr to user, do not recover

**LLM-native fallback**: Manually group files into batches of ~10 files each, respecting directory locality. Store as `$BATCHES` in memory.

---

## Phase 2 — ANALYZE

`[Phase 2/7] Analyzing files — <N> files in <B> batches (up to 5 concurrent)...`

**Scripted mode**: Load `intermediate/batches.json`. For each batch, dispatch a `file-analyzer` subagent (definition at `agents/file-analyzer.md`). Run ≤5 concurrently.

Dispatch prompt template:
```
Analyze these files and produce GraphNode and GraphEdge objects.
Project root: $PROJECT_ROOT
Project: <projectName>
Languages: <languages>
Batch: <i>/<total>
Skill directory: <SKILL_DIR>
Output: write to $PROJECT_ROOT/.understand-anything/intermediate/batch-<i>.json

Pre-resolved import data:
<batchImportData JSON from batches.json[i].batchImportData>

Cross-batch neighbors with exported symbols:
<neighborMap JSON from batches.json[i].neighborMap>

Files: [list with path, sizeLines, language, fileCategory for each]
```

**CRITICAL**: Output file MUST be named `batch-<batchIndex>.json` or `batch-<batchIndex>-part-<k>.json`.
After each dispatch, verify each `batchIndex` has a corresponding output file before continuing.

**LLM-native mode**: Analyze each batch directly (no subagent dispatch). For each file in the batch:
- Read the file
- Extract nodes: file-level node, plus function/class nodes for significant components
- Extract edges: imports, calls, depends_on, contains, inherits, implements
- Write to `intermediate/batch-<i>.json`

**After all batches (both modes)**:
Run merge script (scripted) or merge manually (LLM-native):
```bash
python <SKILL_DIR>/merge-batch-graphs.py $PROJECT_ROOT
```
Output: `intermediate/assembled-graph.json`

The merge pass:
- Combines all nodes and edges from `batch-*.json`
- Normalizes node IDs (strips double prefixes, adds missing prefixes)
- Normalizes complexity: `low`→`simple`, `medium`→`moderate`, `high`→`complex`
- Deduplicates nodes by ID (keeps last), edges by `(source, target, type)`
- Drops dangling edges referencing missing nodes
- Runs `tested_by` linker: production → test direction, drops broken test edges

**Incremental update path**:
```bash
git diff <lastCommitHash>..HEAD --name-only > intermediate/changed-files.txt
node <SKILL_DIR>/compute-batches.mjs $PROJECT_ROOT --changed-files=intermediate/changed-files.txt
```
After fresh batches complete:
1. Remove old nodes whose `filePath` matches any changed file from existing graph
2. Remove old edges referencing removed nodes
3. Write pruned existing data as `batch-existing.json`
4. Run merge script on combined `batch-existing.json` + fresh `batch-*.json`

---

## Phase 3 — ASSEMBLE REVIEW

`[Phase 3/7] Reviewing assembled graph...`

Dispatch `assemble-reviewer` subagent (or review inline in LLM-native mode).

Input: `intermediate/assembled-graph.json`
Output: `intermediate/assemble-review.json` — `{ issues: string[], warnings: string[] }`

Inject:
- Full stderr from `merge-batch-graphs.py`
- `$IMPORT_MAP` for cross-batch edge verification
- List of batch files at `intermediate/batch-*.json`

Add any reviewer notes to `$PHASE_WARNINGS`.

---

## Phase 4 — ARCHITECTURE

`[Phase 4/7] Identifying architectural layers...`

Dispatch `architecture-analyzer` subagent (or analyze inline in LLM-native mode).

**Context injection** (always):
- Language context files from `skills/understand/languages/<lang>.md` for each detected language
- Framework files from `skills/understand/frameworks/<framework>.md` for each detected framework
- Locale file from `skills/understand/locales/<lang>.md` if `$OUTPUT_LANGUAGE` ≠ `en`
- `$DIR_TREE` and framework list from Phase 1

**Input to subagent**:
- All file-level nodes: `{ id, type, name, filePath, summary, tags }`
- `imports` edges
- All edge types (for cross-category analysis)

**Output**: `intermediate/layers.json`

**Normalize output** (in order):
1. Unwrap `{ "layers": [...] }` envelope if present
2. Rename `nodes` → `nodeIds`; if entries are objects, extract `.id` values
3. Synthesize missing `id` as `layer:<kebab-case-name>`
4. Convert raw file paths in `nodeIds` to `file:<relative-path>` (or appropriate type prefix)
5. Drop `nodeIds` entries that don't exist in the node set

Final layer shape (all 4 fields required):
```json
{ "id": "layer:<name>", "name": "...", "description": "...", "nodeIds": ["file:src/..."] }
```

---

## Phase 5 — TOUR

`[Phase 5/7] Building guided tour...`

Dispatch `tour-builder` subagent (or build inline in LLM-native mode).

**Context injection**: `$README_CONTENT`, `$ENTRY_POINT`, `$LANGUAGE_DIRECTIVE`

**Input to subagent**:
- All file-level nodes: `{ id, name, filePath, summary, type }`
- Layers: `{ id, name, description }` (omit nodeIds)
- All edges (all types)

**Output**: `intermediate/tour.json`

**Normalize output** (in order):
1. Unwrap `{ "steps": [...] }` envelope if present
2. Rename `nodesToInspect` → `nodeIds`; `whyItMatters` → `description`
3. Convert raw file paths in `nodeIds` to `file:<relative-path>`
4. Drop `nodeIds` entries that don't exist in the node set
5. Sort by `order`

Final step shape (all required):
```json
{ "order": 1, "title": "...", "description": "...", "nodeIds": ["file:src/..."] }
```
Optional: `languageLesson` string field.

---

## Phase 6 — REVIEW

`[Phase 6/7] Validating knowledge graph...`

Assemble final KnowledgeGraph:
```json
{
  "version": "1.0.0",
  "project": { "name", "languages", "frameworks", "description", "analyzedAt", "gitCommitHash" },
  "nodes": [...],
  "edges": [...],
  "layers": [...],
  "tour": [...]
}
```

Write to `intermediate/assembled-graph.json`.

### Default Path — Inline Deterministic Validation (no `--review` flag)

**Scripted mode**: Write and execute the Node.js inline validator (full script in main plugin SKILL.md).
Checks: required fields on all nodes, duplicate IDs, dangling edges, all file nodes assigned to layers, no multi-layer assignments, no orphan nodes.

**LLM-native mode**: Validate manually:
- Every node has: `id`, `type`, `name`, `summary`, `tags[]`
- No duplicate node IDs
- All edge `source`/`target` reference existing node IDs
- All file-type nodes assigned to exactly one layer
- All `layers[*].nodeIds` and `tour[*].nodeIds` reference existing nodes

### `--review` Path — Full LLM Review

Dispatch `graph-reviewer` subagent with:
- Assembled graph
- Phase 1 file inventory (all `{ path, sizeLines }`)
- `$PHASE_WARNINGS` list
- Cross-validation: every scan file should have a corresponding node; every graph node's `filePath` should appear in scan inventory

Output: `intermediate/review.json` — `{ issues: string[], warnings: string[], stats: {...} }`

### Issue Resolution

If `issues[]` is non-empty:
1. Auto-fix where possible: remove dangling edges, fill missing required fields (`tags` → `["untagged"]`, `summary` → `"No summary available"`), remove invalid-type nodes
2. Re-run validation once
3. If critical issues remain: save graph with warnings, skip dashboard auto-launch

---

## Phase 7 — SAVE

`[Phase 7/7] Saving knowledge graph...`

1. Write final graph to `$PROJECT_ROOT/.understand-anything/knowledge-graph.json`

2. **Scripted mode only — Generate fingerprints** (required before writing meta.json):
   ```bash
   node <SKILL_DIR>/build-fingerprints.mjs intermediate/fingerprint-input.json
   ```
   If this fails, abort Phase 7 — do NOT write meta.json.

3. Write `$PROJECT_ROOT/.understand-anything/meta.json`:
   ```json
   { "lastAnalyzedAt": "<ISO 8601>", "gitCommitHash": "<hash>", "version": "1.0.0", "analyzedFiles": <N> }
   ```

4. Clean up intermediate (preserve `scan-result.json` for future incremental runs):
   ```bash
   find $PROJECT_ROOT/.understand-anything/intermediate -mindepth 1 -maxdepth 1 \
     -not -name 'scan-result.json' -exec rm -rf {} +
   rm -rf $PROJECT_ROOT/.understand-anything/tmp
   ```

5. Report summary:
   - Project name and description
   - Files analyzed / total (breakdown by fileCategory)
   - Nodes created (by type)
   - Edges created (by type)
   - Layers identified (with names)
   - Tour steps generated
   - Warnings from `$PHASE_WARNINGS`
   - Output path

6. Only auto-launch `/understand-dashboard` if final validation passed. Otherwise report saved-with-warnings, skip dashboard.
