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

    # A spawn prompt that never names the resume doc produces a Hub that keeps no tracker.
    #
    # Measured: a spawned Hub read relay.md, passed a thirteen-question context check, found four
    # real defects in its handover — and created no tracker, because nothing asked it to. The work
    # survived only because the OUTGOING Hub had written one into relay.md an hour earlier, unasked.
    #
    # The parking-lot note suggested checking that relay.md was "modified in the same commit range".
    # That cannot work: relay.md is GITIGNORED by design, so git never sees it. What is checkable is
    # the instruction — does the spawn prompt tell its successor to keep the tracker at all?
    # ONLY the newest spawn doc, by hub number. Older ones are immutable history: a spawn prompt
    # that was already used cannot be fixed, only falsified, and a gate that stays red on a record
    # nobody may edit is the "always red, therefore ignored" failure this file keeps warning about.
    spawns = sorted(reports.glob("hub-*.spawn.md"),
                    key=lambda p: (int(m.group(1)) if (m := re.search(r"hub-(\d+)", p.name)) else 0,
                                   p.name))
    newest = spawns[-1] if spawns else None
    if newest and "relay" not in newest.read_text(encoding="utf-8", errors="ignore").lower():
        sys.stderr.write(
            f"[caddis-gate] the newest spawn prompt never mentions the resume doc:\n"
            f"    {newest.name}\n")
        sys.stderr.write(
            "  The succession table records WHO HELD THE ROLE; .caddis/relay.md records WHERE THE\n"
            "  WORK IS. The table is only written when a Hub ends, so nothing covers the hours a\n"
            "  Hub spends working — the exact period this mechanism exists to protect. Tell the\n"
            "  incoming Hub to mirror its task list into relay.md as it goes.\n")
        return EXIT_BLOCKED

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


def gate_parking_lot(repo_root: Path) -> int:
    """Every future-work item conforms to the one-register contract, or the push stops.

    caddis had the parking-lot convention for months and it drifted anyway: on 2026-08-14 the
    directory held four different `type:` values (`issue`, `proposal`, `plan`, `parking-lot`), four
    different `status:` spellings, and one 89 KB file that was a second register wearing an item's
    clothes. None of that was caught, because nothing was looking.

    Docs alone were already tried. Parking-lot item 002 is the record of an agent that filed a hub
    artifact in the wrong directory while the correct path sat unread on line 188 of the command it
    skipped. The lesson generalises: a convention nothing can fail is a convention that decays.

    Degrades open like every gate here — no `.caddis/`, no directory, an unreadable file: exit 0.
    Only a positively identified violation blocks.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caddis_tidy
    except Exception as exc:
        return _degrade(f"caddis_tidy unavailable: {type(exc).__name__}")

    d = repo_root / ".caddis" / caddis_tidy.PARKING_LOT_DIR
    if not d.is_dir():
        return _degrade(f"no parking-lot at {d}")
    report = caddis_tidy.tidy(repo_root, apply=False, kinds=(caddis_tidy.PARKING_LOT_DIR,))
    if not report.violations:
        return EXIT_OK
    sys.stderr.write(
        f"[caddis-gate] {len(report.violations)} parking-lot violation(s) — future work must be "
        "one item per file, under one contract:\n")
    for path, msg in report.violations:
        try:
            shown = path.relative_to(repo_root)
        except ValueError:
            shown = path
        sys.stderr.write(f"    {shown}: {msg}\n")
    sys.stderr.write(
        "  Fix them, or run `/caddis:park` to file the item correctly. The contract is in\n"
        "  .caddis/parking-lot/README.md.\n")
    return EXIT_BLOCKED


def gate_vendor_drift(repo_root: Path) -> int:
    """A vendored `.github/tools/*.py` that no longer matches the caddis copy it came from.

    This gate exists because of a FALSE PASS, not a crash. On 2026-08-10 `/caddis:cross-review`
    returned CLEAN on a database write path that was never reviewed. The tool was fixed on
    2026-08-01; the repo was running its own vendored copy from before that, because the command
    resolves `.github/tools/` FIRST and nothing compared the two files.

    The general shape is the dangerous part: a vendored copy makes every caddis fix conditional on
    a file nobody remembers copying. It fails in the safe-looking direction, which is why it went
    unnoticed for nine days.

    Degrades open: no CLAUDE_PLUGIN_ROOT (nothing to compare), no vendored dir, or the caddis
    authoring repo itself -> exit 0.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import claudster_doctor
    except Exception as exc:
        return _degrade(f"claudster_doctor unavailable: {type(exc).__name__}")

    if not os.environ.get("CLAUDE_PLUGIN_ROOT"):
        return _degrade("CLAUDE_PLUGIN_ROOT unset — nothing to compare the vendored copies against")
    drift = claudster_doctor.vendored_drift(repo_root)
    if not drift:
        return EXIT_OK
    sys.stderr.write(
        f"[caddis-gate] {len(drift)} vendored script(s) differ from the caddis copy:\n")
    for line in drift:
        sys.stderr.write(f"    {line}\n")
    sys.stderr.write(
        "  The vendored copy WINS at run time, so a caddis fix you already paid for may never\n"
        "  reach you. Delete the vendored copy to use the shipped one, or diff them and keep the\n"
        "  local change deliberately.\n")
    return EXIT_BLOCKED


# A backticked path in a handover. Placeholders (`<feature>`, `{slug}`, globs) are excluded here
# rather than filtered later, because a gate that reports `\.caddis/plans/<feature>.md` as missing
# teaches the reader to skim its output, and a skimmed gate catches nothing.
_DOC_PATH = re.compile(r"`([^`\s<>{}*?]+?\.(?:md|py|ts|tsx|json|ya?ml|sh|ps1|html|toml|sql))`")


def gate_handover_check(doc: Path, repo_root: Path) -> int:
    """Every file a handover names must exist. Nothing else in a handover is machine-checkable.

    A succession prompt is written from memory, so it names files the writer BELIEVES are there.
    Bringing one Hub to a usable state took nine corrective round trips and the user caught six of
    them; one was "which prompt exists — the legacy one or the contract-shaped one?", which is this
    check exactly (`.caddis/parking-lot/004-handover-is-recalled-not-generated.md`).

    SCOPE, STATED HONESTLY. The parking-lot note asks for four checks. Two are mechanical and are
    implemented here: paths exist, and generated artefacts are not older than their generators. The
    other two — "do the numbers match the live system" and "is a settled claim contradicted by a
    later withdrawal" — need conventions that do not exist yet, and a gate that pretends to check
    them would be worse than one that says it does not.

    Degrades open on a missing/unreadable doc. Blocks only on a path the doc claims and the repo
    does not have.
    """
    if not doc.is_file():
        return _degrade(f"no handover doc at {doc}")
    try:
        text = doc.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return _degrade(f"cannot read {doc}: {type(exc).__name__}")

    missing: list[str] = []
    for raw in sorted(set(_DOC_PATH.findall(text))):
        # A backtick often wraps a whole command; the path is the token that looks like one.
        cand = next((tok for tok in raw.split() if "/" in tok or tok.endswith(".md")), raw)
        cand = cand.strip("(),;:'\"")
        if cand.startswith(("http://", "https://", "~", "$")) or ".." in cand:
            continue
        if not (repo_root / cand).exists():
            missing.append(cand)

    stale: list[dict] = []
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caddis_inventory
        stale = caddis_inventory.stale_artifacts(repo_root)
    except Exception:
        pass  # advisory half — never let it decide the exit code

    for s in stale:
        sys.stderr.write(
            f"[caddis-gate] note: {s['artifact']} was committed before {s['generator']} last "
            "changed — rebuild it before quoting it\n")

    if not missing:
        return EXIT_OK
    sys.stderr.write(
        f"[caddis-gate] the handover names {len(missing)} path(s) that do not exist:\n")
    for m in missing:
        sys.stderr.write(f"    {m}\n")
    sys.stderr.write(
        "  The incoming session cannot know these are wrong — it has no other source for them.\n"
        "  Fix the paths, or generate the inventory with `python scripts/caddis_inventory.py`\n"
        "  instead of writing it from memory.\n")
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
    pl = sub.add_parser("parking-lot")
    pl.add_argument("--repo-root", default=".")
    vd = sub.add_parser("vendor-drift")
    vd.add_argument("--repo-root", default=".")
    hc = sub.add_parser("handover-check")
    hc.add_argument("--doc", required=True)
    hc.add_argument("--repo-root", default=".")
    a = ap.parse_args(argv)

    plan = Path(getattr(a, "plan", "") or ".")
    try:
        if a.cmd == "lane-check":
            return gate_lane(plan, a.phase)
        if a.cmd == "verdict-gate":
            return gate_verdict(plan, a.phase)
        if a.cmd == "hub-artifacts":
            return gate_hub_artifacts(Path(a.reports), [Path(r) for r in a.refs])
        if a.cmd == "parking-lot":
            return gate_parking_lot(Path(a.repo_root).resolve())
        if a.cmd == "vendor-drift":
            return gate_vendor_drift(Path(a.repo_root).resolve())
        if a.cmd == "handover-check":
            return gate_handover_check(Path(a.doc), Path(a.repo_root).resolve())
        return gate_tracker(plan)
    except Exception as exc:  # pragma: no cover — a gate must never crash the caller
        return _degrade(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
