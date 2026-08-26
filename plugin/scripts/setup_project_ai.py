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
import hashlib
import json
import os
import re
from datetime import datetime, timezone
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


def _load_artifact_helpers():
    """`(ARTIFACT_DIRS, artifact_root)` from the shared reader, with an inline fallback.

    The artifact dir name lives in ONE place (claude-harness/scripts/claudster_config.py). This
    generator runs from both layouts above, so the helper is imported off whichever scripts/ dir
    carries it; the fallback re-states the same rule rather than letting a bootstrap crash.
    """
    here = Path(__file__).resolve().parent
    for cand in (here.parent / "claude-harness" / "scripts", here):
        if (cand / "claudster_config.py").is_file():
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            break
    try:
        from claudster_config import ARTIFACT_DIRS, artifact_root
        return ARTIFACT_DIRS, artifact_root
    except Exception:  # pragma: no cover — defensive
        dirs = (".caddis",)

        def _artifact_root(root):
            return Path(root) / dirs[0]

        return dirs, _artifact_root


ARTIFACT_DIRS, artifact_root = _load_artifact_helpers()


HARNESS_DIR = _resolve_harness_dir()
PLACEHOLDER_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache",
             ".ruff_cache", ".pytest_cache", "dist", "build", ".tanstack", ".codex-tmp"}
TEXT_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".toml", ".txt",
                 ".yml", ".yaml", ".cfg", ".ini", ".html", ".css", ".env", ".ps1", ".sh",
                 # .mjs was missing until 2026-08-03. A .mjs carrying a {{PLACEHOLDER}} was
                 # skipped by the scan, so the leftover-placeholder gate could not see it and
                 # the file shipped unrendered and SILENTLY. Found while porting a Playwright
                 # prod-render check (an .mjs) into the fleet template. Same class as the
                 # VersionBadge trap: a hardcoded extension/file list that a new file type
                 # falls straight through.
                 ".mjs", ".cjs"}


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
        out = existing
        verb = "merge"
    else:
        base["permissions"]["allow"] = allow
        # No statusLine here on purpose: it is user-scope now, installed once per machine
        # by `/caddis:statusline`. A per-project copy is exactly how four status-line
        # scripts came to exist and drift apart.
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
# so it runs under Git's bundled shell on Windows/Linux/macOS.
#
# TOOLS RUN IN THE PROJECT'S OWN INTERPRETER, NOT WHATEVER IS ON PATH. This was a real
# defect found by app-forge's dry run (2026-08-06): the gate resolved bare `pytest` and
# `mypy` off PATH, which on Windows is the machine-wide C:\Python interpreter — so it
# tested the app in an environment without the app's dependencies. Meanwhile `ruff` was
# not on PATH at all and was silently skipped, even though the app had ruff in its venv.
# It ran the two checks that could not work and skipped the one that would.
#
# A DECLARED-BUT-MISSING TOOL NOW BLOCKS. The old rule was "auto-skip anything not
# installed", which is degrade-open: the gate reported success precisely when it had
# checked the least. If a project asks for ruff in its pyproject and ruff cannot run,
# that is a broken environment, not a project without linting — and a check that cannot
# run must not report success. Tools the project never asked for are still skipped
# silently, because those genuinely are not part of its standards.
PRE_PUSH_HOOK = r"""#!/usr/bin/env sh
# Managed by caddis setup-project-ai. Delete this file to opt out.
set -eu
echo "[caddis] pre-push quality gate"
fail=0

# Prefer the project's virtualenv over PATH. Checked in venv-layout order for both
# Windows (Scripts/) and POSIX (bin/) so the same hook works on either.
PY=""
for cand in .venv/Scripts/python.exe .venv/bin/python venv/Scripts/python.exe venv/bin/python; do
  if [ -x "$cand" ]; then PY="$cand"; break; fi
done
if [ -z "$PY" ]; then PY=$(command -v python || command -v python3 || true); fi

# Runnable IN $PY - not merely present on PATH. This is the whole point: `command -v mypy`
# answers a question about PATH, and the question we care about is about the environment
# the app's code actually imports from.
py_has() { [ -n "$PY" ] && "$PY" -m "$1" --version >/dev/null 2>&1; }
# Does the project ASK for this tool? If so, being unable to run it is a failure.
py_wants() { grep -qi -- "$1" pyproject.toml requirements.txt requirements-dev.txt 2>/dev/null; }

# Does this project actually contain Python source? A pyproject.toml alone does not mean it
# does - a config-only or frontend repo can carry one - and mypy exits non-zero with "There
# are no .py[i] files in directory" when handed nothing. Skipping a checker that has nothing
# to check is honest; failing the push over it is not.
py_sources_exist() {
  [ -n "$(find . -name '*.py' -not -path './.venv/*' -not -path './venv/*'             -not -path './node_modules/*' -not -path './.git/*' 2>/dev/null | head -1)" ]
}

py_gate() {
  tool=$1; shift
  if py_has "$tool"; then
    echo "[gate] $tool $*"
    rc=0
    "$PY" -m "$tool" "$@" || rc=$?
    if [ "$rc" -ne 0 ]; then
  # pytest exit 5 = "no tests collected". A repo that has not written tests yet is not a
  # failing repo, and blocking it would hit exactly the fresh-scaffold case this fix exists
  # for. Every other non-zero code is a real failure.
      if [ "$tool" = "pytest" ] && [ "$rc" -eq 5 ]; then
        echo "[gate] pytest: no tests collected yet - not treated as a failure"
      else
        fail=1
      fi
    fi
  elif py_wants "$tool"; then
    echo "[gate] $tool: DECLARED by this project but not runnable in $PY - environment is broken" >&2
    echo "       fix: activate the venv, or reinstall dev deps (pip install -e '.[dev]')" >&2
    fail=1
  fi
}

if [ -f "pyproject.toml" ] || [ -f "requirements.txt" ]; then
  if [ -z "$PY" ]; then
    echo "[gate] python project, but no interpreter found (.venv or PATH) - cannot verify" >&2
    fail=1
  else
    echo "[gate] interpreter: $PY"
    py_gate ruff check .
    if py_sources_exist; then py_gate mypy .; else echo "[skip] mypy: no Python sources"; fi
    py_gate pytest -q
  fi
fi
if [ -f "package.json" ] && command -v npm >/dev/null 2>&1; then
  npm run 2>/dev/null | grep -q " lint"      && { echo "[gate] npm run lint"; npm run lint --silent || fail=1; }
  npm run 2>/dev/null | grep -q " typecheck" && { echo "[gate] npm run typecheck"; npm run typecheck --silent || fail=1; }
  npm run 2>/dev/null | grep -q " test"       && { echo "[gate] npm test"; npm test --silent || fail=1; }
fi
# Doc-coverage discipline (any stack). The checker exits non-zero ONLY on a hard invariant
# (missing route / dangling doc-map link); soft signals warn without failing. Auto-skips when the
# checker isn't present (older repos). Reuses $PY - resolved above with the project venv preferred -
# rather than re-probing PATH, so it reads the same tree the rest of the gate does.
if [ -f "scripts/check_doc_coverage.py" ]; then
  DOC_PY="$PY"
  if [ -z "$DOC_PY" ]; then DOC_PY=$(command -v python || command -v python3 || true); fi
  if [ -n "$DOC_PY" ]; then
    echo "[gate] doc coverage"
    "$DOC_PY" scripts/check_doc_coverage.py --check || fail=1
  fi
fi
if [ "$fail" -ne 0 ]; then
  echo "[caddis] push BLOCKED - fix the above, or 'git push --no-verify' to override." >&2
  exit 1
fi
echo "[caddis] gate passed - pushing."
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


def emit_doc_discipline(target: Path, ident: dict[str, str], force: bool, dry: bool) -> list[str]:
    """Scaffold the doc-coverage discipline into the target:
      • `<artifact-dir>/kb/DOC-MAP.md` — reference-doc index (always);
      • `UI_PAGE_GUIDE.md` — page→endpoints→DB stub (frontend repos only, i.e. a `frontend/` dir);
      • copy `scripts/check_doc_coverage.py` into the target.
    Idempotent: never clobbers an edited file unless --force. The scaffolded DOC-MAP carries no
    `.md` links so a fresh repo is gate-clean (no dangling-link hard failure)."""
    notes: list[str] = []
    cm = HARNESS_DIR / "claude-md"
    mapping = {"PROJECT_NAME": ident["name"], "PROJECT_DESCRIPTION": ident["desc"],
               "ARTIFACT_DIR": artifact_root(target).name}

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
    dm_dest = artifact_root(target) / "kb" / "DOC-MAP.md"
    dm_rel = dm_dest.relative_to(target).as_posix()
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
    # claudster_config.py must ride along or the checker's [doc_coverage]
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
    """Seed <artifact-dir>/PROJECT-FACTS.md so the AI enrichment step starts from real data."""
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
    dest = artifact_root(target) / "PROJECT-FACTS.md"
    if not dry:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text("\n".join(out), encoding="utf-8")
    n = sum(len(v) for v in facts.values())
    rel = dest.relative_to(target).as_posix()
    return [f"project facts: wrote {rel} ({n} facts — fold into the hierarchy, then delete)"]


# Scaffolded into <artifact-dir>/comms/. The convention is deliberately thin - one file per
# message, one row here - because the failure it prevents is not complexity, it is evaporation.
COMMS_REGISTER_TEMPLATE = """# Comms register

Outbound messages live in this directory - anything that must be **sent to a human outside this
repo**: an access request, a decision from another team, a change only someone else can make.

**A message not in this table does not exist.** The directory stops a draft from evaporating; this
table stops a sent message from going unchased. Comms are almost always sent to get an *action*, and
an unanswered ask looks exactly like a forgotten one unless something is tracking it.

| Raised | Audience | Subject | Status | Blocks | File |
|---|---|---|---|---|---|
| _(none yet)_ | | | | | |

## Status vocabulary

| Status | Means |
|---|---|
| `DRAFT` | Written, not sent. Needs a human to send it. |
| `SENT` | Sent - record the date and channel. |
| `ANSWERED` | A reply arrived. Record the outcome, including a "no". |
| `ACTIONED` | The thing we asked for actually happened. |
| `DROPPED` | Deliberately abandoned - **record why**, or the next session re-raises it. |

`ANSWERED` and `ACTIONED` are separate on purpose: "they replied" and "they did it" are different
states, and treating them as one is how work stalls while looking resolved.

## Writing one

- Name it `YYYY-MM-DD-<audience>-<subject>.md`, and add its row here in the SAME commit.
- **Write it send-ready.** The recipient has not read the plan. No internal paths, no repo slugs, no
  phase numbers. If it cannot be pasted into an email unedited, it is not finished.
- **State the ask in one sentence, near the top.** Everything else is supporting evidence.
- **Give them a cheap way to say yes** - an alternative that costs them less than the primary ask
  converts far better than take-it-or-leave-it.
- `blocks:` is the field that earns its keep: what stalls if this is never answered?
- **Never put secrets here.** Comms are the artifact most likely to be copied outward.
"""


# Scaffolded into <artifact-dir>/parking-lot/. Same reasoning as the comms register: a directory
# alone fixes "never written down", and it takes a stated contract to fix "written down in six
# different shapes so nothing can count them".
PARKING_LOT_README_TEMPLATE = """# Parking lot - the ONE register of future work

Anything that must happen later lives here. A defect you are not fixing now, a proposal, a parked
plan, an idea worth keeping. **One item, one file.**

**If it is not in this directory, it is not on the backlog.** That is the whole rule. Every other
place work used to hide - a note inside a plan, a "things owed" section in `relay.md`, a KB note, a
second register file - now POINTS here instead of holding the item itself.

## Why one place

Future work spread across many files looks organised and is not. Nobody can answer "what is left to
do?" without reading all of them, so nobody asks, and items are re-raised or quietly dropped. One
directory makes the answer a directory listing.

## Frontmatter (this is checked, not suggested)

```yaml
---
type: parking-lot        # always this, whatever the item started life as
status: open             # open | doing | done | dropped
future: yes              # OPTIONAL. yes = decided and owed. Absent or `no` = a candidate.
severity: high           # OPTIONAL. high | medium | low
found: 2026-08-14        # OPTIONAL. When it was raised.
found-by: <repo/session> # OPTIONAL. Who or what raised it.
---
```

`status` and `future` are **two independent questions**. `status` asks where the item is in its
life. `future` asks whether we have committed to it. An item can be `status: open` and
`future: yes` - agreed, not started. Do not fold them together.

## Status vocabulary

| Status | Means |
|---|---|
| `open` | Raised, not started. |
| `doing` | Someone is on it now. |
| `done` | Finished. `caddis_tidy.py --apply` moves it to `done/`. |
| `dropped` | Deliberately abandoned. **Write why in the body**, or the next session re-raises it. |

The list is closed on purpose. `wip`, `todo` and `pending` are not accepted, because "how many open
items?" has no answer when one state has three spellings.

## Writing one

- Name it `<short-slug>.md`. No number prefix: two sessions filing at once would pick the same number.
- Say what you saw, then what it costs, then the suggested fix. Evidence first.
- Give it a `severity` an outsider could check, not one that reflects how annoyed you were.
- **Do not start a second register.** A file here over 20 KB fails the check. If an item grew that
  big it is several items.

## What does NOT belong here

| Not this | Where it goes | Why |
|---|---|---|
| Work in flight right now | `.caddis/plans/<feature>.md` | A plan is being executed. A parking-lot item is not. |
| A task interrupted mid-session | `/caddis:digress` stack | That is a pause, not a backlog item. `/caddis:resume` pops it. |
| An ask only an outsider can resolve | `.caddis/comms/register.md` | Blocked on a human, not on us. |
| Board cards | `.caddis/backlog/` | **docket writes that directory.** It is a projection of the board, not a hand-written register. Never edit it by hand. |

## Commands

- `/caddis:park` - file an item correctly, or list what is open.
- `python scripts/caddis_tidy.py --check` - fails (exit 1) on any item that breaks the contract.
- `python scripts/caddis_tidy.py --apply` - sweeps `done` and `dropped` items into `done/`.
"""


# Scaffolded into <artifact-dir>/kb/environment-map.md. An empty file with the right headings gets
# filled in; a blank page does not, and neither does a rule with nowhere to write.
ENVIRONMENT_MAP_TEMPLATE = """---
type: reference
title: Environment map - hosts, logins, repos, and what is really where
description: Durable facts about the environment this project runs in. Read on demand; not loaded every turn.
tags: [environment, hosts, access, topology]
---

# Environment map

**Facts about the world outside this repository.** Hostnames, which login actually works, where
another team's repository lives, what a folder really contains, which port a service listens on.

## The rule

**If you learn an environment fact, write it here in the same turn.** A fact that exists only in a
conversation is lost the moment that session ends, and the next session cannot know it was ever
said.

Three real examples of the cost:

| Fact | Told in chat | What it cost |
|---|---|---|
| A reporting tool refused Windows auth; a named SQL login was required | yes | ~10 minutes, **three separate times** |
| A queue table's true row count | measured, written to one file and not another | An incoming session found the contradiction and had to resolve it |
| An app lived in the local Gitea, not on disk | yes | A session searched the filesystem for it; the user had to stop it |

The third is the clearest. Documents cited a file in that repository **by path**, so somebody had
read it - and nothing anywhere recorded **where the repository was**.

## Why here and not in AGENTS.md

`AGENTS.md` and `CLAUDE.md` load on **every** turn, so a connection string there costs context in
every session forever. `AGENTS.md` is also for durable **rules**, and a hostname is not a rule. The
KB is read on demand, indexed in `DOC-MAP.md`, and gate-checked. This is the right shelf.

**Never put a secret here.** Record *where* a credential lives and *which* account works, never the
value. Keys belong in a keys file outside every git repository.

## Hosts and services

| Host | What runs there | How to reach it | Notes |
|---|---|---|---|
| _(none recorded yet)_ | | | |

## Databases

| Database | Server | Which login works | Gotchas |
|---|---|---|---|
| _(none recorded yet)_ | | | |

Record the login that **works**, and the one that looks right and does not. The second saves more
time than the first.

## Repositories that are not this one

| Repository | Where it actually lives | Why we care |
|---|---|---|
| _(none recorded yet)_ | | |

"Where it actually lives" means the clone URL or the host - not a guess that it is on disk.

## Data outside the repository

| What | Where | Refreshed how |
|---|---|---|
| _(none recorded yet)_ | | |

## Accounts and access

| What | Account or role | Requested from | Notes |
|---|---|---|---|
| _(none recorded yet)_ | | | |

## Things that look like facts and are not

Readings that mislead: a virtualisation flag that reads false because a hypervisor is already
running, a file whose encoding mangles under an older shell, a command whose exit code means
"nothing to do" rather than "failed". Record each one you hit, with what it actually means.

| Reading | Looks like | Actually means |
|---|---|---|
| _(none recorded yet)_ | | |
"""


ARTIFACT_GITIGNORE = """\
# caddis artifacts — commit plans/handoffs/agent-docs/prd; ignore transient state
reviews/*.html
usage-log.jsonl
agent-log.jsonl
.last-usage-review
relay.md
relay/
PROJECT-FACTS.md
memory.jsonl
"""


ARTIFACT_CONFIG_EXAMPLE = """\
# caddis per-repo configuration — a documented template.
#
# Nothing here takes effect until you copy this file to `config.toml` (same directory) and
# uncomment the keys you want. The caddis hooks/scripts read `config.toml` (never this `.example`)
# from the repo root's `.caddis/`. Unknown sections/keys are ignored, so a section that a given
# caddis version doesn't yet honor is harmless to leave in place.
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

# ── [handover] — what /caddis:handoff measures (scripts/caddis_inventory.py) ── LIVE ──
# [handover]
# test_cmd = "pytest tests/ -q"   # THIS REPO'S test command. Without it the inventory
#                                 # guesses `pytest` at the root, which is right in a
#                                 # single-package repo and wrong in any repo carrying a
#                                 # vendored or generated tree. Generated trees
#                                 # (vscode-extensions/, dist/, node_modules/, .venv/) are
#                                 # excluded automatically; set this when that is not enough.
"""


def stamp_caddis_version(target: Path, dry: bool) -> list[str]:
    """Record WHICH caddis scaffolded this project, in `.caddis/.caddis-version`.

    Without this, "is this app's harness stale?" cannot be answered without diffing every
    generated file against a current caddis - so in practice nobody asks, and apps drift silently
    for months. One line makes the question cheap, and makes a fleet-wide staleness sweep a loop
    rather than an investigation.

    Deliberately NOT gitignored: the whole point is that a reviewer, or a future session, can see
    what built this and when. Rewritten on every run, so re-running the harness updates the stamp.
    """
    notes: list[str] = []
    version = "unknown"
    # The harness may be running from an installed plugin (.../cache/caddis/caddis/1.3.68/scripts)
    # or from a source checkout. Read the version from the plugin path when that is where we are;
    # a checkout has no released version number, and saying "source-checkout" is more honest than
    # inventing one.
    here = Path(__file__).resolve()
    parts = [p.name for p in here.parents]
    if "caddis" in parts:
        for parent in here.parents:
            if re.fullmatch(r"\d+\.\d+\.\d+", parent.name):
                version = parent.name
                break
    if version == "unknown" and "plugins" not in parts:
        version = "source-checkout"

    dest = artifact_root(target) / ".caddis-version"
    stamped = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    body = "\n".join([
        "# Which caddis scaffolded this project. Rewritten whenever the harness is re-run.",
        "# Answers \"is this app's harness stale?\" without diffing every generated file.",
        f"caddis_version={version}",
        f"scaffolded_at={stamped}",
        f"harness_path={here.parent}",
        "",
    ])
    if not dry:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(body, encoding="utf-8")
    notes.append(f"caddis stamp: {version} -> {dest.relative_to(target)}")
    return notes


# ── the `Plain` output style ────────────────────────────────────────────────────────────────
# caddis SUPPLIES this style and never selects it. Claude Code offers `force-for-plugin: true`,
# which would apply it automatically and override the user's own `outputStyle`; that was considered
# and rejected. A plugin that silently repoints a global preference is the behaviour people file
# bugs about, and it would make `Explanatory` unreachable for as long as caddis is enabled.
# So: write the file where the picker looks, and let the human choose it in `/config`.
OUTPUT_STYLE_SRC_REL = ("claude-md", "output-style-plain.md")
OUTPUT_STYLE_DEST_NAME = "Plain.md"
OUTPUT_STYLE_STAMP_NAME = ".caddis-plain.sha256"


def _style_hash(text: str) -> str:
    """Hash on LF-normalised text. Git checkouts flip line endings on Windows, and without this
    a pure CRLF/LF difference reads as "the user edited it" and freezes updates forever."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def provision_output_style(dry: bool, home: Path | None = None) -> list[str]:
    """Put `Plain.md` in the user's global output-styles dir. Never selects it, never edits settings.

    Update rule: write when absent; refresh when the file on disk still matches the copy caddis last
    shipped; otherwise leave it alone. The stamp file is what separates "unmodified, safe to update"
    from "the user tuned this" — without it the only safe policy is never to update, and a shipped
    wording fix would never reach anyone who installed once.
    """
    if os.environ.get("CADDIS_NO_OUTPUT_STYLE"):
        return ["output style: skipped (CADDIS_NO_OUTPUT_STYLE set)"]
    src = HARNESS_DIR.joinpath(*OUTPUT_STYLE_SRC_REL)
    if not src.is_file():
        return [f"output style: skipped (no source at {src})"]
    try:
        new_text = src.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"output style: skipped ({type(exc).__name__})"]

    # CADDIS_HOME exists so a test (or a sandboxed run) can point this at a temp dir. Without it,
    # merely importing and calling this function writes into the real user's home — which is exactly
    # the kind of side effect a test suite must never have.
    root = home or Path(os.environ.get("CADDIS_HOME") or Path.home())
    dest_dir = root / ".claude" / "output-styles"
    dest = dest_dir / OUTPUT_STYLE_DEST_NAME
    stamp = dest_dir / OUTPUT_STYLE_STAMP_NAME
    new_hash = _style_hash(new_text)

    if dest.is_file():
        cur_hash = _style_hash(dest.read_text(encoding="utf-8", errors="ignore"))
        if cur_hash == new_hash:
            return [f"output style: {dest} already current"]
        prev = ""
        if stamp.is_file():
            prev = stamp.read_text(encoding="utf-8", errors="ignore").strip()
        if prev and prev != cur_hash:
            return [f"output style: {dest} kept — locally edited, not overwritten"]
        action = "updated"
    else:
        action = "wrote"

    if not dry:
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest.write_text(new_text, encoding="utf-8")
        stamp.write_text(new_hash + "\n", encoding="utf-8")
    return [f"output style: {action} {dest} (select it in /config — caddis never sets it for you)"]


# ── user-level settings.json ────────────────────────────────────────────────────────────────
TODO_TOOLS_ENV_KEY = "CLAUDE_CODE_ENABLE_TODO_TOOLS"


def _user_settings_path(home: Path | None = None) -> Path:
    root = home or Path(os.environ.get("CADDIS_HOME") or Path.home())
    return root / ".claude" / "settings.json"


def ensure_user_env(dry: bool, home: Path | None = None) -> list[str]:
    """Add `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` to the user's global settings, additively.

    WHY THIS ONE IS SAFE TO SET WHEN `outputStyle` WAS NOT. Adding a key to `env` does not override
    a preference the user expressed — it turns on a capability that is otherwise absent. An existing
    value is ALWAYS left alone, including an explicit "0", so a deliberate opt-out survives every
    reinstall.

    NEVER REWRITE A FILE THAT DOES NOT PARSE. Found live on 2026-08-16: a hand-added line in this
    exact file was missing its comma, so the JSON was invalid and Claude Code silently ignored
    EVERY setting in it — guard mode, permissions, hooks, statusline, plugins. A "helpful" rewrite
    of an unparseable file would have discarded all of it. So this reports the breakage and stops,
    which also converts a silent total failure into a visible one. That report is most of the value
    here; the key it adds is the smaller half.
    """
    if os.environ.get("CADDIS_NO_SETTINGS_ENV"):
        return ["user env: skipped (CADDIS_NO_SETTINGS_ENV set)"]
    path = _user_settings_path(home)

    if path.is_file():
        raw = path.read_text(encoding="utf-8", errors="ignore")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return [f"user env: {path} is NOT VALID JSON ({exc.msg}, line {exc.lineno}) — "
                    "every setting in it is being ignored. Left untouched; fix it by hand."]
        if not isinstance(data, dict):
            return [f"user env: {path} is not a JSON object — left untouched"]
    else:
        raw, data = "", {}

    env_block = data.get("env")
    if env_block is None:
        env_block = {}
    elif not isinstance(env_block, dict):
        return [f"user env: {path} has a non-object `env` — left untouched"]

    if TODO_TOOLS_ENV_KEY in env_block:
        return [f"user env: {TODO_TOOLS_ENV_KEY} already set to "
                f"{env_block[TODO_TOOLS_ENV_KEY]!r} — left alone"]

    env_block[TODO_TOOLS_ENV_KEY] = "1"
    data["env"] = env_block
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Back up before touching a global config, and write via a temp file so an interrupted
        # write cannot leave the user with a half-written settings.json — the failure mode this
        # whole function exists to notice.
        if raw:
            path.with_suffix(".json.caddis-bak").write_text(raw, encoding="utf-8")
        tmp = path.with_suffix(".json.caddis-tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    verb = "would add" if dry else "added"
    return [f"user env: {verb} {TODO_TOOLS_ENV_KEY}=1 to {path}"
            + ("" if not raw else " (previous version saved as settings.json.caddis-bak)")]


def scaffold_artifact_dir(target: Path, dry: bool) -> list[str]:
    """Create the harness-owned .caddis/ artifact tree + a default .gitignore + a config example.

    Committed subdirs: plans, handoffs, agent-docs, prd, kb, prompts, comms. Transient state
    (reviews/*.html, usage-log.jsonl, .last-usage-review, relay*, PROJECT-FACTS.md, memory.jsonl)
    is gitignored. .caddis/ is the default home for every working-artifact kind (Track A
    Phase A3) — kb/ and prompts/ round out plans/prd/agent-docs/reviews so nothing has to
    scatter to the repo root or .github/. Also drops a documented `config.toml.example`
    (guard/doc_coverage). Idempotent; never clobbers an existing .gitignore or
    config example.

    Writes into the repo's `.caddis/`.
    """
    notes: list[str] = []
    root = artifact_root(target)
    label = root.name
    # `comms` holds outbound messages — anything only a human OUTSIDE this repo can resolve
    # (an access request, a firmware change, a decision from another team). Without a home,
    # those get written into a chat reply and evaporate when the session ends.
    # `parking-lot` holds future work — the ONE register. It was a convention with no home until
    # 2026-08-14: it appeared nowhere in the scaffold, nowhere in the AGENTS.md "Where things live"
    # table, and nowhere in the tidy lifecycle. So future work scattered to nine places at once and
    # no session could answer "what is left to do?". A directory the harness creates on every
    # project is what makes "one place" true rather than aspirational.
    for sub in ("plans", "handoffs", "agent-docs", "reviews", "prd", "kb", "prompts", "comms",
                "parking-lot"):
        d = root / sub
        if d.is_dir():
            continue
        if not dry:
            d.mkdir(parents=True, exist_ok=True)
        notes.append(f"scaffold: {label}/{sub}/")

    # The comms REGISTER is the half that earns its keep, so it is scaffolded rather than left
    # to convention. A directory only fixes "drafted but never sent"; the register fixes "sent
    # but never chased" — and comms are almost always sent to GET AN ACTION, so an unanswered
    # ask is indistinguishable from a forgotten one unless something tracks it.
    reg = root / "comms" / "register.md"
    if reg.exists():
        notes.append(f"scaffold: {label}/comms/register.md present — kept")
    else:
        if not dry:
            reg.parent.mkdir(parents=True, exist_ok=True)
            reg.write_text(COMMS_REGISTER_TEMPLATE, encoding="utf-8")
        notes.append(f"scaffold: wrote {label}/comms/register.md")
    # The parking-lot README is the CONTRACT, not decoration. Without it the directory is just a
    # folder, and a folder does not tell the next agent that `type: parking-lot` is mandatory or
    # that a second register is forbidden. Same reasoning as comms/register.md above.
    pl = root / "parking-lot" / "README.md"
    if pl.exists():
        notes.append(f"scaffold: {label}/parking-lot/README.md present — kept")
    else:
        if not dry:
            pl.parent.mkdir(parents=True, exist_ok=True)
            pl.write_text(PARKING_LOT_README_TEMPLATE, encoding="utf-8")
        notes.append(f"scaffold: wrote {label}/parking-lot/README.md")
    # The environment map. Same reasoning as the two registers above: the failure is not complexity,
    # it is EVAPORATION. Environment facts used to land wherever the agent happened to be typing —
    # relay.md (rewritten at every handover), mid-plan (nobody looks), a KB note (only when framed
    # as a trap), or most often a chat reply that ends with the session. One project lost time to
    # the same three facts repeatedly. A file with headings gets filled in; a blank page does not.
    em = root / "kb" / "environment-map.md"
    if em.exists():
        notes.append(f"scaffold: {label}/kb/environment-map.md present — kept")
    else:
        if not dry:
            em.parent.mkdir(parents=True, exist_ok=True)
            em.write_text(ENVIRONMENT_MAP_TEMPLATE, encoding="utf-8")
        notes.append(f"scaffold: wrote {label}/kb/environment-map.md")
    gi = root / ".gitignore"
    if gi.exists():
        notes.append(f"scaffold: {label}/.gitignore present — kept")
    else:
        if not dry:
            root.mkdir(parents=True, exist_ok=True)
            gi.write_text(ARTIFACT_GITIGNORE, encoding="utf-8")
        notes.append(f"scaffold: wrote {label}/.gitignore")
    cfg = root / "config.toml.example"
    if cfg.exists():
        notes.append(f"scaffold: {label}/config.toml.example present — kept")
    else:
        if not dry:
            root.mkdir(parents=True, exist_ok=True)
            cfg.write_text(ARTIFACT_CONFIG_EXAMPLE, encoding="utf-8")
        notes.append(f"scaffold: wrote {label}/config.toml.example")
    return notes


def relocate_legacy(target: Path, dry: bool) -> list[str]:
    """One-way relocate of pre-artifact-dir harness files into the repo's artifact dir.

    Moves each source only when it exists AND the destination does not — never
    clobbers an already-migrated file (logs a skip instead). Idempotent: a second
    run finds no sources and is a no-op. Also migrates .github/plans/*.md into
    <artifact-dir>/plans/ — EXCEPT on the caddis authoring source (the caddis repo,
    detected by a claude-harness/ dir), where .github/plans is pool-synced to the
    public caddis-plugin mirror and must stay put (migration decision 5).

    The destination is always `.caddis/` — this relocation is about the OLD `.claude/`+root
    layout, not about renaming a repo's artifact dir (that is `/caddis:migrate-dir`, opt-in).
    """
    art = artifact_root(target).name
    moves = [
        ("relay.md", f"{art}/relay.md"),
        (".claude/usage-log.jsonl", f"{art}/usage-log.jsonl"),
        (".claude/.last-usage-review", f"{art}/.last-usage-review"),
        (".claude/PROJECT-FACTS.md", f"{art}/PROJECT-FACTS.md"),
        (".claude/relay", f"{art}/relay"),
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

    # .github/plans/*.md → <artifact-dir>/plans/ — per-file (the dir may already exist from the
    # scaffold step), clobber-safe. SKIPPED for the caddis authoring source (the caddis repo),
    # where .github/plans is pool-synced to the public caddis-plugin mirror (migration decision 5).
    # Detected by the presence of a claude-harness/ dir in the target.
    gh_plans = target / ".github" / "plans"
    if gh_plans.is_dir():
        if (target / "claude-harness").is_dir():
            notes.append("migrate: .github/plans/ kept (authoring source — pool-synced)")
        else:
            dest_dir = target / art / "plans"
            for src in sorted(gh_plans.glob("*.md")):
                dst = dest_dir / src.name
                if dst.exists():
                    notes.append(f"migrate: skip (already at {art}/plans/{src.name})")
                    continue
                if not dry:
                    dest_dir.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(src), str(dst))
                notes.append(f"migrate: .github/plans/{src.name} → {art}/plans/{src.name}")

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
    ap.add_argument("--hooks-only", action="store_true",
                    help="Install ONLY the pre-push gate and exit. For callers that create the git "
                         "repo after deploying the harness - the generator runs this script at stage "
                         "10 and `git init` at stage 11, so the gate could never install and no "
                         "bootstrapped app has ever had one.")
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

    if args.hooks_only:
        # Idempotent and clobber-safe: never replaces a hook it did not write unless --force.
        # Exists because the gate cannot install before the repo does. Safe to call on an
        # already-set-up project, which is what makes it usable as a retrofit for existing apps.
        for note in install_git_hooks(target, args.force, args.dry_run):
            print(f"  {note}")
        return 0

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

    print(f"-- migrate legacy state → {artifact_root(target).name}")
    for line in relocate_legacy(target, args.dry_run):
        print(f"   {line}")

    print("-- project facts (auto-extracted → seed for enrichment)")
    for line in write_project_facts(target, extract_project_facts(target, stack), args.dry_run):
        print(f"   {line}")

    print(f"-- {artifact_root(target).name} artifact tree")
    for line in scaffold_artifact_dir(target, args.dry_run):
        print(f"   {line}")
    for line in stamp_caddis_version(target, args.dry_run):
        print(f"   {line}")

    print("-- output style (supplied, never selected for you)")
    for line in provision_output_style(args.dry_run):
        print(f"   {line}")

    print("-- user settings (additive only, never overwrites a value you set)")
    for line in ensure_user_env(args.dry_run):
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
    print("   user-scope now — run /caddis:statusline once per machine (not per project)")

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
