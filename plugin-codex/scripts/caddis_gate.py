#!/usr/bin/env python3
"""Machine-enforced gates for the caddis implement loop.

WHY
---
Most of caddis's guarantees are sentences in markdown that a model may or may not honour
(measured: 7.0% machine-enforced at the time this landed — `scripts/enforcement_inventory.py`).
The two gates below are the ones that have actually bitten, so they become exit codes:

  lane-check      the assigned execution lane was never read, so a "cheap" lane ran nothing
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

try:
    import caddis_frontmatter
except ModuleNotFoundError as exc:
    if exc.name != "caddis_frontmatter":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_frontmatter

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
    return str(e.get("CADDIS_HEADLESS", "")).strip().lower() in _TRUTHY


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
    """The literal command for a non-claude lane, if the phase names one.

    Also matches a caddis_lanes.py run command, a direct codex/agy command, and an agy command
    wrapped in the spend cap (`python .../caddis_spend.py run --caller X -- agy ...`).
    """
    m = re.search(
        r'`((?:claude-(?:glm|oss|deepseek)\b|' + _LANES_RUN + r'\b|' + _SPEND_RUN
        + r'\b|codex\s+exec\b|agy\b)[^`]*)`',
        block,
    )
    return m.group(1).strip() if m else ""


_LANES_RUN = r'python\s+"?\$\{CLAUDE_PLUGIN_ROOT\}/scripts/caddis_lanes\.py"?\s+run'
# Every agy lane goes through the global spend cap (caddis-next Phase 4). Any path that ends in
# scripts/caddis_spend.py: `${CLAUDE_PLUGIN_ROOT}/...`, an expanded plugin-cache path (the codex bundle
# rewrites the variable), or the bare repo-relative `scripts/caddis_spend.py` - which gate_lane accepts
# only in the caddis source repo, because in an app repo that path is a file the agent can write.
_SPEND_RUN = r'python3?\s+"?[^"\s`]*scripts/caddis_spend\.py"?\s+run'
_SPEND_PATH = re.compile(r'python3?\s+"?([^"\s`]*scripts/caddis_spend\.py)"?\s+run')
# Shell control characters outside the quoted prompt would chain a second, uncapped command.
_SHELL_CHAIN = re.compile(r"[;&|`\n]|\$\(")


def _caddis_source_root(plan: Path) -> bool:
    """True when the plan lives in the caddis source repo (the only place a repo-relative wrapper is trusted)."""
    for parent in plan.resolve().parents:
        if (parent / ".git").exists():
            return (parent / "claude-harness" / "scripts" / "caddis_governor.py").is_file()
    return False


# ── gate: lane-check ────────────────────────────────────────────────────────

_QUOTED = re.compile(r"\"[^\"]*\"|'[^']*'")


def _has_print_flag(cmd: str) -> bool:
    """True when the command carries a real -p/--print flag.

    The quoted prompt is blanked first: a prompt that merely contains the text " -p " must not
    count, or an interactive child passes the gate (R3 cross-review, 2026-09-30).
    """
    return bool(re.search(r"(?:^|\s)(?:-p|--print)(?:\s|$)", _QUOTED.sub('""', cmd)))


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
    if re.match(r"agy\b", cmd):
        sys.stderr.write(
            f"[caddis-gate] phase {phase}'s agy command is not wrapped in the spend cap: {cmd}\n"
            "  agy lanes must go through caddis_spend.py run --caller <name> -- agy ... Refusing to run it.\n")
        return EXIT_MALFORMED
    inner = cmd
    if re.match(_SPEND_RUN, cmd):
        wrapped = re.match(_SPEND_RUN + r'\s+--caller\s+\S+\s+--\s+(agy\b.*)$', cmd, re.S)
        if not wrapped:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s spend-cap command is malformed: {cmd}\n"
                "  Expected: caddis_spend.py run --caller <name> -- agy ... Refusing to run it.\n")
            return EXIT_MALFORMED
        inner = wrapped.group(1)
        # Command substitution runs even inside double quotes (bash and PowerShell), so `$(` and
        # backticks are refused anywhere; `${` is refused after the `--` (the wrapper path may use it).
        if (_SHELL_CHAIN.search(_QUOTED.sub('""', cmd)) or "$(" in cmd or "`" in cmd
                or "${" in inner):
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s agy command chains another command: {cmd}\n"
                "  A second command after the wrapped agy would run outside the spend cap. Refusing to run it.\n")
            return EXIT_MALFORMED
        formats = re.findall(r"--output-format(?:\s+|=)(\S+)", _QUOTED.sub('""', inner))
        if formats != ["json"]:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s agy command must have exactly one --output-format json: {cmd}\n"
                "  Without JSON output the spend cap cannot read the token counts. Refusing to run it.\n")
            return EXIT_MALFORMED
        path = _SPEND_PATH.match(cmd).group(1)
        norm = path.replace("\\", "/")
        trusted = (norm == "${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spend.py"
                   or ("/plugins/cache/" in norm and (norm.startswith("/") or re.match(r"[A-Za-z]:/", norm)
                                                      or norm.startswith("${HOME}/")))
                   or (norm == "scripts/caddis_spend.py" and _caddis_source_root(plan)))
        if not trusted:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s agy command uses an untrusted caddis_spend.py path: {cmd}\n"
                "  Use \"${CLAUDE_PLUGIN_ROOT}/scripts/caddis_spend.py\" (or the installed plugin-cache path;\n"
                "  the bare scripts/caddis_spend.py only in the caddis source repo). Refusing to run it.\n")
            return EXIT_MALFORMED
    if re.match(_LANES_RUN, cmd):
        named = re.search(r"--phase[\s=]+(\d+)", cmd)
        if not named:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s caddis_lanes command has no --phase N: {cmd}\n"
                "  Without it the lane would run the whole plan. Refusing to run it.\n")
            return EXIT_MALFORMED
        if int(named.group(1)) != phase:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s caddis_lanes command names --phase {named.group(1)}: {cmd}\n"
                "  The lane would run another phase's work. Refusing to run it.\n")
            return EXIT_MALFORMED
    elif re.match(r"(?:codex\s+exec|agy)\b", inner):
        if "HEADLESS RUN RULES" not in inner:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s direct command has no HEADLESS RUN RULES: {cmd}\n"
                "  The child has no headless run rules. Refusing to run it.\n")
            return EXIT_MALFORMED
        named = re.search(r"Implement Phase (\d+) only", inner)
        if not named:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s direct command has no phase restriction: {cmd}\n"
                "  The lane could run the wrong phase. Refusing to run it.\n")
            return EXIT_MALFORMED
        if int(named.group(1)) != phase:
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s direct command names Phase {named.group(1)}: {cmd}\n"
                "  The lane would run another phase's work. Refusing to run it.\n")
            return EXIT_MALFORMED
        if inner.startswith("agy") and not _has_print_flag(inner):
            sys.stderr.write(
                f"[caddis-gate] phase {phase}'s direct agy command has no -p/--print: {cmd}\n"
                "  The child would not run headless. Refusing to run it.\n")
            return EXIT_MALFORMED
    elif not _has_print_flag(cmd):
        sys.stderr.write(
            f"[caddis-gate] phase {phase}'s launch command has no -p/--print: {cmd}\n"
            "  Without it the child is not marked headless, reads the same Lane line, and spawns\n"
            "  again — unbounded recursion. Refusing to run it.\n")
        return EXIT_MALFORMED
    print(cmd)
    sys.stderr.write(f"[caddis-gate] phase {phase} belongs to lane '{lane}' — spawn the command above\n")
    return EXIT_WRONG_LANE


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


def gate_handover_check(doc: Path, repo_root: Path, max_chars: int | None = None) -> int:
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

    Degrades open on a missing/unreadable doc. Blocks on a path the doc claims and the repo does
    not have, and -- only when the caller passes ``max_chars`` -- on a doc longer than that. The
    cap is opt-in: /handoff caps a workstream relay at 4,000 characters, but a /spawn-session
    handover may embed a full inventory verbatim and would not fit.
    """
    if not doc.is_file():
        return _degrade(f"no handover doc at {doc}")
    try:
        text = doc.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return _degrade(f"cannot read {doc}: {type(exc).__name__}")

    if max_chars is not None and len(text) > max_chars:
        sys.stderr.write(
            f"[caddis-gate] handover doc {doc.name} exceeds {max_chars:,} characters ({len(text)} chars)\n"
        )
        return EXIT_BLOCKED

    # `/handoff` Step 3c saves the open tasks beside the relay. A tasks file the resume prompt
    # never names is a task list the next session never reloads.
    tasks_file = doc.with_name(doc.stem + ".tasks.md")
    if tasks_file.is_file() and tasks_file.name not in text:
        sys.stderr.write(f"handover-check: the resume prompt does not load {tasks_file.name}\n")
        return EXIT_BLOCKED

    done_bullets = 0
    in_done = in_fence = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```"):  # a heading or bullet inside a code block is text, not structure
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if stripped.startswith("## Done"):
            in_done = True
            continue
        if in_done:
            if re.match(r"#{1,2} ", stripped):  # the next ## (or #) section ends Done; a ### stays inside it
                in_done = False
                continue
            if line.lstrip().startswith(("- ", "* ")):
                done_bullets += 1
    if done_bullets > 8:
        sys.stderr.write(f"handover-check: Done has {done_bullets} bullets; the cap is 8\n")
        return EXIT_BLOCKED

    missing: list[str] = []
    try:
        # One rule for both gates: `caddis_spawn.check_document` already treats a bare filename
        # that matches no tracked file as a note (probably another repository's file), and one
        # that matches tracked files as a block that names the full path. Two gates giving
        # different answers to the same question is the defect this replaces.
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import caddis_spawn
        findings = caddis_spawn.check_document(text, repo_root)
        missing = sorted(set(findings.missing_paths))
        for name in findings.unresolved_names:
            sys.stderr.write(
                f"[caddis-gate] note: `{name}` is a bare filename that matches no tracked file here; "
                "not checked\n")
    except Exception as exc:
        # Degrade to the plain existence rule, but say why: a bug inside the shared helper must
        # not hide behind the fallback (an ImportError is the expected, quiet case).
        if not isinstance(exc, ImportError):
            sys.stderr.write(
                f"[caddis-gate] note: shared path check failed ({type(exc).__name__}: {exc}); "
                "using the plain existence rule\n")
        missing = []
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


# ── cross-review trigger ────────────────────────────────────────────────────────────────────
# serve-sight shipped FOUR production releases in one day, sixteen fixes across SQL, caches,
# refresh jobs and React. `/caddis:cross-review` ran ZERO times. Not because it was broken:
# `oss_review.py --check-config` reported it ready with two providers keyed. Nothing called it.
#
# Measured there: 4 of 39 plan files mention cross-review, and all four are /feature-plan outputs,
# because that command writes the line into the plan template it emits. So planned feature work
# got reviewed and a bug batch did not — REVIEW COVERAGE INVERSELY CORRELATED WITH URGENCY.
#
# Two of that day's sixteen fixes were diff-visible defects: a cache whose docstring said "cached
# for the instance's life" while a FastAPI dependency rebuilt the object per request, so the cache
# was never once read (5.03s per call, and the docstring described the bug while reading as a
# design note); and two endpoints with no cache at all on a page with a 1s standard.
#
# Every rule below is checkable from `git diff --name-only` plus a line count. NO JUDGEMENT — that
# is the point, because judgement is exactly what failed. Prose in a command would be one more
# thing to remember, and 008 section 2 is this repo's record of a rule that lived only in a
# document and lost to the artefact.
REVIEW_BIG_DIFF_LINES = 400

# (label, why, path-segment needles). Matched against lowercased POSIX path segments and the file
# stem, never a bare substring of the whole path — `services` must be a directory or a filename
# part, so `deprecated_services_notes.md` matches and `microservices-README` in a docs tree does
# not sneak in through a parent directory nobody meant.
REVIEW_TRIGGERS = [
    ("sql", "where a wrong number is born — presence is not correctness",
     ("sql", "queries", "query", "repositories", "repository", "migrations", "migration")),
    ("services", "the layer the 2026-08-31 cache defects lived in, with no SQL in the diff",
     ("services", "service")),
    ("caching", "hit twice in one day at serve-sight",
     ("cache", "caches", "caching", "refresh", "memo", "memoize")),
    ("auth", "a mistake here is a breach, not a bug",
     ("auth", "rbac", "permission", "permissions", "role", "roles", "authz", "authn")),
]


def _changed(repo_root: Path, rev_range: str | None) -> tuple[list[str], int]:
    """(paths, changed-line-count) for the working tree, or for an explicit range."""
    args = ["git", "-C", str(repo_root), "diff", "--numstat"]
    if rev_range:
        args.append(rev_range)
    out = subprocess.run(args, capture_output=True, text=True, timeout=30).stdout
    paths, lines = [], 0
    for row in out.splitlines():
        parts = row.split("	")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        paths.append(path.strip())
        for n in (add, dele):
            if n.isdigit():
                lines += int(n)
    return paths, lines


def review_triggers(paths: list[str], changed_lines: int) -> list[tuple[str, str, list[str]]]:
    """[(label, why, matching paths)] — empty means the diff does not warrant a second opinion."""
    fired: list[tuple[str, str, list[str]]] = []
    for label, why, needles in REVIEW_TRIGGERS:
        hits = []
        for p in paths:
            segs = [seg.lower() for seg in p.replace("\\", "/").split("/")]
            stem = segs[-1].rsplit(".", 1)[0] if segs else ""
            parts = set(segs[:-1]) | set(stem.replace("-", "_").split("_")) | {stem}
            # `.sql` belongs to the sql rule ONLY. Left in the shared condition it made every
            # trigger fire on any .sql file, so one migration reported sql+services+caching+auth
            # and the reason column became noise.
            if parts & set(needles) or (label == "sql" and segs[-1].endswith(".sql")):
                hits.append(p)
        if hits:
            fired.append((label, why, sorted(hits)))
    if changed_lines > REVIEW_BIG_DIFF_LINES:
        fired.append(("size", f"{changed_lines} changed lines — size alone stops being reviewable",
                      []))
    return fired


def gate_review_trigger(repo_root: Path, rev_range: str | None = None) -> int:
    """EXIT_NOTE when the diff warrants cross-review, EXIT_OK when it does not.

    NOTE, never BLOCKED. This decides when to ASK for a second opinion; it is not itself a verdict
    and must not stop a ship. The honest limit, from the item that raised it: a trigger does not
    make the review good, it makes it happen — and on the measured evidence that was the binding
    constraint, with a configured, capable tool idle through sixteen chances to use it.
    """
    paths, changed = _changed(repo_root, rev_range)
    if not paths:
        print("[gate] review-trigger: empty diff — nothing to review")
        return EXIT_OK
    fired = review_triggers(paths, changed)
    if not fired:
        print(f"[gate] review-trigger: {len(paths)} file(s), {changed} line(s) — no trigger")
        return EXIT_OK
    print(f"[gate] review-trigger: RUN CROSS-REVIEW — {len(paths)} file(s), {changed} line(s)")
    for label, why, hits in fired:
        shown = ", ".join(hits[:4]) + (", ..." if len(hits) > 4 else "")
        print(f"    {label}: {why}" + (f"{chr(10)}      {shown}" if hits else ""))
    print("    /caddis:cross-review   (or: python .github/tools/oss_review.py)")
    return EXIT_NOTE


TIER_REVIEWERS = {
    "0": 0,
    "1-small": 0,
    "1": 1,
    "2": 2,
}


def is_test_file(path: str) -> bool:
    norm = path.replace("\\", "/").lower()
    if norm.startswith("./"):
        norm = norm[2:]
    segs = norm.split("/")
    filename = segs[-1]
    if any(s in ("tests", "test") for s in segs[:-1]):
        return True
    if filename.startswith("test_") and filename.endswith(".py"):
        return True
    if filename.endswith("_test.py"):
        return True
    for ext in (".test.ts", ".test.tsx", ".test.js", ".test.jsx"):
        if filename.endswith(ext):
            return True
    return False


def is_tier0_file(path: str) -> bool:
    norm = path.replace("\\", "/").lower()
    if norm.startswith("./"):
        norm = norm[2:]
    if norm.startswith("docs/") or norm.startswith(".caddis/"):
        return True
    if "/" not in norm:
        stem = norm.rsplit(".", 1)[0]
        ext = norm.rsplit(".", 1)[1] if "." in norm else ""
        if ext == "md" and (stem.startswith("readme") or stem.startswith("changelog")):
            return True
    if is_test_file(norm):
        return True
    return False


BINARY_LINES = 41  # a binary change has no line count: count it above the 40-line small limit, never "1-small"


def _rename_paths(path: str) -> list[str]:
    """Both sides of a `--numstat` rename path (`old => new` or `pre/{old => new}/post`); [path] when not a rename."""
    if " => " not in path:
        return [path]
    if "{" in path and "}" in path:
        prefix, rest = path.split("{", 1)
        inner, suffix = rest.split("}", 1)
        old, new = inner.split(" => ", 1)
        return [f"{prefix}{side}{suffix}".replace("//", "/").lstrip("/") for side in (old, new)]
    old, new = path.split(" => ", 1)
    return [old, new]


def _numstat(rng: str | None = None, repo_root: Path = Path(".")) -> list[tuple[str, int]]:
    """(path, changed-lines) per file for an explicit range or the working tree.

    A rename lists BOTH the old and the new path, so moving code into `docs/` or `tests/` is not tier 0. A binary
    change counts `BINARY_LINES`. A failed `git diff` raises RuntimeError: the caller must not read it as an empty
    diff (tier 0)."""
    args = ["git", "-C", str(repo_root), "diff", "--numstat"]
    if rng:
        args.append(rng)
    res = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if res.returncode != 0:
        reason = (res.stderr or "").strip().splitlines()
        raise RuntimeError(f"git diff --numstat exited {res.returncode}: {reason[0] if reason else 'no message'}")
    files: list[tuple[str, int]] = []
    for row in res.stdout.splitlines():
        parts = row.split("\t")
        if len(parts) != 3:
            continue
        add, dele, path = parts
        if add == "-" or dele == "-":
            line_count = BINARY_LINES
        else:
            line_count = (int(add) if add.isdigit() else 0) + (int(dele) if dele.isdigit() else 0)
        paths = _rename_paths(path.strip())
        if len(paths) == 2:
            # A rename moves code out of its old path; a pure rename has 0 changed lines, so without this a move
            # into tests/ would read as a small, covered change (tier 1-small, no review). The old path counts as large.
            files.append((paths[0], max(line_count, BINARY_LINES)))
            files.append((paths[1], max(line_count, BINARY_LINES)))  # tests/x.py -> x.py moves test code into production
        else:
            for p in paths:
                files.append((p, line_count))
    return files


def review_tier(files: list[tuple[str, int]], plan_risk: str = "normal") -> str:
    """Return '0', '1-small', '1' or '2' by the model routing review budget."""
    non_tier0 = [(p, lines) for p, lines in files if not is_tier0_file(p)]
    if not non_tier0:
        return "0"
    if str(plan_risk).strip().lower() == "high":
        return "2"
    non_tier0_paths = [p for p, _ in non_tier0]
    non_tier0_lines = sum(lines for _, lines in non_tier0)
    if review_triggers(non_tier0_paths, non_tier0_lines):
        return "2"
    has_test = any(is_test_file(p) for p, _ in files)
    if non_tier0_lines <= 40 and has_test:
        return "1-small"
    return "1"


def gate_review_tier(
    repo_root: Path,
    rev_range: str | None = None,
    plan: Path | str | None = None,
    phase: int | str | None = None,
) -> int:
    """Print the tier and reviewer count for the diff and plan phase."""
    risk = "normal"
    if plan and phase is None:
        risk = "high"  # fail closed: a plan without a phase cannot give a risk
    elif plan and phase is not None:
        try:
            try:
                import caddis_review
            except ModuleNotFoundError:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import caddis_review
            risk = caddis_review.phase_risk(Path(plan), phase)
        except Exception:
            # Fail closed: a plan risk we cannot read counts as high (tier 2).
            risk = "high"
    try:
        files = _numstat(rev_range, repo_root)
    except Exception as exc:  # noqa: BLE001 - a diff we cannot read is reviewed in full, never skipped
        sys.stderr.write(f"caddis-gate: review-tier could not read the diff ({exc}); counting it as tier 2\n")
        print("TIER: 2")
        print("REVIEWERS: 2")
        return EXIT_OK
    tier = review_tier(files, plan_risk=risk)
    reviewers = TIER_REVIEWERS.get(tier, 2)
    print(f"TIER: {tier}")
    print(f"REVIEWERS: {reviewers}")
    return EXIT_OK


def gate_docs_check(root: Path) -> int:
    """Report every typed .caddis Markdown document with an invalid header."""
    failures = 0
    for path in sorted((root / ".caddis").rglob("*.md")):
        relative = path.relative_to(root).as_posix()
        if not caddis_frontmatter.doc_in_scope(relative, root):
            continue
        error = caddis_frontmatter.validate(
            path.read_text(encoding="utf-8"), caddis_frontmatter.ALLOWED_TYPES
        )
        if error:
            print(f"{relative}: {error}")
            failures += 1
    return EXIT_BLOCKED if failures else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="caddis machine gates")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("lane-check",):
        s = sub.add_parser(name)
        s.add_argument("--plan", required=True)
        s.add_argument("--phase", type=int, required=True)
    t = sub.add_parser("tracker-vs-git")
    t.add_argument("--plan", required=True)
    pl = sub.add_parser("parking-lot")
    pl.add_argument("--repo-root", default=".")
    rt = sub.add_parser("review-trigger")
    rt.add_argument("--repo-root", default=".")
    rt.add_argument("--range", dest="rev_range", default=None,
                    help="revision range, e.g. origin/main...HEAD (default: the working tree)")
    rw = sub.add_parser("review-tier")
    rw.add_argument("--repo-root", default=".")
    rw.add_argument("--range", dest="rev_range", default=None,
                    help="revision range, e.g. origin/main...HEAD (default: the working tree)")
    rw.add_argument("--plan", default=None, help="path to plan markdown")
    rw.add_argument("--phase", default=None, help="phase number or heading")
    vd = sub.add_parser("vendor-drift")
    vd.add_argument("--repo-root", default=".")
    hc = sub.add_parser("handover-check")
    hc.add_argument("--doc", required=True)
    hc.add_argument("--repo-root", default=".")
    hc.add_argument("--max-chars", type=int, default=None,
                    help="block a doc longer than this (relays: 4000); default: no cap")
    dc = sub.add_parser("docs-check")
    dc.add_argument("--root", default=".")
    a = ap.parse_args(argv)

    plan = Path(getattr(a, "plan", "") or ".")
    if a.cmd == "docs-check":
        try:
            return gate_docs_check(Path(a.root).resolve())
        except Exception as exc:
            sys.stderr.write(f"[caddis-gate] docs-check cannot evaluate: {type(exc).__name__}: {exc}\n")
            return EXIT_BLOCKED  # CI must not pass without completing the scan.
    try:
        if a.cmd == "lane-check":
            return gate_lane(plan, a.phase)
        if a.cmd == "parking-lot":
            return gate_parking_lot(Path(a.repo_root).resolve())
        if a.cmd == "review-trigger":
            return gate_review_trigger(Path(a.repo_root).resolve(), a.rev_range)
        if a.cmd == "review-tier":
            return gate_review_tier(
                Path(a.repo_root).resolve(),
                a.rev_range,
                getattr(a, "plan", None),
                getattr(a, "phase", None),
            )
        if a.cmd == "vendor-drift":
            return gate_vendor_drift(Path(a.repo_root).resolve())
        if a.cmd == "handover-check":
            return gate_handover_check(Path(a.doc), Path(a.repo_root).resolve(), a.max_chars)
        return gate_tracker(plan)
    except Exception as exc:  # pragma: no cover — a gate must never crash the caller
        return _degrade(f"{type(exc).__name__}: {exc}")


if __name__ == "__main__":
    raise SystemExit(main())
