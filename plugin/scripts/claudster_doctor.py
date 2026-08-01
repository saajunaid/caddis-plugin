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
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Probed contract versions (docs/analysis/*-contract.md). WARN when the installed binary drifts past
# these — the recorded schemas may be stale and want a re-probe.
PROBED_VERSIONS = {"codex": "0.137", "agy": "1.1.5"}
AGENTS_MD_BUDGET = 200  # always-loaded rules file line budget (mirrors check_doc_coverage)

# Per-repo artifact dir + env prefix, mirrored from claude-harness/scripts/claudster_config.py —
# the doctor is a standalone, import-free diagnostic that must run from a bare checkout.
ARTIFACT_DIRS = (".caddis",)
ENV_PREFIX = "CADDIS"


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
        signals.append(f"{days} days since last caddis doctor — run caddis-init --doctor")
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


# ── report ───────────────────────────────────────────────────────────────────
def run(dest: Path, quiet: bool) -> int:
    if quiet:  # SessionStart mode: only the nudge, never non-zero
        line = nudge_line(dest)
        if line:
            print(line)
        return 0

    hard = 0
    print(f"=== caddis doctor — {dest} ===")
    print(f"python: {sys.version.split()[0]}  ({sys.executable})")
    for name in ("codex", "agy", "claude"):
        path = _which(name)
        if path:
            ver = _binary_version(path) or "?"
            print(f"  {name:7} OK   {ver}   [{path}]")
        else:
            print(f"  {name:7} not found on PATH (install, or open a new terminal so PATH refreshes)")

    print("-- rules integrity")
    findings = rules_findings(dest)
    if findings:
        hard = 1
        for f in findings:
            print(f"  FAIL {f}")
    else:
        root = dest / "AGENTS.md"
        print(f"  OK   root AGENTS.md {'present' if root.is_file() else 'ABSENT (not migrated yet?)'}; shims are shims")

    print("-- maintenance signals (deterministic — read-only)")
    sig = maintenance_signals(dest)
    if sig:
        for s in sig:
            print(f"  ~ {s}")
    else:
        print("  none")

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
