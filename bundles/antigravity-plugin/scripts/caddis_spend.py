#!/usr/bin/env python3
"""caddis_spend - one global spend cap for agy, in EUR per rolling 24 hours, on this machine.

Why: on 7 Oct 2026 two unsupervised overnight agy runs cost EUR 793 in one billing day. Nothing in
caddis capped money (caddis_governor caps CPU and memory only). Every agy launch that caddis makes
through a lane (`caddis_lanes.run_lane`, which ci-watch also uses) or a plan Lane line
(`caddis_spend.py run -- agy ...`) goes through `reserve()` before it starts and `settle()` after it ends.
The roadmap/plan runner (`caddis_roadmap_run.py --engine agy`) reserves before each agy session and settles after it.

Config `~/.caddis/spend-cap.toml` (the owner writes it; caddis never does):

    [agy]
    eur_per_24h = 200
    reserve_eur_per_call = 10            # what a call still running, or killed, is assumed to cost
    eur_per_million_input_tokens = 0     # from Google Cloud billing; 0 = unset
    eur_per_million_output_tokens = 0

Every value must be a finite number above 0. Anything else means NOT CONFIGURED, and every agy launch is
refused (fail closed).

Log `~/.caddis/spend/agy.jsonl`, append-only. A `pending` line is written under a file lock before the
launch and a `settled` line with the same id after it. A pending line with no valid settled line keeps
counting its reserve for 24 h, so a killed or crashed call is never free, and two callers cannot both
pass the check with the last EUR of the cap.

Limits (by design, see .caddis/plans/caddis-next.md Phase 4):
- The cap is per machine. The only cap across machines is a Google Cloud budget alert.
- agy started by hand, or by a script outside caddis, is not covered.
- The cap file and the log are plain files of this user: any process of this user, including an agy
  session started with --dangerously-skip-permissions, can edit them. The cap stops accidents and
  runaway loops; it is not a security boundary against a hostile local process.
- The check runs at launch. A long call can cost more than its reserve before it is settled; an
  estimated settle records its duration so the overshoot is visible.
- EUR is an estimate from token counts and the owner's prices, not the real bill.

CLI:
    python caddis_spend.py check                 exit 0 allowed, 1 over cap, 3 not configured
    python caddis_spend.py status                prints the committed spend of the last 24 h
    python caddis_spend.py run --caller X -- agy ...
        reserve, run, settle. Returns agy's own exit code, or 75 over the cap / could not lock,
        or 78 not configured, or 124 when the command ran past its time limit (--timeout-s, else
        CADDIS_SPEND_RUN_TIMEOUT_S, else 3600 s) and its process tree was killed. 75 and 78 are never
        agy's own codes for a refusal, so a caller can tell "the cap refused" from "agy failed". Each
        refusal also prints a `caddis_spend:` line.
        On Windows the command runs on a hidden desktop (caddis_hidden_desktop.py), so the console windows agy opens
        for its tools never show; CADDIS_AGY_VISIBLE=1 runs it on the normal desktop.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

EXIT_OK = 0
EXIT_OVER_CAP = 1          # `check` only
EXIT_NOT_CONFIGURED = 3    # `check` only
RUN_REFUSED = 75           # `run`: over the cap, or could not lock (EX_TEMPFAIL)
RUN_NOT_CONFIGURED = 78    # `run`: not configured (EX_CONFIG)
RUN_TIMEOUT = 124          # `run`: the child ran past its time limit and its process tree was killed (as timeout(1))
DEFAULT_RUN_TIMEOUT_S = 3600.0   # one hour: a run over about 1 hour needs the owner's approval anyway
# No console window for the child on Windows (robustness #19; see no_window.py: never DETACHED_PROCESS).
_NO_WINDOW_KW = {"creationflags": 0x08000000} if os.name == "nt" else {}
LOCK_TIMEOUT_S = 10.0
NOT_CONFIGURED_MESSAGE = ("caddis_spend: spend cap not configured: set eur_per_24h, reserve_eur_per_call and both "
                          "token prices (finite, above 0) in ~/.caddis/spend-cap.toml; every agy launch is refused "
                          "until then")


# Recursion guard on headless starts (robustness #19). Every launcher of a headless caddis session passes
# CADDIS_HEADLESS_DEPTH one higher than it got, and refuses to launch once the depth is at the limit, so a
# headless session that starts a headless session that starts one... ends after MAX_HEADLESS_DEPTH levels.
# The owner may change the limit with CADDIS_HEADLESS_MAX_DEPTH. This stops accidents and loops; a hostile
# process can reset the variable, like the cap file (see the Limits above).
HEADLESS_DEPTH_VAR = "CADDIS_HEADLESS_DEPTH"
MAX_HEADLESS_DEPTH = 3


class HeadlessDepthExceeded(RuntimeError):
    """A headless start was refused because headless sessions are already nested too deep."""


def headless_depth(env) -> int:
    """How many headless launches lie above this process: CADDIS_HEADLESS_DEPTH, or 0 when unset or not a count."""
    raw = str(env.get(HEADLESS_DEPTH_VAR, "")).strip()
    return int(raw) if raw.isdigit() else 0


def bump_headless_depth(env) -> dict:
    """A copy of `env` for a child headless session: CADDIS_HEADLESS=1 and the depth one higher.
    Raises HeadlessDepthExceeded when the depth is already at the limit."""
    limit_raw = str(env.get("CADDIS_HEADLESS_MAX_DEPTH", "")).strip()
    limit = int(limit_raw) if limit_raw.isdigit() and int(limit_raw) > 0 else MAX_HEADLESS_DEPTH
    depth = headless_depth(env)
    if depth >= limit:
        raise HeadlessDepthExceeded(
            f"caddis: headless depth {depth} is at the limit ({limit}); not starting another headless session "
            f"({HEADLESS_DEPTH_VAR}; the owner can raise CADDIS_HEADLESS_MAX_DEPTH)")
    out = dict(env)
    out[HEADLESS_DEPTH_VAR] = str(depth + 1)
    out["CADDIS_HEADLESS"] = "1"
    return out


class NotConfigured(Exception):
    """The cap file is missing, unreadable, or holds a value that is not a finite number above 0."""


@dataclass
class Cap:
    eur_per_24h: float
    reserve: float
    price_in: float
    price_out: float


def _cap_path(home: Path) -> Path:
    return home / ".caddis" / "spend-cap.toml"


def _log_path(home: Path) -> Path:
    return home / ".caddis" / "spend" / "agy.jsonl"


def _positive(value) -> float:
    """A finite float above 0, or ValueError (bool and NaN/inf rejected)."""
    if isinstance(value, bool):
        raise ValueError(f"not a number: {value!r}")
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"must be a finite number above 0: {value!r}")
    return number


def load_cap(home: Path) -> Cap:
    import tomllib

    path = _cap_path(home)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8")).get("agy", {})
        return Cap(_positive(data["eur_per_24h"]), _positive(data.get("reserve_eur_per_call", 10)),
                   _positive(data["eur_per_million_input_tokens"]), _positive(data["eur_per_million_output_tokens"]))
    except (OSError, ValueError, KeyError, TypeError, AttributeError, tomllib.TOMLDecodeError) as exc:
        raise NotConfigured(f"{path}: {exc}") from exc


@contextmanager
def _locked(home: Path):
    lock = _log_path(home).with_name("agy.lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock, "a+b")
    deadline = time.monotonic() + LOCK_TIMEOUT_S
    try:
        while True:
            try:
                if sys.platform == "win32":
                    import msvcrt

                    fh.seek(0)
                    msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"caddis_spend: could not lock {lock} within {LOCK_TIMEOUT_S:g} s")
                time.sleep(0.05)
        yield
    finally:
        try:
            if sys.platform == "win32":
                import msvcrt

                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def json_mode(argv: list[str]) -> bool:
    """True only when the command has exactly ONE output-format flag and its value is `json`
    (`--output-format json` or `--output-format=json`). A second flag could switch agy to text, where the
    model's own lines could pose as a usage document."""
    values = []
    for i, arg in enumerate(argv):
        if arg == "--output-format":
            values.append(argv[i + 1] if i + 1 < len(argv) else "")
        elif arg.startswith("--output-format="):
            values.append(arg.split("=", 1)[1])
    return values == ["json"]


def _read(home: Path) -> list[dict]:
    try:
        text = _log_path(home).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    out = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue  # a torn line never hides the rest of the log
        if isinstance(record, dict) and isinstance(record.get("id", ""), str):
            out.append(record)  # a non-string id (hand edit) is skipped, never a crash
    return out


def _append(home: Path, record: dict) -> None:
    path = _log_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record) + "\n")


def _when(record: dict) -> datetime | None:
    try:
        when = datetime.fromisoformat(record["ts"])
    except (KeyError, TypeError, ValueError):
        return None
    return when if when.tzinfo else when.replace(tzinfo=timezone.utc)


def _amount(value) -> float | None:
    """A finite EUR amount of 0 or more, else None (NaN, inf, negative, text and null are not money)."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def committed_last_24h(home: Path, now: datetime) -> float:
    """Valid settled EUR, plus the reserve of every pending call with no valid settled line, newer than 24 h.

    A settled line with a bad `eur` does not count as settled, so its pending reserve keeps counting.
    A pending line with a bad reserve (only a hand edit can write one; reserve() always writes a valid
    value) counts as 0."""
    since = now - timedelta(hours=24)
    records = _read(home)
    settled: dict[str, float] = {}
    for r in records:
        if r.get("kind") == "settled":
            amount = _amount(r.get("eur"))
            when = _when(r)
            if amount is not None and when is not None and isinstance(r.get("id"), str):
                settled[r["id"]] = settled.get(r["id"], 0.0) + (amount if when > since else 0.0)
    total = sum(settled.values())
    for r in records:
        if r.get("kind") != "pending" or r.get("id") in settled:
            continue
        when = _when(r)
        if when is None or when <= since:
            continue
        total += _amount(r.get("reserve_eur")) or 0.0
    return total


def reserve(home: Path, caller: str, now: datetime) -> str | None:
    """Book a pending call. None when it would go over the cap. Raises NotConfigured or TimeoutError."""
    cap = load_cap(home)
    with _locked(home):
        if committed_last_24h(home, now) + cap.reserve > cap.eur_per_24h:
            return None
        rid = uuid.uuid4().hex
        _append(home, {"kind": "pending", "id": rid, "ts": now.isoformat(), "caller": caller,
                       "pid": os.getpid(), "reserve_eur": cap.reserve})
        return rid


def settle(home: Path, rid: str, tokens: tuple[int, int] | None, now: datetime,
           duration_s: float | None = None) -> float:
    """Record the real cost of a reserved call; with no token counts, its reserve (estimated, with duration)."""
    try:
        cap = load_cap(home)
    except NotConfigured:
        cap = None
    record: dict = {"kind": "settled", "id": rid, "ts": now.isoformat()}
    if tokens is None or cap is None:
        pending = next((r for r in _read(home) if r.get("kind") == "pending" and r.get("id") == rid), {})
        eur = _amount(pending.get("reserve_eur"))
        if eur is None:
            eur = cap.reserve if cap else 0.0
        record.update({"tokens_in": 0, "tokens_out": 0, "eur": round(eur, 4), "estimated": True})
    else:
        t_in, t_out = tokens
        eur = t_in / 1e6 * cap.price_in + t_out / 1e6 * cap.price_out
        record.update({"tokens_in": t_in, "tokens_out": t_out, "eur": round(eur, 4), "estimated": False})
    if duration_s is not None:
        record["duration_s"] = round(duration_s, 1)
    with _locked(home):
        _append(home, record)
    return eur


def _agy_document(stdout: str) -> dict | None:
    """agy's own JSON document from `agy --output-format json` (sample: scripts/tests/fixtures/agy-json-sample.json).

    The document may follow other lines (on Windows the governor writes `[caddis-governor] scope=...` first,
    and run_lane merges stderr into stdout), and agy pretty-prints it over several lines. So: try every `{`
    that starts a line, decode one JSON value from there, and keep the LAST dict that has agy's top-level
    keys (`status`, `response`, `usage`). The model's reply is inside the `response` string, where a `{`
    never starts a line of the raw output, so text the model prints cannot pose as the usage document."""
    decoder = json.JSONDecoder()
    text = stdout or ""
    found = None
    starts = [0] if text.startswith("{") else []
    starts += [i + 1 for i, ch in enumerate(text) if ch == "\n" and text[i + 1:i + 2] == "{"]
    for start in starts:
        try:
            obj, _end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and {"status", "response", "usage"} <= obj.keys():
            found = obj
    return found


def _count(value) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def tokens_from_output(stdout: str) -> tuple[int, int] | None:
    """(usage.input_tokens, usage.output_tokens) from agy's JSON document; output_tokens includes thinking
    tokens (sample: 27249 in, 85 out of which 84 thinking, total 27334). None when not readable, or when a
    count is not a non-negative integer (then the call settles at its reserve)."""
    doc = _agy_document(stdout)
    usage = doc.get("usage") if doc else None
    if not isinstance(usage, dict):
        return None
    t_in, t_out = _count(usage.get("input_tokens")), _count(usage.get("output_tokens"))
    return (t_in, t_out) if t_in is not None and t_out is not None else None


def result_text(stdout: str) -> str:
    """The `response` text from agy's JSON document; the raw text when there is no such document."""
    doc = _agy_document(stdout)
    if doc and isinstance(doc.get("response"), str):
        return doc["response"]
    return stdout


def run_timeout_s() -> float:
    """The wall-clock limit of one `run` child: CADDIS_SPEND_RUN_TIMEOUT_S, else DEFAULT_RUN_TIMEOUT_S.
    A value that is not a finite number above 0 is ignored."""
    try:
        value = float(os.environ.get("CADDIS_SPEND_RUN_TIMEOUT_S", ""))
    except ValueError:
        return DEFAULT_RUN_TIMEOUT_S
    return value if math.isfinite(value) and value > 0 else DEFAULT_RUN_TIMEOUT_S


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the child and everything it started (taskkill /T on Windows, the process group on POSIX)."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True, timeout=15,
                           **_NO_WINDOW_KW)
        else:
            import signal
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


HIDDEN_DESKTOP_SCRIPT = Path(__file__).with_name("caddis_hidden_desktop.py")
AGY_VISIBLE_VAR = "CADDIS_AGY_VISIBLE"


def hidden_argv(argv: list[str], env: dict | None = None) -> list[str]:
    """`argv` wrapped to run on the hidden desktop (caddis_hidden_desktop.py), so the console windows agy opens for
    its tools never show on the owner's screen. Unchanged when: not Windows, env CADDIS_AGY_VISIBLE=1, the launcher
    is not beside this file, or the program is not found. In the last case the caller's own start raises
    FileNotFoundError as before; the program is resolved here, so the launcher never has to report it."""
    env = os.environ if env is None else env
    if os.name != "nt" or not argv or env.get(AGY_VISIBLE_VAR) == "1" or not HIDDEN_DESKTOP_SCRIPT.is_file():
        return list(argv)
    program = shutil.which(argv[0], path=env.get("PATH"))
    if program is None:
        return list(argv)
    return [sys.executable, str(HIDDEN_DESKTOP_SCRIPT), "--", program, *argv[1:]]


def _run_child(argv: list[str], env: dict, timeout_s: float) -> tuple[int | None, str, str]:
    """Run `argv` with a time limit, on the hidden desktop on Windows (hidden_argv). Returns (returncode, stdout,
    stderr); returncode is None on a timeout, after the whole process tree was killed. Raises FileNotFoundError when
    the program does not exist."""
    group = {} if os.name == "nt" else {"start_new_session": True}
    proc = subprocess.Popen(hidden_argv(argv, env), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace", env=env, **_NO_WINDOW_KW, **group)
    try:
        out, err = proc.communicate(timeout=timeout_s)
        return proc.returncode, out or "", err or ""
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:  # the pipes close once the tree is dead; do not wait for ever if a stray holder survives
            out, err = proc.communicate(timeout=10)
        except Exception:
            out, err = "", ""
        return None, out or "", err or ""
    except BaseException:
        # Ctrl-C or any other error while waiting: the child (agy, spending) must not outlive us. It runs in its
        # own session/group, so it does not get our SIGINT. Kill the tree, then let the exception go on; run()
        # settles the reserve in its `finally`.
        _kill_tree(proc)
        raise


def run(argv: list[str], caller: str, home: Path, timeout_s: float | None = None) -> int:
    """Reserve, run agy, settle. Returns agy's exit code, or RUN_REFUSED (75) / RUN_NOT_CONFIGURED (78) /
    RUN_TIMEOUT (124: the child ran past `timeout_s`, default run_timeout_s(); its process tree was killed and the
    call is booked at its reserve)."""
    now = lambda: datetime.now(timezone.utc)  # noqa: E731
    try:
        env = bump_headless_depth(os.environ)  # before the reserve: a refused start costs nothing
    except HeadlessDepthExceeded as exc:
        print(str(exc), file=sys.stderr)
        return RUN_REFUSED
    try:
        rid = reserve(home, caller, now())
    except NotConfigured:
        print(NOT_CONFIGURED_MESSAGE, file=sys.stderr)
        return RUN_NOT_CONFIGURED
    except TimeoutError as exc:
        print(str(exc), file=sys.stderr)
        return RUN_REFUSED
    except Exception as exc:  # an unreadable log or file error: refuse with the refusal code, never exit 1
        print(f"caddis_spend: could not check the spend cap: {exc!r}", file=sys.stderr)
        return RUN_REFUSED
    if rid is None:
        print(f"caddis_spend: over cap: agy refused ({status_line(home, now())})", file=sys.stderr)
        return RUN_REFUSED
    out = ""
    counts: tuple[int, int] | None = None
    started = time.monotonic()
    try:
        limit = run_timeout_s() if timeout_s is None else timeout_s
        returncode, out, err = _run_child(argv, env, limit)
        if returncode is None:  # timed out: whatever it printed is passed on, but no token count is trusted
            sys.stdout.write(out)
            sys.stderr.write(err)
            print(f"caddis_spend: {argv[0]} timed out after {limit:g}s; its process tree was killed "
                  f"(booked at the reserve). Set CADDIS_SPEND_RUN_TIMEOUT_S or --timeout-s to change the limit.",
                  file=sys.stderr)
            return RUN_TIMEOUT
        # Tokens only from JSON mode: in text mode the model's own lines could pose as a usage document.
        if json_mode(argv):
            counts = tokens_from_output(out)
        sys.stdout.write(out)
        sys.stderr.write(err)
        return returncode
    except FileNotFoundError:
        counts = (0, 0)  # nothing ran, nothing was spent
        print(f"caddis_spend: command not found: {argv[0]}", file=sys.stderr)
        return 127
    finally:
        try:
            settle(home, rid, counts, now(), duration_s=time.monotonic() - started)
        except Exception as exc:  # the pending reserve keeps counting; never lose agy's own result
            print(f"caddis_spend: could not settle {rid}: {exc}", file=sys.stderr)


def status_line(home: Path, now: datetime) -> str:
    try:
        cap = f"{load_cap(home).eur_per_24h:g}"
    except NotConfigured:
        cap = "NOT CONFIGURED"
    return f"agy: EUR {committed_last_24h(home, now):.2f} of {cap} in the last 24 h on this machine"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    raw = list(sys.argv[1:] if argv is None else argv)
    tail: list[str] = []
    if "--" in raw:
        i = raw.index("--")
        raw, tail = raw[:i], raw[i + 1:]
    parser = argparse.ArgumentParser(description="global agy spend cap (EUR per rolling 24 h, this machine)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check")
    sub.add_parser("status")
    p_run = sub.add_parser("run")
    p_run.add_argument("--caller", required=True)
    p_run.add_argument("--timeout-s", type=float, default=None,
                       help="kill the command's process tree after this many seconds "
                            "(default: CADDIS_SPEND_RUN_TIMEOUT_S, else 3600)")
    args = parser.parse_args(raw)
    home = Path.home()
    now = datetime.now(timezone.utc)
    if args.cmd == "status":
        try:
            print(status_line(home, now))
        except Exception as exc:
            print(f"caddis_spend: could not read the spend log: {exc!r}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED
        return EXIT_OK
    if args.cmd == "check":
        try:
            cap = load_cap(home)
        except NotConfigured:
            print(NOT_CONFIGURED_MESSAGE, file=sys.stderr)
            return EXIT_NOT_CONFIGURED
        try:
            committed = committed_last_24h(home, now)
        except Exception as exc:
            print(f"caddis_spend: could not read the spend log: {exc!r}", file=sys.stderr)
            return EXIT_NOT_CONFIGURED
        if committed + cap.reserve > cap.eur_per_24h:
            print(f"over cap: {status_line(home, now)}")
            return EXIT_OVER_CAP
        print(f"ok: {status_line(home, now)}")
        return EXIT_OK
    if not tail:
        parser.error("run needs the agy command after --")
    if args.timeout_s is not None and not (math.isfinite(args.timeout_s) and args.timeout_s > 0):
        parser.error("--timeout-s must be a number above 0")
    return run(tail, args.caller, home, timeout_s=args.timeout_s)


if __name__ == "__main__":
    sys.exit(main())
