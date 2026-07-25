"""setup_project_ai — deterministic layer of the Claude Code harness generator.

Deploys and customizes the canonical harness (claude-harness/) into a target project:
  • stack detection (pyproject/requirements/package.json + path signals, per stack-map.json)
  • placeholder substitution for provided keys, with a report of any leftovers (Phase 0 friction #1)
  • AGENTS.md-canonical rules hierarchy (root + folder AGENTS.md) with a CLAUDE.md `@AGENTS.md` shim
    beside each, so every agent reads one source of rules and Claude Code inlines it via @import
  • subagents → .claude/agents/, commands → .claude/commands/, settings → .claude/settings.json (merged)
  • frontend Vitest/jsdom test-harness scaffold when react+vitest but no DOM env (Phase 0 friction #4)
  • venv / dev-deps detection (report; create+install only with --install)

Idempotent: existing AGENTS.md / CLAUDE.md / settings are preserved unless --force; settings allow-lists
are always merged (union). This script is the must-not-vary part; AGENTS.md *enrichment* with
project-specific facts is the AI step of the setup-project-ai skill that wraps this. The CLAUDE.md
files are @import shims and are never enriched — durable rules always go in the matching AGENTS.md.

Usage:
    python scripts/setup_project_ai.py <target_dir> --name "My App" --desc "One-line description"
        [--set KEY=VALUE ...] [--force] [--install] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

def _resolve_harness_dir() -> Path:
    """Locate the harness resource root (templates, settings template, stack map).

    Two supported layouts:
      • caddis dev:            scripts/setup_project_ai.py  → ../claude-harness/
      • bundled in plugin:  plugin/scripts/setup_project_ai.py → ../  (claude-md/ et al.
        sit directly at the plugin root, with no claude-harness/ subdir).
    Pick the first candidate that actually carries the templates.
    """
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "claude-harness", here.parent):
        if (cand / "claude-md").is_dir() and (cand / "settings.template.json").is_file():
            return cand
    return here.parent / "claude-harness"  # dev default; missing-template error surfaced later


HARNESS_DIR = _resolve_harness_dir()
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
             ".ruff_cache", ".pytest_cache", "dist", "build", ".tanstack", ".codex-tmp"}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".toml", ".txt",
                 ".yml", ".yaml", ".cfg", ".ini", ".html", ".css", ".env", ".ps1", ".sh"}


# ── helpers ──────────────────────────────────────────────────────────────────
def load_stack_map() -> dict:
    return json.loads((HARNESS_DIR / "stack-map.json").read_text(encoding="utf-8"))


def iter_text_files(root: Path):
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and path.suffix in TEXT_SUFFIXES:
            yield path


def read_deps(target: Path) -> tuple[set[str], set[str]]:
    """Return (python_deps, js_deps) as lowercased package-name sets."""
    py: set[str] = set()
    for fname in ("pyproject.toml", "requirements.txt", "setup.py"):
        fp = target / fname
        if fp.exists():
            text = fp.read_text(encoding="utf-8", errors="ignore").lower()
            py.update(re.findall(r"[a-z0-9][a-z0-9._-]+", text))
    js: set[str] = set()
    for pj in (target / "package.json", target / "frontend" / "package.json"):
        if pj.exists():
            try:
                data = json.loads(pj.read_text(encoding="utf-8"))
                js.update(k.lower() for k in {**data.get("dependencies", {}),
                                             **data.get("devDependencies", {})})
            except json.JSONDecodeError:
                pass
    return py, js


def path_exists_any(target: Path, globs: list[str]) -> bool:
    for g in globs:
        if "*" in g:
            if any(p for p in target.glob(g) if not any(s in p.parts for s in SKIP_DIRS)):
                return True
        elif (target / g).exists():
            return True
    return False


def detect_stack(target: Path, stack_map: dict) -> dict:
    py_deps, js_deps = read_deps(target)
    matched: list[dict] = []
    for det in stack_map["detectors"]:
        ok = False
        if det.get("any_path") and path_exists_any(target, det["any_path"]):
            ok = True
        if det.get("any_dep") and any(d in py_deps for d in det["any_dep"]):
            ok = True
        if det.get("any_dep_json") and any(d in js_deps for d in det["any_dep_json"]):
            ok = True
        if ok:
            matched.append(det)
    return {"matched": matched, "py_deps": py_deps, "js_deps": js_deps}


def stack_summary(stack: dict) -> str:
    ids = {d["id"] for d in stack["matched"]}
    parts = []
    if "python-backend" in ids:
        parts.append("Python")
    if "fastapi" in ids:
        parts.append("FastAPI")
    if "pytest" in ids:
        parts.append("pytest")
    if "react-frontend" in ids:
        parts.append("React/Vite")
    return " · ".join(parts) if parts else "general"


def render(text: str, mapping: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        return mapping.get(m.group(1), m.group(0))
    return PLACEHOLDER_RE.sub(repl, text)


# ── steps ────────────────────────────────────────────────────────────────────
def substitute_placeholders(target: Path, mapping: dict[str, str], dry: bool) -> tuple[int, dict[str, list[str]]]:
    """Replace provided keys across text files; report leftover {{TOKENS}} grouped by file."""
    changed = 0
    leftovers: dict[str, list[str]] = {}
    for fp in iter_text_files(target):
        try:
            text = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        if "{{" not in text:
            continue
        new = render(text, mapping)
        if new != text and not dry:
            fp.write_text(new, encoding="utf-8")
        if new != text:
            changed += 1
        remaining = sorted(set(PLACEHOLDER_RE.findall(new)))
        if remaining:
            leftovers[str(fp.relative_to(target))] = remaining
    return changed, leftovers


# A folder CLAUDE.md is a 2-line @import shim — Claude Code inlines the sibling AGENTS.md (the
# canonical rules) at load. The shim resolves `@AGENTS.md` relative to its own folder, so the same
# text works at any depth. Durable folder rules always go in AGENTS.md, never in this shim.
SUBFOLDER_SHIM = (
    "# Folder conventions — canonical in AGENTS.md (imported below; Claude Code inlines it)\n"
    "@AGENTS.md\n"
)


def compose_claude_md(target: Path, stack: dict, ident: dict[str, str], force: bool, dry: bool) -> list[str]:
    """Emit the AGENTS.md-canonical rules hierarchy with a CLAUDE.md @import shim beside each.

    Root:    AGENTS.md (canonical, from agents.md.tmpl) + CLAUDE.md shim (from root.md.tmpl —
             `@AGENTS.md` + a small Claude-native-only block).
    Folders: <dir>/AGENTS.md (the composed fragment body) + <dir>/CLAUDE.md (the 2-line shim).
    stack-map `target` keys stay as `<dir>/CLAUDE.md`; the AGENTS.md path is derived here so the
    map need not change.
    """
    cm = HARNESS_DIR / "claude-md"
    written: list[str] = []
    has_stack_md = (target / "STACK.md").exists()
    mapping = {
        "PROJECT_NAME": ident["name"],
        "PROJECT_DESCRIPTION": ident["desc"],
        "STACK_SUMMARY": stack_summary(stack),
        "STACK_REFERENCE_LINE": "Full stack reference: `STACK.md`." if has_stack_md else "",
    }

    def write(rel: str, content: str):
        dest = target / rel
        if dest.exists() and not force:
            written.append(f"skip (exists): {rel}")
            return
        if not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(content, encoding="utf-8")
        written.append(f"write: {rel}")

    # root: canonical rules + the shim that imports them
    write("AGENTS.md", render((cm / "agents.md.tmpl").read_text(encoding="utf-8"), mapping))
    write("CLAUDE.md", render((cm / "root.md.tmpl").read_text(encoding="utf-8"), mapping))

    # folder fragments — only when the target folder exists. Canonical → <dir>/AGENTS.md; shim → <dir>/CLAUDE.md.
    by_target: dict[str, list[str]] = {}
    for det in stack["matched"]:
        tgt = det.get("target")
        if not tgt:
            continue
        by_target.setdefault(tgt, []).extend(det.get("fragments", []))
    for tgt, frags in by_target.items():
        folder = (target / tgt).parent
        if not folder.exists():
            written.append(f"skip (no folder): {tgt}")
            continue
        body = "\n".join((cm / f).read_text(encoding="utf-8") for f in frags)
        head, _, _fname = tgt.rpartition("/")
        agents_rel = f"{head}/AGENTS.md" if head else "AGENTS.md"
        write(agents_rel, render(body, mapping))
        write(tgt, render(SUBFOLDER_SHIM, mapping))  # <dir>/CLAUDE.md shim
    return written


def deploy_dir(src: Path, dest: Path, force: bool, dry: bool) -> list[str]:
    out: list[str] = []
    for fp in sorted(src.glob("*.md")):
        d = dest / fp.name
        if d.exists() and not force:
            out.append(f"skip (exists): {d.name}")
            continue
        if not dry:
            dest.mkdir(parents=True, exist_ok=True)
            d.write_text(fp.read_text(encoding="utf-8"), encoding="utf-8")
        out.append(f"deploy: {d.name}")
    return out


# Ask-rules the harness itself injected in older template versions. An `ask` entry OVERRIDES
# bypassPermissions and forces a prompt every time (precedence: deny → ask → allow), so these
# silently defeat a user who has opted into no-prompts. The current template ships `ask: []`;
# on merge we prune these legacy entries so already-deployed projects self-heal. Any OTHER ask
# rule a user added intentionally is left untouched.
_LEGACY_HARNESS_ASK = {"Bash(git push:*)", "Bash(rm:*)", "Bash(git reset:*)"}


def merge_settings(target: Path, stack: dict, dry: bool) -> str:
    base = json.loads((HARNESS_DIR / "settings.template.json").read_text(encoding="utf-8"))
    allow = list(base["permissions"]["allow"])
    for det in stack["matched"]:
        for a in det.get("settings_allow", []):
            if a not in allow:
                allow.append(a)
    statusline = {"type": "command", "command": "bash .claude/statusline-command.sh"}
    dest = target / ".claude" / "settings.json"
    notes: list[str] = []
    if dest.exists():
        existing = json.loads(dest.read_text(encoding="utf-8"))
        ex_allow = existing.get("permissions", {}).get("allow", [])
        for a in allow:
            if a not in ex_allow:
                ex_allow.append(a)
        existing.setdefault("permissions", {})["allow"] = ex_allow
        # Self-heal: prune legacy harness-injected `ask` rules that override bypassPermissions.
        ex_ask = existing["permissions"].get("ask", [])
        pruned_ask = [a for a in ex_ask if a not in _LEGACY_HARNESS_ASK]
        if len(pruned_ask) != len(ex_ask):
            removed = [a for a in ex_ask if a in _LEGACY_HARNESS_ASK]
            existing["permissions"]["ask"] = pruned_ask
            notes.append(f"pruned stale ask rules that override bypassPermissions ({', '.join(removed)})")
        # Strip stale hooks block — the caddis plugin owns all hooks via hooks.json.
        # Defining them here too causes double-fire at session start / pre-compact.
        if "hooks" in existing:
            del existing["hooks"]
            notes.append("removed stale hooks block (now owned by caddis plugin)")
        if "statusLine" not in existing:  # never clobber a user's own status line
            existing["statusLine"] = statusline
            notes.append("added status line")
        out = existing
        verb = "merge"
    else:
        base["permissions"]["allow"] = allow
        base["statusLine"] = statusline
        out = base
        verb = "write"
    if not dry:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    suffix = f" [{'; '.join(notes)}]" if notes else ""
    return f"{verb}: .claude/settings.json ({len(allow)} allow rules){suffix}"


def ensure_frontend_test_harness(target: Path, stack: dict, dry: bool) -> list[str]:
    cfg = load_stack_map().get("frontend_test_harness", {})
    js = stack["js_deps"]
    notes: list[str] = []
    if not any(d in js for d in cfg.get("trigger_dep_any", [])):
        return notes  # no vitest → nothing to do
    if any(d in js for d in cfg.get("require_dep_any", [])):
        notes.append("frontend test harness: DOM env already present — ok")
        return notes
    fe = target / "frontend" if (target / "frontend" / "package.json").exists() else target
    pj = fe / "package.json"
    if pj.exists() and not dry:
        data = json.loads(pj.read_text(encoding="utf-8"))
        dev = data.setdefault("devDependencies", {})
        for dep in cfg.get("ensure_dev_deps", []):
            dev.setdefault(dep, "latest")
        pj.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    notes.append(f"frontend test harness: added {cfg.get('ensure_dev_deps')} to devDependencies (run npm install)")
    setup_rel = cfg.get("setup_file", "src/test/setup.ts")
    setup_fp = fe / setup_rel
    if not setup_fp.exists() and not dry:
        setup_fp.parent.mkdir(parents=True, exist_ok=True)
        setup_fp.write_text(
            '// Vitest global setup: jest-dom matchers + DOM cleanup between tests.\n'
            'import "@testing-library/jest-dom/vitest";\n'
            'import { afterEach } from "vitest";\n'
            'import { cleanup } from "@testing-library/react";\n\n'
            'afterEach(() => {\n  cleanup();\n});\n',
            encoding="utf-8",
        )
        notes.append(f"frontend test harness: wrote {setup_rel}")
    notes.append("frontend test harness: ensure vite config uses `vitest/config` with a "
                 "`test` block (environment: jsdom, globals: true, setupFiles: './src/test/setup.ts')")
    return notes


def check_venv(target: Path, install: bool, dry: bool) -> list[str]:
    notes: list[str] = []
    has_py = (target / "pyproject.toml").exists() or (target / "requirements.txt").exists()
    if not has_py:
        return notes
    venv = target / ".venv"
    if venv.exists():
        notes.append("venv: .venv present — ok")
    elif install and not dry:
        import subprocess
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=False)
        notes.append("venv: created .venv (install dev deps: .venv/Scripts/pip install -e .[dev])")
    else:
        notes.append("venv: MISSING — create with `python -m venv .venv` then "
                     "`pip install -e .[dev]` (or re-run with --install)")
    return notes


# Enforced "green before push" gate. Installed into .git/hooks/pre-push. Pure POSIX sh
# so it runs under Git's bundled shell on Windows/Linux/macOS. Auto-skips tools that
# aren't installed; only blocks when a present tool actually fails.
PRE_PUSH_HOOK = r"""#!/usr/bin/env sh
# Managed by caddis setup-project-ai. Delete this file to opt out.
set -eu
echo "[caddis] pre-push quality gate"
fail=0
if [ -f "pyproject.toml" ] || [ -f "requirements.txt" ]; then
  command -v ruff   >/dev/null 2>&1 && { echo "[gate] ruff check ."; ruff check . || fail=1; }
  command -v mypy   >/dev/null 2>&1 && { echo "[gate] mypy ."; mypy . || fail=1; }
  command -v pytest >/dev/null 2>&1 && { echo "[gate] pytest -q"; pytest -q || fail=1; }
fi
if [ -f "package.json" ] && command -v npm >/dev/null 2>&1; then
  npm run 2>/dev/null | grep -q " lint"      && { echo "[gate] npm run lint"; npm run lint --silent || fail=1; }
  npm run 2>/dev/null | grep -q " typecheck" && { echo "[gate] npm run typecheck"; npm run typecheck --silent || fail=1; }
  npm run 2>/dev/null | grep -q " test"       && { echo "[gate] npm test"; npm test --silent || fail=1; }
fi
# Doc-coverage discipline (any stack). The checker exits non-zero ONLY on a hard invariant
# (missing route / dangling doc-map link); soft signals warn without failing. Auto-skips when the
# checker isn't present (older repos) or no python is on PATH. Probe python then python3 so the gate
# isn't silently disabled on python3-only systems (common on Linux/CI). `|| true` keeps it set -e-safe.
DOC_PY=$(command -v python || command -v python3 || true)
[ -n "$DOC_PY" ] && [ -f "scripts/check_doc_coverage.py" ] && { echo "[gate] doc coverage"; "$DOC_PY" scripts/check_doc_coverage.py --check || fail=1; }
if [ "$fail" -ne 0 ]; then
  echo "[caddis] push BLOCKED — fix the above, or 'git push --no-verify' to override." >&2
  exit 1
fi
echo "[caddis] gate passed — pushing."
"""


def install_git_hooks(target: Path, force: bool, dry: bool) -> list[str]:
    """Install the enforced pre-push quality gate into .git/hooks/pre-push."""
    notes: list[str] = []
    git = target / ".git"
    if not git.exists():
        return ["pre-push gate: no .git (not a git repo) — skipped"]
    if git.is_file():  # worktree/submodule: .git is a pointer file
        return ["pre-push gate: .git is a worktree pointer — skipped (install manually if wanted)"]
    hooks_dir = git / "hooks"
    dest = hooks_dir / "pre-push"
    if dest.exists() and not force:
        _hook_txt = dest.read_text(encoding="utf-8", errors="ignore")
        managed = "caddis" in _hook_txt or "claudster" in _hook_txt  # recognise pre-rename hooks too
        return [f"pre-push gate: exists ({'ours' if managed else 'yours — left intact, use --force to replace'}) — skipped"]
    if not dry:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(PRE_PUSH_HOOK, encoding="utf-8", newline="\n")
        try:
            import os, stat
            dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        except Exception:
            pass
    notes.append("pre-push gate: installed .git/hooks/pre-push (green-before-push enforced)")
    return notes


def deploy_statusline(target: Path, force: bool, dry: bool) -> list[str]:
    """Copy the status-line script into .claude/ so settings.json can reference it."""
    src = HARNESS_DIR / "statusline-command.sh"
    if not src.is_file():
        return []
    dest = target / ".claude" / "statusline-command.sh"
    if dest.exists() and not force:
        return ["status line: .claude/statusline-command.sh present — skipped"]
    if not dry:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
    return ["status line: wrote .claude/statusline-command.sh"]


def emit_doc_discipline(target: Path, ident: dict[str, str], force: bool, dry: bool) -> list[str]:
    """Scaffold the doc-coverage discipline into the target:
      • `.claudster/kb/DOC-MAP.md` — reference-doc index (always);
      • `UI_PAGE_GUIDE.md` — page→endpoints→DB stub (frontend repos only, i.e. a `frontend/` dir);
      • copy `scripts/check_doc_coverage.py` into the target (mirrors deploy_statusline).
    Idempotent: never clobbers an edited file unless --force. The scaffolded DOC-MAP carries no
    `.md` links so a fresh repo is gate-clean (no dangling-link hard failure)."""
    notes: list[str] = []
    cm = HARNESS_DIR / "claude-md"
    mapping = {"PROJECT_NAME": ident["name"], "PROJECT_DESCRIPTION": ident["desc"]}

    def _emit(rel: str, tmpl: str, label: str):
        src = cm / tmpl
        if not src.is_file():
            notes.append(f"{label}: template missing — skipped")
            return
        dest = target / rel
        if dest.exists() and not force:
            notes.append(f"{label}: {rel} present — kept")
            return
        if not dry:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(render(src.read_text(encoding="utf-8"), mapping),
                            encoding="utf-8", newline="\n")
        notes.append(f"{label}: wrote {rel}")

    # DOC-MAP: render the template, then pre-link the repo's discovered reference docs (README,
    # docs/…) and any existing KB notes, so a fresh repo starts with a *useful* index instead of an
    # empty placeholder. Reuses check_doc_coverage's helpers (one implementation of the link logic).
    # Idempotent: an existing (possibly edited) map is kept untouched unless --force.
    dm_rel = ".claudster/kb/DOC-MAP.md"
    dm_dest = target / dm_rel
    if not (cm / "doc-map.md.tmpl").is_file():
        notes.append("doc-map: template missing — skipped")
    elif dm_dest.exists() and not force:
        notes.append(f"doc-map: {dm_rel} present — kept")
    else:
        text = render((cm / "doc-map.md.tmpl").read_text(encoding="utf-8"), mapping)
        n_links = None
        try:
            _cs = str(HARNESS_DIR / "scripts")
            if _cs not in sys.path:
                sys.path.insert(0, _cs)
            import check_doc_coverage as _cdc
            text = _cdc.insert_table_rows(text, "Knowledge base", _cdc.kb_note_rows(target))
            text = _cdc.insert_table_rows(text, "Other key", _cdc.reference_rows(target))
            n_links = text.count("](")
        except Exception:
            pass  # discovery is a nicety — a plain template scaffold is still valid & gate-clean
        if not dry:
            dm_dest.parent.mkdir(parents=True, exist_ok=True)
            dm_dest.write_text(text, encoding="utf-8", newline="\n")
        notes.append(f"doc-map: wrote {dm_rel}" + (f" ({n_links} link(s) pre-indexed)" if n_links else ""))

    if (target / "frontend").exists():
        _emit("UI_PAGE_GUIDE.md", "ui-page-guide.md.tmpl", "page guide")

    # Copy the checker + its shared config reader into the target's scripts/ (same pattern as
    # deploy_statusline). claudster_config.py must ride along or the checker's [doc_coverage]
    # override can't be read (it falls back to defaults — safe, but the config would be inert).
    for fname, label in (
        ("check_doc_coverage.py", "doc-coverage checker"),
        ("claudster_config.py", "config reader"),
    ):
        src = HARNESS_DIR / "scripts" / fname
        dest = target / "scripts" / fname
        if not src.is_file():
            notes.append(f"{label}: source missing — skipped")
        elif dest.exists() and not force:
            notes.append(f"{label}: scripts/{fname} present — skipped")
        else:
            if not dry:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
            notes.append(f"{label}: wrote scripts/{fname}")
    return notes


def extract_project_facts(target: Path, stack: dict) -> dict:
    """Mechanically pull the facts the AI enrichment step (skill Step 3) otherwise has to
    hunt for: run/test/build commands, env-var names, CI/deploy workflows, entry points.
    Best-effort — any unreadable source is skipped. NEVER reads a real .env (only *.example),
    and captures variable NAMES only, never values."""
    facts: dict[str, list[str]] = {"commands": [], "env": [], "workflows": [], "entry": []}

    # npm scripts (root + frontend/)
    for pj in (target / "package.json", target / "frontend" / "package.json"):
        if pj.is_file():
            try:
                scripts = json.loads(pj.read_text(encoding="utf-8")).get("scripts", {})
                rel = pj.parent.relative_to(target)
                prefix = "" if str(rel) == "." else f"(in {rel}/) "
                for name in scripts:
                    facts["commands"].append(f"{prefix}npm run {name}")
            except Exception:
                pass

    # python scripts + the obvious test runner
    pp = target / "pyproject.toml"
    if pp.is_file():
        try:
            import tomllib
            data = tomllib.loads(pp.read_text(encoding="utf-8"))
            tables = [data.get("project", {}).get("scripts", {}),
                      data.get("tool", {}).get("poetry", {}).get("scripts", {})]
            for table in tables:
                for name in (table or {}):
                    facts["commands"].append(f"{name}  (pyproject script)")
        except Exception:
            pass
    if pp.is_file() or (target / "requirements.txt").is_file():
        facts["commands"].append("pytest -q   (if pytest configured)")

    # env var NAMES from example files only — never the real .env (it holds secrets)
    for envf in (".env.example", ".env.sample", ".env.template"):
        ef = target / envf
        if ef.is_file():
            try:
                for line in ef.read_text(encoding="utf-8").splitlines():
                    s = line.strip()
                    if s and not s.startswith("#") and "=" in s:
                        nm = s.split("=", 1)[0].strip()
                        if nm and nm == nm.upper() and nm.replace("_", "").isalnum():
                            facts["env"].append(nm)
            except Exception:
                pass
            break

    # CI / deploy workflows
    for wfdir in (".gitea/workflows", ".github/workflows"):
        d = target / wfdir
        if d.is_dir():
            for f in sorted(list(d.glob("*.yml")) + list(d.glob("*.yaml"))):
                facts["workflows"].append(f"{wfdir}/{f.name}")

    # entry points: detected stack folders + common entry files
    for det in stack.get("matched", []):
        tgt = det.get("target")
        if not tgt:
            continue
        folder = (target / tgt).parent
        if folder.exists() and str(folder.relative_to(target)) != ".":
            facts["entry"].append(f"{folder.relative_to(target)}/  ({det.get('id', 'stack')})")
    for cand in ("main.py", "app.py", "manage.py", "src/main.tsx", "src/main.ts",
                 "src/index.tsx", "src/App.tsx"):
        if (target / cand).is_file():
            facts["entry"].append(cand)

    for k, vals in facts.items():
        seen: set[str] = set()
        facts[k] = [v for v in vals if not (v in seen or seen.add(v))]
    return facts


def write_project_facts(target: Path, facts: dict, dry: bool) -> list[str]:
    """Seed .claude/PROJECT-FACTS.md so the AI enrichment step starts from real data."""
    if not any(facts.values()):
        return ["project facts: nothing auto-extractable — skipped"]
    out = [
        "# Project facts — auto-extracted by setup-project-ai",
        "",
        "> Starting point for AGENTS.md enrichment (skill Step 3). Pulled mechanically from",
        "> package.json / pyproject.toml / .env.example / workflows — **verify, refine, fold the",
        "> right ones into the matching AGENTS.md (root vs backend/ vs frontend/) — the canonical rules",
        "> file, NOT the CLAUDE.md shim — then delete this file.**",
        "",
    ]

    def sec(title: str, items: list[str]) -> list[str]:
        return [f"## {title}", "", *[f"- `{i}`" for i in items], ""] if items else []

    out += sec("Commands (run / test / build)", facts["commands"])
    out += sec("Environment variables (names only — values live in your real .env)", facts["env"])
    out += sec("CI / deploy workflows", facts["workflows"])
    out += sec("Entry points / key folders", facts["entry"])
    dest = target / ".claudster" / "PROJECT-FACTS.md"
    if not dry:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(out), encoding="utf-8")
    n = sum(len(v) for v in facts.values())
    return [f"project facts: wrote .claudster/PROJECT-FACTS.md ({n} facts — fold into the hierarchy, then delete)"]


CLAUDSTER_GITIGNORE = """\
# caddis artifacts — commit plans/handoffs/agent-docs/prd; ignore transient state
reviews/*.html
usage-log.jsonl
.last-usage-review
relay.md
relay/
PROJECT-FACTS.md
memory.jsonl
"""


CLAUDSTER_CONFIG_EXAMPLE = """\
# caddis per-repo configuration — a documented template.
#
# Nothing here takes effect until you copy this file to `.claudster/config.toml` (same directory)
# and uncomment the keys you want. The caddis hooks/scripts read `config.toml` (never this
# `.example`) from the repo root's `.claudster/`. Unknown sections/keys are ignored, so a section
# that a given caddis version doesn't yet honor is harmless to leave in place.
#
# All three sections below are honored. Every key falls back to a baked-in default, so uncomment
# only the ones you want to change.

# ── [guard] — PreToolUse safety hook (hooks/guard.py) ── LIVE ──
# The guard classifies each Bash/Edit/Write into deny | ask | allow. `allow` is an escape hatch that
# may ONLY DOWNGRADE an `ask` to `allow` — it can never override a `deny` (a secret write, a
# catastrophic shell command). Each entry is a case-insensitive SUBSTRING matched against the command
# text (Bash) or the file path (Edit/Write). Keep entries specific: a broad substring like "git"
# would silence every gated git operation.
#
# KILL SWITCH — turn the guard OFF entirely (bypasses ALL tiers, deny included). For users who run
# Claude Code with `bypassPermissions` and want no second enforcement layer. Either:
#   enabled = false            # (or mode = "off") — disables the guard for THIS repo.
#   env CADDIS_GUARD_DISABLED=1   — global, applies everywhere, survives plugin auto-updates.
# The env var is the recommended global switch; add it under `"env"` in ~/.claude/settings.json.
[guard]
# enabled = false
allow = [
  # "git push --force origin scratch",   # allow force-push to one throwaway branch
  # "yarn.lock",                         # stop confirming routine lockfile edits in this repo
  # "npm publish --dry-run",             # a publish you run often and trust
]

# ── [doc_coverage] — reference-doc gate (scripts/check_doc_coverage.py) ── LIVE ──
# [doc_coverage]
# route_tree = "frontend/src/routeTree.gen.ts"   # where the generated route tree lives
# page_guide = "UI_PAGE_GUIDE.md"                # the guide that must cover every live route
# agents_md_budget = 200                         # warn when an always-loaded AGENTS.md (+ its CLAUDE.md
#                                                # shim) exceeds N lines. `claude_md_budget` is the
#                                                # accepted back-compat alias for this key.
# ignore_routes = ["/health", "/__internal"]     # routes intentionally left out of the page guide

# ── [dream_memory] — short-term fact store (scripts/dream_memory.py) ── LIVE ──
# [dream_memory]
# prune_age_days = 14    # single-hit facts older than this decay out
# max_facts = 200        # hard cap on the store
# surface_limit = 5      # how many facts SessionStart prints
"""


def scaffold_claudster(target: Path, dry: bool) -> list[str]:
    """Create the harness-owned .claudster/ artifact tree + a default .gitignore + a config example.

    Committed subdirs: plans, handoffs, agent-docs, prd, kb, prompts. Transient state
    (reviews/*.html, usage-log.jsonl, .last-usage-review, relay*, PROJECT-FACTS.md, memory.jsonl)
    is gitignored. .claudster/ is the default home for every working-artifact kind (Track A
    Phase A3) — kb/ and prompts/ round out plans/prd/agent-docs/reviews so nothing has to
    scatter to the repo root or .github/. Also drops a documented `config.toml.example`
    (guard/doc_coverage/dream_memory). Idempotent; never clobbers an existing .gitignore or
    config example.
    """
    notes: list[str] = []
    root = target / ".claudster"
    for sub in ("plans", "handoffs", "agent-docs", "reviews", "prd", "kb", "prompts"):
        d = root / sub
        if d.is_dir():
            continue
        if not dry:
            d.mkdir(parents=True, exist_ok=True)
        notes.append(f"scaffold: .claudster/{sub}/")
    gi = root / ".gitignore"
    if gi.exists():
        notes.append("scaffold: .claudster/.gitignore present — kept")
    else:
        if not dry:
            root.mkdir(parents=True, exist_ok=True)
            gi.write_text(CLAUDSTER_GITIGNORE, encoding="utf-8")
        notes.append("scaffold: wrote .claudster/.gitignore")
    cfg = root / "config.toml.example"
    if cfg.exists():
        notes.append("scaffold: .claudster/config.toml.example present — kept")
    else:
        if not dry:
            root.mkdir(parents=True, exist_ok=True)
            cfg.write_text(CLAUDSTER_CONFIG_EXAMPLE, encoding="utf-8")
        notes.append("scaffold: wrote .claudster/config.toml.example")
    return notes


def relocate_legacy(target: Path, dry: bool) -> list[str]:
    """One-way relocate of pre-.claudster harness files into .claudster/.

    Moves each source only when it exists AND the destination does not — never
    clobbers an already-migrated file (logs a skip instead). Idempotent: a second
    run finds no sources and is a no-op. Also migrates .github/plans/*.md into
    .claudster/plans/ — EXCEPT on the caddis authoring source (the caddis repo,
    detected by a claude-harness/ dir), where .github/plans is pool-synced to the
    public caddis-plugin mirror and must stay put (migration decision 5).
    """
    moves = [
        ("relay.md", ".claudster/relay.md"),
        (".claude/usage-log.jsonl", ".claudster/usage-log.jsonl"),
        (".claude/.last-usage-review", ".claudster/.last-usage-review"),
        (".claude/PROJECT-FACTS.md", ".claudster/PROJECT-FACTS.md"),
        (".claude/relay", ".claudster/relay"),
    ]
    notes: list[str] = []
    for src_rel, dst_rel in moves:
        src, dst = target / src_rel, target / dst_rel
        if not src.exists():
            continue
        if dst.exists():
            notes.append(f"migrate: skip (already at {dst_rel}) — left legacy {src_rel} in place")
            continue
        if not dry:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
        notes.append(f"migrate: {src_rel} → {dst_rel}")

    # .github/plans/*.md → .claudster/plans/ — per-file (the dir may already exist from the
    # scaffold step), clobber-safe. SKIPPED for the caddis authoring source (the caddis repo),
    # where .github/plans is pool-synced to the public caddis-plugin mirror (migration decision 5).
    # Detected by the presence of a claude-harness/ dir in the target.
    gh_plans = target / ".github" / "plans"
    if gh_plans.is_dir():
        if (target / "claude-harness").is_dir():
            notes.append("migrate: .github/plans/ kept (authoring source — pool-synced)")
        else:
            dest_dir = target / ".claudster" / "plans"
            for src in sorted(gh_plans.glob("*.md")):
                dst = dest_dir / src.name
                if dst.exists():
                    notes.append(f"migrate: skip (already at .claudster/plans/{src.name})")
                    continue
                if not dry:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                notes.append(f"migrate: .github/plans/{src.name} → .claudster/plans/{src.name}")

    if not notes:
        notes.append("migrate: no legacy files to relocate")
    return notes


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 can't encode → · ✅ ⚠
    ap = argparse.ArgumentParser(description="Deploy the Claude Code harness into a project.")
    ap.add_argument("target", type=Path)
    ap.add_argument("--name", default=None, help="Project name for CLAUDE.md identity")
    ap.add_argument("--desc", default="", help="One-line project description")
    ap.add_argument("--set", action="append", default=[], metavar="KEY=VALUE",
                    help="Placeholder substitution, e.g. --set API_PORT_DEV=8099 (repeatable)")
    ap.add_argument("--substitute", action="store_true",
                    help="Apply placeholder substitution across repo files (for fresh-from-template "
                         "projects only). OFF by default — existing projects are scanned/reported, never rewritten.")
    ap.add_argument("--force", action="store_true", help="Overwrite existing CLAUDE.md/AGENTS.md/harness files")
    ap.add_argument("--install", action="store_true", help="Create venv if missing")
    ap.add_argument("--dry-run", action="store_true", help="Report actions without writing")
    ap.add_argument("--vendor", action="store_true",
                    help="Copy plugin-owned agents+commands into .claude/ (for raw checkouts without "
                         "the caddis plugin installed; plugin installs load them globally — no copy needed)")
    args = ap.parse_args()

    target = args.target.resolve()
    if not target.is_dir():
        print(f"ERROR: target not a directory: {target}", file=sys.stderr)
        return 2
    if not HARNESS_DIR.is_dir():
        print(f"ERROR: harness templates not found at {HARNESS_DIR}", file=sys.stderr)
        return 2

    name = args.name or target.name
    mapping: dict[str, str] = {"PROJECT_NAME": name}
    if args.desc:
        mapping["PROJECT_DESCRIPTION"] = args.desc
    for kv in args.set:
        if "=" in kv:
            k, v = kv.split("=", 1)
            mapping[k.strip()] = v.strip()

    stack_map = load_stack_map()
    stack = detect_stack(target, stack_map)
    ident = {"name": name, "desc": args.desc or f"{name} — (fill in: what this project is)."}

    print(f"=== setup-project-ai → {target} {'(dry-run)' if args.dry_run else ''}")
    print(f"Stack detected: {stack_summary(stack)}  [{', '.join(d['id'] for d in stack['matched']) or 'none'}]")

    # Substitution rewrites repo files — only when explicitly requested (fresh-from-template).
    # Otherwise report-only so we never touch an existing project's docs/code.
    apply_sub = args.substitute and not args.dry_run
    sub_changed, leftovers = substitute_placeholders(target, mapping, dry=not apply_sub)
    if args.substitute:
        print(f"\n-- placeholders: substituted in {sub_changed} file(s)")
    else:
        print(f"\n-- placeholders: report-only ({sub_changed} file(s) contain provided keys; "
              f"pass --substitute to apply — intended for fresh template copies, not existing repos)")
    if leftovers:
        print(f"   ⚠ UNRESOLVED placeholders in {len(leftovers)} file(s)"
              f"{' — provide via --set' if args.substitute else ' (informational)'}:")
        seen: set[str] = set()
        for f, toks in sorted(leftovers.items()):
            for t in toks:
                seen.add(t)
            print(f"     {f}: {', '.join(toks)}")
        print(f"   tokens needing values: {', '.join(sorted(seen))}")

    # Fail-loud gate: in --substitute mode (a fresh-from-template render) any leftover
    # {{TOKEN}} means a half-rendered harness. Refuse to emit — exit 3 so the bootstrap
    # aborts rather than shipping a CLAUDE.md with literal {{TOKEN}}s a future session
    # would read as truth. Report-only runs (existing repos) are never gated.
    if args.substitute and leftovers:
        print("\nERROR: unresolved {{TOKEN}}s remain after --substitute — refusing to emit a "
              "half-rendered harness.\n       Provide the missing values via --set and re-run.",
              file=sys.stderr)
        return 3

    print("\n-- CLAUDE.md hierarchy")
    for line in compose_claude_md(target, stack, ident, args.force, args.dry_run):
        print(f"   {line}")

    print("-- migrate legacy state → .claudster")
    for line in relocate_legacy(target, args.dry_run):
        print(f"   {line}")

    print("-- project facts (auto-extracted → seed for enrichment)")
    for line in write_project_facts(target, extract_project_facts(target, stack), args.dry_run):
        print(f"   {line}")

    print("-- .claudster artifact tree")
    for line in scaffold_claudster(target, args.dry_run):
        print(f"   {line}")

    print("-- doc-coverage discipline (DOC-MAP + page guide + checker)")
    for line in emit_doc_discipline(target, ident, args.force, args.dry_run):
        print(f"   {line}")

    if args.vendor:
        print("\n-- subagents (vendored)")
        for line in deploy_dir(HARNESS_DIR / "agents", target / ".claude" / "agents", args.force, args.dry_run):
            print(f"   {line}")
        print("-- commands (vendored)")
        for line in deploy_dir(HARNESS_DIR / "commands", target / ".claude" / "commands", args.force, args.dry_run):
            print(f"   {line}")
    else:
        print("\n-- subagents/commands: skipped (provided by the caddis plugin; pass --vendor for a raw checkout)")

    print("\n-- settings")
    print(f"   {merge_settings(target, stack, args.dry_run)}")

    print("-- status line")
    for line in deploy_statusline(target, args.force, args.dry_run):
        print(f"   {line}")

    print("-- git hooks")
    for line in install_git_hooks(target, args.force, args.dry_run):
        print(f"   {line}")

    fe_notes = ensure_frontend_test_harness(target, stack, args.dry_run)
    if fe_notes:
        print("\n-- frontend test harness")
        for n in fe_notes:
            print(f"   {n}")

    venv_notes = check_venv(target, args.install, args.dry_run)
    if venv_notes:
        print("\n-- python env")
        for n in venv_notes:
            print(f"   {n}")

    print("\n✅ done. Next: review CLAUDE.md hierarchy, then enrich it with project-specific facts "
          "(the setup-project-ai skill's AI step), and run a smoke test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
