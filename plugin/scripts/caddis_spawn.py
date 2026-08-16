#!/usr/bin/env python3
"""caddis_spawn — shared machinery for handing work to a fresh session.

WHY THIS IS ONE MODULE AND NOT TWO
----------------------------------
`/caddis:spawn-hub` and `/caddis:spawn-session` transfer different things — a validation ROLE and
the WORK itself — but they fail the same way and defend against it with the same four mechanisms:

  1. capture from the repo, never from recall
  2. a self-check whose naive answer is WRONG, so a successor that skimmed fails visibly
  3. no stored answer key: re-derive at validation time, which checks the DOCUMENT as well
  4. refuse to write anything that goes stale (a commit hash, a test count) as a fact

Built as one module so a fix lands in both. The alternative was already visible in the codebase:
`succession.md` §J had the trap idea and `spawn-session` was about to grow a second copy of it.

THE FAILURE MODE, PRECISELY
---------------------------
A long session does not forget. It **recalls superseded facts fluently**. Measured in one session:
two throughput figures the agent had itself withdrawn were re-quoted days later; "E8 is blocked on
F1" was repeated for three days without a re-test; a commit hash written into a handover went stale
within the hour. None of that is amnesia, and none of it is caught by asking the outgoing agent
what it knows — because the failure mode IS what it knows.

Usage:
  python scripts/caddis_spawn.py preflight              # refuse to spawn from an unsafe state
  python scripts/caddis_spawn.py fingerprint            # head + counts, for stale-paste detection
  python scripts/caddis_spawn.py check --doc <file>     # round 0: the parent checks its own handover
  python scripts/caddis_spawn.py verify-question --answer-in <file> --needle <text>
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EXIT_OK, EXIT_REFUSED = 0, 1

ART = ".caddis"
SPAWN_DIR = f"{ART}/spawn-session"


def _run(args: list[str], cwd: Path) -> str:
    try:
        r = subprocess.run(args, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


# ── things that go stale ────────────────────────────────────────────────────────────────────
#
# A 7-to-40 character hex run is a commit hash. A handover that states one as a fact is wrong
# within the hour — measured twice in one session. The fix is not a fresher hash, it is to write
# the COMMAND that produces it, so the reader gets today's answer instead of yesterday's.
_HASH = re.compile(r"(?<![0-9a-zA-Z/])[0-9a-f]{7,40}(?![0-9a-zA-Z/])")
# "1,066 tests" / "821 passed". Same problem: true when written, false an hour later.
_COUNT = re.compile(r"\b\d[\d,]*\s+(?:tests?|passed|failed|skipped)\b", re.I)

# A fingerprint is a MEASUREMENT, explicitly stamped at a moment, and it exists precisely so a
# stale paste can be detected. That is the opposite of a fact stated as durable, so it is exempt.
#
# ANCHORED TO `SPAWN`, AND ONLY THAT. The first version also exempted any line starting with
# `head` — which exempts "HEAD is currently abc1234", the single most common way of writing the
# exact thing this check exists to catch. Its own test found it. An exemption is a hole in a check,
# so it gets the narrowest possible shape: the literal first token of `fingerprint_line()`.
_FINGERPRINT_LINE = re.compile(r"^\s*SPAWN\b", re.I)


# THE DISTINCTION THAT KEEPS THIS CHECK SWITCHED ON.
#
# A hash naming a PAST commit ("shipped in abc1234") is immutable and perfectly safe. A hash
# offered as CURRENT STATE ("HEAD is abc1234", "we are currently at abc1234") is wrong within the
# hour — that is the failure 007 recorded, twice. The first version of this flagged both and
# produced seven findings on one real handover, every one a historical citation. A check with that
# hit rate gets switched off before it ever catches the one that matters.
_CURRENT_STATE = re.compile(
    r"\b(head|current|currently|latest|now at|tip of|as of now|at present|working tree)\b", re.I)


def _is_exempt(line: str, in_fence: bool) -> bool:
    """Fenced blocks are commands and transcripts — quoting a hash there is the CURE, not the bug."""
    return in_fence or bool(_FINGERPRINT_LINE.match(line))


@dataclass
class DocFindings:
    """`stale_prone` refuses; `historical` only advises.

    Two tiers because the cost of each error differs. A current-state hash that goes stale sends
    the successor to the wrong commit — block it. A historical citation is durable and merely worth
    a second look — flagging it as a failure is how a check earns a reputation for crying wolf.
    """
    stale_prone: list[tuple[int, str]] = field(default_factory=list)
    historical: list[tuple[int, str]] = field(default_factory=list)
    missing_paths: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.stale_prone and not self.missing_paths


_DOC_PATH = re.compile(r"`([^`\s<>{}*?]+?\.(?:md|py|ts|tsx|json|ya?ml|sh|ps1|html|toml|sql))`")


def check_document(text: str, repo_root: Path | None = None) -> DocFindings:
    """Round 0: the parent validates its OWN handover before anyone reads it.

    This is the cheapest round and the one issue 004 is really about. In the manual run a child
    caught a stale commit hash the parent could have caught alone — a wasted relay trip, and the
    relay trip is the expensive part of the whole exercise.

    Fails closed: a claim that cannot survive this does not go in the handover.
    """
    out = DocFindings()
    in_fence = False
    for n, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if _is_exempt(line, in_fence):
            continue
        for m in _HASH.finditer(line):
            # A bare decimal number is not a hash; require at least one a-f digit so version
            # strings and dates do not produce a check nobody can ever get to green.
            if not any(c in "abcdef" for c in m.group(0)):
                continue
            if _CURRENT_STATE.search(line):
                out.stale_prone.append((n, f"commit hash `{m.group(0)}` given as CURRENT state — "
                                           "wrong within the hour, twice. Write the command "
                                           "(`git rev-parse --short HEAD`) instead"))
            else:
                out.historical.append((n, f"commit hash `{m.group(0)}` — reads as a historical "
                                          "citation, which is durable. Check that it is not "
                                          "standing in for current state"))
        for m in _COUNT.finditer(line):
            out.stale_prone.append((n, f"`{m.group(0)}` stated as a fact — write the command "
                                       "instead; this was wrong within the hour, twice"))
    if repo_root is not None:
        for raw in sorted(set(_DOC_PATH.findall(text))):
            cand = next((tok for tok in raw.split() if "/" in tok or tok.endswith(".md")), raw)
            cand = cand.strip("(),;:'\"")
            if cand.startswith(("http://", "https://", "~", "$")) or ".." in cand:
                continue
            if not (repo_root / cand).exists():
                out.missing_paths.append(cand)
    return out


# ── refusals ────────────────────────────────────────────────────────────────────────────────

@dataclass
class Preflight:
    refusals: list[str] = field(default_factory=list)
    dirty: int = 0
    parking_open: int | None = None

    def ok(self) -> bool:
        return not self.refusals


def preflight(repo_root: Path) -> Preflight:
    """Conditions under which a spawn must not happen at all.

    A dirty tree is the sharp one: the successor starts by pulling, so **uncommitted work is
    invisible to it**. It will then either redo that work or build on a state that does not exist.
    """
    p = Preflight()
    status = _run(["git", "status", "--short"], repo_root)
    p.dirty = len([l for l in status.splitlines() if l.strip()])
    if p.dirty:
        p.refusals.append(
            f"{p.dirty} uncommitted file(s). The successor pulls, so uncommitted work is invisible "
            "to it — it will redo the work or build on a state that does not exist. Commit first.")

    d = repo_root / ART / "parking-lot"
    if d.is_dir():
        p.parking_open = len([f for f in d.glob("*.md") if f.name.lower() != "readme.md"])
    else:
        # The count is the INTEGRITY CHECK on the handover: a successor that revives 13 of 15 has
        # silently dropped two, and nothing else would show it.
        p.refusals.append(
            f"no {ART}/parking-lot/ — the open-item count is the integrity check on a handover, "
            "and without it a dropped item is undetectable.")
    return p


# ── fingerprint ─────────────────────────────────────────────────────────────────────────────

def fingerprint(repo_root: Path, with_tests: bool = False) -> dict:
    """A stamp the child echoes back, so the parent can spot a stale or mismatched paste.

    NOT a fact for the handover body — a measurement, at a moment, for exactly one purpose.
    """
    fp = {
        "head": _run(["git", "rev-parse", "--short", "HEAD"], repo_root) or "unknown",
        "branch": _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_root) or "unknown",
        "parking_open": preflight(repo_root).parking_open,
        "tests": "not measured",
    }
    if with_tests:
        out = _run([sys.executable, "-m", "pytest", "-q", "--tb=no"], repo_root)
        tail = [l for l in out.splitlines() if "passed" in l or "failed" in l]
        fp["tests"] = tail[-1] if tail else "suite reported no summary"
    return fp


def fingerprint_line(fp: dict) -> str:
    return (f"SPAWN | head {fp['head']} ({fp['branch']}) | parking-lot open {fp['parking_open']} "
            f"| tests: {fp['tests']}")


# ── question answerability ──────────────────────────────────────────────────────────────────

def verify_answerable(repo_root: Path, answer_in: str, needle: str) -> tuple[bool, str]:
    """A question must be answerable from a COMMITTED file, or it tests memory.

    Testing memory is the thing being replaced, so a question that fails this is not a harder
    question — it is the old failure wearing an exam's clothes.
    """
    path = repo_root / answer_in
    if not path.is_file():
        return False, f"{answer_in} does not exist — the answer is not written down anywhere"
    tracked = _run(["git", "ls-files", "--error-unmatch", answer_in], repo_root)
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return False, f"{answer_in} unreadable: {type(exc).__name__}"
    if needle.lower() not in text.lower():
        return False, f"{answer_in} does not contain {needle!r} — the answer is not in that file"
    if not tracked:
        return True, (f"{answer_in} contains the answer, but is NOT COMMITTED — the successor "
                      "pulls and will not see it")
    return True, f"{answer_in} contains {needle!r} and is committed"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("preflight", "fingerprint"):
        s = sub.add_parser(name)
        s.add_argument("--repo-root", default=".")
        if name == "fingerprint":
            s.add_argument("--with-tests", action="store_true")
    c = sub.add_parser("check")
    c.add_argument("--doc", required=True)
    c.add_argument("--repo-root", default=".")
    q = sub.add_parser("verify-question")
    q.add_argument("--answer-in", required=True)
    q.add_argument("--needle", required=True)
    q.add_argument("--repo-root", default=".")
    a = ap.parse_args(argv)
    root = Path(a.repo_root).resolve()

    if a.cmd == "preflight":
        p = preflight(root)
        if p.ok():
            print(f"[spawn] ready — clean tree, {p.parking_open} open parking-lot item(s)")
            return EXIT_OK
        sys.stderr.write("[spawn] REFUSING to spawn:\n")
        for r in p.refusals:
            sys.stderr.write(f"    {r}\n")
        return EXIT_REFUSED

    if a.cmd == "fingerprint":
        print(fingerprint_line(fingerprint(root, with_tests=a.with_tests)))
        return EXIT_OK

    if a.cmd == "check":
        doc = Path(a.doc)
        if not doc.is_file():
            sys.stderr.write(f"[spawn] no document at {doc}\n")
            return EXIT_REFUSED
        f = check_document(doc.read_text(encoding="utf-8", errors="ignore"), root)
        for n, msg in f.historical:
            print(f"  note  line {n}: {msg}")
        if f.ok():
            print(f"[spawn] {doc.name} passes round 0 — nothing stale-prone, every path exists")
            return EXIT_OK
        sys.stderr.write(f"[spawn] {doc.name} FAILS round 0:\n")
        for n, msg in f.stale_prone:
            sys.stderr.write(f"    line {n}: {msg}\n")
        for p_ in f.missing_paths:
            sys.stderr.write(f"    names a path that does not exist: {p_}\n")
        sys.stderr.write("  A claim that cannot be re-derived does not go in the handover.\n")
        return EXIT_REFUSED

    ok, msg = verify_answerable(root, a.answer_in, a.needle)
    (print if ok else sys.stderr.write)(f"[spawn] {msg}" + ("" if ok else "\n"))
    return EXIT_OK if ok else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
