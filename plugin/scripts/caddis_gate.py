#!/usr/bin/env python3
"""Machine-enforced gates for the caddis implement loop.

WHY
---
Most of caddis's guarantees are sentences in markdown that a model may or may not honour
(measured: 7.0% machine-enforced at the time this landed — `scripts/enforcement_inventory.py`).
The three gates below are the ones that have actually bitten, so they become exit codes:

  lane-check      the assigned execution lane was never read, so a "cheap" lane ran nothing
  verdict-gate    an Advisory-Hub verdict from a DIFFERENT plan could unlock the next phase,
                  and a batched verdict (`phase-10-11`) falsely blocked the phase after it
  tracker-vs-git  a stray staged edit reverted four completed Tracker rows to "not started"
                  and it was caught two milestones later

DEGRADE OPEN, ALWAYS
--------------------
Every failure to *evaluate* is exit 0 with a note on stderr. A missing plan, an unparseable
Tracker, no git — none of those are gate failures, they are "this gate could not run". A gate
that hard-fails when it cannot read its inputs breaks every consumer the day it ships, and the
first thing anyone does with a gate that cries wolf is switch it off. Only a genuine, positively
identified violation is non-zero.

EXIT CODES
  0  proceed
  1  blocked           — a real violation; the caller must stop
  2  proceed-with-note — degraded/uncertain; caller proceeds but must record it
  3  wrong-lane        — this phase belongs to another lane; the launch command is on stdout
  4  malformed         — the phase's launch command cannot be spawned safely
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

EXIT_OK, EXIT_BLOCKED, EXIT_NOTE, EXIT_WRONG_LANE, EXIT_MALFORMED = 0, 1, 2, 3, 4

_TRUTHY = {"1", "true", "yes", "on"}


def _degrade(msg: str) -> int:
    """Could not evaluate. Never a failure — see DEGRADE OPEN above."""
    sys.stderr.write(f"[caddis-gate] cannot evaluate: {msg} — proceeding\n")
    return EXIT_OK


def is_headless(env=None) -> bool:
    e = env if env is not None else os.environ
    if str(e.get("CADDIS_HEADLESS", "")).strip().lower() in _TRUTHY:
        return True
    return bool(e.get("DOCKET_PLAN") or e.get("DOCKET_BRANCH"))


# ── plan parsing ────────────────────────────────────────────────────────────

_PHASE_HEAD = re.compile(r"^###\s+Phase\s+(\d+)\b", re.M)


def phase_block(plan_text: str, phase: int) -> str:
    """The text of one phase, from its heading to the next."""
    starts = [(int(m.group(1)), m.start()) for m in _PHASE_HEAD.finditer(plan_text)]
    for i, (num, pos) in enumerate(starts):
        if num == phase:
            end = starts[i + 1][1] if i + 1 < len(starts) else len(plan_text)
            return plan_text[pos:end]
    return ""


def phase_lane(block: str) -> str:
    m = re.search(r"^\*\*Lane:\*\*\s*(.+)$", block, re.M)
    if not m:
        return ""
    # "claude — this session | glm-headless — `cmd`" → the lane is the first token.
    return m.group(1).strip().split()[0].strip("`*")


def launch_command(block: str) -> str:
    """The literal command for a non-claude lane, if the phase names one."""
    m = re.search(r"`(claude-(?:glm|oss|deepseek)[^`]*)`", block)
    return m.group(1).strip() if m else ""


# ── gate: lane-check ────────────────────────────────────────────────────────

def gate_lane(plan: Path, phase: int) -> int:
    if not plan.is_file():
        return _degrade(f"no plan at {plan}")
    block = phase_block(plan.read_text(encoding="utf-8", errors="ignore"), phase)
    if not block:
        return _degrade(f"phase {phase} not found in {plan.name}")
    lane = phase_lane(block)
    if not lane:
        return _degrade(f"phase {phase} names no Lane:")

    # The asymmetric rule, and the reason this gate is machine-checkable at all: we cannot prove
    # which model we are, but we CAN prove whether someone placed us. A headless/runner session
    # was placed deliberately; an interactive one was not.
    if lane.startswith("claude") or is_headless():
        return EXIT_OK

    cmd = launch_command(block)
    if not cmd:
        sys.stderr.write(f"[caddis-gate] phase {phase} is lane '{lane}' but names no launch command\n")
        return EXIT_MALFORMED
    if not re.search(r"(?:^|\s)(?:-p|--print)(?:\s|$)", cmd):
        sys.stderr.write(
            f"[caddis-gate] phase {phase}'s launch command has no -p/--print: {cmd}\n"
            "  Without it the child is not marked headless, reads the same Lane line, and spawns\n"
            "  again — unbounded recursion. Refusing to run it.\n")
        return EXIT_MALFORMED
    print(cmd)
    sys.stderr.write(f"[caddis-gate] phase {phase} belongs to lane '{lane}' — spawn the command above\n")
    return EXIT_WRONG_LANE


# ── gate: verdict-gate ──────────────────────────────────────────────────────

def _frontmatter(p: Path) -> dict:
    t = p.read_text(encoding="utf-8", errors="ignore")
    if not t.startswith("---"):
        return {}
    end = t.find("\n---", 3)
    out = {}
    for line in t[3:end if end > 0 else 400].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def _covers(phase_field: str, n: int) -> bool:
    s = str(phase_field).strip()
    m = re.fullmatch(r"(\d+)\s*-\s*(\d+)", s)
    if m:
        return int(m.group(1)) <= n <= int(m.group(2))
    return s.isdigit() and int(s) == n


def _hub_context_for(plan: Path) -> Path | None:
    """The advisory-context doc guarding this plan, or None if Hub mode is off.

    Primary: the documented `<plan-stem>-advisory-context.md`.

    Fallback by IDENTITY, and it is load-bearing: a real plan was renamed
    `genesys-rebuild.md` -> `genesys-rebuild-ui-revamp.md` and its context doc kept the old stem.
    The filename convention therefore stopped matching, Advisory-Hub mode silently switched OFF
    for every subsequent run, and nobody noticed because the Hub kept being driven by hand — 31
    artifacts were written while the gate meant to enforce them was dark. Both files still carry
    `feature: genesys-rebuild-ui-revamp`, so identity survives a rename where a filename does not.

    Requires an explicit matching `feature:` on BOTH sides, so it cannot switch Hub mode on for a
    plan that never opted in — "no file -> zero behaviour change" still holds.
    """
    exact = plan.with_name(plan.stem + "-advisory-context.md")
    if exact.is_file():
        return exact
    mine = _frontmatter(plan).get("feature", "").strip()
    if not mine:
        return None
    for cand in sorted(plan.parent.glob("*-advisory-context.md")):
        if _frontmatter(cand).get("feature", "").strip() == mine:
            sys.stderr.write(
                "[caddis-gate] Hub context matched by feature slug, not filename: "
                f"{cand.name} (expected {exact.name} - a rename left the convention broken)\n")
            return cand
    return None


def gate_verdict(plan: Path, phase: int, reports: Path | None = None) -> int:
    if phase <= 1:
        return EXIT_OK  # no predecessor
    if not _hub_context_for(plan):
        return EXIT_OK  # Advisory-Hub mode is OFF — the normal case, zero behaviour change
    d = reports or (plan.parent.parent / "advisory-hub-reports")
    if not d.is_dir():
        sys.stderr.write(f"[caddis-gate] hub mode ON but no {d} — phase {phase-1} unvalidated\n")
        return EXIT_BLOCKED

    want = phase - 1
    slug, path_s = plan.stem, str(plan).replace("\\", "/")
    for f in sorted(d.glob("*.verdict.md")):
        fm = _frontmatter(f)
        if not _covers(fm.get("phase", ""), want):
            continue
        ident = fm.get("plan") or fm.get("feature") or ""
        # Accept either spelling: both are in live fleet use and neither is wrong.
        if ident and not (slug in ident or ident.replace("\\", "/") in path_s or ident == slug):
            continue
        v = fm.get("verdict", "")
        if v in ("accept", "accept-with-correction"):
            return EXIT_OK
        if v == "accept-degraded":
            sys.stderr.write(f"[caddis-gate] {f.name} is accept-degraded — validated WITHOUT an "
                             "advisory context; record that you proceeded on it\n")
            return EXIT_NOTE
        sys.stderr.write(f"[caddis-gate] {f.name} is '{v}' — phase {want} must be redone\n")
        return EXIT_BLOCKED
    sys.stderr.write(f"[caddis-gate] no verdict covering phase {want} for plan '{slug}'\n")
    return EXIT_BLOCKED


# ── gate: tracker-vs-git ────────────────────────────────────────────────────

_ROW = re.compile(r"^\|\s*(\d+(?:-\d+)?)\s*\|(.*)$", re.M)


def gate_tracker(plan: Path, cwd: Path | None = None) -> int:
    if not plan.is_file():
        return _degrade(f"no plan at {plan}")
    text = plan.read_text(encoding="utf-8", errors="ignore")
    if "## Tracker" not in text:
        return _degrade("plan has no ## Tracker")
    tracker = text.split("## Tracker", 1)[1]

    problems: list[str] = []
    for m in _ROW.finditer(tracker):
        cells = [c.strip() for c in m.group(2).split("|")]
        if len(cells) < 4:
            continue
        status, commit = cells[2].lower(), cells[3].strip("`* ")
        done = "done" in status or "✅" in status
        has_commit = commit not in ("", "—", "-", "–")
        if done and not has_commit:
            problems.append(f"phase {m.group(1)} is '{cells[2]}' with no commit recorded")
    if not problems:
        return EXIT_OK
    for p in problems:
        sys.stderr.write(f"[caddis-gate] tracker/git mismatch: {p}\n")
    sys.stderr.write("  A done row with no commit means the Tracker and the repo disagree. Four rows\n"
                     "  were once reverted by a stray staged edit and caught two milestones later.\n")
    return EXIT_NOTE



# ── gate: hub-artifacts ─────────────────────────────────────────────────────

def gate_hub_artifacts(reports: Path, extra_refs: list[Path] | None = None) -> int:
    """An artifact that exists on disk but is referenced nowhere the next Hub will look.

    `/spawn-hub` already conserves LEDGER IDS mechanically and fails the spawn when one vanishes.
    There was no equivalent for the artifacts the Hub itself writes, so the failure mode was exactly
    inverted: the ledger check catches an id that DISAPPEARED; nothing caught a file that EXISTS and
    is invisible.

    Observed 2026-08-05: a Hub wrote `phase-15-16.prompt.md` and `phase-17.prompt.md`, and its spawn
    prompt named only the first. The spawn passed cleanly - ids conserved, every context question
    answered, plan drift caught. Nothing failed because nothing was looking. The successor would have
    found no prompt for Phase 17, written a fresh one, and silently lost the single load-bearing
    paragraph explaining why that phase must run from a cold process - the whole reason it was split
    out of its batch. A regenerated prompt would have looked complete.

    Degrades open like every gate here: no directory, no artifacts, nothing readable -> exit 0.
    """
    if not reports.is_dir():
        return _degrade(f"no reports dir at {reports}")
    # PROMPTS ONLY, and deliberately so. A successor Hub regenerates a phase PROMPT it does not
    # know about - that is the documented near-miss. It does not regenerate reports (the
    # implementer writes those) or verdicts (it writes those after the fact, per phase). Checking
    # all three flagged 11 of 37 artifacts in one live repo and 25 of 37 in another, which is a
    # gate nobody keeps switched on. Narrow to the file class that can actually be clobbered.
    artifacts = sorted(reports.glob("phase-*.prompt.md"))
    if not artifacts:
        return _degrade(f"no phase artifacts in {reports}")

    # Everywhere a successor Hub is told to look: the dir's own index/rules, the most recent
    # spawn docs, and any relay handed over. Read them all as one corpus.
    # This gate is about HANDOVER conservation. With no spawn doc, no handover has happened,
    # so there is no successor and nothing can be orphaned from one. Flagging every prompt in a
    # single-Hub repo would be pure noise: one live repo with 8 prompts and zero handovers was
    # reporting all 8 until this check was added.
    if not any(reports.glob("hub-*.spawn.md")):
        return _degrade(f"no handover has occurred in {reports.name} (no spawn doc)")

    ref_files: list[Path] = []
    for pat in ("README.md", "AGENTS.md", "hub-*.spawn.md"):
        ref_files += sorted(reports.glob(pat))
    for extra in (extra_refs or []):
        if extra.is_file():
            ref_files.append(extra)
    corpus = ""
    for f in ref_files:
        try:
            corpus += f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
    if not corpus:
        return _degrade(f"nothing references artifacts in {reports} (no index, no spawn doc)")

    orphans = [f.name for f in artifacts if f.name not in corpus and f.stem not in corpus]
    if not orphans:
        return EXIT_OK
    sys.stderr.write(
        f"[caddis-gate] {len(orphans)} Hub artifact(s) exist on disk but are referenced nowhere "
        "the next Hub will look:\n")
    for o in orphans:
        sys.stderr.write(f"    {o}\n")
    sys.stderr.write(
        "  A successor will not know these exist, will regenerate them, and will lose whatever\n"
        "  reasoning they carried. Reference them in the spawn doc or the index before handing over.\n")
    return EXIT_BLOCKED


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="caddis machine gates")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("lane-check", "verdict-gate"):
        s = sub.add_parser(name)
        s.add_argument("--plan", required=True)
        s.add_argument("--phase", type=int, required=True)
    t = sub.add_parser("tracker-vs-git")
    t.add_argument("--plan", required=True)
    h = sub.add_parser("hub-artifacts")
    h.add_argument("--reports", required=True)
    h.add_argument("--refs", nargs="*", default=[])
    a = ap.parse_args(argv)

    plan = Path(getattr(a, "plan", "") or ".")
    try:
        if a.cmd == "lane-check":
            return gate_lane(plan, a.phase)
        if a.cmd == "verdict-gate":
            return gate_verdict(plan, a.phase)
        if a.cmd == "hub-artifacts":
            return gate_hub_artifacts(Path(a.reports), [Path(r) for r in a.refs])
        return gate_tracker(plan)
    except Exception as exc:  # pragma: no cover — a gate must never crash the caller
        return _degrade(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
