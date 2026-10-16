"""Agentic review: a lane worktree against a card (GLM, DeepSeek), or a plan phase with Claude and the review protocol.

`--plan <path> --phase <n> --runs <k>` reviews the phase's commits k times, each run in its own throwaway worktree, merges
the FINDING lines of all runs and exits by the findings, never by a verdict: a `blocking` finding -> 1; only
`should-fix`, `nit` or no findings -> 0 (the should-fix and nit findings are listed in the merged report under
`Follow-up (not blocking)`, for a follow-up list; they never stop a merge); a run that did not complete (cut off, no END
REVIEW line, wrong count, a line that names a finding but is not one, changed the live repo) -> 3, and so does any
unexpected error. Exit 4 means the review could not start (bad arguments, `--runs` over 3, no protocol file, no such
phase, not a git repo, an unreadable rounds file): a caller treats 4 exactly like 3, NOT_RUN.

Round limit: every tool run that reached the reviewers is recorded in `<out-dir>/review-<phase>-rounds.json` (one
entry per run: round, plan, utc, head sha, result, exit; a completed round that is not CLEAN also keeps its
blocking finding lines, which the next fix-diff review gets again). Only a COMPLETED run (not NOT_RUN) of the same plan is a
round; a NOT_RUN entry has round null and uses nothing. A phase gets 3 rounds (`MAX_ROUNDS`). The 4th and every later round still runs and writes its report, but a round that completed exits 5
(`caddis_exit.ROUND_LIMIT`) whatever it found, clean included: stop, the owner decides. A caller treats 5 as a stop, not
as a pass and not as a reason to start another round. A round that did not complete still exits 3. The count lives in
the out dir: a new out dir starts again at round 1. Run one review of a phase at a time: the rounds file has no lock.
Round 2 and later review only the fix diff, `<head of the last completed round>..HEAD`, when that head is an ancestor
of HEAD after the base; else (no head, not a commit, not an ancestor, the same head) the full range, with a stderr note.
A fix diff of review tier 0 (`caddis_gate.review_tier` with risk "normal": docs, `.caddis`, tests only) launches no
reviewer: it exits 0 and records `SKIPPED delta tier 0`, which is not a round.
On a POSIX host with no usable systemd user scope the governor refuses, so every run there is NOT_RUN (fails safe);
plan reviews run on the Windows dev box.

The live-repo check is a TRIPWIRE, not a sandbox. The reviewer runs with full Bash and the real HOME: it can write
outside the repo, and nothing stops it. The check only compares a snapshot of the live repo (HEAD, refs, index, config
files, every `git config` scope with its origin, hooks, info, changed and untracked files, high-risk files inside
ignored cache folders) before and after each run, and makes the run NOT_RUN when they differ. Known gaps (not seen):
`objects/info/alternates`, pseudo-refs and MERGE_MSG, submodule configs, and an edit that keeps a file's size and
mtime (files over 50 MB only). Ignored logs or caches written by other processes during a run make it NOT_RUN: that
fails safe."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path

try:
    import caddis_exit
    import caddis_redact
    import caddis_routing
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_exit", "caddis_redact", "caddis_routing"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit
    import caddis_redact
    import caddis_routing

USAGE_LIMIT_RE = re.compile(
    r"Usage limit reached for|Limit Exhausted|Insufficient balance|You.ve hit your .*limit|RESOURCE_EXHAUSTED",
    re.IGNORECASE,
)


def _review_role(repo: Path) -> list[str]:
    return caddis_routing.resolve(Path.home(), repo).get("review", [])


def provider_order(provider: str | None, repo: Path) -> list[str]:
    role = [p for p in _review_role(repo) if p != "claude"]
    if not provider:
        return role
    order = [provider]
    for p in role:
        if p != provider:
            order.append(p)
    return order


def _find_launcher_ps1() -> Path:
    if hasattr(caddis_routing, "__file__") and caddis_routing.__file__:
        routing_dir = Path(caddis_routing.__file__).resolve().parent
        if (routing_dir / "claude-oss.ps1").is_file():
            return routing_dir / "claude-oss.ps1"
    this_dir = Path(__file__).resolve().parent
    if (this_dir / "claude-oss.ps1").is_file():
        return this_dir / "claude-oss.ps1"
    harness_script = Path(__file__).resolve().parents[1] / "claude-harness" / "scripts" / "claude-oss.ps1"
    if harness_script.is_file():
        return harness_script
    return this_dir / "claude-oss.ps1"


def launch(provider: str, prompt: str, cwd: Path) -> tuple[int, str]:
    shell = "pwsh" if shutil.which("pwsh") else "powershell"
    script = _find_launcher_ps1()
    cmd = [
        shell, "-NoProfile", "-File", str(script),
        provider, "-p", "--permission-mode", "plan",
        "--output-format", "json", prompt,
    ]
    # Print mode returns only the LAST message. A reviewer that starts a background task ends on a note about that task,
    # and the verdict is lost (seen with DeepSeek on 10 Oct 2026). claude-oss.ps1 sets this for GLM only.
    env = {**os.environ, "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1"}
    # stdin closed: started from a background shell with an open stdin, the launcher hung 40 minutes (10 Oct 2026).
    res = subprocess.run(cmd, cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", env=env)
    if res.returncode != 0 and res.stderr:
        # A limit or key message often comes on stderr; keep it for the switch decision.
        return res.returncode, (res.stdout + "\n" + res.stderr).strip() + "\n"
    return res.returncode, res.stdout


def _leading_json(output: str) -> object:
    """The JSON value at the start of `output`; text after it (stderr appended on a failed run) is ignored."""
    return json.JSONDecoder().raw_decode(output.lstrip())[0]


def _usage(output: str) -> tuple[int, int] | None:
    """(input tokens, output tokens) from `claude -p --output-format json`, or None when absent."""
    try:
        usage = _leading_json(output).get("usage", {})
        return int(usage.get("input_tokens", 0)) + int(usage.get("cache_read_input_tokens", 0)) + int(
            usage.get("cache_creation_input_tokens", 0)), int(usage.get("output_tokens", 0))
    except (ValueError, AttributeError, TypeError):
        return None


def _verdicts(text: str) -> set[str]:
    found = set()
    for line in text.splitlines():
        cleaned = line.strip().strip("*`").strip()
        if cleaned in ("VERDICT: APPROVE", "VERDICT: CHANGES"):
            found.add(cleaned.split()[-1])
    return found


def _extract_review_text(output: str) -> str:
    try:
        data = _leading_json(output)
        if isinstance(data, dict) and isinstance(data.get("result"), str):
            return data["result"]
    except Exception:
        pass
    return output


def run_review(
    *,
    worktree: Path,
    card: Path,
    providers: list[str],
    out_dir: Path,
    launch,
    base: str = "origin/main",
    contract: Path | None = None,
    budget=None,
    record=None,
) -> int:
    """Review the worktree's diff with the first provider that can run. Optional spend hooks (the CLI passes none
    since the programme ledger went, caddis-next Phase 7): `budget(provider)` returns 0 when the call is inside a
    budget, else an exit code (nothing is called). `record(provider, tokens_in, tokens_out)` records one call and
    returns True; False stops the review, because spend that is not recorded would let the cap pass unseen."""
    card = Path(card)
    worktree = Path(worktree)
    out_dir = Path(out_dir)

    if not card.is_file():
        print(f"caddis_review: card missing: {card}", file=sys.stderr)
        return caddis_exit.ERROR

    res = subprocess.run(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"],
        cwd=worktree,
        capture_output=True,
        check=True,
    )
    untracked_raw = [f for f in res.stdout.split(b"\0") if f]
    untracked_files = [os.fsdecode(f) for f in untracked_raw]

    try:
        if untracked_files:
            # Inside the try: a partial add is undone too.
            subprocess.run(["git", "add", "-N", "--", *untracked_files], cwd=worktree, check=True)
        prompt_lines = [
            f"Review the changes in this worktree against card {card}.",
            f"Card: {card}",
            f"Base: git diff {base}",
        ]
        if contract is not None:
            prompt_lines.append(f"Contract: {contract}")
        prompt_lines.extend([
            "Pass criteria: Check correctness against the card's pass criteria.",
            "Checks: a test that cannot fail, silent failures, the repo's own landmines.",
            "Instructions:",
            "- Do not edit files.",
            "- Do not run git commands that change anything.",
            "- Return exactly one line VERDICT: APPROVE or VERDICT: CHANGES, then at most 10 findings with file:line and severity (blocker/major/minor).",
        ])
        # One line: the prompt is an argument to claude-oss.ps1 and then to claude, an npm .cmd shim on Windows that
        # cuts a multi-line argument at its first newline (.caddis/kb/headless-runner-probes.md).
        prompt = " ".join(prompt_lines)

        out_dir.mkdir(parents=True, exist_ok=True)
        # Provider output can hold a key (a launcher that echoes its env, 10 Oct 2026): mask the values from the
        # keys file before anything is parsed, printed or written.
        masks = caddis_redact.load_secrets(Path.home())
        raw_launch = launch

        def launch(provider, prompt, cwd):  # noqa: F811 - every provider call returns masked output
            code, text = raw_launch(provider, prompt, cwd=cwd)
            return code, caddis_redact.redact(text, masks)

        idx = 0
        while idx < len(providers):
            provider = providers[idx]
            next_provider = providers[idx + 1] if idx + 1 < len(providers) else None

            for attempt in range(2):
                budget_code = budget(provider) if budget is not None else caddis_exit.CLEAN
                if budget_code != caddis_exit.CLEAN:
                    reason = ("budget cap reached" if budget_code == caddis_exit.BLOCKED
                              else f"budget cannot be checked (spend check exit {budget_code})")
                    called = "nothing more was called (one billed attempt)" if attempt else "nothing was called"
                    print(f"REVIEW {provider}: FAILED {reason}; {called}")
                    return caddis_exit.BLOCKED
                t0 = time.monotonic()
                code, output = launch(provider, prompt, cwd=worktree)
                duration = int(time.monotonic() - t0)
                tokens = _usage(output)
                if record is not None:
                    # Known usage is always recorded. A completed run with no usage has unknown spend: stop. A failed
                    # run with no usage (no key, usage error, limit text) is most likely not billed: warn, then retry
                    # or switch as usual.
                    if tokens is not None and record(provider, *tokens) is False:
                        print(f"REVIEW {provider}: FAILED the call's spend was not recorded; stopping")
                        return caddis_exit.BLOCKED
                    if tokens is None and code == 0:
                        print(f"REVIEW {provider}: FAILED the call completed but reported no usage; stopping")
                        return caddis_exit.BLOCKED
                    if tokens is None:
                        print(f"WARNING: {provider} exit {code} reported no usage; no spend line written")
                if code != 2:
                    break

            # Limit text counts only when the run gave no verdict: a review may quote such text from the code.
            has_usage_limit = bool(USAGE_LIMIT_RE.search(output)) and not (
                code == 0 and _verdicts(_extract_review_text(output)))
            needs_switch = (code == 3) or (code == 2) or has_usage_limit

            # Again after the JSON decode: an escaped key form that survived in the raw JSON is plain text now.
            review_text = caddis_redact.redact(_extract_review_text(output), masks)
            review_file = out_dir / f"{card.stem}-{provider}.txt"
            content = review_text.rstrip("\r\n") + f"\nEXIT {code} secs {duration}\n"

            if needs_switch:
                if code == 3:
                    reason = "exit 3"
                elif code == 2:
                    reason = "exit 2"
                elif has_usage_limit:
                    reason = "usage limit reached"
                else:
                    reason = f"exit {code}"

                if next_provider is not None:
                    switch_line = f"SWITCH {provider} -> {next_provider}: {reason}"
                    print(switch_line)
                    content += switch_line + "\n"
                    review_file.write_text(content, encoding="utf-8")
                    idx += 1
                    continue
                else:
                    review_file.write_text(content, encoding="utf-8")
                    print(f"caddis_review: no further providers available (failed on {provider}: {reason})")
                    return caddis_exit.NOT_RUN

            review_file.write_text(content, encoding="utf-8")

            verdicts = _verdicts(review_text)

            if len(verdicts) == 1:
                verdict = next(iter(verdicts))
                print(f"REVIEW {provider}: {verdict}")
                return caddis_exit.CLEAN if verdict == "APPROVE" else caddis_exit.BLOCKED
            else:
                print(f"REVIEW {provider}: FAILED no verdict line")
                return caddis_exit.BLOCKED

        print("caddis_review: no providers configured", file=sys.stderr)
        return caddis_exit.NOT_RUN
    finally:
        if untracked_files:
            undo = subprocess.run(["git", "reset", "-q", "--", *untracked_files], cwd=worktree, check=False,
                                  capture_output=True, text=True)
            if undo.returncode != 0:
                print(f"WARNING: intent-to-add not undone in {worktree} (git reset exit {undo.returncode}): "
                      f"{undo.stderr.strip()}; run: git reset -q -- <new files>")


# -- plan-phase review: Claude with the review protocol, k independent runs, findings merged ---------------------------

_HERE = Path(__file__).resolve().parent
PROTOCOL_NAME = "review-protocol.md"
CLAUDE_TIMEOUT_SECS = 30 * 60
MAX_BUDGET_USD = 5
# One shell command may run at most this long. A reviewer that ran whole suites in the background and polled them
# with `sleep 590` spent the full 1800 s on two runs in a row (12 Oct 2026), so every run was NOT_RUN.
BASH_MAX_MS = 180_000
TIME_RULE = (
    f"TIME LIMIT: this whole review must finish within {CLAUDE_TIMEOUT_SECS // 60} minutes of wall-clock time; at the "
    f"limit the run is killed and discarded. Each command is cut off after {BASH_MAX_MS // 60_000} minutes. Run only "
    "targeted checks: one test file or a `-k` selection, a dry run, a probe script. Never run a whole test suite (the "
    "implementer and CI run it), never start a command in the background (`&`, `nohup`, `start`), and never wait or "
    "poll (`sleep`, `timeout`, `tail` loops). When a check would take longer, skip it and write one line "
    "`not executed: <command> (too slow)` in step 4."
)
HASH_LIMIT_BYTES = 50 * 1024 * 1024
SEVERITY_RANK = {"nit": 0, "should-fix": 1, "blocking": 2}
# Look-alike letters of the word "finding" (Cyrillic, Greek, Armenian, IPA) mapped to ASCII, for detection only.
_CONFUSABLES = str.maketrans({
    "\u03dc": "f", "\u03dd": "f", "\u0493": "f", "\u0492": "f",
    "\u0456": "i", "\u0406": "i", "\u04c0": "i", "\u04cf": "i", "\u03b9": "i", "\u0399": "i", "\u0131": "i",
    "\u026a": "i", "\u0269": "i", "\u01c0": "i", "\u2160": "i",
    "\u039d": "n", "\u0578": "n", "\u0274": "n", "\u043f": "n", "\u0438": "n",
    "\u0501": "d", "\u0500": "d", "\u0257": "d", "\u13e7": "d",
    "\u0261": "g", "\u050d": "g", "\u050c": "g", "\u0262": "g",
})
# A list, quote, table or heading prefix: `- `, `* `, `+ `, `> `, `1. `, `1) `, `| `, `#`, backticks and whitespace.
_LEAD_RE = re.compile(r"^(?:[\s>*+|`#-]|\d+[.)](?=\s))+")
# Anywhere in a (normalized) line: it names a finding, so it must be one, else the run is NOT_RUN.
_FINDING_MENTION_RE = re.compile(r"finding\s*[-#:(]?\s*\d", re.IGNORECASE)
_FINDING_RE = re.compile(r"^finding\s*[#:]?\s*(\d+)\s*\|\s*([a-z_ -]+?)\s*\|\s*([^|]*?\S)\s*\|\s*(.*\S)$",
                         re.IGNORECASE)
# Anywhere in a line: two of these on one line are two findings run together, which the per-line parser cannot split.
_FINDING_ANYWHERE_RE = re.compile(r"finding\s*[#:]?\s*\d+\s*\|", re.IGNORECASE)
_END_RE = re.compile(r"^END REVIEW\s+(\d+)$", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,3} ")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
# A closing fence: only the fence characters (at least as many as the opening one), nothing after them.
_FENCE_CLOSE_RE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
# A Risk line in any markup: `Risk:`, `**Risk:**`, `__Risk:__`, `**Risk** :`, `Risk level =`, after a list, quote,
# heading or task-list marker. Not preceded or followed by a letter or digit (`_` counts as markup, unlike `\b`).
# A Risk MARKER line: the label starts the line, after only markup (list, task box, quote, heading, emphasis).
# Prose that mentions "risk: high" mid-sentence is not a marker (the real-run review of 12 Oct: Phases 11 and 12
# say "for risk: high phases" and must not become high).
_RISK_RE = re.compile(r"^[\s>*_`~#+\-\[\]xX]*(?:\d+[.)]\s*)?[\s*_`~\[\]xX]*risk(?:\s+level)?(?![a-z0-9])[\W_]{0,6}?\s*[:=]",
                      re.IGNORECASE)
# A table row whose cell is `Risk` (or `Risk level`), in any markup: the value is the next cell.
_RISK_CELL_RE = re.compile(r"^\s*\|\s*[*_`~]*\s*risk(?:\s+level)?\s*[*_`~]*\s*\|([^|]*)", re.IGNORECASE)
_RISK_ORDER = ("low", "normal", "medium", "high")
MAX_RUNS = 3
MAX_ROUNDS = 3  # review rounds per phase; the next one exits ROUND_LIMIT, the owner decides
# Folders a run may legitimately write to in the live repo (tool caches, installs, builds): not hashed when git reports
# the folder itself as ignored, except the high-risk files in them (`_risky_file`).
_SNAPSHOT_SKIP_PARTS = frozenset({".venv", "venv", "node_modules", "dist", "build", "__pycache__", ".mypy_cache",
                                  ".pytest_cache", ".ruff_cache", ".tox", ".cache", ".next", "coverage", ".git"})
# High-risk files inside a skipped folder, always hashed: they change what Python or a tool runs next time.
_RISKY_NAMES = frozenset({"pyvenv.cfg", "sitecustomize.py", "usercustomize.py"})
_GIT_FLAGS = ("--no-optional-locks", "-c", "core.fsmonitor=false")
_CARD_FIELDS = ("Goal", "Touches", "Exit gate")
_PREFIX = "caddis_review: "
FOLLOW_UP_HEADING = "## Follow-up (not blocking)"


@dataclass(frozen=True)
class Finding:
    severity: str
    location: str
    scenario: str

    def line(self, n: int) -> str:
        return f"FINDING {n} | {self.severity} | {self.location} | {self.scenario}"


def find_protocol() -> Path | None:
    """The review protocol shipped with the roadmap skill: the source tree first, then an installed bundle."""
    for candidate in (_HERE.parent / ".github" / "skills" / "workflow" / "roadmap" / "assets" / PROTOCOL_NAME,
                      _HERE.parent / "skills" / "roadmap" / "assets" / PROTOCOL_NAME):
        if candidate.is_file():
            return candidate
    return None


def default_governor() -> list[str] | None:
    """`caddis_governor.py exec --scope session --`, preferring the admin-installed copy (as caddis-run.ps1 does)."""
    installed = Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "caddis" / "caddis_governor.py"
    for gov in (installed, _HERE / "caddis_governor.py", _HERE.parent / "claude-harness" / "scripts" / "caddis_governor.py"):
        if gov.is_file():
            return [sys.executable, str(gov), "exec", "--scope", "session", "--"]
    return None


def phase_section(plan: Path, n: int | str) -> str:
    """The text from the heading `### Phase <n> ` to the next heading of level 1-3 outside a code fence."""
    start = f"### Phase {n} "
    section: list[str] | None = None
    fence = ""
    for line in Path(plan).read_text(encoding="utf-8").splitlines():
        heading = not fence and _HEADING_RE.match(line)
        if not fence:
            m = _FENCE_RE.match(line)
            fence = m.group(1) if m else ""
        else:
            m = _FENCE_CLOSE_RE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = ""
        if section is None:
            if heading and line.startswith(start):
                section = [line]
        elif heading:
            break
        else:
            section.append(line)
    if section is None:
        raise ValueError(f"no heading '### Phase {n} ' in {plan}")
    return "\n".join(section).rstrip() + "\n"


def phase_risk(plan: Path, n: int | str) -> str:
    """The phase's risk, failing closed. A Risk line is a line (after `_normalize`) that STARTS with `Risk:` or
    `Risk level:` after only markup, or a table row whose first cell is `Risk`. Its value is the first word after it, markup stripped: `normal`,
    `low` or `medium` give that value, anything else (`high`, `very high`, `critical`, none) gives `high`. The highest
    of several Risk lines wins. No Risk line: `normal`."""
    values = []
    for raw in phase_section(plan, n).splitlines():
        line = _normalize(raw)
        cell = _RISK_CELL_RE.search(line)
        m = cell or _RISK_RE.match(line)
        if m is None:
            continue
        rest = cell.group(1) if cell else line[m.end():]
        word = re.match(r"""[\s*_`~>|\[\]()"']*([a-z]+)""", rest.lower())
        value = word.group(1) if word else ""
        values.append(value if value in _RISK_ORDER[:3] else "high")
    return max(values, key=_RISK_ORDER.index) if values else "normal"


def plan_card(plan: Path, n: int | str, plan_ref: str | None = None) -> str:
    """The review card for one plan phase: its heading, Goal, Touches and Exit gate."""
    lines = phase_section(plan, n).splitlines()
    fields = {}
    for line in lines:
        for name in _CARD_FIELDS:
            if line.startswith(f"**{name}:**") and name not in fields:
                fields[name] = line[len(name) + 5:].strip()
    card = [f"# Card: {lines[0].lstrip('#').strip()}", f"Plan: {plan_ref or plan}, section '### Phase {n} '", ""]
    for name in _CARD_FIELDS:
        card.append(f"**{name}:** {fields.get(name, '(not in the plan section; read the section itself)')}")
    return "\n".join(card) + "\n"


def _normalize(line: str) -> str:
    """NFKC (full-width and other compatibility forms become ASCII), then every format character (Unicode category
    Cf: zero-width space and joiners, LRM, RLM, U+202A-202E, word joiner, BOM, soft hyphen) removed."""
    return "".join(c for c in unicodedata.normalize("NFKC", line) if unicodedata.category(c) != "Cf")


def _skeleton(line: str) -> str:
    """For detection only: accents dropped and look-alike letters mapped to ASCII, so `FІNDING 1` (Cyrillic І) or
    `fíndíng 1` still counts as a line that names a finding."""
    decomposed = unicodedata.normalize("NFKD", line.translate(_CONFUSABLES))
    return "".join(c for c in decomposed if not unicodedata.combining(c)).translate(_CONFUSABLES)


def _clean(line: str) -> str:
    """The line after `_normalize`, without a list, quote, table or heading prefix, bold or code marks and a
    trailing `|`."""
    text = _LEAD_RE.sub("", _normalize(line)).rstrip().rstrip("*`").rstrip()
    if text.endswith("|"):
        text = text[:-1].rstrip().rstrip("*`").rstrip()
    return text


def _scan(text: str) -> tuple[list[Finding], list[str]]:
    """(findings, bad lines). Decided per line, failing closed: a line that names a finding anywhere (`finding`, an
    optional `-`, `#`, `:` or `(`, then a digit; any case, after `_normalize`, look-alike letters included) either is
    a full finding after `_clean` or is a bad line, which makes the run NOT_RUN. So is a line with two
    `FINDING <n> |`."""
    findings, bad = [], []
    for raw in text.splitlines():
        line = _clean(raw)
        if len(_FINDING_ANYWHERE_RE.findall(line)) > 1:
            bad.append(line)
            continue
        if not _FINDING_MENTION_RE.search(_skeleton(_normalize(raw))):
            continue
        m = _FINDING_RE.match(line)
        severity = re.sub(r"[_ ]", "-", m.group(2).lower()) if m else ""
        if severity in SEVERITY_RANK:
            findings.append(Finding(severity, m.group(3), m.group(4)))
        else:
            bad.append(line)
    return findings, bad


def parse_findings(text: str) -> list[Finding]:
    """Every `FINDING <n> | <severity> | <file>:<line> | <scenario>` line; other lines (VERDICT included) are ignored."""
    return _scan(text)[0]


def _location_key(location: str) -> str:
    key = location.strip().replace("\\", "/")
    return key[2:] if key.startswith("./") else key


def merge_findings(runs: list[list[Finding]]) -> list[Finding]:
    """Every distinct (location, scenario); an exact duplicate keeps its highest severity. Blocking first, then
    should-fix, then nit; first appearance within a severity."""
    best: dict[tuple[str, str], Finding] = {}
    for run in runs:
        for finding in run:
            key = (_location_key(finding.location), " ".join(finding.scenario.split()).lower())
            kept = best.get(key)
            if kept is None or SEVERITY_RANK[finding.severity] > SEVERITY_RANK[kept.severity]:
                best[key] = finding
    return sorted(best.values(), key=lambda f: -SEVERITY_RANK[f.severity])


def check_complete(output: str) -> tuple[str, str, float | None]:
    """(review text, problem, cost in USD). `problem` is "" only for a run that completed: JSON with `is_error: false`
    and `subtype: "success"`, whose result ends with `END REVIEW <k>`, k = the number of findings, every line that
    starts like a finding is one, and `NO FINDINGS` when k is 0. A run with a problem is NOT_RUN, whatever it found."""
    if output.startswith(_PREFIX):
        return output, output.splitlines()[0][len(_PREFIX):], None
    try:
        data = _leading_json(output)
    except ValueError:
        return output, "output is not JSON (cut off, timed out or not started)", None
    if not isinstance(data, dict):
        return output, "output is not a JSON object", None
    text = data.get("result") if isinstance(data.get("result"), str) else ""
    cost = data.get("total_cost_usd")
    cost = float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None
    if data.get("is_error") is not False:
        return text, f"is_error is {data.get('is_error')!r}, not false", cost
    if data.get("subtype") != "success":
        return text, f"subtype is {data.get('subtype')!r}, not 'success'", cost
    lines = [c for c in (_clean(line) for line in text.splitlines()) if c]
    end = _END_RE.match(lines[-1]) if lines else None
    if end is None:
        return text, "the last line is not 'END REVIEW <count>'", cost
    count = int(end.group(1))
    findings, bad = _scan(text)
    if bad:
        return text, (f"{len(bad)} line(s) name a finding but are not "
                      f"'FINDING <n> | blocking|should-fix|nit | <file>:<line> | <text>': {bad[0][:120]}"), cost
    if count != len(findings):
        return text, f"END REVIEW {count} but {len(findings)} FINDING line(s)", cost
    no_findings = any(line.upper() == "NO FINDINGS" for line in lines)
    if count == 0 and not no_findings:
        return text, "END REVIEW 0 without a NO FINDINGS line", cost
    if count and no_findings:
        return text, "NO FINDINGS next to FINDING lines", cost
    return text, "", cost


def _kill_tree(proc) -> None:
    """Kill the child and everything it started (it runs in its own process group / session)."""
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            proc.kill()


def launch_claude(prompt: str, worktree: Path, out: Path) -> str:
    """One review run: `claude -p` in `worktree`, the prompt on stdin. Writes the masked output to `out`, returns it.
    A timeout, a start failure or a non-zero exit returns a `caddis_review: ` line first, which makes the run NOT_RUN."""
    # Not plan mode: in plan mode the reviewer refuses any command that writes a file, so it cannot run the tests
    # (tested 11 Oct 2026). Edit tools are off; the live repo is checked by the caller, because Bash can still write.
    cmd = [shutil.which("claude") or "claude", "-p", "--model", "opus", "--permission-mode", "bypassPermissions",
           "--disallowedTools", "Edit Write NotebookEdit Bash(sleep:*)", "--output-format", "json",
           "--max-budget-usd", str(MAX_BUDGET_USD)]
    governor = default_governor()
    if governor:
        cmd = governor + cmd
    else:
        print("WARNING: caddis_governor.py not found; the review runs without a CPU and memory cap", file=sys.stderr)
    # CADDIS_HEADLESS keeps relay and session-end hooks quiet (claude-oss.ps1 sets it too).
    # The Bash timeouts make a slow or polling command fail fast instead of eating the run's 30 minutes.
    env = {**os.environ, "CADDIS_HEADLESS": "1", "CLAUDE_CODE_DISABLE_BACKGROUND_TASKS": "1",
           "BASH_DEFAULT_TIMEOUT_MS": str(BASH_MAX_MS), "BASH_MAX_TIMEOUT_MS": str(BASH_MAX_MS)}
    # Its own process group (Windows) or session (POSIX), so a timeout kills the whole tree, not only the top process.
    group = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt"
             else {"start_new_session": True})
    masks = caddis_redact.load_secrets(Path.home())
    try:
        proc = subprocess.Popen(cmd, cwd=worktree, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace", env=env, **group)
    except OSError as exc:
        output = f"{_PREFIX}claude could not start: {exc}\n"
    else:
        finished = False
        try:
            try:
                # Prompt on stdin: the npm .cmd shim on Windows cuts a multi-line argument at its first newline.
                stdout, stderr = proc.communicate(prompt, timeout=CLAUDE_TIMEOUT_SECS)
            except subprocess.TimeoutExpired:
                _kill_tree(proc)
                try:
                    stdout, stderr = proc.communicate(timeout=60)
                except subprocess.TimeoutExpired:
                    stdout, stderr = "", ""
                output = f"{_PREFIX}claude timed out after {CLAUDE_TIMEOUT_SECS} s; process tree killed\n{stdout or ''}"
            else:
                output = stdout or ""
                if proc.returncode != 0:
                    output = f"{_PREFIX}claude exited {proc.returncode}\n{output}\n{stderr or ''}".rstrip() + "\n"
            finished = True
        finally:
            # Ctrl+C (KeyboardInterrupt) or any other exception: kill the tree, so no reviewer runs on orphaned; the
            # exception then propagates.
            if not finished:
                _kill_tree(proc)
    output = caddis_redact.redact(output, masks)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(output, encoding="utf-8")
    return output


def _git_out(repo: Path, *args: str, ok: tuple[int, ...] = (0,)) -> str:
    """git's stdout; an exit code not in `ok` raises CalledProcessError with stderr. `--no-optional-locks`: a read
    (`git status`) never rewrites the index, so a snapshot does not change what it measures. `core.fsmonitor=false`:
    no fsmonitor hook (a program the repo config names) runs, and status does not trust its answers."""
    res = subprocess.run(["git", *_GIT_FLAGS, *args], cwd=repo, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    if res.returncode not in ok:
        raise subprocess.CalledProcessError(res.returncode, res.args, res.stdout, res.stderr)
    return res.stdout


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, subprocess.CalledProcessError):
        cmd = exc.cmd if isinstance(exc.cmd, list) else [str(exc.cmd)]
        args = cmd[1 + len(_GIT_FLAGS):] if tuple(cmd[1:1 + len(_GIT_FLAGS)]) == _GIT_FLAGS else cmd[1:]
        return f"git {' '.join(args)} exited {exc.returncode}: {(exc.stderr or '').strip()}"
    return f"{type(exc).__name__}: {exc}"


def _default_base(repo: Path) -> str:
    res = subprocess.run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], cwd=repo,
                         capture_output=True, text=True)
    return res.stdout.strip() if res.returncode == 0 and res.stdout.strip() else "origin/main"


def _inside(path: Path, folder: Path) -> bool:
    return path == folder or folder in path.parents


def _is_link(st: os.stat_result) -> bool:
    """A symlink, or on Windows any reparse point (a junction included), from `os.lstat`."""
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    return stat.S_ISLNK(st.st_mode) or bool(getattr(st, "st_file_attributes", 0) & reparse)


def _unlink_link(path: str, st: os.stat_result) -> None:
    """Remove the link itself, never its target: on Windows a junction or a directory symlink with os.rmdir, any
    other link with os.unlink."""
    directory = getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0x10)
    if os.name == "nt" and getattr(st, "st_file_attributes", 0) & directory:
        os.rmdir(path)
    else:
        os.unlink(path)


def _remove_links(top: Path) -> None:
    """Remove every symlink and junction at or under `top`, bottom-up, never following one. Raises OSError when a link
    cannot be removed: the caller must then delete nothing, because a delete through a link destroys its target."""
    st = os.lstat(top)
    if _is_link(st):
        _unlink_link(str(top), st)
        return
    folders = [str(top)]
    order: list[str] = []
    while folders:                      # top-down collection of real folders only; a link is never entered
        folder = folders.pop()
        order.append(folder)
        with os.scandir(folder) as entries:
            for entry in entries:
                entry_st = os.lstat(entry.path)
                if not _is_link(entry_st) and stat.S_ISDIR(entry_st.st_mode):
                    folders.append(entry.path)
    for folder in reversed(order):      # bottom-up removal of the links in each folder
        with os.scandir(folder) as entries:
            found = [(entry.path, os.lstat(entry.path)) for entry in entries]
        for path, entry_st in found:
            if _is_link(entry_st):
                _unlink_link(path, entry_st)


def _file_hash(path: Path) -> str:
    try:
        st = os.lstat(path)
        if _is_link(st):
            return f"link -> {os.readlink(path)}"
        if st.st_size > HASH_LIMIT_BYTES:
            return f"size {st.st_size} mtime {st.st_mtime_ns}"
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except FileNotFoundError:
        return "missing"
    except OSError as exc:
        return f"unreadable ({type(exc).__name__})"


def _is_venv(folder: Path) -> bool:
    return folder.name in (".venv", "venv") or os.path.lexists(folder / "pyvenv.cfg")


def _risky_file(path: Path) -> bool:
    """A file that changes what Python or a tool runs next: `pyvenv.cfg`, a `.pth` file, `sitecustomize.py`,
    `usercustomize.py`, a file directly in a venv's `Scripts/` or `bin/`, or a file in `node_modules/.bin/`."""
    parent = path.parent
    return (path.name in _RISKY_NAMES or path.name.endswith(".pth")
            or (parent.name in ("Scripts", "bin") and _is_venv(parent.parent))
            or (parent.name == ".bin" and parent.parent.name == "node_modules"))


def _entries(current: Path, folder: Path, label: str, snap: dict[str, str]) -> list[tuple[Path, str, os.stat_result]]:
    """(path, snap key, lstat) of each entry of `current`, sorted; a folder or entry that cannot be read is recorded as
    unreadable in `snap`."""
    try:
        with os.scandir(current) as it:
            names = sorted(it, key=lambda e: e.name)
    except FileNotFoundError:
        return []
    except OSError as exc:
        snap[f"{label}{current.relative_to(folder).as_posix()}/"] = f"unreadable ({type(exc).__name__})"
        return []
    found = []
    for entry in names:
        path = Path(entry.path)
        key = f"{label}{path.relative_to(folder).as_posix()}"
        try:
            found.append((path, key, os.lstat(path)))
        except OSError as exc:
            snap[key] = f"unreadable ({type(exc).__name__})"
    return found


def _hash_risky(folder: Path, label: str, snap: dict[str, str]) -> None:
    """Only the `_risky_file` files under `folder` (an ignored cache folder), without following a link. Inside a
    `node_modules` folder only `.bin/` is entered: its packages are not walked (too many files)."""
    stack = [folder]
    while stack:
        current = stack.pop()
        for path, key, st in _entries(current, folder, label, snap):
            if not _is_link(st) and stat.S_ISDIR(st.st_mode):
                if path.name != ".git" and (current.name != "node_modules" or path.name == ".bin"):
                    stack.append(path)
            elif _risky_file(path):
                snap[key] = _file_hash(path)


def _hash_folder(folder: Path, label: str, snap: dict[str, str], skip: Path | None = None, skipped=None) -> None:
    """`snap["<label><relative path>"]` = the content hash of every file under `folder`, without following a link and
    without entering `skip`. For a folder where `skipped(path)` is True only its `_risky_file` files are hashed; where
    it is None the folder is left out."""
    stack = [folder]
    while stack:
        current = stack.pop()
        for path, key, st in _entries(current, folder, label, snap):
            if not _is_link(st) and stat.S_ISDIR(st.st_mode):
                if skip is not None and _inside(path.resolve(), skip):
                    continue
                verdict = skipped(path) if skipped is not None else False
                if verdict:
                    _hash_risky(path, f"{key}/", snap)
                elif verdict is not None:
                    stack.append(path)
            else:
                snap[key] = _file_hash(path)


def _snapshot(root: Path, skip: Path) -> dict[str, str]:
    """Everything of the live repo a run could change, as {what: fingerprint}: HEAD and what it points at, `git status`
    (porcelain v2: it holds the HEAD and index object ids), the content of each tracked file changed in the work
    tree, every ref, `.git/config`, `.git/config.worktree`, `.git/index`, every file under `.git/hooks/` and
    `.git/info/`, `git config --list --show-origin --show-scope` (every scope: system, global, local, worktree,
    command, with their include files), and the content of every untracked and ignored file. Not hashed: `skip` (the
    out-dir), nested `.git` folders, files over 50 MB (size and mtime only), and a tool cache or install folder
    (`_SNAPSHOT_SKIP_PARTS`) that git reports as ignored at its own path - except its `_risky_file` files, which are
    always hashed. An untracked folder that is not ignored is always hashed in full, whatever its name. Every git call
    passes `-c core.fsmonitor=false`. A git error raises CalledProcessError; the caller makes the run NOT_RUN."""
    skip = skip.resolve()
    ignored = {name for name in _git_out(root, "ls-files", "--others", "--ignored", "--exclude-standard",
                                         "--directory", "-z").split("\0") if name.endswith("/")}

    def skipped_rel(rel: str) -> bool:
        return rel.rstrip("/").rsplit("/", 1)[-1] in _SNAPSHOT_SKIP_PARTS and rel.rstrip("/") + "/" in ignored

    def skipped(path: Path) -> bool | None:
        """None for a nested `.git` (never hashed); True for a cache folder that git reports as ignored itself."""
        if path.name == ".git":
            return None
        try:
            rel = path.relative_to(root).as_posix()
        except ValueError:
            return False
        return skipped_rel(rel)

    paths = _git_out(root, "rev-parse", "--git-path", "config", "--git-path", "config.worktree", "--git-path", "index",
                     "--git-path", "hooks", "--git-path", "info").splitlines()
    config, config_worktree, index, hooks, info = ((root / p).resolve() for p in paths)
    snap = {"HEAD": _git_out(root, "rev-parse", "HEAD").strip(),
            "symbolic HEAD (git symbolic-ref)": _git_out(root, "symbolic-ref", "-q", "HEAD", ok=(0, 1)).strip(),
            # Every scope with its origin: a global or system change (core.hooksPath, an alias, a credential helper,
            # an include) changes what git runs next, in this repo too.
            "git config (every scope)": _git_out(root, "config", "--list", "--show-origin", "--show-scope"),
            ".git/config": _file_hash(config),
            ".git/config.worktree": _file_hash(config_worktree),
            ".git/index": _file_hash(index)}
    # Not `git diff HEAD`: it refreshes and rewrites the index even with --no-optional-locks (tested 12 Oct 2026).
    # Porcelain v2 holds the HEAD and index object ids; the work-tree content of a changed tracked file is hashed here.
    entries = iter(_git_out(root, "status", "--porcelain=v2", "--untracked-files=normal", "-z").split("\0"))
    for entry in entries:
        kind = entry[:2]
        if kind == "? ":
            if not _inside((root / entry[2:]).resolve(), skip):
                snap[f"status '{entry}'"] = ""
            continue
        fields = {"1 ": 9, "2 ": 10, "u ": 11}.get(kind)
        if fields is None:
            continue
        snap[f"status '{entry}'"] = ""
        if kind == "2 ":
            next(entries, None)         # the rename's original path
        name = entry.split(" ", fields - 1)[-1]
        if entry[3] != ".":             # changed in the work tree: its content counts, not only its status
            snap[f"worktree {name}"] = _file_hash(root / name)
    for line in _git_out(root, "for-each-ref", "--format=%(refname) %(objectname)").splitlines():
        ref, _sep, obj = line.rpartition(" ")
        snap[f"ref {ref}"] = obj
    _hash_folder(hooks, "hook ", snap)
    _hash_folder(info, "git info/", snap)
    # Without --exclude-standard, --others lists untracked AND ignored entries; --directory lists a folder with no
    # tracked file once (`node_modules/`), so an ignored cache folder is never listed file by file.
    risky_done: set[str] = set()
    for name in _git_out(root, "ls-files", "--others", "--directory", "-z").split("\0"):
        if not name or _inside((root / name).resolve(), skip):
            continue
        parts = name.rstrip("/").split("/")
        if ".git" in parts:
            continue
        cut = next((i for i in range(len(parts)) if skipped_rel("/".join(parts[:i + 1]))), None)
        if cut is not None:
            # An ignored cache folder (or an entry inside one): only its high-risk files.
            prefix = "/".join(parts[:cut + 1])
            if prefix not in risky_done:
                risky_done.add(prefix)
                _hash_risky(root / prefix, f"file {prefix}/", snap)
            continue
        if name.endswith("/"):
            _hash_folder(root / name.rstrip("/"), f"file {name}", snap, skip, skipped)
        else:
            snap[f"file {name}"] = _file_hash(root / name)
    return snap


def _live_changes(before: dict[str, str], after: dict[str, str]) -> list[str]:
    return [key for key in sorted(before.keys() | after.keys()) if before.get(key) != after.get(key)]


def _review_worktrees(root: Path) -> list[Path]:
    listing = _git_out(root, "worktree", "list", "--porcelain")
    return [Path(line[len("worktree "):]) for line in listing.splitlines()
            if line.startswith("worktree ") and Path(line[len("worktree "):]).name.startswith("caddis-review-")]


def _drop_registration(root: Path, path: Path) -> None:
    """Remove the admin folder `<git-common-dir>/worktrees/<name>` of the `caddis-review-*` worktree `path` when its
    folder is gone. Never `git worktree prune`: that would also drop the registrations of other tools."""
    if not path.name.startswith("caddis-review-") or os.path.lexists(path):
        return
    admin_root = (root / _git_out(root, "rev-parse", "--git-common-dir").strip()).resolve() / "worktrees"
    if not admin_root.is_dir():
        return
    for admin in admin_root.iterdir():
        try:
            registered = Path((admin / "gitdir").read_text(encoding="utf-8").strip()).parent
        except OSError:
            continue
        if registered.name == path.name and os.path.normcase(os.path.normpath(registered)) == os.path.normcase(
                os.path.normpath(path)):
            _remove_links(admin)
            shutil.rmtree(admin)


def _prune_stale_review_worktrees(root: Path) -> None:
    """Drop `caddis-review-*` registrations whose folder is gone (a crash, a reboot), locked ones included."""
    for path in _review_worktrees(root):
        _drop_registration(root, path)


def _add_worktree(root: Path, head: str, phase: int | str, run: int) -> Path:
    path = Path(tempfile.gettempdir()) / f"caddis-review-{phase}-{run}-{uuid.uuid4().hex[:8]}"
    _git_out(root, "worktree", "add", "--detach", str(path), head)
    return path


def _remove_worktree(root: Path, path: Path) -> str:
    """Remove the run's worktree. "" when it is gone and unregistered, else the problem (the run is then NOT_RUN).
    First every symlink and junction inside it goes, without following any: `git worktree remove` or rmtree through a
    junction would delete the junction's target (a venv, the live repo). If one cannot go, nothing is deleted."""
    try:
        if os.path.lexists(path):
            _remove_links(path)
        # Twice --force: also when the run locked it.
        subprocess.run(["git", "worktree", "remove", "--force", "--force", str(path)], cwd=root, capture_output=True)
        if os.path.lexists(path):
            shutil.rmtree(path)
        _drop_registration(root, path)
        if os.path.lexists(path) or any(p.name == path.name for p in _review_worktrees(root)):
            problem = f"review worktree not removed: {path}"
        else:
            return ""
    except (OSError, subprocess.CalledProcessError) as exc:
        problem = f"review worktree not removed: {path}: {_error_text(exc)}"
    print(f"WARNING: {problem}; remove its links first, then: git worktree remove --force --force {path}")
    return problem


def plan_prompt(protocol_text: str, card_text: str, base_sha: str, head_sha: str, delta: bool = False,
                prior_blocking: list[str] | None = None) -> str:
    """`delta`: `base_sha` is the head the last completed round reviewed, so the diff is only the fix.
    `prior_blocking`: the blocking findings of that round; the reviewer must check each one at `head_sha`, because
    a fix diff alone cannot show that a bug outside it is still there."""
    _meta, _sep, body = protocol_text.partition("\n---\n") if protocol_text.startswith("---") else ("", "", protocol_text)
    what = ("the head the last review round reviewed; this diff is only the fix made since then" if delta
            else "the merge-base with the default branch")
    return "\n".join([
        "You review one phase of a plan. The working folder is a throwaway checkout of the commit under review.",
        f"Diff to review: git diff {base_sha}..{head_sha}",
        f"(base {base_sha} is {what}; head {head_sha} is the commit under review)",
        "",
        TIME_RULE,
        "",
        card_text.rstrip(),
        "",
        *(["The last review round found these BLOCKING issues. For each one, read the whole affected files at "
           f"{head_sha} (not only the diff) and check that it is fixed. Report each one that is not fixed again "
           "as blocking:", *prior_blocking, ""] if prior_blocking else []),
        body.strip(),
        "",
    ])


def _read_rounds(out_dir: Path, phase: int | str) -> list[dict]:
    """The rounds recorded for `phase` in `out_dir`; [] when there is no file. ValueError for a file that is not a list
    of objects: a damaged count must stop the review, not reset the limit."""
    path = out_dir / f"review-{phase}-rounds.json"
    if not path.is_file():
        return []
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"{path} cannot be read ({exc}); fix or delete it") from exc
    if not isinstance(entries, list) or not all(isinstance(e, dict) for e in entries):
        raise ValueError(f"{path} is not a list of rounds; fix or delete it")
    return entries


SKIPPED_DELTA = "SKIPPED delta tier 0"


def _is_completed(entry: dict, plan_ref: str) -> bool:
    """A completed round of this plan: not NOT_RUN and not SKIPPED (a skip launched no reviewer). Entries without a
    plan (older files) count for every plan."""
    result = str(entry.get("result", ""))
    return result != "NOT_RUN" and not result.startswith("SKIPPED") and entry.get("plan", plan_ref) == plan_ref


def _prior_blocking(entries: list[dict], plan_ref: str) -> list[str] | None:
    """The blocking finding lines stored in the last completed (not NOT_RUN, not SKIPPED) round of this plan, or None
    when that round has none or has no `blocking` key (older entries). The merged report is not read: a later NOT_RUN
    run writes over it, and the findings must not be lost."""
    last = next((e for e in reversed(entries) if _is_completed(e, plan_ref)), None)
    if last is None:
        return None
    blocking = last.get("blocking")
    if not isinstance(blocking, list) or not all(isinstance(b, str) for b in blocking):
        return None
    return list(blocking) or None


def _completed_rounds(entries: list[dict], plan_ref: str) -> int:
    """Rounds used: completed runs of this plan. NOT_RUN and SKIPPED entries use no round."""
    return sum(_is_completed(e, plan_ref) for e in entries)


def _is_ancestor(root: Path, older: str, newer: str) -> bool:
    """True only when git says `older` is an ancestor of `newer` (exit 0); exit 1 or any error is False."""
    res = subprocess.run(["git", *_GIT_FLAGS, "merge-base", "--is-ancestor", older, newer], cwd=root,
                         capture_output=True)
    return res.returncode == 0


def _delta_base(root: Path, entries: list[dict], plan_ref: str, base_sha: str, head: str) -> str | None:
    """The head the last completed round of this plan reviewed, when the fix diff `<it>..head` is a real sub-range of
    `base_sha..head`: a descendant of `base_sha`, an ancestor of `head`, not `head` itself, and the diff changes files.
    Else None: review the full range. A stderr note says why, only when a completed round exists."""
    last = next((e for e in reversed(entries) if _is_completed(e, plan_ref)), None)
    if last is None:
        return None
    prev = last.get("head")
    if not isinstance(prev, str) or not re.fullmatch(r"[0-9a-fA-F]{7,64}", prev):
        why = f"the last round has no usable head ({prev!r})"
    else:
        try:
            prev = _git_out(root, "rev-parse", "--verify", "--quiet", f"{prev}^{{commit}}").strip()
        except subprocess.CalledProcessError:
            prev, why = None, f"its head {prev} is not a commit here"
        if prev is None:
            pass
        elif prev == head:
            why = f"the last round reviewed this head {head}"
        elif not _is_ancestor(root, prev, head):
            why = f"its head {prev} is not an ancestor of HEAD {head}"
        elif not _is_ancestor(root, base_sha, prev):
            why = f"its head {prev} is not after the base {base_sha}"
        elif not _git_out(root, "diff", "--name-only", f"{prev}..{head}").strip():
            why = f"the diff {prev}..{head} changes no file"
        else:
            return prev
    print(f"{_PREFIX}previous review head: {why}; reviewing the full range {base_sha}..{head}", file=sys.stderr)
    return None


def _delta_tier(root: Path, rng: str) -> str | None:
    """`caddis_gate.review_tier` of the fix diff with plan risk "normal" (the plan risk would make a high-risk phase
    tier 2 always, so a docs-only fix could never skip). None when it cannot be computed: the delta is then reviewed."""
    try:
        try:
            import caddis_gate  # lazy: caddis_gate imports caddis_review lazily too, so there is no cycle
        except ModuleNotFoundError as exc:
            if exc.name != "caddis_gate":
                raise
            sys.path.insert(0, str(_HERE))
            import caddis_gate
        files = caddis_gate._numstat(rng, root)
        if not files:  # the range changes files (checked before), so no rows means git failed: never a skip
            raise ValueError("git diff --numstat returned no rows")
        return caddis_gate.review_tier(files, "normal")
    except Exception as exc:  # noqa: BLE001 - a tier that cannot be computed is reviewed, never skipped
        print(f"{_PREFIX}review tier of {rng} not computed ({type(exc).__name__}: {exc}); reviewing it",
              file=sys.stderr)
        return None


def _record_round(out_dir: Path, phase: int | str, entries: list[dict], round_no: int | None, plan_ref: str,
                  head: str, result: str, code: int, blocking: list[str] | None = None) -> None:
    """Append one entry to `review-<phase>-rounds.json`. A completed round that is not CLEAN also stores its blocking
    finding lines (`blocking`), so the next delta review can give them to the reviewer again."""
    entry = {"round": round_no, "plan": plan_ref, "utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "head": head,
             "result": result, "exit": code}
    if blocking is not None and result != "NOT_RUN" and not result.startswith("SKIPPED") and code != caddis_exit.CLEAN:
        entry["blocking"] = list(blocking)
    path = out_dir / f"review-{phase}-rounds.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(entries + [entry], indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_results(out_dir: Path, phase: int | str, header: list[str], problems: list[str], costs: list[float | None],
                   merged: list[Finding], code: int, label: str, notes: list[str] | None = None) -> Path:
    """`review-<phase>-cost.json` and `review-<phase>-merged.md` (ends with `END REVIEW <count>`). The `blocking`
    findings come first; `should-fix` and `nit` findings follow under `## Follow-up (not blocking)`."""
    # A run with unknown cost (timeout, crash, no total_cost_usd) may have spent up to its --max-budget-usd.
    (out_dir / f"review-{phase}-cost.json").write_text(json.dumps(
        {"phase": str(phase), "runs_usd": costs,
         "total_cost_usd": round(sum(MAX_BUDGET_USD if c is None else c for c in costs), 6),
         "runs_without_cost": sum(c is None for c in costs)}, indent=2) + "\n", encoding="utf-8")
    report = header + [f"Result: {label} (exit {code})"] + (notes or []) + [""]
    report += [f"- Run {i}: {f'NOT_RUN {p}' if p else 'complete'}" for i, p in enumerate(problems, 1)]
    report.append("")
    lines = [f.line(i) for i, f in enumerate(merged, 1)]
    blocking = [ln for f, ln in zip(merged, lines) if f.severity == "blocking"]
    follow_up = [ln for f, ln in zip(merged, lines) if f.severity != "blocking"]
    if blocking:
        report += ["## Blocking", *blocking, ""]
    if follow_up:
        report += [FOLLOW_UP_HEADING, *follow_up, ""]
    if not merged:
        report.append("NO FINDINGS")
    report.append(f"END REVIEW {len(merged)}")
    merged_path = out_dir / f"review-{phase}-merged.md"
    merged_path.write_text("\n".join(report) + "\n", encoding="utf-8")
    return merged_path


def run_plan_review(*, repo: Path, plan: Path, phase: int | str, runs: int, out_dir: Path, launch=None,
                    base: str | None = None, protocol: Path | None = None) -> int:
    """Review Phase `phase` of `plan` (the commits of `repo`'s HEAD since the merge-base with `base`) `runs` times,
    each run in its own throwaway worktree. Exit by the merged findings, never by a verdict; 0 only when every run
    completed on a non-empty diff, left the live repo as it was, and no finding is blocking. should-fix and nit
    findings do not stop it: the report lists them under `Follow-up (not blocking)`. A completed round that is the
    4th or later of the phase (see `MAX_ROUNDS`) exits ROUND_LIMIT instead, clean or not."""
    repo, plan, out_dir = Path(repo), Path(plan), Path(out_dir)
    launch = launch or launch_claude
    protocol = protocol or find_protocol()
    if protocol is None:
        print(f"{_PREFIX}{PROTOCOL_NAME} not found next to {_HERE}", file=sys.stderr)
        return caddis_exit.ERROR
    try:
        root = Path(_git_out(repo, "rev-parse", "--show-toplevel").strip()).resolve()
    except subprocess.CalledProcessError as exc:
        print(f"{_PREFIX}not a git repo: {repo} ({exc.stderr.strip()})", file=sys.stderr)
        return caddis_exit.ERROR
    if _inside(root, out_dir.resolve()):
        print(f"{_PREFIX}--out-dir {out_dir} is the repo root or contains it; use a folder inside or outside the repo",
              file=sys.stderr)
        return caddis_exit.ERROR
    try:
        plan_ref = plan.resolve().relative_to(root).as_posix()
    except ValueError:
        plan_ref = str(plan.resolve())
    try:
        card_text = plan_card(plan, phase, plan_ref)
        head = _git_out(root, "rev-parse", "HEAD").strip()
        base_sha = _git_out(root, "merge-base", base or _default_base(root), head).strip()
        diff_empty = base_sha == head or not _git_out(root, "diff", "--name-only", f"{base_sha}..{head}").strip()
    except (OSError, ValueError) as exc:
        print(f"{_PREFIX}{exc}", file=sys.stderr)
        return caddis_exit.ERROR
    except subprocess.CalledProcessError as exc:
        print(f"{_PREFIX}{_error_text(exc)}", file=sys.stderr)
        return caddis_exit.ERROR

    out_dir.mkdir(parents=True, exist_ok=True)
    header = [f"# Review of Phase {phase} - {plan_ref}", "", f"Head: {head}", f"Base: {base_sha}"]
    if diff_empty:
        problem = "nothing to review: base == head" if base_sha == head else "nothing to review: the diff is empty"
        print(f"REVIEW phase {phase}: NOT_RUN {problem}")
        _write_results(out_dir, phase, header, [problem], [0.0], [], caddis_exit.NOT_RUN, "NOT_RUN")
        return caddis_exit.NOT_RUN
    try:
        rounds = _read_rounds(out_dir, phase)
    except ValueError as exc:
        print(f"{_PREFIX}{exc}", file=sys.stderr)
        return caddis_exit.ERROR
    round_no = _completed_rounds(rounds, plan_ref) + 1
    # Round 2 and later read only the fix diff: from the head the last completed round reviewed.
    review_base = _delta_base(root, rounds, plan_ref, base_sha, head) or base_sha
    prior_blocking: list[str] | None = None
    if review_base != base_sha:
        last = next(e for e in reversed(rounds) if _is_completed(e, plan_ref))
        last_clean = last.get("exit") == caddis_exit.CLEAN
        if not last_clean:
            # After a round that was not CLEAN the fix diff alone cannot show that a blocking bug outside it is still
            # there: give the reviewer those findings to re-check, and never skip. No readable findings: full range.
            prior_blocking = _prior_blocking(rounds, plan_ref)
            if prior_blocking is None:
                print(f"{_PREFIX}the last round was not CLEAN and its blocking findings cannot be read; reviewing "
                      f"the full range {base_sha}..{head}", file=sys.stderr)
                review_base = base_sha
    if review_base != base_sha:
        header.append(f"Fix diff: {review_base}..{head} (the last completed round reviewed {review_base})")
        if prior_blocking is None and _delta_tier(root, f"{review_base}..{head}") == "0":
            note = f"Skipped: the fix diff {review_base}..{head} is tier 0 (no logic changed); no reviewer launched."
            merged_path = _write_results(out_dir, phase, header, [], [], [], caddis_exit.CLEAN, "CLEAN", [note])
            _record_round(out_dir, phase, rounds, None, plan_ref, head, SKIPPED_DELTA, caddis_exit.CLEAN)
            print(f"REVIEW phase {phase}: CLEAN ({SKIPPED_DELTA}: {review_base}..{head}); not counted as a round; "
                  f"{merged_path}")
            return caddis_exit.CLEAN
    prompt = plan_prompt(protocol.read_text(encoding="utf-8"), card_text, review_base, head,
                         delta=review_base != base_sha, prior_blocking=prior_blocking)
    try:
        _prune_stale_review_worktrees(root)
    except (OSError, subprocess.CalledProcessError) as exc:
        # Only old registrations are affected; each run still checks its own worktree is gone.
        print(f"WARNING: stale caddis-review-* registrations not dropped: {_error_text(exc)}")

    # Provider output can hold a key: mask the values from the keys file before anything is parsed, printed or written.
    masks = caddis_redact.load_secrets(Path.home())
    run_findings: list[list[Finding]] = []
    problems: list[str] = []
    costs: list[float | None] = []
    for run in range(1, runs + 1):
        worktree = None
        output, problem = "", ""
        try:
            before = _snapshot(root, out_dir)
        except (OSError, subprocess.CalledProcessError) as exc:
            # Without a snapshot a change to the live repo cannot be seen: no run, never a pass.
            before, problem = None, f"live repo snapshot failed before the run: {_error_text(exc)}"
        if before is not None:
            try:
                worktree = _add_worktree(root, head, phase, run)
                output = caddis_redact.redact(launch(prompt, worktree, out_dir / f"review-{phase}-run{run}.json"),
                                              masks)
            except subprocess.CalledProcessError as exc:
                problem = f"review worktree not created: {_error_text(exc)}"
            except Exception as exc:  # noqa: BLE001 - a launcher that crashed is a run that did not happen, never a pass
                problem = f"launcher failed: {type(exc).__name__}: {exc}"
            finally:
                if worktree is not None:
                    removal = _remove_worktree(root, worktree)
                    problem = problem or removal
        text, incomplete, cost = check_complete(output)
        if before is None:
            cost = 0.0                  # nothing was launched
        problem = problem or incomplete
        changed: list[str] = []
        if before is not None:
            try:
                changed = _live_changes(before, _snapshot(root, out_dir))
            except (OSError, subprocess.CalledProcessError) as exc:
                problem = f"live repo snapshot failed after the run: {_error_text(exc)}" + (
                    f"; {problem}" if problem else "")
        if changed:
            problem = "the run changed the live repo: " + "; ".join(changed)
        text = caddis_redact.redact(text, masks)
        findings = parse_findings(text)
        status = f"NOT_RUN {problem}" if problem else f"complete, {len(findings)} finding(s)"
        (out_dir / f"review-{phase}-run{run}.txt").write_text(
            text.rstrip("\r\n") + f"\nRUN {run}: {status}\n", encoding="utf-8")
        print(f"REVIEW run {run}: {status}")
        run_findings.append(findings)
        problems.append(problem)
        costs.append(cost)

    merged = merge_findings(run_findings)
    notes: list[str] = []
    if any(problems):
        code, label = caddis_exit.NOT_RUN, "NOT_RUN"
    elif any(f.severity == "blocking" for f in merged):
        code, label = caddis_exit.BLOCKED, "BLOCKED"
    else:
        code, label = caddis_exit.CLEAN, "CLEAN"
    outcome, outcome_code = label, code
    if round_no > MAX_ROUNDS and code != caddis_exit.NOT_RUN:
        code, label = caddis_exit.ROUND_LIMIT, "ROUND_LIMIT"
        notes = [f"Review outcome: {outcome} (exit {outcome_code})",
                 f"Round limit: this is round {round_no}; {MAX_ROUNDS} are allowed. Stop: the owner decides."]
    merged_path = _write_results(out_dir, phase, header, problems, costs, merged, code, label, notes)
    blocking_lines = [f.line(i) for i, f in enumerate(merged, 1) if f.severity == "blocking"]
    _record_round(out_dir, phase, rounds, None if outcome == "NOT_RUN" else round_no, plan_ref, head, outcome, code,
                  blocking=blocking_lines)
    follow_up = sum(f.severity != "blocking" for f in merged)
    print(f"REVIEW phase {phase}: {label} ({len(merged)} finding(s) from {runs} run(s), {follow_up} not blocking); "
          f"{'not counted as a round' if outcome == 'NOT_RUN' else f'round {round_no}'}; {merged_path}")
    if code == caddis_exit.ROUND_LIMIT:
        print(f"REVIEW phase {phase}: round limit reached ({MAX_ROUNDS} rounds); the review outcome was {outcome}. "
              "Stop: the owner decides.")
    return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worktree", type=Path, required=True, help="path to worktree (with --plan: the repo)")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--card", type=Path, help="path to card")
    what.add_argument("--plan", type=Path, help="path to a plan; the card is built from its --phase section")
    parser.add_argument("--phase", help="with --plan: the phase number")
    parser.add_argument("--runs", type=int, default=None, help="with --plan: independent review runs (default 1)")
    parser.add_argument("--provider", default=None,
                        help="preferred provider (--plan: claude only; --card: the review role's order)")
    parser.add_argument("--base", default=None,
                        help="base git ref (with --card: origin/main; with --plan: origin/<default branch>)")
    parser.add_argument("--contract", type=Path, default=None, help="path to contract")
    parser.add_argument("--out-dir", type=Path, default=None,
                        help="output directory for reviews (with --plan it also holds the round count: new dir, round 1)")
    args = parser.parse_args(argv)
    if args.plan is None and (args.phase is not None or args.runs is not None):
        parser.error("--phase and --runs need --plan")
    if args.plan is not None:
        if args.phase is None:
            parser.error("--plan requires --phase")
        runs = 1 if args.runs is None else args.runs
        if not 1 <= runs <= MAX_RUNS:  # each run may cost up to --max-budget-usd; more needs the owner (cost rule)
            print(f"caddis_review: --runs must be 1-{MAX_RUNS}", file=sys.stderr)
            return caddis_exit.ERROR
        if runs < 1:
            parser.error("--runs must be 1 or more")
        if (args.provider or "claude") != "claude":
            print(f"{_PREFIX}--plan reviews need a provider that can run tests (claude)", file=sys.stderr)
            return caddis_exit.ERROR
        out_dir = args.out_dir if args.out_dir is not None else (
            args.worktree.resolve() / ".caddis" / "reviews" / ".local" / f"review-{args.phase}")
        try:
            return run_plan_review(repo=args.worktree, plan=args.plan, phase=args.phase, runs=runs, out_dir=out_dir,
                                   launch=launch_claude, base=args.base)
        except Exception as exc:  # noqa: BLE001 - an error the review did not map is a review that did not run
            message = " ".join(f"{type(exc).__name__}: {exc}".split())
            print(f"{_PREFIX}NOT_RUN unexpected error: {message}", file=sys.stderr)
            return caddis_exit.NOT_RUN
    out_dir = args.out_dir if args.out_dir is not None else (args.worktree.resolve().parent / "reviews")
    providers = provider_order(args.provider, args.worktree)
    return run_review(
        worktree=args.worktree,
        card=args.card,
        providers=providers,
        out_dir=out_dir,
        launch=launch,
        base=args.base or "origin/main",
        contract=args.contract,
    )


if __name__ == "__main__":
    raise SystemExit(main())
