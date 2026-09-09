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
import json
import re
import os
import subprocess
import sys
import time
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
    # A THIRD refusing tier, kept separate from stale_prone so the message can say something
    # different. A stale hash is an accident the successor will notice; a stored answer key
    # defeats the exercise SILENTLY — it certifies a reader who understood nothing.
    answer_key: list[tuple[int, str]] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.stale_prone and not self.missing_paths and not self.answer_key


# ── answer-key detection ────────────────────────────────────────────────────────────────────
# 008 §2: "store no answer key" was ALREADY written down, in 007 §5 — and the session that had
# that rule available wrote one anyway, into the same file the successor reads, inside a
# <details> block, as though that were a lock. A model reads the whole file, so the questionnaire
# tested nothing: the successor could answer perfectly having understood none of it.
#
# The lesson is not "say it louder in the doc". A rule and an artefact that contradict each other
# do not fail loudly — the artefact wins silently, because the artefact is what gets read. So the
# check lives HERE, in the tooling, and it REFUSES rather than warns.
#
# Deliberately STRUCTURAL rather than semantic. A check that tries to judge whether prose reveals
# an answer is wrong in both directions, and a check that cries wolf gets skimmed — which is how
# the hash tier earned its two-tier split above.
_DETAILS = re.compile(r"<details" + r"\b", re.I)
_ANSWER_KEY_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*|\*\*|<summary>)?\s*"
    r"(?:answer\s*key|expected\s+answers?|correct\s+answers?|model\s+answers?|"
    r"answers?\s*[-—]\s*for\s+the)",
    re.I,
)
# `Q3: ... A: ...` — a question and its answer on one line.
_INLINE_ANSWER = re.compile(r"\bQ\s*\d{1,2}\b.*?\b(?:A|Ans|Answer)\s*[:.\)]", re.I)


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
        # These three run BEFORE the fence exemption and are not subject to it. A fence exempts
        # a hash because quoting one there is the cure; an answer key inside a fence is still an
        # answer key, and a template showing `Q1: ... A: ...` is precisely the shape that teaches
        # the next author to fill it in.
        if _DETAILS.search(line):
            out.answer_key.append((n, "<details> block — a rendering hint, not a lock. The child "
                                      "reads the whole file. Move whatever it hides out of any "
                                      "document the successor is told to open"))
        if _ANSWER_KEY_HEADING.search(line):
            out.answer_key.append((n, "reads as an answer key. It must not exist in a file the "
                                      "examinee can reach — re-derive each answer from the repo "
                                      "at validation time instead"))
        if _INLINE_ANSWER.search(line):
            out.answer_key.append((n, "a question and its answer on one line. The questions may "
                                      "ship; the answers may not"))
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

# ── the context gate (008 section 7a) ───────────────────────────────────────────────────────
# REFUSE above 95%, do not warn. The thing that degrades first is exactly the thing this command
# depends on: 007 section 1 names the failure as confident recall of SUPERSEDED facts, not
# forgetting. A handover written from a nearly-full context is written by the failing faculty, and
# it comes out fluent, cited and wrong. A warning does not help, because the agent that most needs
# to heed it is the one least able to judge that it should.
#
# The costs are not symmetric either. Refusing early costs one session's remaining headroom.
# A confident wrong handover costs the successor's whole session plus everything built on the
# error, and is not discovered until much later, if at all.
CONTEXT_REFUSE_ABOVE = 95.0
CONTEXT_NOTE_ABOVE = 85.0
# Generous on purpose. The cached figure can only be a LOWER bound — context goes up, never down —
# so an old reading that already says "over 95" is still a valid refusal, and one that says 90 may
# really be higher. Staleness is reported rather than silently trusted.
CONTEXT_MAX_AGE_S = 900


def read_context_pct(repo_root: Path) -> tuple[float | None, str]:
    """(percentage, provenance) from the statusline's cache, or (None, why not).

    Written by `caddis_statusline.record_context`. Claude Code gives the figure to the status
    line and to nothing else, so this file is the only runtime-sourced number a plain command
    can reach.
    """
    target = repo_root / ART / "context-window.json"
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
        pct = float(raw["used_percentage"])
        age = max(0, int(time.time()) - int(raw.get("at", 0)))
    except Exception:
        return None, ("no runtime context figure at "
                      + f"{ART}/context-window.json — run `/caddis:statusline` to install the "
                      "status line that writes it")
    if age > CONTEXT_MAX_AGE_S:
        return pct, f"runtime figure, STALE by {age}s (a lower bound — the real number is >= this)"
    return pct, f"runtime figure, {age}s old"


@dataclass
class Preflight:
    refusals: list[str] = field(default_factory=list)
    dirty: int = 0
    parking_open: int | None = None
    # The context figure and where it came from. Provenance is carried, not just the number,
    # because a self-reported figure and a runtime one are not the same evidence and the
    # handover has to say which it had (008 section 7a: the 85-95 band must state the figure).
    context_pct: float | None = None
    context_source: str = ""
    notes: list[str] = field(default_factory=list)

    def ok(self) -> bool:
        return not self.refusals


def preflight(repo_root: Path, context_pct: float | None = None) -> Preflight:
    """Conditions under which a spawn must not happen at all.

    A dirty tree is the sharp one: the successor starts by pulling, so **uncommitted work is
    invisible to it**. It will then either redo that work or build on a state that does not exist.

    `context_pct` is the caller's own reading, for machines with no caddis status line — see
    _gate_context for why it can only ever tighten the gate.
    """
    p = Preflight()
    _gate_context(p, repo_root, context_pct)
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


def _gate_context(p: Preflight, repo_root: Path, self_reported: float | None) -> None:
    """008 section 7a: refuse above 95%, note between 85 and 95, and never silently proceed.

    Two sources, and the rule between them is the whole design:

      * the status line's cache — runtime-sourced, and the only such number a plain command can
        reach, because Claude Code hands `used_percentage` to the status line and nothing else;
      * `--context-pct`, the caller's own reading, for a machine with no caddis status line.

    **A self-reported figure may only TIGHTEN the gate, never loosen it** — so the two are
    combined with max(). That is what makes the fallback safe rather than theatre. 007 section 1
    names the failure as confident recall by a degraded context; a self-report that can talk its
    way THROUGH the gate is exactly that failure wearing the gate's clothes, while one that can
    only trip it earlier cannot be gamed into a pass.

    With NO figure from either source it refuses, per 008: "an unmeasurable gate that defaults to
    proceed is not a gate". But it refuses with two ways out, because a gate that cannot be
    satisfied on a machine without the status line would simply be switched off.
    """
    pct, source = read_context_pct(repo_root)
    if self_reported is not None:
        if pct is None or self_reported > pct:
            pct = self_reported
            source = "SELF-REPORTED via --context-pct, not verified against the runtime"
        else:
            source = source + f"; --context-pct said {self_reported:.0f}%, kept the higher figure"
    p.context_pct, p.context_source = pct, source

    if pct is None:
        p.refusals.append(
            "no context figure, so the 95% gate cannot be applied — and a gate that defaults to "
            "proceed is not a gate. Either run `/caddis:statusline` (its status line caches the "
            "runtime figure for this repo), or pass `--context-pct <n>` with the number your "
            "harness reports. A self-reported figure is accepted and recorded as such.")
        return
    if pct > CONTEXT_REFUSE_ABOVE:
        p.refusals.append(
            f"context is {pct:.0f}% ({source}). A handover written from here would be fluent and "
            "unreliable, which is the failure this command exists to prevent. Do this instead, "
            "in order: (1) commit and push everything now; (2) write ONLY the task list to "
            f"{ART}/parent-session-state.md, the smallest durable artefact and the one a task "
            "widget loses; (3) TELL the product owner which capture steps you skipped; (4) let "
            "the successor rebuild the relay from the repo, which beats this session's memory of "
            "it anyway. A partial handover that SAYS it is partial is worth far more than a "
            "complete-looking one nobody can trust.")
        return
    if pct > CONTEXT_NOTE_ABOVE:
        p.notes.append(
            f"context is {pct:.0f}% ({source}). Under the refusal line, but STATE THIS FIGURE in "
            "the handover so the reader can weigh what it says.")


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


# ── the capture order (008 section 4) ──────────────────────────────────────────────────────
# Knowledge -> durable state -> task list -> relay -> questions. Out of sequence it produces a
# handover that describes a state that never existed: the relay CITES the first three, so writing
# it earlier cites things that have since moved, and questions written first test the outgoing
# agent's MEMORY, which is the thing under suspicion.
#
# mtimes are the evidence. This does not check that each step was done well — nothing can — it
# checks the one property that is mechanically knowable and that a tired session gets wrong.
PARENT_RELAY = "parent-relay.md"
PARENT_STATE = "parent-session-state.md"


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def capture_order(repo_root: Path, spawn_id: str) -> tuple[list[str], list[str]]:
    """(refusals, notes) on the ORDER the handover artefacts were written in.

    Required: the relay and the prompt. The task list is advisory, because a session can
    legitimately end with nothing on it — but a MISSING step must be declared, not inferred,
    which is why it is a note rather than silence.
    """
    refusals: list[str] = []
    notes: list[str] = []
    art = repo_root / ART
    relay, state = art / PARENT_RELAY, art / PARENT_STATE
    prompt = repo_root / SPAWN_DIR / (spawn_id + "-prompt.md")

    t_relay, t_state, t_prompt = _mtime(relay), _mtime(state), _mtime(prompt)
    if t_relay is None:
        refusals.append(f"no {ART}/{PARENT_RELAY} — step 4 of the capture order never happened")
    if t_prompt is None:
        refusals.append(f"no {SPAWN_DIR}/{spawn_id}-prompt.md — step 5 never happened")
    if refusals:
        return refusals, notes

    if t_state is None:
        notes.append(f"no {ART}/{PARENT_STATE}. A task widget does not survive a `/clear` and this "
                     "project has already lost one — if the list is genuinely empty, SAY so in the "
                     "handover rather than leaving the reader to infer it.")
    elif t_state > t_relay:
        refusals.append(f"{PARENT_STATE} is NEWER than {PARENT_RELAY}. The relay cites the task "
                        "list, so a list written afterwards means the relay describes a state "
                        "that never existed. Rewrite the relay, do not re-touch the list.")

    if t_relay > t_prompt:
        refusals.append(f"{PARENT_RELAY} is NEWER than the prompt. The questions must target what "
                        "the relay actually says — derived from a relay that has since changed, "
                        "they test your memory of it, which is the thing under suspicion.")

    # Anything the relay quotes that moved after it was written.
    for sub_dir in ("kb", "parking-lot"):
        d = art / sub_dir
        if not d.is_dir():
            continue
        moved = sorted(f.name for f in d.glob("*.md") if (_mtime(f) or 0) > t_relay)
        if moved:
            notes.append(f"{sub_dir}/ changed AFTER the relay was written: "
                         + ", ".join(moved[:5]) + ("" if len(moved) <= 5 else ", ...")
                         + ". The relay quotes these, so re-read them before issuing it.")
    return refusals, notes


# ── the handshake (008 section 3) ───────────────────────────────────────────────────────────
# 007 routed every round trip through a human paste. Sessions can message each other now, so the
# human is an approver rather than a transport — but only where a transport exists.
#
# THE CHILD INITIATES. It cannot message until it has answers, so the message itself is evidence
# it did the reading. But child-initiated ALONE leaves the worst failure invisible: a successor
# that skips the gate and just starts working produces silence, and silence is indistinguishable
# from "still reading". So the parent holds a timeout and CHASES.
#
# None of that can be enforced by prose. Section 2 of 008 is the proof: a rule written in a
# document lost to the artefact that contradicted it, within a day, in this very command. So the
# state lives in a file and `close` refuses to let the parent finish while the handshake is open.
# "Closing on an unanswered handshake is the same as never running one."
CHASE_AFTER_S = 1800

# Ordered. Each event may only move the handshake forward.
HANDSHAKE_STATES = ("awaiting-answers", "answered", "verdict-sent", "acknowledged")
_EVENT_STATE = {"answers": "answered", "verdict": "verdict-sent", "ack": "acknowledged"}


def detect_transport(env: dict | None = None) -> tuple[str, str]:
    """('message' | 'paste', why) — tests the CAPABILITY, not the vendor.

    `SendMessage` is Claude Code only; the harness also ships an `agy/` directory and targets
    Codex, so a Claude-only command would simply not run on two of three targets. That makes the
    paste path a supported route, not a degraded one.

    The signal is `CLAUDE_CODE_MESSAGING_SOCKET`, which IS the cross-session transport — a peer
    message arrives addressed from that socket. Keying on the socket rather than on "is this
    Claude Code" means a runtime that gains messaging later works with no change here, and a
    Claude Code with messaging switched off correctly falls back instead of failing at the moment
    it tries to send.
    """
    env = os.environ if env is None else env
    if env.get("CLAUDE_CODE_MESSAGING_SOCKET"):
        return "message", "CLAUDE_CODE_MESSAGING_SOCKET is set — peers are reachable directly"
    if env.get("CLAUDECODE"):
        return "paste", ("Claude Code, but no messaging socket — the transport is off or this "
                         "build predates it. The human carries the round trip.")
    return "paste", ("no messaging transport (agy, Codex or a plain shell). The human carries "
                     "the round trip — this is a supported path, not a broken one.")


def _handshake_path(repo_root: Path, spawn_id: str) -> Path:
    return repo_root / SPAWN_DIR / (spawn_id + "-handshake.json")


def handshake_open(repo_root: Path, spawn_id: str, transport: str = "auto",
                   peer: str = "") -> dict:
    """Record that a handover was issued. Written by the PARENT, at the moment it prints the
    prompt — not when the child replies, because the whole point is to make an unanswered
    handshake visible."""
    chosen, why = detect_transport()
    if transport != "auto":
        chosen, why = transport, "forced with --transport"
    state = {
        "id": spawn_id,
        "state": HANDSHAKE_STATES[0],
        "transport": chosen,
        "transport_reason": why,
        # HOW TO ADDRESS THE CHILD. `SendMessage` takes the name `ListAgents` shows, and until
        # 2026-09-08 this file recorded none — so the parent knew a handshake was open and had no
        # idea who to send the chase or the verdict to. Usually EMPTY at open: the child does not
        # exist yet. The parent fills it in from the `from-name` of the child's first message,
        # which is the only moment either side reliably knows that name.
        "peer": peer,
        "opened_at": int(time.time()),
        "history": [],
    }
    path = _handshake_path(repo_root, spawn_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2) + chr(10), encoding="utf-8")
    return state


def handshake_read(repo_root: Path, spawn_id: str) -> dict | None:
    try:
        return json.loads(_handshake_path(repo_root, spawn_id).read_text(encoding="utf-8"))
    except Exception:
        return None


def handshake_record(repo_root: Path, spawn_id: str, event: str,
                     peer: str = "") -> tuple[dict | None, str]:
    """Advance the handshake. Never rewinds: a verdict cannot un-answer the questions, and an
    out-of-order event is a sign the operator has lost track of which round they are in — which
    is exactly when a silent overwrite would hurt."""
    state = handshake_read(repo_root, spawn_id)
    if state is None:
        return None, f"no handshake for {spawn_id} — run `handshake open --id {spawn_id}` first"
    target = _EVENT_STATE[event]
    if HANDSHAKE_STATES.index(target) <= HANDSHAKE_STATES.index(state["state"]):
        return state, (f"already at `{state['state']}`; `{event}` would not move it forward. "
                       "Refusing rather than rewriting — an out-of-order event means the round "
                       "is not the one you think it is.")
    if peer:
        state["peer"] = peer
    state["history"].append({"event": event, "at": int(time.time()),
                             **({"peer": peer} if peer else {})})
    state["state"] = target
    _handshake_path(repo_root, spawn_id).write_text(
        json.dumps(state, indent=2) + chr(10), encoding="utf-8")
    return state, ""


def chase_instruction(state: dict) -> str:
    """What to actually DO when a chase is due — addressed if we can, honest if we cannot."""
    peer = (state.get("peer") or "").strip()
    if state.get("transport") != "message":
        return ("This handshake is on the paste route, so the chase goes through the human. Say "
                "so explicitly — otherwise they watch nothing happen and conclude it is broken.")
    if peer:
        return f'SendMessage to: "{peer}"  — carry TWO FRESH questions, not just a reminder.'
    return ("No peer address recorded, so the child has not made contact yet — which is itself "
            "the signal. Run `ListAgents` and look for a session in this repo; a session started "
            "seconds ago may be absent from one listing, so a single empty result is not proof it "
            "does not exist. Once it replies, capture the name: "
            "`handshake record --id <id> --event answers --peer <from-name>`.")


def handshake_chase_due(state: dict, now: int | None = None) -> int:
    """Seconds overdue for a chase, or 0. Only meaningful while awaiting answers.

    A chase is not a reminder. It should carry two FRESH questions, which cannot have been
    pre-read in the handover file — a stronger test than the original set, and free, because the
    parent is holding the context anyway.
    """
    if state.get("state") != HANDSHAKE_STATES[0]:
        return 0
    now = int(time.time()) if now is None else now
    return max(0, now - int(state.get("opened_at", now)) - CHASE_AFTER_S)


def handshake_close(repo_root: Path, spawn_id: str) -> tuple[bool, str]:
    """May the parent stop now? The lifecycle rule, made mechanical.

    A handover nobody has read is not a handover, it is a file. Grading RE-DERIVES, so it audits
    the document as well as the reader — in the manual run that pass found a defect in the
    parent's own handover. `/clear` in the parent's terminal destroys the only thing that can do
    that, so the parent must outlive the handshake.

    NOTE the distinction this makes explicit, because two documents look like they disagree:
    `spawn-hub` says the outgoing session STOPS WRITING the moment the prompt is issued (two
    sessions committed to one repo concurrently and one's work landed inside the other's commit).
    008 says the parent is not CLOSED until the child passes. Alive is not writing. Both hold.
    """
    state = handshake_read(repo_root, spawn_id)
    if state is None:
        return False, (f"no handshake recorded for {spawn_id}. If one was run, it was not "
                       "recorded, and an unrecorded handshake cannot be distinguished from none.")
    if state["state"] != HANDSHAKE_STATES[-1]:
        return False, (f"handshake is at `{state['state']}`, not `acknowledged`. The parent stays "
                       "ALIVE until the child confirms it has the verdict — closing on an "
                       "unanswered handshake is the same as never running one. (It may stop "
                       "WRITING to the repo now; that is a different rule and both hold.)")
    return True, "acknowledged — the parent may close"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("preflight", "fingerprint"):
        s = sub.add_parser(name)
        s.add_argument("--repo-root", default=".")
        if name == "fingerprint":
            s.add_argument("--with-tests", action="store_true")
        else:
            s.add_argument("--context-pct", type=float, default=None,
                           help="your own context-usage reading, 0-100, for a machine with no "
                                "caddis status line. Only ever tightens the gate: the higher of "
                                "this and the cached runtime figure wins.")
    c = sub.add_parser("check")
    c.add_argument("--doc", required=True)
    c.add_argument("--repo-root", default=".")
    o = sub.add_parser("capture-check")
    o.add_argument("--id", required=True)
    o.add_argument("--repo-root", default=".")
    h = sub.add_parser("handshake")
    h.add_argument("action", choices=["open", "status", "record", "close"])
    h.add_argument("--id", required=True)
    h.add_argument("--repo-root", default=".")
    h.add_argument("--event", choices=sorted(_EVENT_STATE))
    h.add_argument("--transport", choices=["auto", "message", "paste"], default="auto")
    h.add_argument("--peer", default="",
                   help="the child's name as ListAgents shows it — take it from the `from-name` "
                        "of its first message; that is the only moment it is reliably known")
    q = sub.add_parser("verify-question")
    q.add_argument("--answer-in", required=True)
    q.add_argument("--needle", required=True)
    q.add_argument("--repo-root", default=".")
    a = ap.parse_args(argv)
    root = Path(a.repo_root).resolve()

    if a.cmd == "preflight":
        p = preflight(root, context_pct=a.context_pct)
        for note in p.notes:
            print(f"  note  {note}")
        if p.ok():
            ctx = f", context {p.context_pct:.0f}%" if p.context_pct is not None else ""
            print(f"[spawn] ready — clean tree, {p.parking_open} open parking-lot item(s){ctx}")
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
        for n, msg in f.answer_key:
            sys.stderr.write(f"    line {n}: ANSWER KEY — {msg}" + chr(10))
        for n, msg in f.stale_prone:
            sys.stderr.write(f"    line {n}: {msg}\n")
        for p_ in f.missing_paths:
            sys.stderr.write(f"    names a path that does not exist: {p_}\n")
        sys.stderr.write("  A claim that cannot be re-derived does not go in the handover.\n")
        if f.answer_key:
            sys.stderr.write("  And an answer the examinee can read is not a check. This REFUSES "
                             "rather than warns because the rule was already written down, in "
                             "007 section 5, and a session that had it broke it within a day."
                             + chr(10))
        return EXIT_REFUSED

    if a.cmd == "capture-check":
        refusals, notes = capture_order(root, a.id)
        for n in notes:
            print(f"  note  {n}")
        if not refusals:
            print("[spawn] capture order holds — relay after the task list, questions after both")
            return EXIT_OK
        sys.stderr.write("[spawn] capture order is WRONG:" + chr(10))
        for r in refusals:
            sys.stderr.write("    " + r + chr(10))
        sys.stderr.write("  Out of sequence, a handover describes a state that never existed."
                         + chr(10))
        return EXIT_REFUSED

    if a.cmd == "handshake":
        if a.action == "open":
            st = handshake_open(root, a.id, a.transport, a.peer)
            print(f"[spawn] handshake {a.id} open — transport `{st['transport']}` "
                  f"({st['transport_reason']})")
            if st["transport"] == "paste":
                print("  The child cannot message you. Print the prompt for the human to carry, "
                      "and say so — otherwise they watch nothing happen and conclude it is "
                      "broken.")
            return EXIT_OK
        st = handshake_read(root, a.id)
        if st is None:
            sys.stderr.write(f"[spawn] no handshake for {a.id}" + chr(10))
            return EXIT_REFUSED
        if a.action == "status":
            over = handshake_chase_due(st)
            peer = st.get("peer") or "(not recorded — see below)"
            print(f"[spawn] {a.id}: {st['state']} via {st['transport']}, peer {peer}")
            if over:
                print(f"  CHASE DUE — {over}s past the {CHASE_AFTER_S}s window. Silence is not "
                      "success: a child that skipped the gate and started work looks exactly "
                      "like one still reading.")
                print("  " + chase_instruction(st))
            return EXIT_OK
        if a.action == "record":
            if not a.event:
                sys.stderr.write("[spawn] --event is required for `record`" + chr(10))
                return EXIT_REFUSED
            st, err = handshake_record(root, a.id, a.event, a.peer)
            if err:
                sys.stderr.write("[spawn] " + err + chr(10))
                return EXIT_REFUSED
            print(f"[spawn] {a.id}: {st['state']}")
            return EXIT_OK
        if a.action == "close" and not (st.get("peer") or "").strip() \
                and st["state"] != HANDSHAKE_STATES[0]:
            # Contact happened but nobody wrote down who with. The verdict has to reach someone.
            print("  note  no peer recorded although the handshake progressed — re-run "
                  "`record --peer <from-name>` so the next session can see who this was with.")
        ok, msg = handshake_close(root, a.id)
        (print if ok else sys.stderr.write)("[spawn] " + msg + ("" if ok else chr(10)))
        return EXIT_OK if ok else EXIT_REFUSED

    ok, msg = verify_answerable(root, a.answer_in, a.needle)
    (print if ok else sys.stderr.write)(f"[spawn] {msg}" + ("" if ok else "\n"))
    return EXIT_OK if ok else EXIT_REFUSED


if __name__ == "__main__":
    raise SystemExit(main())
