"""claudster_doctor — read-only health + maintenance report for a caddis install, any harness.

Diagnoses the things that silently break a cross-harness setup: a harness binary missing from PATH
(the Windows "new terminal" gotcha), a harness version that has drifted past the probed contract,
rules-file integrity (root AGENTS.md present; CLAUDE.md is a shim, not a fork), the user-level skills
path, and python for the tooling itself. It also computes DETERMINISTIC maintenance signals (no LLM):
an oversize always-loaded AGENTS.md, dangling DOC-MAP links, harness-contract version drift, and days
since the last doctor run. Read-only; exit 1 on a hard failure.

Usage:
    python claudster_doctor.py                 # check cwd + all known harnesses
    python claudster_doctor.py --dest <proj>   # check a specific project's rules
    python claudster_doctor.py --quiet         # only the one-line maintenance nudge (for SessionStart)
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

FIX_HINTS: dict[str, str] = {
    "python-missing": "install Python 3.11 or later; on Linux also run: sudo apt install python-is-python3",
    "python-store-alias": "this is the Microsoft Store alias; install Python from python.org or with winget, then turn off the alias in Settings > Apps > App execution aliases",
    "python-old": "install Python 3.11 or later and make it the first python on PATH",
    "git-missing": "install git (Windows: winget install Git.Git; Linux: sudo apt install git)",
    "keys-none": "optional: run caddis keys to add GLM or DeepSeek keys",
    "deny-rules": "run /caddis:setup-project-ai to add the missing deny rules",
    "gitignore": "run /caddis:setup-project-ai to add the missing .caddis ignore entries",
    "misfiled": "move the file into a caddis document folder, or delete it",
}

# Probed contract versions (docs/analysis/*-contract.md). WARN when the installed binary drifts past
# these — the recorded schemas may be stale and want a re-probe.
PROBED_VERSIONS = {"codex": "0.137", "agy": "1.1.5"}
AGENTS_MD_BUDGET = 200  # always-loaded rules file line budget (mirrors check_doc_coverage)

# Per-repo artifact dir + env prefix, mirrored from claude-harness/scripts/claudster_config.py —
# the doctor is a standalone, import-free diagnostic that must run from a bare checkout.
ARTIFACT_DIRS = (".caddis",)
ENV_PREFIX = "CADDIS"

# Known top-level document and working artifact folders under .caddis/
KNOWN_CADDIS_DIRS: set[str] = {
    "plans",
    "prd",
    "kb",
    "rca",
    "decisions",
    "parking-lot",
    "reviews",
    "todo-list",
    "comms",
    "handoffs",
    "prompts",
    "relay",
    "session-state",
    "advisory-hub-reports",
    "orchestrator",
    "spawn-session",
    "metrics",
    "agent-docs",
    "backlog",
}


def _home() -> Path:
    return Path(os.environ.get(f"{ENV_PREFIX}_FAKE_HOME") or Path.home())


def _user_scope_path(name: str) -> Path:
    """A ``~/.caddis/<name>`` user-scope file."""
    return _home() / ".caddis" / name


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _which(name: str) -> str | None:
    hit = shutil.which(name)
    if hit:
        return hit
    # off-PATH but installed (the agy case on Windows): probe the known install dir
    if name == "agy":
        cand = _home() / "AppData" / "Local" / "agy" / "bin" / "agy.exe"
        if cand.is_file():
            return str(cand)
    return None


def _binary_version(path: str) -> str | None:
    try:
        out = subprocess.run([path, "--version"], capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0] if (out.stdout or out.stderr) else None
    except Exception:
        return None


# ── rules integrity (self-contained fork detector — same rule as claudster_migrate_rules --check) ──
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "dist", "build", "done", "archive"}


def _is_shim(text: str) -> bool:
    return any(ln.strip() == "@AGENTS.md" for ln in text.splitlines())


def rules_findings(dest: Path) -> list[str]:
    """Fork detector: a non-shim CLAUDE.md beside an AGENTS.md, or a bare CLAUDE.md with no sibling."""
    dest = Path(dest)
    out: list[str] = []
    for dirpath, dirnames, filenames in os.walk(dest):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        if "CLAUDE.md" not in filenames:
            continue
        d = Path(dirpath)
        rel = (d / "CLAUDE.md").relative_to(dest).as_posix()
        try:
            text = (d / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "AGENTS.md" in filenames:
            if not _is_shim(text):
                out.append(f"{rel}: not a shim but a sibling AGENTS.md exists (drifted shim)")
        else:
            out.append(f"{rel}: bare CLAUDE.md with no sibling AGENTS.md (fork — run /caddis:add-rules)")
    return out


def has_document_frontmatter_rule(dest: Path) -> bool:
    """True when root AGENTS.md puts type: in its Document frontmatter section."""
    path = Path(dest) / "AGENTS.md"
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return False
    section = False
    for line in lines:
        if re.match(r"^\s*(?:#{1,6}\s+|[-*]\s+\*\*)Document frontmatter(?:\*\*)?\s*:?.*$", line):
            section = True
            if "type:" in line:
                return True
            continue
        if section and ("type:" in line or re.match(r"^\s*[-*]\s+\*\*type\*\*\s*:", line)):
            return True
        if section and (re.match(r"^#{1,6}\s+", line) or
                        re.match(r"^\s*[-*]\s+\*\*[^*]+\*\*\s*:", line)):
            section = False
    return False


def oversize_rules_files(dest: Path, budget: int = AGENTS_MD_BUDGET) -> list[tuple[str, int]]:
    """Always-loaded rules files (AGENTS.md, or CLAUDE.md pre-migration) over the line budget."""
    dest = Path(dest)
    out: list[tuple[str, int]] = []
    for dirpath, dirnames, filenames in os.walk(dest):
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS]
        d = Path(dirpath)
        f = "AGENTS.md" if "AGENTS.md" in filenames else ("CLAUDE.md" if "CLAUDE.md" in filenames else None)
        if not f:
            continue
        try:
            n = len((d / f).read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            continue
        if n > budget:
            out.append(((d / f).relative_to(dest).as_posix(), n))
    return out


def _severity_word(ratio: float) -> str:
    """Coarse severity label so a 1.1x overage doesn't read identically to a 5x one
    (register 0e: the nudge used to print the exact same sentence for both)."""
    if ratio >= 3.0:
        return "way"
    if ratio >= 1.5:
        return "well"
    return "slightly"


def oversize_message(rel_path: str, lines: int, budget: int = AGENTS_MD_BUDGET) -> str:
    """One-line, severity-scaled description of an oversize rules file. Shared by the
    SessionStart/PreCompact nudge (nudge_line) and the PostToolUse re-warn
    (hooks/rules_budget_nudge.py) so both read identically and the threshold lives in
    exactly one place: ``AGENTS_MD_BUDGET`` above (mirrored in check_doc_coverage.py)."""
    ratio = lines / budget if budget else 0.0
    return (f"AGENTS.md {_severity_word(ratio)} over budget "
            f"({rel_path}: {lines} lines, {ratio:.1f}x the {budget}-line budget) — run claude-md-curator")


def docmap_dangling(dest: Path) -> list[str]:
    """Dangling `.md` links in <artifact-dir>/kb/DOC-MAP.md (the '/caddis:kb' signal)."""
    dm = next((p for p in (Path(dest) / n / "kb" / "DOC-MAP.md" for n in ARTIFACT_DIRS) if p.is_file()), None)
    if dm is None:
        return []
    import re
    text = dm.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"\A---\r?\n.*?\r?\n---\r?\n", "", text, flags=re.DOTALL)
    text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    dangling = []
    for target in re.findall(r"\]\(([^)]+\.md)\)", text):
        target = target.strip()
        if target.startswith(("http://", "https://")):
            continue
        resolved = (dm.parent / target).resolve()
        if not resolved.exists():
            dangling.append(target)
    return dangling


# ── maintenance signals + nudge ──────────────────────────────────────────────
def _last_doctor_path() -> Path:
    return _user_scope_path("last-doctor.json")


def days_since_last_doctor() -> int | None:
    p = _last_doctor_path()
    if not p.is_file():
        return None
    try:
        ts = json.loads(p.read_text(encoding="utf-8")).get("timestamp")
        last = datetime.fromisoformat(ts)
        return (_now() - last).days
    except Exception:
        return None


def _stamp_last_doctor() -> None:
    p = _last_doctor_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"timestamp": _now().isoformat(timespec="seconds")}) + "\n", encoding="utf-8")


def version_drift() -> list[str]:
    out = []
    for name, probed in PROBED_VERSIONS.items():
        path = _which(name)
        if not path:
            continue
        ver = _binary_version(path) or ""
        # crude: if the probed version string isn't a substring of the reported version, it drifted
        digits = "".join(c for c in ver if c.isdigit() or c == ".")
        if probed not in digits and digits:
            out.append(f"{name} {digits.strip('.')} vs probed {probed} — re-probe the contract")
    return out


def _is_caddis_source(dest: Path) -> bool:
    """True for the caddis authoring repo, where `.github/tools/` is the MASTER, not a copy.

    Without this the drift check fires permanently in the one repo where a difference is the
    normal state — and a check that is always red is a check nobody reads."""
    return (dest / "claude-harness").is_dir()


def _norm(text: str) -> str:
    return text.replace("\r\n", "\n").strip()


def vendored_drift(dest: Path, plugin_root: Path | None = None) -> list[str]:
    """Vendored `.github/tools/*.py` copies that no longer match the plugin's shipped copy.

    WHY THIS EXISTS
    ---------------
    `/caddis:cross-review` resolved its tool as `.github/tools/oss_review.py` FIRST and the plugin
    copy second, with nothing comparing them. On 2026-08-10 a repo ran a stale vendored
    `oss_review.py` and got a false CLEAN on a database write path; the fixed copy was sitting
    unused in the plugin the whole time. The bug had been fixed on 2026-08-01 and the fix simply
    never reached the caller.

    That is worse than an ordinary stale file. It means **any** caddis fix is untrustworthy in a
    repo that vendored early, and nothing anywhere reports the skew. The vendoring itself was
    reasonable when it happened — the plugin did not ship these scripts until 2026-07-30 — which is
    exactly why the copies are still lying around.

    Pure file comparison, no subprocess, safe for SessionStart. Returns [] when there is nothing to
    compare against (no plugin root, no vendored dir) — silence, not a complaint.
    """
    # The SessionStart hook passes ROOT as a str, not a Path. Coerce rather than assume — the
    # first version of this function assumed Path and broke the hook's own regression test.
    dest = Path(dest)
    if _is_caddis_source(dest):
        return []
    root = plugin_root or (Path(os.environ["CLAUDE_PLUGIN_ROOT"])
                           if os.environ.get("CLAUDE_PLUGIN_ROOT") else None)
    if root is None:
        return []
    tools = dest / ".github" / "tools"
    if not tools.is_dir():
        return []
    out: list[str] = []
    for local in sorted(tools.glob("*.py")):
        shipped = root / "scripts" / local.name
        if not shipped.is_file():
            continue
        try:
            if _norm(local.read_text(encoding="utf-8", errors="ignore")) != \
               _norm(shipped.read_text(encoding="utf-8", errors="ignore")):
                out.append(f".github/tools/{local.name} differs from the caddis copy — "
                           "probably a stale vendor; delete it or keep the change deliberately")
        except OSError:
            continue
    return out


def _file_signals(dest: Path) -> list[str]:
    """PURE FILE-CHECK signals only (no subprocess) — safe + fast for SessionStart. One line each."""
    signals: list[str] = []
    over = oversize_rules_files(dest)
    if over:
        worst = max(over, key=lambda x: x[1])
        signals.append(oversize_message(worst[0], worst[1]))
    dangling = docmap_dangling(dest)
    if dangling:
        signals.append(f"{len(dangling)} dangling DOC-MAP link(s) — run /caddis:kb")
    days = days_since_last_doctor()
    if days is not None and days >= 30:
        signals.append(f"{days} days since last caddis doctor — run caddis doctor")
    # Listed LAST but it is the most dangerous signal here: the others degrade a session's quality,
    # this one silently runs old code and reports success. It is cheap (a file compare) and almost
    # always empty, so it costs nothing to carry.
    signals += vendored_drift(dest)
    return signals


def maintenance_signals(dest: Path) -> list[str]:
    """All deterministic signals (file checks + harness-version drift). For the full doctor report."""
    return _file_signals(dest) + version_drift()


def nudge_line(dest: Path) -> str | None:
    """The single SessionStart nudge line, or None. PURE FILE CHECKS only (no subprocess, no LLM, no
    auto-fix) so it never slows session start; curator/kb stay human-triggered."""
    sig = _file_signals(dest)
    if not sig:
        return None
    head = sig[0]
    more = f" (+{len(sig) - 1} more — run caddis doctor)" if len(sig) > 1 else ""
    return f"[caddis] {head}{more}"


def _load_sibling(name: str, fallback_dir: Path | str | None = None):
    """Load a helper module by filename/module name: sibling first, then fallback_dir."""
    scripts = Path(__file__).resolve().parent
    file_name = name if name.endswith(".py") else f"{name}.py"
    mod_name = name[:-3] if name.endswith(".py") else name
    path = scripts / file_name
    if not path.is_file() and fallback_dir:
        path = Path(fallback_dir) / file_name
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location(f"caddis_{mod_name}", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hook_errors(dest: Path) -> str:
    """Recent hook failures, counted by hook. Empty when the ledger is clean."""
    scripts = Path(__file__).resolve().parent
    try:
        hook_log = _load_sibling("hook_log.py", scripts.parent / "claude-harness" / "scripts")
        if hook_log is None or not hook_log.summarise(str(dest), days=7):
            return ""
        cutoff = time.strftime("%Y-%m-%d", time.localtime(time.time() - 7 * 86400))
        counts: dict[str, int] = {}
        with (dest / ".caddis" / "hook-errors.jsonl").open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(row, dict) and str(row.get("ts", ""))[:10] >= cutoff:
                    hook = str(row.get("hook", "?"))
                    counts[hook] = counts.get(hook, 0) + 1
        return ", ".join(f"{hook} x{count}" for hook, count in sorted(counts.items()))
    except Exception:
        return ""  # a damaged ledger must not break the doctor


def machine_findings(which: Callable[[str], str | None] | None = None,
                     version: Callable[[str], str | None] | None = None) -> list[tuple[str, str]]:
    """Machine faults that stop caddis on a new laptop. Levels: OK, INFO, FAIL (never raises)."""
    which = which or shutil.which  # resolved at call time, so a test can patch shutil.which
    version = version or _binary_version

    out: list[tuple[str, str]] = []

    # python
    py_path = which("python")
    if py_path is None:
        out.append(("FAIL", f"python (on PATH): not found — {FIX_HINTS['python-missing']}"))
    elif "windowsapps" in py_path.lower() or "WindowsApps" in py_path:
        out.append(("FAIL", f"python (on PATH): [{py_path}] — {FIX_HINTS['python-store-alias']}"))
    else:
        ver_str = None
        try:
            ver_str = version(py_path)
        except Exception:
            ver_str = None

        m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", ver_str or "")
        if not m:
            out.append(("INFO", "python (on PATH): could not read its version"))
        else:
            major, minor = int(m.group(1)), int(m.group(2))
            ver_display = (ver_str or "").strip()
            if ver_display.startswith("Python "):
                ver_display = ver_display[7:].strip()
            if (major, minor) < (3, 11):
                out.append(("FAIL", f"python (on PATH): {ver_display} [{py_path}] — {FIX_HINTS['python-old']}"))
            else:
                out.append(("OK", f"python (on PATH): {ver_display} [{py_path}]"))

    # git
    git_path = which("git")
    if git_path is None:
        out.append(("FAIL", f"git: not found — {FIX_HINTS['git-missing']}"))
    else:
        out.append(("OK", f"git: [{git_path}]"))

    return out


def keys_line(env: Mapping[str, str]) -> tuple[str, str]:
    scripts = Path(__file__).resolve().parent
    try:
        oss_model = _load_sibling("oss_model.py", scripts.parent / "claude-harness" / "scripts")
        if oss_model is None:
            return ("INFO", "keys: could not check")

        env_dict = dict(env)
        fake_home = env_dict.get(f"{ENV_PREFIX}_FAKE_HOME") or os.environ.get(f"{ENV_PREFIX}_FAKE_HOME")
        if fake_home and "CADDIS_KEYS_FILE" not in env_dict:
            env_dict["CADDIS_KEYS_FILE"] = str(Path(fake_home) / ".caddis" / "keys.env")

        providers = oss_model.configured_providers(env_dict)
        if providers:
            return ("OK", f"keys: {', '.join(providers)}")
        return ("INFO", f"keys: none — {FIX_HINTS['keys-none']}")
    except Exception:
        return ("INFO", "keys: could not check")


# ── project checks (read-only — WARN or INFO, never FAIL) ─────────────────────
def deny_rule_findings(dest: Path) -> list[tuple[str, str]]:
    dest = Path(dest)
    if _is_caddis_source(dest):
        return []

    scripts = Path(__file__).resolve().parent
    tmpl_path = scripts.parent / "settings.template.json"
    if not tmpl_path.is_file():
        tmpl_path = scripts.parent / "claude-harness" / "settings.template.json"
    if not tmpl_path.is_file():
        return []

    settings_path = dest / ".claude" / "settings.json"
    if not settings_path.is_file():
        return [("INFO", "no .claude/settings.json")]

    try:
        tmpl = json.loads(tmpl_path.read_text(encoding="utf-8"))
        required_deny = tmpl.get("permissions", {}).get("deny", [])
    except Exception:
        return []

    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        dest_deny = set(settings.get("permissions", {}).get("deny", []))
    except Exception:
        dest_deny = set()

    missing = [r for r in required_deny if r not in dest_deny]
    if missing:
        return [("WARN", f"deny rules: {len(missing)} missing — {FIX_HINTS['deny-rules']}")]
    return []


def gitignore_findings(dest: Path) -> list[tuple[str, str]]:
    dest = Path(dest)
    if _is_caddis_source(dest):
        return []
    if not (dest / ".caddis").is_dir():
        return []

    scripts = Path(__file__).resolve().parent
    try:
        setup_mod = _load_sibling("setup_project_ai.py", scripts.parent / "scripts")
        if setup_mod is None:
            return [("INFO", "gitignore: could not check")]
        artifact_gitignore = getattr(setup_mod, "ARTIFACT_GITIGNORE", None)
        if not artifact_gitignore:
            return [("INFO", "gitignore: could not check")]

        entries = [
            line.strip()
            for line in artifact_gitignore.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        caddis_ignore = dest / ".caddis" / ".gitignore"
        caddis_lines: set[str] = set()
        if caddis_ignore.is_file():
            try:
                caddis_lines = {line.strip() for line in caddis_ignore.read_text(encoding="utf-8", errors="replace").splitlines()}
            except OSError:
                pass

        root_ignore = dest / ".gitignore"
        root_lines: set[str] = set()
        if root_ignore.is_file():
            try:
                root_lines = {line.strip() for line in root_ignore.read_text(encoding="utf-8", errors="replace").splitlines()}
            except OSError:
                pass

        missing: list[str] = []
        for entry in entries:
            if entry in caddis_lines or f".caddis/{entry}" in root_lines:
                continue
            missing.append(entry)

        if missing:
            first_three = ", ".join(missing[:3])
            return [("WARN", f"gitignore: {len(missing)} missing ({first_three}) — {FIX_HINTS['gitignore']}")]
        return []
    except Exception:
        return [("INFO", "gitignore: could not check")]


def misfiled_findings(dest: Path) -> list[tuple[str, str]]:
    dest = Path(dest)
    if _is_caddis_source(dest):
        return []

    caddis_dir = dest / ".caddis"
    if not caddis_dir.is_dir():
        return []

    out: list[tuple[str, str]] = []
    try:
        subdirs = sorted(p for p in caddis_dir.iterdir() if p.is_dir())
    except OSError:
        return []

    for top_dir in subdirs:
        if top_dir.name in _SKIP_DIRS:
            continue
        if top_dir.name not in KNOWN_CADDIS_DIRS:
            md_files = list(top_dir.rglob("*.md"))
            if md_files:
                out.append(("WARN", f".caddis/{top_dir.name}/ is not a caddis folder ({len(md_files)} file(s)) — {FIX_HINTS['misfiled']}"))
    return out


# ── report ───────────────────────────────────────────────────────────────────
def run(dest: Path, quiet: bool) -> int:
    if quiet:  # SessionStart mode: only the nudge, never non-zero
        line = nudge_line(dest)
        if line:
            print(line)
        return 0

    hard = 0
    print(f"=== caddis doctor — {dest} ===")
    print(f"python (running this check): {sys.version.split()[0]}  ({sys.executable})")
    for name in ("codex", "agy", "claude"):
        path = _which(name)
        if path:
            ver = _binary_version(path) or "?"
            print(f"  {name:7} OK   {ver}   [{path}]")
        else:
            print(f"  {name:7} not found on PATH (install, or open a new terminal so PATH refreshes)")

    print("-- machine")
    for level, text in machine_findings():
        if level == "FAIL":
            hard = 1
        print(f"  {level:4} {text}")
    k_level, k_text = keys_line(os.environ)
    if k_level == "FAIL":
        hard = 1
    print(f"  {k_level:4} {k_text}")

    print("-- project")
    proj_findings = deny_rule_findings(dest) + gitignore_findings(dest) + misfiled_findings(dest)
    if proj_findings:
        for level, text in proj_findings:
            if level == "FAIL":
                hard = 1
            print(f"  {level:4} {text}")
    else:
        print("  OK   deny rules, gitignore entries and document folders clean")

    print("-- rules integrity")
    findings = rules_findings(dest)
    if findings:
        hard = 1
        for f in findings:
            print(f"  FAIL {f}")
    else:
        root = dest / "AGENTS.md"
        print(f"  OK   root AGENTS.md {'present' if root.is_file() else 'ABSENT (not migrated yet?)'}; shims are shims")

    if has_document_frontmatter_rule(dest):
        print("  OK   AGENTS.md carries the document-header rule")
    else:
        print("  WARN AGENTS.md carries the document-header rule: missing Document frontmatter section with type:")

    print("-- maintenance signals (deterministic — read-only)")
    sig = maintenance_signals(dest)
    if sig:
        for s in sig:
            print(f"  ~ {s}")
    else:
        print("  none")

    errors = hook_errors(dest)
    if errors:
        print(f"  WARN hook errors (7 days): {errors}")
    else:
        print("  OK   hook errors (7 days): 0")

    print("-- install registry")
    reg = _user_scope_path("installs.json")
    if reg.is_file():
        try:
            installs = json.loads(reg.read_text(encoding="utf-8")).get("installs", [])
            vers = {e.get("version") for e in installs}
            print(f"  {len(installs)} install(s); versions: {sorted(v for v in vers if v)}"
                  + ("  ⚠ skew" if len([v for v in vers if v]) > 1 else ""))
        except Exception:
            print("  (registry unreadable)")
    else:
        print("  no installs recorded")

    _stamp_last_doctor()
    print(f"\n{'FAIL — fix the above.' if hard else 'OK.'}")
    return hard


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="caddis health + maintenance report (read-only).")
    ap.add_argument("--dest", default=".", help="Project dir whose rules to check (default: cwd).")
    ap.add_argument("--quiet", action="store_true", help="Print only the one-line maintenance nudge (SessionStart).")
    args = ap.parse_args(argv)
    return run(Path(args.dest).resolve(), args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
