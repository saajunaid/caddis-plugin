# Changelog

All notable changes to **caddis** are documented here.
Format: [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
Versioning: [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

> Naming note: caddis was published as **claudster** through 1.3.29. Entries below keep the name
> that was current when they shipped — that history is provenance, not an oversight.

---

## [1.3.34] — 2026-07-26

### Fixed

- **Migration-audit remediation (source lane).** The antigravity hook fixture now logs
  `CADDIS-HOOK-FIRED` → `~/.caddis-agy-hook.log` (was still claudster-named); the scaffolded
  `DOC-MAP.md` names the artifact dir the repo actually uses (`{{ARTIFACT_DIR}}` placeholder —
  an unmigrated `.claudster/` repo no longer gets a map pointing at `.caddis/kb/`);
  `windows-deployment` no longer ships in both the core and extras plugins; and a shipped
  instruction file no longer cites the never-built `claudster_tidy` tool.
- **Repo-root docs de-branded.** `README.md` / `USERGUIDE.md` / this changelog rewritten from the
  legacy junai product pages to caddis — what browsers of this mirror actually get.

## [1.3.30 – 1.3.33] — 2026-07-24

### Changed

- **claudster → caddis rename.** The plugin, marketplace, and commands are now `caddis` /
  `/caddis:*`; the per-repo artifact dir is `.caddis/` (with a `.claudster/` read-fallback so
  pre-rename repos keep working — run `/caddis:migrate-dir` to convert a repo, opt-in).
  Deliberately frozen under the old names: the `~/.claudster/` user scope (keys, install records),
  `claudster_*.py` script filenames, and historical provenance in docs.
- **1.3.31 – 1.3.33** — post-rename prose sweeps, `caddis_ping` MCP fixture rename, and dual-ref
  fixes across the pool.

## [1.3.11] — 2026-07-01

### Added

- **Per-repo config is fully live** — `.claudster/config.toml` now drives three sections through a
  single fail-open reader (`scripts/claudster_config.py`): `[guard]` (secret/destructive-action
  allowlist), `[doc_coverage]` (`route_tree`, `page_guide`, `claude_md_budget`, `ignore_routes`), and
  `[dream_memory]` (`prune_age_days`, `max_facts`, `surface_limit`). Every key falls back to a baked-in
  default, so the file is entirely opt-in. `config.toml.example` relabelled from RESERVED to LIVE, and
  `setup-project-ai` now deploys the config reader alongside the doc-coverage checker.

## [1.3.10] — 2026-07-01

### Added

- **Dream Memory — a self-maintaining, per-repo short-term fact store** (adapted from fann; roadmap
  Phase 5). Automatic facts that reinforce when they recur and decay when they don't, complementing
  `relay.md`, `.claudster/kb`, and the central memory via a one-way promotion path.
  - **Engine** (`scripts/dream_memory.py`) — pure, filesystem-free `merge` / `prune` (14-day decay,
    cap 200) / `conflicts` / `rank_for_surfacing`, over a fail-open JSONL store
    (`.claudster/memory.jsonl`, gitignored by default).
  - **Capture** (`scripts/dream_capture.py`, wired into the `Stop` hook) — deterministic mining of the
    session transcript: a Bash command that failed, or a build/test that went red→green. Privacy-first:
    secret-touching commands are skipped entirely, and any inline tokens/keys/credentials are redacted
    from the stored key *and* summary.
  - **Surface** (SessionStart hook) — the top ~5 reinforced facts, capped and weighted toward the
    "don't repeat this" failures. Honors `[dream_memory] surface_limit`.
  - **Reason + promote** (knowledge-transfer agent) — appends the reasoned kinds (`rejected-approach`,
    `repo-fact`) and, once a fact has recurred (hitCount ≥ 3), promotes it into a curated doc and drops
    it from the store, so nothing double-surfaces.
- **`.claudster/config.toml.example`** — a documented, opt-in template for per-repo claudster config,
  scaffolded into new repos by `setup-project-ai`.

## [1.1.0] — 2026-06-10

### Fixed

- **relay.md context bloat** — `inject_relay.py` now caps injected output at 120 lines. When the
  file exceeds the cap, the Done section bullets are replaced with a one-line summary
  (`[N bullets omitted — see git log]`). Next step, Read first on resume, Validation state, Open
  questions, and Resume prompt are always preserved in full. Graceful degradation if sections are
  unparseable.

### Changed

- **`/handoff` Done section cap** — Added a count-based pruning rule: the Done section must contain
  at most 8 bullets after writing. Older bullets collapse to
  `- [N prior milestones — see git log for full history]`. Complements the existing merge-based
  prune rule. Target: relay.md stays under ~80 lines on disk.

- **Output paths → `.claudster/`** — `/prd` now writes to `.claudster/prd/<slug>.md`; `/feature-plan`
  writes to `.claudster/plans/<slug>.md`. Keeps agent output out of `.github/`, which is reserved for
  GitHub Actions and pool infrastructure. Existing projects are unaffected until they re-run
  `/setup-project-ai`.

- **Document frontmatter** — All commands that produce deliverable Markdown (plans, PRDs, etc.) now
  include an 8-field YAML provenance block:
  `type`, `status`, `feature`, `creation-agent: claudster`,
  `Original Author`, `Creation Date`, `Creating Model`
  (plus `Last Author` / `Last Updated` / `Last Model Used` on update).
  The rule is also baked into the CLAUDE.md template deployed by `/setup-project-ai`.

### Added

- **`claudster/` docs folder** — `CLAUDSTER.md` developer handbook, `CLAUDSTER-FLOW.svg` workflow
  poster, and `CLAUDSTER-REFERENCE.svg` command/agent/skill reference poster added to the repo root.

---

## [1.0.0] — 2026-06-09

First semver release. Establishes baseline from the implicit `ab34a435430a` → `be44cc02b4c6` commit range.

### Fixed

- **Cross-platform hooks** — Rewrote all bash SessionStart / PreCompact / Stop hook commands as
  standalone Python scripts (`inject_relay.py`, `session_end.py`, `agent_log.py`). The old bash
  commands (`test -f relay.md && cat relay.md || true`, `printf '...'`) were broken on Windows where
  bash is unavailable. The Python scripts work identically on Windows, Linux, and macOS.

- **Windows UTF-8 encoding** — Added `sys.stdout.reconfigure(encoding="utf-8")` at the top of all
  hook scripts. Without this, any Unicode in relay.md (em-dashes, curly quotes, etc.) raised
  `UnicodeEncodeError` on Windows consoles running cp1252 / cp437.

- **Broken pipe / stdin drain** — `inject_relay.py` and `session_end.py` now read stdin with
  `json.load(sys.stdin)` wrapped in `try/except`. The old hooks ignored stdin entirely, which caused
  broken-pipe errors on some platforms.

### Changed

- **Skills directory flattened** — Layout changed from nested categories
  (`skills/coding/`, `skills/frontend/`, `skills/workflow/`, …) to flat top-level directories
  (`skills/react-dev/`, `skills/fastapi-dev/`, …) to match Claude Code's flat plugin-discovery
  requirement.

- **Hooks extracted from settings.template.json** — Hook definitions now live exclusively in
  `hooks.json`. `settings.template.json` contains only `permissions`. Defining hooks in both files
  caused double-firing and re-introduced machine-specific paths.

### Added

- **PostToolUse auto-lint hook** (`auto_lint.py`) — Runs `ruff` on `.py` files and `eslint` on
  `.ts` / `.tsx` / `.js` / `.jsx` files automatically after every Edit or Write tool call. No
  equivalent existed before.

- **`/ui-brief` command** — Design-first workflow: proposes font, colour, and animation tokens
  before any UI code is written. Run before any `/tdd` cycle that involves frontend work.

- **Five hook script files** — `inject_relay.py`, `agent_log.py`, `session_end.py`,
  `auto_lint.py`, `hooks.json` (replaces inline bash in settings.template.json).

- **Semver versioning** — `version` field added to both `plugin.json` files (`claudster` and
  `claudster-extras`). Version is the single source of truth in `runtime-targets.json` under each
  target's `plugin` section; `export_runtime_resources.py --profile claude` propagates it to the
  generated plugin bundles on every `junai-push`.
