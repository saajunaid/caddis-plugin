"""Transfer one workstream relay through an isolated, leased Git ref."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from caddis_workstreams import _name, _validate_relay, read_relay, write_relay
    import secret_filter
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_workstreams", "secret_filter"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / ".github" / "tools"))
    from caddis_workstreams import _name, _validate_relay, read_relay, write_relay
    import secret_filter


MAX_NOTE_CHARS = 4000


def _git(repo: Path, *args: str, input_data: bytes | None = None,
         env: dict[str, str] | None = None) -> bytes:
    result = subprocess.run(["git", *args], cwd=repo, env=env, input=input_data,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode:
        # Name the subcommand, not a leading "-c key=value" option.
        command = next((arg for i, arg in enumerate(args) if not arg.startswith("-") and (i == 0 or args[i - 1] != "-c")), "?")
        raise RuntimeError(f"git {command} failed: {result.stderr.decode('utf-8', 'replace').strip()}")
    return result.stdout


def _ref(workstream: str) -> str:
    return "refs/caddis/relay/" + _name(workstream)


def _check_note(workstream: str, note: str) -> None:
    if len(note) > MAX_NOTE_CHARS:
        raise ValueError("relay exceeds 4,000 characters")
    _validate_relay(workstream, note)


def _pre_send(note: str) -> None:
    # A synthetic new-file diff makes the existing filter scan every line, not
    # only lines changed since a prior relay. No user-configured allowlist is
    # accepted for this outbound note.
    lines = note.splitlines()
    diff = ("diff --git a/relay.md b/relay.md\nnew file mode 100644\n"
            "--- /dev/null\n+++ b/relay.md\n"
            f"@@ -0,0 +1,{len(lines)} @@\n" +
            "".join("+" + line + "\n" for line in lines))
    result = secret_filter.filter_diff(diff, list(secret_filter.DEFAULT_DENY_GLOBS), [])
    if result.hits or result.dropped_paths or not result.kept_diff:
        raise ValueError("relay refused by pre-send filter")


def push_relay(repo: Path, workstream: str, *, confirmed: bool, interactive: bool) -> int:
    """Return 0 on a leased push, 1 on refusal or conflict.

    A Git or network failure before the push (for example an unreachable remote in
    ``ls-remote``) raises RuntimeError, so the caller reports it instead of a refusal.

    The caller must obtain this invocation's interactive decision. This API
    never reads an ambient confirmation variable or prompts by itself.
    """
    if not confirmed or not interactive:
        return 1
    repo = Path(repo)
    ref = _ref(workstream)
    note, digest = read_relay(repo, workstream)
    if digest is None:
        return 1
    _check_note(workstream, note)
    _pre_send(note)
    with tempfile.TemporaryDirectory(prefix="caddis-relay-index-") as temp:
        index = Path(temp) / "index"
        env = os.environ.copy()
        env["GIT_INDEX_FILE"] = str(index)
        _git(repo, "read-tree", "--empty", env=env)
        blob = _git(repo, "hash-object", "-w", "--stdin", input_data=note.encode("utf-8"), env=env).decode().strip()
        _git(repo, "update-index", "--add", "--cacheinfo", "100644", blob, "relay.md", env=env)
        tree = _git(repo, "write-tree", env=env).decode().strip()
        commit = _git(repo, "-c", "user.name=Caddis Relay", "-c", "user.email=relay@localhost",
                      "commit-tree", tree, input_data=b"Relay note\n", env=env).decode().strip()
        old = _git(repo, "ls-remote", "origin", ref, env=env).decode().strip()
        expected = old.split("\t", 1)[0] if old else ""
        try:
            _git(repo, "push", f"--force-with-lease={ref}:{expected}", "origin",
                 f"{commit}:{ref}", env=env)
        except RuntimeError:
            return 1
    return 0


def fetch_relay(repo: Path, workstream: str, *, replace: bool = False) -> str:
    """Fetch one explicit ref, validate its one-file tree, then store by local CAS.

    A local relay that differs from the fetched one is never replaced unless the caller
    passes ``replace=True``: it may hold newer, never-pushed work.
    """
    repo = Path(repo)
    ref = _ref(workstream)
    local, expected_hash = read_relay(repo, workstream)
    _git(repo, "fetch", "--no-tags", "origin", ref)
    fetched = _git(repo, "rev-parse", "FETCH_HEAD").decode().strip()
    entries = _git(repo, "ls-tree", "-z", fetched).split(b"\0")
    if len(entries) != 2 or not entries[0].startswith(b"100644 blob ") or not entries[0].endswith(b"\trelay.md"):
        raise ValueError("remote relay tree must contain only an ordinary relay.md")
    size = int(_git(repo, "cat-file", "-s", f"{fetched}:relay.md").decode().strip())
    if size > MAX_NOTE_CHARS * 4:  # UTF-8 upper bound; read nothing larger into memory
        raise ValueError("remote relay exceeds 4,000 characters")
    note = _git(repo, "show", f"{fetched}:relay.md").decode("utf-8")
    _check_note(workstream, note)
    if expected_hash is not None and local != note and not replace:
        raise ValueError("local relay differs from the fetched one; pass replace=True to overwrite it")
    result = write_relay(repo, workstream, note, expected_hash)
    if result.status != "written":
        raise RuntimeError("local relay changed during fetch")
    return note


def _headless() -> bool:
    """No human is watching: the caddis launchers and the docket runner set these."""
    return any(os.environ.get(name) for name in ("CADDIS_HEADLESS", "DOCKET_PLAN", "DOCKET_BRANCH"))


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Move one workstream relay between machines")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--repo", type=Path, default=Path("."))
    sub = parser.add_subparsers(dest="command", required=True)
    push_p = sub.add_parser("push", parents=[common], help="publish .caddis/relay/<name>.md to refs/caddis/relay/<name>")
    push_p.add_argument("name")
    push_p.add_argument("--user-said-yes", action="store_true",
                        help="pass only after the user answered y to the push question in this session")
    fetch_p = sub.add_parser("fetch", parents=[common], help="fetch refs/caddis/relay/<name> into .caddis/relay/<name>.md")
    fetch_p.add_argument("name")
    fetch_p.add_argument("--replace", action="store_true",
                         help="overwrite a different local relay (it may hold never-pushed work)")
    args = parser.parse_args(argv)
    try:
        if args.command == "push":
            code = push_relay(args.repo, args.name, confirmed=args.user_said_yes, interactive=not _headless())
            print("relay pushed" if code == 0 else "relay not pushed (no consent, headless, missing relay, or remote conflict)")
            return code
        print(fetch_relay(args.repo, args.name, replace=args.replace), end="")
        return 0
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"caddis-relay: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
