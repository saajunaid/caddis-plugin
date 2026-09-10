"""claudster_migrate_rules — migrate a repo's rules hierarchy to AGENTS.md-canonical + CLAUDE.md shims.

`AGENTS.md` is the canonical rules file every agent reads (Claude Code, Codex CLI, Antigravity); each
`CLAUDE.md` becomes a thin `@AGENTS.md` import shim. This tool migrates an existing repo — root pair +
every subfolder `CLAUDE.md` — to that layout, safely and idempotently.

Behavior (per target repo):
  • ROOT: CLAUDE.md's (fuller, possibly enriched) content becomes the canonical AGENTS.md, re-headed
    agent-neutrally; CLAUDE.md becomes the shim. An existing AGENTS.md that is the old caddis mirror
    (a subset of CLAUDE.md) is replaced. If the existing AGENTS.md carries content CLAUDE.md LACKS
    (project enrichments on both sides), it is a CONFLICT — the root pair is skipped and reported
    (exit 1); a human resolves the few by hand-merge, then re-runs to confirm.
  • SUBFOLDERS: each <dir>/CLAUDE.md is `git mv`'d to <dir>/AGENTS.md (content verbatim) + a <dir>/CLAUDE.md shim.
  • Idempotent (a re-run is a no-op); refuses a dirty tree (unless --allow-dirty); `--dry-run` is the
    default (`--apply` executes); `git mv` when tracked; never touches archived `done/`-style files.
  • --check (fork detector): flags any CLAUDE.md that is NOT a shim beside an AGENTS.md (drifted shim),
    and any bare CLAUDE.md with no sibling AGENTS.md (a hand-created fork). Exit 1 on findings.

Usage:
    python scripts/claudster_migrate_rules.py [target]              # dry-run (default)
    python scripts/claudster_migrate_rules.py [target] --apply      # execute
    python scripts/claudster_migrate_rules.py [target] --check      # fork detector (gate)
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Reuse the harness templates + folder shim so the migration output matches what the generator emits.
try:
    from setup_project_ai import HARNESS_DIR, SUBFOLDER_SHIM, render as _render
except Exception:  # pragma: no cover — standalone fallback if setup_project_ai isn't importable
    HARNESS_DIR = None
    SUBFOLDER_SHIM = ("# Folder conventions — canonical in AGENTS.md (imported below; Claude Code inlines it)\n"
                      "@AGENTS.md\n")

    def _render(text, mapping):  # type: ignore
        for k, v in mapping.items():
            text = text.replace("{{" + k + "}}", v)
        return text

# Directories we never migrate into (vendored/generated + archived rules).
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".mypy_cache", ".ruff_cache",
             ".pytest_cache", "dist", "build", ".tanstack", "done", "archive", "archived"}

# Section headings whose bodies are pure template boilerplate — their wording differs between the old
# root.md.tmpl and agents.md.tmpl, so they are excluded from the divergence check (only PROJECT content
# is compared). "What this project is" is intentionally NOT here — its content IS compared.
_BOILERPLATE_HEADING_KEYS = (
    "the laws", "the harness", "development harness", "context discipline", "conventions",
    "where things live", "doc discipline", "resuming a session", "resources", "why subagents",
)

_CANONICAL_PREAMBLE = (
    "> **This is the canonical rules file.** Every coding agent reads it — Claude Code (via the one-line\n"
    "> `@AGENTS.md` import in `CLAUDE.md`), OpenAI Codex CLI, and Antigravity (`agy`). `CLAUDE.md` is a\n"
    "> thin `@AGENTS.md` import shim; keep durable project rules HERE, never in the shim."
)


# ── git helpers ──────────────────────────────────────────────────────────────
def _git(target: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=str(target), capture_output=True, text=True)


def _in_git_repo(target: Path) -> bool:
    r = _git(target, "rev-parse", "--is-inside-work-tree")
    return r.returncode == 0 and r.stdout.strip() == "true"


def _is_dirty(target: Path) -> bool:
    return bool(_git(target, "status", "--porcelain").stdout.strip())


def _is_tracked(target: Path, rel: str) -> bool:
    return bool(_git(target, "ls-files", "--error-unmatch", rel).returncode == 0)


# ── content helpers ──────────────────────────────────────────────────────────
def is_shim(text: str) -> bool:
    """A CLAUDE.md is a shim iff it carries a bare `@AGENTS.md` import line."""
    return any(ln.strip() == "@AGENTS.md" for ln in text.splitlines())


def _project_name(claude_text: str, target: Path) -> str:
    for ln in claude_text.splitlines():
        if ln.startswith("# "):
            title = ln[2:].strip()
            # "<name> — Project Memory (root)" -> "<name>"
            for sep in (" — ", " - ", " –– "):
                if sep in title:
                    return title.split(sep, 1)[0].strip()
            return title
    return target.name


def _meaningful(text: str) -> set[str]:
    """Normalized set of content lines (md markers/whitespace stripped), for subset comparison."""
    out: set[str] = set()
    for ln in text.splitlines():
        s = ln.strip().lstrip("#>-*").strip()
        # drop an ordered-list prefix like "1. "
        while s[:1].isdigit():
            s = s[1:]
        s = s.lstrip(". ").strip()
        if len(s) >= 8:
            out.add(s.lower())
    return out


def _checkable_lines(agents_text: str) -> set[str]:
    """AGENTS.md's PROJECT content — meaningful lines from non-boilerplate-heading sections (and the
    preamble is dropped). Compared against CLAUDE.md to detect divergence."""
    lines = agents_text.splitlines()
    # find section spans by "## " headings
    heads = [i for i, l in enumerate(lines) if l.startswith("## ")]
    out: set[str] = set()
    for k, start in enumerate(heads):
        heading = lines[start][3:].strip().lower()
        if any(key in heading for key in _BOILERPLATE_HEADING_KEYS):
            continue
        end = heads[k + 1] if k + 1 < len(heads) else len(lines)
        out |= _meaningful("\n".join(lines[start:end]))
    return out


def root_conflict(claude_text: str, agents_text: str) -> list[str]:
    """Return AGENTS.md project lines that CLAUDE.md lacks (the enrichment residue). Non-empty => the
    two files diverged and must not be auto-merged."""
    residue = _checkable_lines(agents_text) - _meaningful(claude_text)
    return sorted(residue)


def reheaded_agents(claude_text: str, name: str) -> str:
    """Canonical AGENTS.md from CLAUDE.md content: replace the shim/mirror preamble (everything before
    the first `## ` heading) with a canonical header + preamble; keep the body (enrichments) verbatim."""
    lines = claude_text.splitlines()
    idx = next((i for i, l in enumerate(lines) if l.startswith("## ")), None)
    body = "\n".join(lines[idx:]) if idx is not None else claude_text
    header = f"# {name} — Project Memory (canonical rules)\n\n{_CANONICAL_PREAMBLE}\n\n"
    text = header + body
    return text if text.endswith("\n") else text + "\n"


def root_shim(name: str) -> str:
    """The root CLAUDE.md shim — the harness root.md.tmpl rendered (reused, so no drift)."""
    if HARNESS_DIR is not None:
        tmpl = HARNESS_DIR / "claude-md" / "root.md.tmpl"
        if tmpl.is_file():
            return _render(tmpl.read_text(encoding="utf-8"), {"PROJECT_NAME": name})
    return (f"# {name} — Project Memory\n\n@AGENTS.md\n\n"
            "> **Canonical rules live in `AGENTS.md`** (imported above — Claude Code inlines it). This\n"
            "> shim adds only Claude-native conveniences; durable rules go in `AGENTS.md`.\n")


# ── migration steps ──────────────────────────────────────────────────────────
def _write(target: Path, rel: str, content: str, apply: bool, report: list[str], verb: str):
    report.append(f"{verb}: {rel}")
    if apply:
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")


def _move(target: Path, src_rel: str, dst_rel: str, apply: bool, report: list[str]):
    report.append(f"move: {src_rel} -> {dst_rel}")
    if not apply:
        return
    if _is_tracked(target, src_rel):
        r = _git(target, "mv", src_rel, dst_rel)
        if r.returncode == 0:
            return
    # untracked (or git mv failed): plain rename
    (target / dst_rel).parent.mkdir(parents=True, exist_ok=True)
    os.replace(target / src_rel, target / dst_rel)


def migrate_root(target: Path, apply: bool, report: list[str]) -> int:
    """Migrate the root pair. Returns 1 on conflict (root skipped), else 0."""
    claude = target / "CLAUDE.md"
    agents = target / "AGENTS.md"
    if not claude.exists() and not agents.exists():
        report.append("root: no CLAUDE.md/AGENTS.md — nothing to migrate")
        return 0
    claude_text = claude.read_text(encoding="utf-8") if claude.exists() else ""
    if claude.exists() and is_shim(claude_text) and agents.exists():
        report.append("root: already migrated (CLAUDE.md is a shim) — no-op")
        return 0
    if not claude.exists():
        report.append("root: AGENTS.md present, no CLAUDE.md — leaving as-is (already canonical or hand-authored)")
        return 0
    name = _project_name(claude_text, target)
    if agents.exists():
        conflict = root_conflict(claude_text, agents.read_text(encoding="utf-8"))
        if conflict:
            report.append("root: CONFLICT — AGENTS.md carries content CLAUDE.md lacks; skipping root pair. "
                          "Hand-merge into CLAUDE.md, then re-run. Divergent line(s): "
                          + "; ".join(conflict[:5]) + (" …" if len(conflict) > 5 else ""))
            return 1
    # safe: CLAUDE.md content -> canonical AGENTS.md; CLAUDE.md -> shim
    _write(target, "AGENTS.md", reheaded_agents(claude_text, name), apply, report,
           "rewrite (canonical)" if agents.exists() else "create (canonical)")
    _write(target, "CLAUDE.md", root_shim(name), apply, report, "shim")
    return 0


def _iter_subfolder_claude(target: Path):
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        d = Path(dirpath)
        if d == target:
            continue  # root handled separately
        if "CLAUDE.md" in filenames:
            yield d


def migrate_subfolders(target: Path, apply: bool, report: list[str]) -> None:
    for d in _iter_subfolder_claude(target):
        rel = d.relative_to(target).as_posix()
        claude_text = (d / "CLAUDE.md").read_text(encoding="utf-8")
        if is_shim(claude_text) and (d / "AGENTS.md").exists():
            report.append(f"{rel}/: already migrated — no-op")
            continue
        if (d / "AGENTS.md").exists():
            report.append(f"{rel}/: CONFLICT — both AGENTS.md and a non-shim CLAUDE.md present; skipped")
            continue
        _move(target, f"{rel}/CLAUDE.md", f"{rel}/AGENTS.md", apply, report)
        _write(target, f"{rel}/CLAUDE.md", SUBFOLDER_SHIM, apply, report, "shim")


def check_forks(target: Path) -> list[str]:
    """Fork detector: non-shim CLAUDE.md beside an AGENTS.md, or a bare CLAUDE.md with no sibling AGENTS.md."""
    findings: list[str] = []
    for dirpath, dirnames, filenames in os.walk(target):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if "CLAUDE.md" not in filenames:
            continue
        d = Path(dirpath)
        rel = (d / "CLAUDE.md").relative_to(target).as_posix()
        text = (d / "CLAUDE.md").read_text(encoding="utf-8", errors="replace")
        if "AGENTS.md" in filenames:
            if not is_shim(text):
                findings.append(f"{rel}: CLAUDE.md is not a shim but a sibling AGENTS.md exists (drifted shim)")
        else:
            findings.append(f"{rel}: CLAUDE.md has no sibling AGENTS.md (hand-created fork — run /caddis:add-rules semantics)")
    return findings


# ── main ─────────────────────────────────────────────────────────────────────
def main(argv: list[str] | None = None) -> int:
    for _stream in (sys.stdout, sys.stderr):  # Windows cp1252 can't encode em-dashes in our messages
        if hasattr(_stream, "reconfigure"):
            _stream.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="Migrate a repo to AGENTS.md-canonical rules + CLAUDE.md shims.")
    ap.add_argument("target", nargs="?", default=".", type=Path)
    ap.add_argument("--apply", action="store_true", help="Execute (default is --dry-run).")
    ap.add_argument("--allow-dirty", action="store_true", help="Proceed even if the working tree is dirty.")
    ap.add_argument("--check", action="store_true", help="Fork detector only (gate mode); exit 1 on findings.")
    args = ap.parse_args(argv)

    target = args.target.resolve()
    if not target.is_dir():
        print(f"ERROR: target not a directory: {target}", file=sys.stderr)
        return 2

    if args.check:
        findings = check_forks(target)
        for f in findings:
            print(f"  fork: {f}")
        if findings:
            print(f"\n{len(findings)} rules-file fork(s) found.")
            return 1
        print("No rules-file forks — CLAUDE.md shims are clean.")
        return 0

    apply = args.apply
    if not _in_git_repo(target):
        print(f"ERROR: {target} is not a git repository (rules migration uses git mv).", file=sys.stderr)
        return 2
    if apply and _is_dirty(target) and not args.allow_dirty:
        print("ERROR: working tree is dirty — commit/stash first, or pass --allow-dirty.", file=sys.stderr)
        return 2

    print(f"=== caddis-migrate-rules -> {target} {'(APPLY)' if apply else '(dry-run)'}")
    report: list[str] = []
    rc = migrate_root(target, apply, report)
    migrate_subfolders(target, apply, report)
    for line in report:
        print(f"   {line}")
    if not apply:
        print("\n(dry-run — no files changed; pass --apply to execute)")
    print(f"\nresult: {'CONFLICT (root skipped)' if rc else 'ok'}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
