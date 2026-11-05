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
        ex_deny = existing["permissions"].setdefault("deny", [])
        for rule in base["permissions"]["deny"]:
            if rule not in ex_deny:
                ex_deny.append(rule)
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
        # by `/caddis:install-statusline`. A per-project copy is exactly how four status-line
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
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=False,
                       creationflags=0x08000000 if os.name == "nt" else 0)
        notes.append("venv: created .venv (install dev deps: .venv/Scripts/pip install -e .[dev])")
    else:
        notes.append("venv: MISSING — create with `python -m venv .venv` then "
                     "`pip install -e .[dev]` (or re-run with --install)")
    return notes


GATE_STEP_PY = r'''#!/usr/bin/env python3
"""caddis_gate_step.py — Per-step gate runner with timeout and process tree cleanup.

Runs under the PROJECT's interpreter, which may be older than 3.11: no `tomllib` at import time
(the config file is skipped, with one stderr line, when it is missing) and annotations are not evaluated.
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

try:
    import tomllib
except ImportError:  # Python < 3.11
    tomllib = None


def format_elapsed(seconds: float) -> str:
    total_s = max(0, int(round(seconds)))
    if total_s < 60:
        return f"{total_s}s"
    m = total_s // 60
    s = total_s % 60
    return f"{m}m{s:02d}s"


def with_faulthandler(argv: list[str], name: str, env: dict[str, str] | None = None) -> list[str]:
    argv = list(argv)
    if name != "pytest":
        return argv
    if any("faulthandler_timeout" in str(arg) for arg in argv):
        return argv
    env_opts = (env.get("PYTEST_ADDOPTS") if env is not None else os.environ.get("PYTEST_ADDOPTS")) or ""
    if "faulthandler_timeout" in env_opts:
        return argv
    return argv + ["-o", "faulthandler_timeout=300"]


def kill_process_tree(proc: subprocess.Popen) -> None:
    if sys.platform == "win32":
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                capture_output=True,
                timeout=10,
            )
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
    else:
        try:
            pgid = os.getpgid(proc.pid)
        except Exception:
            pgid = proc.pid
        try:
            os.killpg(pgid, signal.SIGTERM)
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except Exception:
                pass
            try:
                proc.wait(timeout=5)
            except Exception:
                pass
        except Exception:
            pass


def main(argv: list[str] | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if "--" in argv:
        sep_idx = argv.index("--")
        runner_args = argv[:sep_idx]
        cmd = argv[sep_idx + 1:]
    else:
        runner_args = argv
        cmd = []

    parser = argparse.ArgumentParser(description="caddis quality gate step runner")
    parser.add_argument("--name", required=True, help="Step name")
    parser.add_argument("--timeout", type=int, required=True, help="Default timeout in seconds")
    parser.add_argument("cmd", nargs="*", help="Command to run (if -- not used)")

    args = parser.parse_args(runner_args)
    if not cmd:
        cmd = args.cmd
        if cmd and cmd[0] == "--":
            cmd = cmd[1:]

    if not cmd:
        print("[gate] error: no command specified to run", file=sys.stderr)
        return 1

    name = args.name
    timeout = args.timeout

    # Config: read .caddis/config.toml in the current directory if present
    cfg_path = Path(".caddis/config.toml")
    gate_cfg: dict = {}
    if cfg_path.is_file() and tomllib is None:
        print("[gate] note: .caddis/config.toml not read (needs Python 3.11 or later)", file=sys.stderr)
    elif cfg_path.is_file():
        try:
            with open(cfg_path, "rb") as f:
                raw_cfg = tomllib.load(f)
            if isinstance(raw_cfg, dict):
                g = raw_cfg.get("gate", {})
                if isinstance(g, dict):
                    gate_cfg = g
        except Exception as exc:
            print(f"[gate] warning: malformed .caddis/config.toml ({exc})", file=sys.stderr)

    # Section [gate]: timeout_<name> overrides --timeout for that step name
    candidate_keys = (
        f"timeout_{name}",
        f"timeout_{name.replace('-', '_')}",
        f"timeout_{name.replace('_', '-')}",
    )
    for k in candidate_keys:
        if k in gate_cfg:
            val = gate_cfg[k]
            if isinstance(val, int) and not isinstance(val, bool) and val > 0:
                timeout = val
            else:
                print(
                    f"[gate] warning: invalid {k}={val!r} in config (must be positive integer)",
                    file=sys.stderr,
                )
            break

    # Env var CADDIS_GATE_TIMEOUT_<NAME upper, - replaced by _> overrides config
    env_var_name = f"CADDIS_GATE_TIMEOUT_{name.upper().replace('-', '_')}"
    if env_var_name in os.environ:
        raw_val = os.environ[env_var_name].strip()
        try:
            env_timeout = int(raw_val)
            if env_timeout > 0:
                timeout = env_timeout
            else:
                print(
                    f"[gate] warning: invalid {env_var_name}={raw_val!r} (must be positive integer)",
                    file=sys.stderr,
                )
        except ValueError:
            print(
                f"[gate] warning: invalid {env_var_name}={raw_val!r} (must be integer)",
                file=sys.stderr,
            )

    # pytest_args (list of strings) are appended to pytest command ONLY when --name is pytest
    if name == "pytest":
        pytest_args = gate_cfg.get("pytest_args")
        if isinstance(pytest_args, list):
            for pa in pytest_args:
                if isinstance(pa, str):
                    cmd.append(pa)
                else:
                    cmd.append(str(pa))

    # Pytest hang dump
    cmd = with_faulthandler(cmd, name, os.environ)

    # Print start line
    print(f"[gate] {name}: start (limit {timeout}s)", flush=True)

    start_time = time.monotonic()
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True

    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except Exception as exc:
        print(f"[gate] {name}: failed to start {cmd[0]}: {exc}", file=sys.stderr)
        return 1

    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        kill_process_tree(proc)
        print(
            f"[gate] {name}: TIMEOUT after {timeout}s - killed the process tree",
            file=sys.stderr,
            flush=True,
        )
        return 124

    elapsed = time.monotonic() - start_time
    rc = proc.returncode
    print(f"[gate] {name}: done in {format_elapsed(elapsed)} (exit {rc})", flush=True)
    return rc


if __name__ == "__main__":
    sys.exit(main())
'''


# Pre-push gate v3 runner, installed as .git/hooks/caddis_prepush.py. The sh hook only finds an interpreter and execs it.
# It runs the [pre_push] checks of .caddis/config.toml (the fast checks the repo's CI runs) inside one time budget, by
# the runtime rules of .caddis/plans/prepush-gate-matches-ci.md. It reuses kill_process_tree and format_elapsed from
# caddis_gate_step.py and ci_caller_sha256 from caddis_prepush_config.py, both in the same hooks folder.
PRE_PUSH_RUNNER_PY = r'''#!/usr/bin/env python3
"""caddis_prepush.py - the caddis pre-push gate (version 3).

Runs the [pre_push] checks of .caddis/config.toml within budget_s seconds. It blocks a push ONLY when a check that ran
fails, or when a check that should run cannot start. Every skip prints one line that names the check.
'git push --no-verify' skips the gate once. Delete .git/hooks/pre-push to remove it.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

try:  # one kill logic for the gate: the step runner installed in the same hooks folder
    from caddis_gate_step import format_elapsed, kill_process_tree
except ImportError:  # main() blocks with a re-install line
    format_elapsed = kill_process_tree = None

try:
    import tomllib
except ImportError:  # Python < 3.11: main() prints one line and passes
    tomllib = None

NO_VERIFY = "'git push --no-verify' overrides"
CONFIG_REL = ".caddis/config.toml"


@dataclass
class Check:
    name: str
    cwd: str
    argv: list
    paths: list | None
    measured_s: float | None
    enabled: bool
    ci_step: str
    venv: str | None


def _num(value: float) -> str:
    return f"{value:g}"


def scripts_dir_hint() -> str | None:
    """The caddis scripts folder named on the HOOK_SCRIPTS_DIR line of the pre-push hook next to this file, if any."""
    hook = HERE / "pre-push"
    try:
        text = hook.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith('HOOK_SCRIPTS_DIR="'):
            value = line[len('HOOK_SCRIPTS_DIR="'):].rstrip().rstrip('"')
            if value and not value.startswith("__"):
                return value
    return None


def no_section_line(scripts_dir: str | None) -> str:
    where = scripts_dir or "<caddis scripts>"
    return ("[gate] no [pre_push] section in .caddis/config.toml - nothing checked here, CI is the first gate. "
            f'Create it: python "{where}/setup_project_ai.py" . --gate-config')


def load_checks(root: Path, config: Path | None = None):
    """(header, checks) from the [pre_push] section, or None when the file or the section is missing.

    Raises ValueError for a file that does not parse or a check without a name or argv: the caller blocks, because a
    gate that cannot read its checks checks nothing."""
    path = config if config is not None else root / CONFIG_REL
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"{path} cannot be read: {exc}") from exc
    section = data.get("pre_push")
    if not isinstance(section, dict):
        return None
    header = {k: v for k, v in section.items() if k != "check"}
    raw = section.get("check", [])
    if not isinstance(raw, list):
        raise ValueError(f"{path}: [pre_push] check must be an array of tables ([[pre_push.check]])")
    checks = []
    for i, item in enumerate(raw):
        name = item.get("name") if isinstance(item, dict) else None
        argv = item.get("argv") if isinstance(item, dict) else None
        if not isinstance(name, str) or not name or not isinstance(argv, list) or not argv \
                or not all(isinstance(a, str) for a in argv):
            raise ValueError(f"{path}: [[pre_push.check]] number {i + 1} needs a name and a non-empty argv list")
        paths = item.get("paths")
        if paths is not None and not (isinstance(paths, list) and all(isinstance(p, str) for p in paths)):
            raise ValueError(f"{path}: check {name}: paths must be a list of strings")
        measured = item.get("measured_s")
        if measured is not None and (isinstance(measured, bool) or not isinstance(measured, (int, float))):
            raise ValueError(f"{path}: check {name}: measured_s must be a number")
        enabled = item.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ValueError(f"{path}: check {name}: enabled must be true or false")
        venv = item.get("venv")
        checks.append(Check(name=name, cwd=str(item.get("cwd", ".")), argv=list(argv),
                            paths=[p[2:] if p.startswith("./") else p for p in paths] if paths else None,
                            measured_s=float(measured) if measured is not None else None,
                            enabled=enabled, ci_step=str(item.get("ci_step", "")),
                            venv=str(venv) if venv else None))
    return header, checks


def decide(checks: list, changed: set | None, budget_s: float) -> list:
    """[(check, None)] to run it, or [(check, skip line)] by rules 1-4. `changed` None = unknown: paths skip nothing."""
    out = []
    for c in checks:
        line = None
        if not c.enabled:
            line = f"[skip] {c.name}: disabled in .caddis/config.toml"
        elif c.measured_s is None:
            line = f"[skip] {c.name}: not measured on this box yet - CI runs it"
        elif c.measured_s > budget_s:
            line = f"[skip] {c.name}: measured {_num(c.measured_s)}s, over the {_num(budget_s)}s budget - CI runs it"
        elif c.paths and changed is not None and not any(f.startswith(p) for f in changed for p in c.paths):
            line = f"[skip] {c.name}: no pushed change under {', '.join(c.paths)}"
        out.append((c, line))
    return out


def ci_caller_sha256(text: str) -> str:
    from caddis_prepush_config import ci_caller_sha256 as sha  # the generator's own hash: one implementation
    return sha(text)


def ci_drift_warning(root: Path, header: dict) -> str | None:
    """Rule 9: a warning line when ci.yml no longer hashes to ci_caller_sha256 (derived configs only). Never a block."""
    expected = header.get("ci_caller_sha256") or ""
    if header.get("source") != "app-ci" or not expected:
        return None
    ci = root / ".github" / "workflows" / "ci.yml"
    try:
        with ci.open(encoding="utf-8", newline="") as fh:
            actual = ci_caller_sha256(fh.read())
    except ImportError:
        return "[gate] note: caddis_prepush_config.py is missing next to this hook - ci.yml drift not checked"
    except (OSError, UnicodeDecodeError):
        actual = ""
    if actual == expected:
        return None
    return ("[gate] WARNING: .github/workflows/ci.yml changed since [pre_push] was derived - "
            "re-derive with --gate-config --force")


def _git_out(root: Path, *args: str) -> str | None:
    """stdout of a git command in `root`, or None when git fails or cannot start."""
    try:
        r = subprocess.run(["git", *args], cwd=str(root), capture_output=True, text=True, timeout=30,
                           stdin=subprocess.DEVNULL, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def _is_zero(sha: str) -> bool:
    return set(sha) == {"0"}


def is_delete_only(stdin_text: str) -> bool:
    """True when every pre-push stdin line deletes a remote ref (local sha all zeros): nothing is pushed to check.

    False for empty stdin (unknown: the dry-run proof uses it) and for any line that is not a ref line."""
    lines = [line.split() for line in stdin_text.splitlines() if line.strip()]
    return bool(lines) and all(len(parts) == 4 and _is_zero(parts[1]) for parts in lines)


def changed_paths(stdin_text: str, root: Path) -> set | None:
    """The files a push changes, from git's pre-push stdin (`<local ref> <local sha> <remote ref> <remote sha>`).

    None = unknown (empty stdin, a line that is not a ref line, or any git failure): rule 4 then runs every check.
    A delete line (local sha all zeros) adds nothing, so a push of deletes only gives the empty set. A new branch
    (remote sha all zeros) diffs against its merge base with origin/HEAD, else origin/main."""
    if stdin_text.strip() == "":
        return None
    changed: set = set()
    for line in stdin_text.splitlines():
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 4:
            return None
        _, local, _, remote = parts
        if _is_zero(local):
            continue
        if _is_zero(remote):
            base = None
            for upstream in ("origin/HEAD", "origin/main"):
                out = _git_out(root, "merge-base", local, upstream)
                if out and out.strip():
                    base = out.strip()
                    break
            if base is None:
                return None
        else:
            base = remote
        out = _git_out(root, "diff", "--name-only", "--no-renames", "-z", base, local)
        if out is None:
            return None
        changed.update(p for p in out.split("\0") if p)
    return changed


def in_linked_worktree(root: Path) -> bool:
    """True in a linked git worktree (its git dir differs from the common dir). False outside a git checkout."""
    git_dir = _git_out(root, "rev-parse", "--git-dir")
    common = _git_out(root, "rev-parse", "--git-common-dir")
    if not git_dir or not common:
        return False
    return (root / git_dir.strip()).resolve() != (root / common.strip()).resolve()


def _venv_candidates(check: Check, root: Path) -> list:
    if check.venv:
        base = root / check.venv
        return [base / "Scripts" / "python.exe", base / "bin" / "python"]
    cwd = root / check.cwd
    found = [cwd / ".venv" / "Scripts" / "python.exe", cwd / ".venv" / "bin" / "python"]
    if cwd.resolve() != root.resolve():
        found += [root / ".venv" / "Scripts" / "python.exe", root / ".venv" / "bin" / "python"]
    return found


def resolve_py(check: Check, root: Path, in_worktree: bool) -> tuple:
    """(interpreter, message) for a {py} check (rule 7). The project venv first. A linked worktree with no venv gives
    (None, block line): it never borrows the main checkout's venv or the system Python. The main checkout falls back to
    python on PATH with a WARNING line."""
    for cand in _venv_candidates(check, root):
        if cand.is_file():
            return str(cand), None
    if in_worktree:
        hint = scripts_dir_hint()
        if hint and (Path(hint) / "caddis_worktree_root.py").is_file():
            fix = f'python "{hint}/caddis_worktree_root.py" --bootstrap'
        else:
            fix = ('python "<caddis scripts>/caddis_worktree_root.py" --bootstrap  '
                   "(the scripts folder of the installed caddis plugin)")
        return None, (f"[gate] {check.name}: cannot start - this git worktree has no .venv, and the gate will not "
                      f"borrow the main checkout's or the system Python - {NO_VERIFY}\n"
                      f"       fix, in this worktree: {fix}")
    system = shutil.which("python") or shutil.which("python3")
    if system:
        return system, (f"[gate] WARNING: no .venv in this checkout - using the system Python ({system}). "
                        "Its packages may differ from the project's pins.")
    return None, f"[gate] {check.name}: cannot start - no .venv and no python on PATH - {NO_VERIFY}"


def _resolve_argv0(arg0: str, cwd: Path) -> str | None:
    """argv[0] as a full path. shutil.which also finds Windows .cmd launchers (npx, npm) that Popen cannot start by
    bare name."""
    if "/" in arg0 or "\\" in arg0:
        p = Path(arg0)
        return shutil.which(str(p if p.is_absolute() else cwd / p))
    return shutil.which(arg0)


def _start(check: Check, root: Path, in_worktree: bool, said: set):
    """(proc, output file, uses_py) or (None, block line, False)."""
    uses_py = any("{py}" in a for a in check.argv)
    py = None
    if uses_py:
        py, message = resolve_py(check, root, in_worktree)
        if message and message not in said:
            said.add(message)
            print(message, file=sys.stderr, flush=True)
        if py is None:
            return None, None, False
    argv = [a.replace("{runner_py}", sys.executable).replace("{py}", py or "") for a in check.argv]
    cwd = root / check.cwd
    exe = _resolve_argv0(argv[0], cwd)
    if exe is None:
        return None, f"[gate] {check.name}: cannot start - {argv[0]} not found - {NO_VERIFY}", False
    argv[0] = exe
    kwargs: dict = {}
    if sys.platform == "win32":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs["start_new_session"] = True
    out = tempfile.TemporaryFile()
    try:
        proc = subprocess.Popen(argv, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                **kwargs)
    except OSError as exc:
        out.close()
        return None, f"[gate] {check.name}: cannot start - {argv[0]}: {exc} - {NO_VERIFY}", False
    return proc, out, uses_py


def run_checks(root: Path, checks: list, budget_s: float, jobs: int, *, changed: set | None = None,
               start: float | None = None) -> int:
    """Rules 1-7 and 10: skip by `decide`, run the rest `jobs` at a time (longest measured_s first) until one deadline.
    0 = pass, 1 = block."""
    start = time.monotonic() if start is None else start
    deadline = start + budget_s
    decided = decide(checks, changed, budget_s)
    skipped = 0
    to_run = []
    for check, line in decided:
        if line is None:
            to_run.append(check)
        else:
            print(line, flush=True)
            skipped += 1
    pending = sorted(to_run, key=lambda c: -(c.measured_s or 0.0))
    in_worktree = any("{py}" in a for c in pending for a in c.argv) and in_linked_worktree(root)
    running: list = []
    failures: list = []
    passed = 0
    said: set = set()
    jobs = max(1, jobs)
    try:
        while pending or running:
            still = []  # poll first: a check that exited before the deadline counts as run, not as killed
            for item in running:
                check, proc, t0, out, uses_py = item
                rc = proc.poll()
                if rc is None:
                    still.append(item)
                    continue
                took = format_elapsed(time.monotonic() - t0)
                out.seek(0)
                text = out.read().decode("utf-8", errors="replace")
                out.close()
                if rc == 0:
                    passed += 1
                    print(f"[gate] {check.name}: passed in {took}", flush=True)
                    continue
                failures.append(check.name)
                print(f"[gate] {check.name}: FAILED (exit {rc}) in {took}", file=sys.stderr, flush=True)
                if text.strip():
                    print(text.rstrip(), file=sys.stderr, flush=True)
                if uses_py and "No module named" in text:
                    print(f"       fix: install the dev dependencies in the project venv (pip install -e \".[dev]\"), "
                          f"or run caddis_worktree_root.py --bootstrap - {NO_VERIFY}", file=sys.stderr, flush=True)
            running = still
            if not pending and not running:
                break
            now = time.monotonic()
            if now >= deadline:
                for check, proc, t0, out, _ in running:
                    kill_process_tree(proc)
                    out.close()
                    print(f"[gate] {check.name}: SKIPPED at the {_num(budget_s)}s budget "
                          f"(ran {format_elapsed(now - t0)}) - not checked here, CI runs it", flush=True)
                    skipped += 1
                running = []
                for check in pending:
                    print(f"[skip] {check.name}: no budget left - CI runs it", flush=True)
                    skipped += 1
                pending = []
                break
            while pending and len(running) < jobs:
                check = pending.pop(0)
                proc, out, uses_py = _start(check, root, in_worktree, said)
                if proc is None:
                    if out:
                        print(out, file=sys.stderr, flush=True)
                    failures.append(check.name)
                    continue
                print(f"[gate] {check.name}: start", flush=True)
                running.append((check, proc, time.monotonic(), out, uses_py))
            if running:
                time.sleep(0.05)
    finally:  # Ctrl+C or any error: no check tree outlives the gate
        for _, proc, _, out, _ in running:
            if proc.poll() is None:
                kill_process_tree(proc)
            out.close()
    if failures:
        print(f"[caddis] push BLOCKED - {', '.join(failures)} failed or could not start - {NO_VERIFY}",
              file=sys.stderr, flush=True)
        return 1
    print(f"[caddis] gate passed - {passed} checked, {skipped} skipped (CI runs them)", flush=True)
    return 0


def _env_number(name: str, default: float, cast):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = cast(raw)
    except ValueError:
        value = 0
    if not (0 < value < float("inf")):  # also rejects nan: a deadline that never comes
        print(f"[gate] warning: {name}={raw!r} is not a positive number - using {_num(default)}", file=sys.stderr,
              flush=True)
        return default
    return value


def _read_stdin() -> str:
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return ""
        return sys.stdin.read()
    except (OSError, ValueError):
        return ""


def main(argv: list | None = None) -> int:
    start = time.monotonic()
    parser = argparse.ArgumentParser(prog="caddis_prepush.py", description="caddis pre-push gate (version 3)")
    parser.add_argument("remote", nargs="?", help="remote name (git passes it; not used)")
    parser.add_argument("url", nargs="?", help="remote URL (git passes it; not used)")
    parser.add_argument("--root", help="repo root (default: git rev-parse --show-toplevel, else the cwd)")
    parser.add_argument("--config", help="config file (default: <root>/.caddis/config.toml)")
    args = parser.parse_args(argv)
    stdin_text = _read_stdin()
    if is_delete_only(stdin_text):  # git push --delete: no commit is pushed, so there is nothing to check
        print("[caddis] delete-only push - nothing to check", flush=True)
        return 0
    print("[caddis] pre-push quality gate", flush=True)
    if tomllib is None:
        print(f"[gate] this gate needs Python 3.11 or later (found {sys.version.split()[0]}) - nothing checked here, "
              "CI is the first gate.", flush=True)
        return 0
    if kill_process_tree is None:
        print("[gate] caddis_gate_step.py is missing next to this hook - re-install the gate with "
              "setup_project_ai.py . --hooks-only", file=sys.stderr, flush=True)
        print(f"[caddis] push BLOCKED - {NO_VERIFY}", file=sys.stderr, flush=True)
        return 1
    if os.environ.get("CADDIS_GATE_PYTEST", "") == "1":
        print("[gate] note: CADDIS_GATE_PYTEST is no longer used - pytest runs in CI", flush=True)
    if args.root:
        root = Path(args.root)
    else:
        top = _git_out(Path.cwd(), "rev-parse", "--show-toplevel")
        root = Path(top.strip()) if top and top.strip() else Path.cwd()
    root = root.resolve()
    try:
        loaded = load_checks(root, Path(args.config) if args.config else None)
    except ValueError as exc:
        print(f"[gate] {exc}", file=sys.stderr, flush=True)
        print(f"[caddis] push BLOCKED - fix .caddis/config.toml - {NO_VERIFY}", file=sys.stderr, flush=True)
        return 1
    if loaded is None:
        print(no_section_line(scripts_dir_hint()), flush=True)
        return 0
    header, checks = loaded
    warning = ci_drift_warning(root, header)
    if warning:
        print(warning, file=sys.stderr, flush=True)
    budget = header.get("budget_s", 30)
    if isinstance(budget, bool) or not isinstance(budget, (int, float)) or not (0 < budget < float("inf")):
        print(f"[gate] warning: budget_s = {budget!r} in [pre_push] is not a positive number - using 30",
              file=sys.stderr, flush=True)
        budget = 30
    budget = _env_number("CADDIS_GATE_BUDGET_S", float(budget), float)
    jobs = _env_number("CADDIS_GATE_JOBS", 3, int)
    changed = changed_paths(stdin_text, root)
    return run_checks(root, checks, budget, jobs, changed=changed, start=start)


if __name__ == "__main__":
    sys.exit(main())
'''


# Enforced "green before push" gate, installed into .git/hooks/pre-push. Pure POSIX sh, so it runs under Git's bundled
# shell on Windows, Linux and macOS. Version 3 (2026-11-04) only finds an interpreter and execs the Python runner
# (PRE_PUSH_RUNNER_PY, .git/hooks/caddis_prepush.py), which runs the [pre_push] checks of .caddis/config.toml: the
# fast checks the repo's CI runs, with CI's scope, inside one time budget. The checks it no longer runs (`ruff check .`,
# `mypy .`, the root package.json scripts, `npm test`, check_doc_coverage.py, the CADDIS_GATE_PYTEST opt-in) are not
# what CI runs, or are tests. Interpreter and worktree rules for the checks live in the runner (rule 7 of
# .caddis/plans/prepush-gate-matches-ci.md): the sh text has no venv check, so a push that needs no venv never asks for one.
# Bump when the hook text changes in a way an installed copy should pick up. install_git_hooks replaces a managed hook
# whose "caddis-pre-push-version" is lower (a hook with no marker counts as 0) and leaves a hook it does not manage alone.
PRE_PUSH_HOOK_VERSION = 3
_HOOK_SCRIPTS_PLACEHOLDER = "__CADDIS_SCRIPTS__"

PRE_PUSH_HOOK = r"""#!/usr/bin/env sh
# Managed by caddis setup-project-ai. Delete this file to opt out.
# caddis-pre-push-version: 3
# Runs the [pre_push] checks of .caddis/config.toml (the fast checks CI runs) within a time budget.
# 'git push --no-verify' skips it once.
set -eu
HOOK_SCRIPTS_DIR="__CADDIS_SCRIPTS__"
if command -v dirname >/dev/null 2>&1; then
  HOOK_DIR="$(dirname "$0")"
elif [ -n "${0%/*}" ] && [ "${0%/*}" != "$0" ]; then
  HOOK_DIR="${0%/*}"
else
  HOOK_DIR="."
fi

# The interpreter for the RUNNER only (it needs Python 3.11+ for tomllib; an older one prints a line and passes).
# CADDIS_PREPUSH_PYTHON pins it; else python, then python3, on PATH.
PYRUN=""
if [ -n "${CADDIS_PREPUSH_PYTHON:-}" ] && [ -x "$CADDIS_PREPUSH_PYTHON" ]; then
  PYRUN="$CADDIS_PREPUSH_PYTHON"
else
  PYRUN=$(command -v python || command -v python3 || true)
fi
if [ -z "$PYRUN" ]; then
  echo "[gate] no python on PATH to run the pre-push gate (set CADDIS_PREPUSH_PYTHON to pin one)" >&2
  echo "[caddis] push BLOCKED - 'git push --no-verify' overrides." >&2
  exit 1
fi
if [ ! -f "$HOOK_DIR/caddis_prepush.py" ]; then
  echo "[gate] $HOOK_DIR/caddis_prepush.py is missing - re-install: python \"$HOOK_SCRIPTS_DIR/setup_project_ai.py\" . --hooks-only" >&2
  echo "[caddis] push BLOCKED - 'git push --no-verify' overrides." >&2
  exit 1
fi
exec "$PYRUN" "$HOOK_DIR/caddis_prepush.py" "$@"
"""


_HOOK_MARKER_RE = re.compile(r"Managed by (caddis|claudster)\b")
_HOOK_VERSION_RE = re.compile(r"^#\s*caddis-pre-push-version:\s*(\d+)", re.MULTILINE)


def render_pre_push_hook() -> str:
    """The hook text to install: the template with this install's scripts folder filled in (forward slashes)."""
    return PRE_PUSH_HOOK.replace(_HOOK_SCRIPTS_PLACEHOLDER, Path(__file__).resolve().parent.as_posix())


def _installed_hook_state(hook_text: str) -> tuple[bool, int]:
    """(managed by caddis, its version). A managed hook with no version marker is version 0. A hook this tool did not
    write is (False, 0): it is never replaced without --force."""
    if not _HOOK_MARKER_RE.search(hook_text):  # also recognises pre-rename ("claudster") hooks
        return False, 0
    m = _HOOK_VERSION_RE.search(hook_text)
    return True, int(m.group(1)) if m else 0


_NO_PRE_PUSH_NOTE = ("pre-push gate: installed, but .caddis/config.toml has no [pre_push] section - it checks nothing "
                     "until you run --gate-config")


def _hook_companions() -> tuple[dict[str, str], list[str]]:
    """The files the v3 hook needs next to it in .git/hooks, as {name: text}, and notes for any that cannot be had.

    `caddis_prepush_config.py` is copied from this scripts folder: the runner imports `ci_caller_sha256` from it (one
    implementation). Without it the runner prints a note and skips only the ci.yml drift check, so it is not fatal."""
    files = {"caddis_prepush.py": PRE_PUSH_RUNNER_PY, "caddis_gate_step.py": GATE_STEP_PY}
    notes: list[str] = []
    src = Path(__file__).resolve().parent / "caddis_prepush_config.py"
    try:
        files["caddis_prepush_config.py"] = src.read_text(encoding="utf-8")
    except OSError as exc:
        notes.append(f"pre-push gate: cannot copy {src.name} ({exc}) - the gate runs, but ci.yml drift is not checked")
    return files, notes


def _pre_push_section_note(target: Path) -> str | None:
    """A note when the gate would check nothing (no `[pre_push]` table) or block every push (unreadable config)."""
    cfg = target / ".caddis" / "config.toml"
    if not cfg.is_file():
        return _NO_PRE_PUSH_NOTE
    try:
        text = cfg.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return f"pre-push gate: installed, but cannot read .caddis/config.toml ({exc}) - the gate blocks every push until it is fixed"
    try:
        import tomllib
    except ModuleNotFoundError:  # Python < 3.11 runs setup: look for the header only
        has_table = any(_is_pre_push_header(line) for line in text.splitlines())
        return None if has_table else _NO_PRE_PUSH_NOTE
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        return f"pre-push gate: installed, but cannot read .caddis/config.toml ({exc}) - the gate blocks every push until it is fixed"
    return None if isinstance(data.get("pre_push"), dict) else _NO_PRE_PUSH_NOTE


def _write_hook_file(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="\n")
    try:
        import stat
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    except OSError:
        pass  # no exec bits on this filesystem; git for Windows runs the hook anyway


def install_git_hooks(target: Path, force: bool, dry: bool) -> list[str]:
    """Install the enforced pre-push quality gate: .git/hooks/pre-push and the files it runs next to it.

    An existing caddis-managed hook is replaced when its version is older than PRE_PUSH_HOOK_VERSION. A current one is
    kept, but a missing or different companion file is written again (a v3 hook without caddis_prepush.py blocks every
    push). A hook caddis did not write is left alone unless `force`. Git shares `.git/hooks` with every worktree of the
    repo, so one install in the main checkout covers them all. A note says when `.caddis/config.toml` has no
    `[pre_push]` section, because the gate then checks nothing."""
    git = target / ".git"
    if not git.exists():
        return ["pre-push gate: no .git (not a git repo) — skipped"]
    if git.is_file():  # worktree/submodule: .git is a pointer file
        return ["pre-push gate: .git is a worktree pointer — skipped (install manually if wanted)"]
    hooks_dir = git / "hooks"
    dest = hooks_dir / "pre-push"
    companions, notes = _hook_companions()
    upgraded_from: int | None = None
    if dest.exists() and not force:
        managed, version = _installed_hook_state(dest.read_text(encoding="utf-8", errors="ignore"))
        if not managed:
            return ["pre-push gate: exists (yours — left intact, use --force to replace) — skipped"]
        if version >= PRE_PUSH_HOOK_VERSION:
            stale = [name for name, text in companions.items() if not _same_text(hooks_dir / name, text)]
            if stale and not dry:
                for name in stale:
                    _write_hook_file(hooks_dir / name, companions[name])
            if stale:
                notes.append(f"pre-push gate: exists (ours) at version {version}, current - repaired {', '.join(stale)}")
            else:
                notes.append(f"pre-push gate: exists (ours) at version {version}, current — skipped")
            section = _pre_push_section_note(target)
            return notes + ([section] if section else [])
        upgraded_from = version
    if not dry:
        hooks_dir.mkdir(parents=True, exist_ok=True)
        _write_hook_file(dest, render_pre_push_hook())
        for name, text in companions.items():
            _write_hook_file(hooks_dir / name, text)
    if upgraded_from is not None:
        head = f".git/hooks/pre-push (version {upgraded_from} -> {PRE_PUSH_HOOK_VERSION})"
        notes.append(f"pre-push gate: upgraded {_and_list([head, *companions])} (green-before-push enforced)")
    else:
        notes.append(f"pre-push gate: installed {_and_list(['.git/hooks/pre-push', *companions])} "
                     "(green-before-push enforced)")
    section = _pre_push_section_note(target)
    return notes + ([section] if section else [])


def _and_list(items: list[str]) -> str:
    """'a', 'a and b', 'a, b and c'."""
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _same_text(path: Path, text: str) -> bool:
    try:
        return path.read_text(encoding="utf-8") == text
    except (OSError, UnicodeDecodeError):
        return False


# Anchored at the end so a line of a multi-line array (`  ["a", "b"],`) is not read as a header.
_TOML_HEADER_RE = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(?:#.*)?$")


def _is_pre_push_header(line: str) -> bool | None:
    """True for a `[pre_push]` / `[pre_push.x]` / `[[pre_push.x]]` header, False for another header, None for no header."""
    m = _TOML_HEADER_RE.match(line)
    if not m:
        return None
    name = m.group(1)
    return name == "pre_push" or name.startswith("pre_push.")


def _remove_pre_push_tables(text: str) -> str:
    """`text` without any `[pre_push*]` table. Each table runs to the next other header or end of file."""
    kept: list[str] = []
    inside = False
    for line in text.splitlines(keepends=True):
        header = _is_pre_push_header(line)
        if header is not None:
            inside = header
        if not inside:
            kept.append(line)
    return "".join(kept)


def write_pre_push_config(target: Path, force: bool, dry: bool) -> list[str]:
    """Append a `[pre_push]` section derived from `.github/workflows/ci.yml` to `.caddis/config.toml`.

    Other sections are never rewritten. An existing `[pre_push]` is kept unless `force`, which removes every
    `[pre_push*]` table first. `dry` returns the section text and writes nothing. Raises `ValueError` for an
    app-ci tag this generator does not know (it stops, it does not guess).
    """
    here = str(Path(__file__).resolve().parent)
    if here not in sys.path:
        sys.path.insert(0, here)
    import caddis_prepush_config as pcfg

    ci = target / ".github" / "workflows" / "ci.yml"
    manual = 'write [pre_push] by hand (source = "manual")'
    if not ci.is_file():
        return [f"pre-push config: no .github/workflows/ci.yml - {manual}"]
    ci_text = ci.read_text(encoding="utf-8")
    parsed = pcfg.parse_app_ci_caller(ci_text)
    if parsed is None:
        return [f"pre-push config: ci.yml does not call app-ci - {manual}"]
    tag, inputs = parsed
    checks = pcfg.derive_checks(tag, inputs, target)
    section = pcfg.render_pre_push_section(checks, source="app-ci", derived_from=tag,
                                           ci_sha256=pcfg.ci_caller_sha256(ci_text))

    config = target / ".caddis" / "config.toml"
    existing = ""
    if config.is_file():
        with config.open(encoding="utf-8", newline="") as fh:  # keep CRLF as is: other sections stay byte-identical
            existing = fh.read()
    has_section = any(_is_pre_push_header(line) for line in existing.splitlines())
    if has_section and not force:
        return ["pre-push config: [pre_push] exists - skipped (--force replaces it)"]
    if dry:
        return [f"pre-push config: would write [pre_push] to {config} (dry-run):", *section.splitlines()]
    base = _remove_pre_push_tables(existing) if has_section else existing
    eol = "\r\n" if "\r\n" in existing else "\n"
    if has_section:
        base = base.rstrip("\r\n")  # one blank line before the new section, however many --force runs
        base = base + eol if base else base
    elif base and not base.endswith(("\n", "\r")):
        base += eol
    if base.strip():
        base += eol
    config.parent.mkdir(parents=True, exist_ok=True)
    config.write_text(base + section.replace("\n", eol), encoding="utf-8", newline="")
    verb = "replaced" if has_section else "wrote"
    return [f"pre-push config: {verb} [pre_push] in {config} ({len(checks)} checks from {tag})"]


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

**Read that rule the other way round: THIS TABLE IS WHERE YOU LOOK BEFORE YOU WRITE ONE.** Check it
before drafting, not only after filing. A handover transfers a task, and for the whole overlap
window two sessions can both believe an outbound note is theirs - on 2026-09-08 two of them wrote
the same note five minutes apart, and both sat here marked ready to send. Two notes on one subject
reaching one team reads as one team not talking to itself.

**If you do find a duplicate, do not delete it.** Verify its unique contributions independently,
fold them into the survivor, and archive the loser with a banner saying why. The second draft is a
second reading - the one in that incident found a defect in the first.

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
| A task interrupted mid-session | `/caddis:digress` stack | That is a pause, not a backlog item. `/caddis:catchup` pops it. |
| An ask only an outsider can resolve | `.caddis/comms/register.md` | Blocked on a human, not on us. |

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
usage-log.jsonl.1
agent-log.jsonl.1
.last-usage-review
.last-preload-review
relay.md
relay/
session-state.md
session-state/
context-window.json
context-window.json.tmp
context-window.json.*.tmp
context-window/
.session-state-*.tmp
hook-errors.jsonl
.relay-injected/
PROJECT-FACTS.md
# lock files beside locked documents, and migration backups (never commit these)
*.lock
*.bak
# retired writer; ignored so old files stay untracked
memory.jsonl
"""


GLOSSARY_TEMPLATE = """\
# Glossary

The words this project invented out of ordinary English, defined once.

**Admission test:** a term belongs here when its meaning in this project is *distinct
enough from its ordinary technical sense that a newcomer would misread it*. `commit` does
not belong. A word this team uses in its own way does.

To find candidates, run the measurer. It ranks the words this repo says often that plain
English does not, and marks which already have an entry:

    python <caddis>/scripts/caddis_glossary.py

It cannot write the definitions - only a person or the model reading the code can say what
a coined word MEANS here. Run `/caddis:glossary` to have them drafted, or write them.

This file is for YOUR project's vocabulary. caddis's own coined words - pool, relay, drift,
export target - are defined separately in `CADDIS-GLOSSARY.md` at the plugin root, which also
serves as a worked example of what a good entry looks like. Do not copy those terms in here.

| Term | Definition | DO NOT USE |
|---|---|---|
| _example_ | Replace this row. Say what the word means HERE, and why the ordinary reading is wrong. | the synonyms that cause confusion |

## Flagged ambiguities

Name the words that are still overloaded rather than pretending the vocabulary is clean. A
glossary that hides its own dirt starts lying. Delete this section only when there is
genuinely nothing to flag.
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


def _atomic_write_json(path: Path, data: dict) -> None:
    """Write `data` to `path` through a temp file. The temp name is unique per process: every
    SessionStart runs this (inject_relay.py), and two sessions starting at once must not share one."""
    tmp = path.with_name(f"{path.name}.caddis-tmp-{os.getpid()}")
    try:
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if tmp.exists():
            tmp.unlink()


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
        _atomic_write_json(path, data)
    verb = "would add" if dry else "added"
    return [f"user env: {verb} {TODO_TOOLS_ENV_KEY}=1 to {path}"
            + ("" if not raw else " (previous version saved as settings.json.caddis-bak)")]


# ── superpowers twins that caddis replaces ──────────────────────────────────────────────────
# caddis owns the routing-critical skills: brainstorming, plans (/caddis:feature-plan), running plans
# (/caddis:implement) and worktrees. The superpowers plugin ships skills with the same names; its
# writing-plans and executing-plans skip the caddis model routing. A deny rule blocks such a skill
# ("Skill execution blocked by permission rules") WITHOUT a prompt, so it keeps the zero-prompt setup
# (an `ask` rule would prompt every time). Every other superpowers skill is used straight from the plugin.
# inject_relay.py re-states this list to warn when a rule is missing; a test keeps the two equal.
SUPERPOWERS_DENY = (
    "Skill(superpowers:brainstorming)",
    "Skill(superpowers:writing-plans)",
    "Skill(superpowers:executing-plans)",
    "Skill(superpowers:subagent-driven-development)",
    "Skill(superpowers:using-git-worktrees)",
)


def ensure_superpowers_deny(dry: bool, home: Path | None = None) -> str:
    """Add the SUPERPOWERS_DENY rules to the user's `permissions.deny`, additively and idempotently.

    Other deny entries (and every other setting) are never removed or reordered. Same safety rules as
    ensure_user_env: a file that does not parse is never rewritten, a backup is kept
    (`settings.json.caddis-deny-bak`, its own name so it cannot overwrite another function's backup), the
    write is atomic, and `CADDIS_NO_SETTINGS_ENV` skips it. Known limit, as for ensure_user_env: a write by
    Claude Code between this read and the replace is lost."""
    if os.environ.get("CADDIS_NO_SETTINGS_ENV"):
        return "superpowers deny rules: skipped (CADDIS_NO_SETTINGS_ENV set)"
    path = _user_settings_path(home)
    if path.is_file():
        raw = path.read_text(encoding="utf-8", errors="ignore")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return (f"superpowers deny rules: {path} is NOT VALID JSON ({exc.msg}, line {exc.lineno}) — "
                    "left untouched; fix it by hand.")
        if not isinstance(data, dict):
            return f"superpowers deny rules: {path} is not a JSON object — left untouched"
    else:
        raw, data = "", {}
    perms = data.get("permissions")
    if perms is None:
        perms = {}
    elif not isinstance(perms, dict):
        return f"superpowers deny rules: {path} has a non-object `permissions` — left untouched"
    deny = perms.get("deny")
    if deny is None:
        deny = []
    elif not isinstance(deny, list):
        return f"superpowers deny rules: {path} has a non-list `permissions.deny` — left untouched"
    missing = [rule for rule in SUPERPOWERS_DENY if rule not in deny]
    if not missing:
        return f"superpowers deny rules: all {len(SUPERPOWERS_DENY)} already in {path}"
    perms["deny"] = deny + missing
    data["permissions"] = perms
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw:
            path.with_suffix(".json.caddis-deny-bak").write_text(raw, encoding="utf-8")
        _atomic_write_json(path, data)
    verb = "would add" if dry else "added"
    return f"superpowers deny rules: {verb} {len(missing)} to permissions.deny in {path}"


CLEANUP_PERIOD_KEY = "cleanupPeriodDays"
CLEANUP_PERIOD_DAYS = 120


def ensure_cleanup_period(dry: bool, home: Path | None = None, days: int = CLEANUP_PERIOD_DAYS) -> str:
    """Keep Claude Code transcripts `days` days (Claude Code's own default is 30) by adding `cleanupPeriodDays`.

    WHY: caddis measures which skills and commands are used from those transcripts; on 11 Oct 2026 only
    35 days were left, too few to decide what to cut (caddis-next checks, section 4.6). Same rules as
    ensure_user_env: an existing value is ALWAYS left alone, a file that does not parse is never rewritten,
    a backup is kept and the write is atomic. `CADDIS_NO_SETTINGS_ENV` skips it. Its backup has its own name
    (`settings.json.caddis-retention-bak`): main() runs ensure_user_env first, and sharing `.caddis-bak` would
    overwrite the user's original file with that function's output. Known limit, as for ensure_user_env: a
    write by Claude Code between this read and the replace is lost."""
    if os.environ.get("CADDIS_NO_SETTINGS_ENV"):
        return "transcript retention: skipped (CADDIS_NO_SETTINGS_ENV set)"
    path = _user_settings_path(home)
    if path.is_file():
        raw = path.read_text(encoding="utf-8", errors="ignore")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            return (f"transcript retention: {path} is NOT VALID JSON ({exc.msg}, line {exc.lineno}) — "
                    "left untouched; fix it by hand.")
        if not isinstance(data, dict):
            return f"transcript retention: {path} is not a JSON object — left untouched"
    else:
        raw, data = "", {}
    if CLEANUP_PERIOD_KEY in data:
        return f"transcript retention: {CLEANUP_PERIOD_KEY} already set to {data[CLEANUP_PERIOD_KEY]!r} — left alone"
    data[CLEANUP_PERIOD_KEY] = days
    if not dry:
        path.parent.mkdir(parents=True, exist_ok=True)
        if raw:
            path.with_suffix(".json.caddis-retention-bak").write_text(raw, encoding="utf-8")
        _atomic_write_json(path, data)
    verb = "would set" if dry else "set"
    return f"transcript retention: {verb} {CLEANUP_PERIOD_KEY}={days} in {path}"


def scaffold_artifact_dir(target: Path, dry: bool) -> list[str]:
    """Create the harness-owned .caddis/ artifact tree + a default .gitignore + a config example.

    Committed subdirs: plans, handoffs, agent-docs, prd, kb, prompts, comms. Transient state
    (reviews/*.html, usage-log.jsonl, .last-usage-review, .last-preload-review, relay*, session-state.md,
    PROJECT-FACTS.md) is gitignored. .caddis/ is the default home for every working-artifact kind (Track A
    Phase A3) — kb/ and prompts/ round out plans/prd/agent-docs/reviews so nothing has to
    scatter to the repo root or .github/. Also drops a documented `config.toml.example`
    (guard/doc_coverage). Idempotent. An existing .caddis/.gitignore is never clobbered or
    reordered, but MISSING entries are appended — otherwise a repo set up before an entry
    existed would never receive it. The config example is left alone entirely.

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
    # A vocabulary stub, seeded but never auto-filled. `caddis_glossary.py` can measure
    # which words a repo coined, but only a person or the model reading the code can say
    # what they MEAN - and a file of correct words with empty meanings looks authoritative
    # while teaching nothing. The stub carries the admission test so whoever fills it in
    # knows what qualifies.
    gl = root / "kb" / "GLOSSARY.md"
    if gl.exists():
        notes.append(f"scaffold: {label}/kb/GLOSSARY.md present - kept")
    else:
        if not dry:
            gl.parent.mkdir(parents=True, exist_ok=True)
            gl.write_text(GLOSSARY_TEMPLATE, encoding="utf-8")
        notes.append(f"scaffold: wrote {label}/kb/GLOSSARY.md (run /caddis:glossary to fill it)")

    gi = root / ".gitignore"
    if gi.exists():
        # APPEND what is missing rather than keeping the file frozen. The old behaviour was
        # "present -> kept", so a repo scaffolded before an entry was added NEVER received it.
        # That is not hypothetical: `session-state.md` is rewritten by the Stop hook on every
        # turn and contains the operator's verbatim words, and an already-scaffolded repo was
        # sitting one hook-fire away from committing it.
        #
        # Only ever adds; a line the user wrote themselves is never touched or reordered.
        try:
            existing = gi.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        have = {ln.strip() for ln in existing.splitlines()}
        missing = [
            ln for ln in ARTIFACT_GITIGNORE.splitlines()
            if ln.strip() and not ln.startswith("#") and ln.strip() not in have
        ]
        if not missing:
            notes.append(f"scaffold: {label}/.gitignore present — up to date")
        else:
            if not dry:
                block = "" if existing.endswith("\n") or not existing else "\n"
                block += "\n# added by caddis — newer transient artifacts\n"
                block += "\n".join(missing) + "\n"
                gi.write_text(existing + block, encoding="utf-8")
            notes.append(
                f"scaffold: {label}/.gitignore — added {len(missing)} missing entry(ies): "
                + ", ".join(missing)
            )
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
    ap.add_argument("--gate-config", action="store_true",
                    help="Write ONLY the [pre_push] section of .caddis/config.toml, derived from the app-ci "
                         "caller in .github/workflows/ci.yml, and exit. An existing section is kept unless "
                         "--force; --dry-run prints it.")
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

    if args.gate_config:
        try:
            gate_notes = write_pre_push_config(target, args.force, args.dry_run)
        except ValueError as exc:
            print(f"ERROR: pre-push config: {exc}", file=sys.stderr)
            return 2
        for note in gate_notes:
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
    print(f"   {ensure_cleanup_period(args.dry_run)}")
    print(f"   {ensure_superpowers_deny(args.dry_run)}")

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
    print("   user-scope now — run /caddis:install-statusline once per machine (not per project)")

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
