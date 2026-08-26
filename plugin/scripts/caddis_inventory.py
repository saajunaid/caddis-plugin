#!/usr/bin/env python3
"""caddis_inventory — enumerate what EXISTS in a repo, so a handover stops being a memory test.

WHY
---
A succession prompt used to be composed from what the outgoing session remembered to mention.
Anything it forgot, the incoming session never learned — and the incoming session cannot know what
it was not told. Bringing one Hub to a usable state took **nine** corrective round trips, and the
user caught six of the nine (`.caddis/parking-lot/004-handover-is-recalled-not-generated.md`).

Look at what the user caught, because the pattern is the whole argument:

    "the handover listed no reports, documents, KB notes or scripts"
    "planned future work is absent"
    "which prompt exists — the legacy one or the contract-shaped one?"

None of those are judgement calls. Every one is a directory listing. They were missed because the
agent was recalling *what it did* rather than enumerating *what exists*, and those are different
sets. A generator cannot forget the report it never wrote.

WHAT THIS IS NOT
----------------
This does not write the handover. Judgement — what matters, what to do next, what nearly went
wrong — is the outgoing session's job and cannot be derived from disk. This produces the half that
can be, so the human-written half is all judgement and no clerical work.

STALENESS IS MEASURED IN COMMITS, NOT MTIMES
--------------------------------------------
A git checkout stamps every file with the checkout time, so mtimes say nothing about whether a
generated report predates the feature it should describe. Last-commit time does. That exact failure
is item 8 of the nine: reports committed before a feature was added and never rebuilt.

Usage:
  python scripts/caddis_inventory.py                    # markdown to stdout
  python scripts/caddis_inventory.py --format json      # machine-readable
  python scripts/caddis_inventory.py --with-tests       # also RUN the suite (never quote a
                                                        # remembered test count — one handover
                                                        # claimed 20 when there were 19)
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ART = ".caddis"

# Artefact kinds worth enumerating, and what a reader needs from each. Order matters: it is the
# order a reader wants them in, not alphabetical.
PLAN_DIRS = ("plans", "prd", "prompts", "handoffs", "agent-docs")


def _run(args: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=30)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def frontmatter(path: Path) -> dict[str, str]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore").lstrip("﻿")
    except OSError:
        return {}
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    out: dict[str, str] = {}
    for line in text[3:end if end > 0 else 800].splitlines():
        if ":" in line and not line.startswith((" ", "\t")):
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def title_of(path: Path) -> str:
    """First markdown H1, else the filename. What a reader scans for."""
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("# "):
                return line[2:].strip()
    except OSError:
        pass
    return path.stem


@dataclass
class Inventory:
    repo: str = ""
    branch: str = ""
    uncommitted: int = 0
    unpushed: int = 0
    artifacts: dict[str, list[dict]] = field(default_factory=dict)
    parking_lot: list[dict] = field(default_factory=list)
    kb: list[dict] = field(default_factory=list)
    comms_open: list[dict] = field(default_factory=list)
    scripts: list[dict] = field(default_factory=list)
    stale_artifacts: list[dict] = field(default_factory=list)
    environment_map: str = "missing"
    tests: str = "not measured — run the suite, never quote a remembered number"


def scan_artifacts(root: Path) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for kind in PLAN_DIRS:
        d = root / ART / kind
        if not d.is_dir():
            continue
        rows = []
        for f in sorted(d.glob("*.md")):
            if f.name.lower() == "readme.md":
                continue
            fm = frontmatter(f)
            rows.append({"file": f"{ART}/{kind}/{f.name}",
                         "title": title_of(f),
                         "status": fm.get("status", "(none)")})
        done = len(list((d / "done").glob("*.md"))) if (d / "done").is_dir() else 0
        if rows or done:
            out[kind] = rows
            if done:
                out[kind].append({"file": f"{ART}/{kind}/done/", "title": f"{done} finished",
                                  "status": "archived"})
    return out


def scan_parking_lot(root: Path) -> list[dict]:
    """The backlog. Listed separately from plans because a reader's question is different:
    plans ask "what is running?", the parking lot asks "what did we agree to do and have not?"."""
    d = root / ART / "parking-lot"
    if not d.is_dir():
        return []
    rows = []
    for f in sorted(d.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        fm = frontmatter(f)
        rows.append({"file": f.name, "title": title_of(f),
                     "status": fm.get("status", "(none)"),
                     "severity": fm.get("severity", ""),
                     "future": fm.get("future", "")})
    # committed work first, then by severity — the order a reader needs, not the filesystem's
    order = {"high": 0, "medium": 1, "low": 2, "": 3}
    rows.sort(key=lambda r: (r["future"].lower() != "yes", order.get(r["severity"].lower(), 3)))
    return rows


def scan_kb(root: Path) -> list[dict]:
    d = root / ART / "kb"
    if not d.is_dir():
        return []
    return [{"file": f"{ART}/kb/{f.name}", "title": title_of(f)}
            for f in sorted(d.glob("*.md")) if f.name != "DOC-MAP.md"]


def environment_map_state(root: Path) -> str:
    """`missing`, `empty` or `filled` — surfaced because an absent environment map is invisible.

    Every other gap in a handover shows up as a section with nothing under it. This one shows up as
    nothing at all, which reads exactly like "there was nothing to say". One session searched the
    filesystem for a repository that lived in Gitea while the project's own docs cited a file inside
    it by path — the fact existed, it just had no shelf.
    """
    f = root / ART / "kb" / "environment-map.md"
    if not f.is_file():
        return "missing"
    try:
        text = f.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "missing"
    # The scaffolded template is all headings and "(none recorded yet)" placeholders. A file that
    # still carries every placeholder has never been filled in, and saying "present" would be a lie
    # of exactly the kind this whole item is about.
    return "empty" if "_(none recorded yet)_" in text and text.count("|") < 60 else "filled"


def scan_comms(root: Path) -> list[dict]:
    """Rows in the comms register that are not yet ACTIONED or DROPPED — an ask nobody is chasing
    is indistinguishable from a forgotten one, which is the whole reason that register exists."""
    reg = root / ART / "comms" / "register.md"
    if not reg.is_file():
        return []
    out = []
    for line in reg.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.startswith("|") or line.startswith("|---") or "_(none yet)_" in line:
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4 or cells[0].lower() in ("raised", "status"):
            continue
        status = cells[3].strip("`").upper()
        if status in ("DRAFT", "SENT", "ANSWERED"):
            out.append({"raised": cells[0], "audience": cells[1],
                        "subject": cells[2], "status": status})
    return out


def scan_scripts(root: Path) -> list[dict]:
    """Every script and the first line of its docstring. A handover that omits these makes the
    next session re-discover the tooling it already owns."""
    d = root / "scripts"
    if not d.is_dir():
        return []
    out = []
    for f in sorted(d.glob("*.py")):
        first = ""
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            m = re.search(r'^\s*"""(.+?)$', text, re.M)
            if m:
                first = m.group(1).strip().rstrip('"')
        except OSError:
            pass
        out.append({"file": f"scripts/{f.name}", "purpose": first})
    return out


# A path literal, not a bare filename. Requiring a directory separator is what stops a script that
# merely MENTIONS "README.md" in a docstring from being reported as that file's generator — the
# first version of this did exactly that, and a check with obvious false positives gets switched off
# before it ever catches a real one.
_OUTPUT_LITERAL = re.compile(r'["\']((?:[\w.-]+/)+[\w.-]+\.(?:html|json|csv|svg|png|md))["\']')
# Names that are always somebody else's file, never a generated artefact.
_NEVER_GENERATED = {"README.md", "AGENTS.md", "CLAUDE.md", "package.json", "pyproject.toml"}
# A generator often builds its output path from parts (`_HERE.parent / ".caddis" / "page.html"`),
# so the literal in the source is a bare filename. Accept that shape too, but ONLY for artefact
# extensions and ONLY when the file really sits in the artefact dir — a bare `.md` literal is
# almost always prose, which is how the README false positive got in.
_BARE_ARTIFACT = re.compile(r'["\']([\w.-]+\.(?:html|json|csv|svg|png))["\']')


def stale_artifacts(root: Path) -> list[dict]:
    """Generated files whose last commit PREDATES their generator's last commit.

    Pairing needs no new convention to maintain: a generator names the file it writes, so grepping
    each script for a path literal that actually exists on disk finds the pair. A manifest would be
    more precise and would rot the first time nobody updated it.

    Uses git commit times, never mtimes — see the module docstring.
    """
    d = root / "scripts"
    if not d.is_dir() or not (root / ".git").exists():
        return []
    out = []
    for script in sorted(d.glob("*.py")):
        try:
            text = script.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        candidates = set(_OUTPUT_LITERAL.findall(text))
        candidates |= {f"{ART}/{n}" for n in _BARE_ARTIFACT.findall(text)
                       if (root / ART / n).is_file()}
        for m in sorted(candidates):
            if Path(m).name in _NEVER_GENERATED:
                continue
            target = root / m
            if not target.is_file():
                continue
            t_art = _run(["git", "log", "-1", "--format=%ct", "--", m], root)
            t_gen = _run(["git", "log", "-1", "--format=%ct", "--", f"scripts/{script.name}"], root)
            if not t_art or not t_gen:
                continue
            if int(t_art) < int(t_gen):
                out.append({"artifact": m, "generator": f"scripts/{script.name}",
                            "behind_seconds": int(t_gen) - int(t_art)})
    return out


def collect(root: Path, with_tests: bool = False) -> Inventory:
    inv = Inventory(repo=root.name)
    inv.branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], root)
    inv.uncommitted = len([l for l in _run(["git", "status", "--short"], root).splitlines() if l])
    upstream = _run(["git", "rev-parse", "--abbrev-ref", "@{upstream}"], root)
    if upstream:
        inv.unpushed = len(_run(["git", "log", "--oneline", f"{upstream}..HEAD"], root).splitlines())
    inv.artifacts = scan_artifacts(root)
    inv.parking_lot = scan_parking_lot(root)
    inv.kb = scan_kb(root)
    inv.comms_open = scan_comms(root)
    inv.scripts = scan_scripts(root)
    inv.stale_artifacts = stale_artifacts(root)
    inv.environment_map = environment_map_state(root)
    if with_tests:
        # Run it. A handover once claimed 20 tests when there were 19, and the incoming Hub found
        # the discrepancy before anyone else did.
        summary, shown = _run_tests(_test_command(root), root)
        # Name the command. "932 passed" means nothing on its own — a reader who cannot see
        # the command cannot tell a scoped run from a whole-tree one, which is exactly the
        # ambiguity that produced this defect.
        inv.tests = f"{summary}  _(`{shown}`)_"
    return inv



# Generated/vendored trees hold COPIES of the harness. They have no node_modules and no
# import path, so collecting them is never right — it only produces collection errors that
# mask the real result. Excluded by default; `[handover] test_cmd` overrides everything.
_GENERATED_TREES = ("vscode-extensions", "dist", "node_modules", ".venv")

# The suite is the one thing here that is not a directory listing, so it gets its own
# runner rather than `_run`. Three reasons `_run` is wrong for it:
#   * it returns "" on a non-zero exit — and pytest exits non-zero when tests FAIL, so a
#     genuinely red suite became "did not report a summary", indistinguishable from a
#     broken invocation. A red suite MUST report "3 failed".
#   * its 30s timeout is shorter than a real suite. This repo's takes 112s, so
#     `--with-tests` could never have produced a number here whatever else was fixed.
#   * it discards stderr, where pytest writes collection errors.
def _run_tests(cmd: list[str], cwd: Path, timeout: int = 900) -> tuple[str, str]:
    """Return ``(summary_line, command_string)``. Never raises."""
    shown = " ".join(cmd[1:]) if cmd and cmd[0] == sys.executable else " ".join(cmd)
    shown = shown.replace("-m pytest", "pytest", 1)
    try:
        r = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return (f"suite exceeded {timeout}s — not run to completion", shown)
    except Exception as exc:
        return (f"could not run the suite ({type(exc).__name__})", shown)

    blob = (r.stdout or "") + chr(10) + (r.stderr or "")
    # pytest's summary line is the last one naming passed/failed/error.
    tail = [l.strip() for l in blob.splitlines()
            if ("passed" in l or "failed" in l or "error" in l.lower()) and "==" not in l[:2]]
    if tail:
        return (tail[-1], shown)
    return (f"suite did not report a summary (exit {r.returncode}) — investigate", shown)


def _test_command(root: Path) -> list[str]:
    """The repo's test command.

    A repo's test command is a PROJECT FACT, and this used to guess it. Bare `pytest` is a
    guess that is right in a single-package repo and wrong in any repo carrying a vendored
    or generated tree — which describes caddis itself and every consumer that vendors
    anything. Set `[handover] test_cmd` in `.caddis/config.toml` to state it.
    """
    # In the SHIPPED bundle this file and claudster_config.py are co-located under
    # scripts/. In the source repo they are not: this lives in scripts/, that one in
    # claude-harness/scripts/. Try both, or the config is silently never read — which is
    # how the first version of this fix looked like it worked and did not.
    here = Path(__file__).resolve().parent
    configured = ""
    for cand in (here, here.parent / "claude-harness" / "scripts"):
        try:
            if str(cand) not in sys.path:
                sys.path.insert(0, str(cand))
            import claudster_config as _cc  # noqa: E402
            configured = _cc.get_str(_cc.load_config(root, "handover"), "test_cmd", "")
            break
        except Exception:
            continue
    if configured:
        import shlex
        return shlex.split(configured)
    cmd = [sys.executable, "-m", "pytest", "-q", "--tb=no"]
    for name in _GENERATED_TREES:
        if (root / name).exists():
            cmd += ["--ignore", name]
    return cmd


def _table(rows: list[dict], cols: list[tuple[str, str]]) -> list[str]:
    head = "| " + " | ".join(c[0] for c in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = ["| " + " | ".join(str(r.get(c[1], "") or "") for c in cols) + " |" for r in rows]
    return [head, sep, *body, ""]


def render_md(inv: Inventory) -> str:
    L: list[str] = [
        f"# Repository inventory — {inv.repo}", "",
        "> Generated by `scripts/caddis_inventory.py`. **Do not hand-edit.** Everything here is a",
        "> directory listing, not a judgement — regenerate it rather than correcting it. The",
        "> judgement half of a handover (what matters, what nearly went wrong, what to do next) is",
        "> written by a human or an agent and belongs above this section, not inside it.", "",
        f"**Branch** `{inv.branch}` · **uncommitted** {inv.uncommitted} file(s) · "
        f"**unpushed** {inv.unpushed} commit(s)", "",
        f"**Tests:** {inv.tests}", "",
    ]
    if inv.environment_map != "filled":
        why = ("does not exist" if inv.environment_map == "missing"
               else "exists but has never been filled in")
        L += [f"> **Environment map {why}.** Hosts, which login actually works, where other",
              "> repositories really live — none of it is written down, so the next session starts",
              "> from zero and asks you again. Write what you know to",
              f"> `{ART}/kb/environment-map.md` before handing over.", ""]
    if inv.stale_artifacts:
        L += ["## ⚠ Generated artefacts older than their generator", "",
              "Each of these was committed BEFORE the script that builds it last changed, so it may",
              "describe a state that no longer exists. Rebuild before quoting any of them.", ""]
        L += _table(inv.stale_artifacts, [("Artefact", "artifact"), ("Built by", "generator")])
    for kind, rows in inv.artifacts.items():
        if not rows:
            continue
        L += [f"## {kind}", ""] + _table(rows, [("File", "file"), ("Title", "title"),
                                                ("Status", "status")])
    if inv.parking_lot:
        L += ["## Parking lot — the backlog", "",
              "Committed work (`future: yes`) first, then by severity.", ""]
        L += _table(inv.parking_lot, [("Item", "file"), ("Severity", "severity"),
                                      ("Future", "future"), ("Status", "status")])
    if inv.kb:
        L += ["## KB notes", ""] + _table(inv.kb, [("File", "file"), ("Title", "title")])
    if inv.comms_open:
        L += ["## Outbound comms still open", "",
              "Anything not yet ACTIONED or DROPPED. An unanswered ask looks exactly like a",
              "forgotten one unless something tracks it.", ""]
        L += _table(inv.comms_open, [("Raised", "raised"), ("Audience", "audience"),
                                     ("Subject", "subject"), ("Status", "status")])
    if inv.scripts:
        L += ["## Scripts", ""] + _table(inv.scripts, [("Script", "file"), ("Purpose", "purpose")])
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--format", choices=("md", "json"), default="md")
    ap.add_argument("--with-tests", action="store_true",
                    help="RUN the suite and report its real result instead of a placeholder")
    a = ap.parse_args(argv)
    root = Path(a.repo_root).resolve()
    inv = collect(root, with_tests=a.with_tests)
    if a.format == "json":
        print(json.dumps(inv.__dict__, indent=2))
    else:
        print(render_md(inv), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
