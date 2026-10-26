#!/usr/bin/env python3
"""Batched hub collector: every repo's roadmaps, plans and relays, plus agy spend and the guide, as one JSON object.

Usage: caddis_hub_collect.py --repos PATH [PATH ...] [--only roadmaps,plans,relays,spend,guide] --json

The hub runs this once per cycle. It runs in ONE Python process for all repos (hub rule R15, spawn cost L8). It
never calls gh, claude or agy, and never runs `git fetch`: the roadmap reader sees the origin refs the repo
already has. The parsers stay in the scripts that own each format (R14); this file only calls them.

Output: {"schema": 1, "generated_at": "<UTC Z>", "repos": [{"path", "fingerprint", "roadmaps", "plans",
"relays"}], "spend": ..., "guide": ...}. A path that is not a folder gives {"path", "error"}. A source that fails
gives {"error": "<one line>"} in its slot. The run still exits 0. Exit 1 is for bad arguments only.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = 1
KINDS = ("roadmaps", "plans", "relays", "spend", "guide")
_REPO_KINDS = ("roadmaps", "plans", "relays")


def _sibling(name: str):
    """A sibling script as a module. The same module object the rest of the process uses."""
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as exc:
        if exc.name != name:
            raise
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        return importlib.import_module(name)


def _error(exc: BaseException) -> dict:
    lines = str(exc).strip().splitlines()
    return {"error": lines[0] if lines else type(exc).__name__}


def _roadmaps_json(root: Path) -> dict:
    module = _sibling("caddis_roadmap")
    saved = module.FETCH
    module.FETCH = False  # R15: no network git. Read the origin refs the repo already has.
    try:
        return module.roadmaps_json(root)
    finally:
        module.FETCH = saved


def _local_origin_branches(common: Path) -> list[str]:
    """Which of origin/main and origin/master exist, from the loose ref files and packed-refs (no subprocess)."""
    try:
        packed = (common / "packed-refs").read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        packed = ""
    packed_refs = {line.split(" ", 1)[1].strip() for line in packed.splitlines() if " refs/" in line}
    return [name for name in ("main", "master")
            if (common / "refs" / "remotes" / "origin" / name).is_file() or f"refs/remotes/origin/{name}" in packed_refs]


def _plans_json(root: Path) -> dict:
    """Plans from the origin ref the repo already has (R15: local git only), so a pushed Tracker edit shows with no
    pull. A folder that is not a git checkout, or has no origin default branch, reads the working tree."""
    branch = None
    common = git_common_dir(Path(root))
    if common is None:
        return _sibling("caddis_todo").plans_json(root)
    try:  # origin/HEAD is a one-line file; reading it saves a git process per repo
        head = (common / "refs" / "remotes" / "origin" / "HEAD").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        head = ""
    if head.startswith("ref: refs/remotes/origin/"):
        branch = head[len("ref: refs/remotes/origin/"):]
    elif len(found := _local_origin_branches(common)) == 1:
        branch = found[0]  # the same rule as caddis_roadmap.default_branch with FETCH off, read from the files
    else:
        roadmap = _sibling("caddis_roadmap")
        saved = roadmap.FETCH
        roadmap.FETCH = False
        try:
            branch = roadmap.default_branch(Path(root))
        except roadmap.RoadmapError:
            branch = None
        finally:
            roadmap.FETCH = saved
    return _sibling("caddis_todo").plans_json(root, branch=branch)


def _relays_json(root: Path) -> dict:
    return _sibling("caddis_workstreams").relays_json(root)


def _spend_json() -> dict:
    return _sibling("caddis_spend").spend_json(Path.home())


# An installed bundle has no source pool to scan: the export writes the guide data beside this script.
GUIDE_DATA = Path(__file__).resolve().parent / "caddis_guide.json"


def _guide_json() -> dict:
    """The guide data file of an install, else build_reference in a source checkout."""
    try:
        text = GUIDE_DATA.read_text(encoding="utf-8")
    except FileNotFoundError:
        text = None
    if text is not None:
        data = json.loads(text)
        if not isinstance(data, dict):
            raise ValueError(f"{GUIDE_DATA.name} is not a JSON object")
        return data
    try:
        module = _sibling("build_reference")
    except ModuleNotFoundError as exc:
        if exc.name != "build_reference":
            raise
        raise RuntimeError(
            f"the guide data is missing from this install: no {GUIDE_DATA.name} beside {Path(__file__).name}"
        ) from None
    return module.guide_json()


_REPO_COLLECTORS = {"roadmaps": _roadmaps_json, "plans": _plans_json, "relays": _relays_json}


RUNNER_DIR = "caddis-runner"  # the runner folder in the git common dir; a test keeps it equal to caddis_roadmap.RUNNER_DIR

_REPARSE_POINT = 0x400  # FILE_ATTRIBUTE_REPARSE_POINT: a junction or a symlink on Windows


def _is_link(path: Path) -> bool:
    """True for a symlink or a Windows junction. Python 3.11 `is_symlink()` is False for a junction."""
    try:
        info = path.lstat()
    except OSError:
        return False  # not there: nothing to follow
    return path.is_symlink() or bool(getattr(info, "st_file_attributes", 0) & _REPARSE_POINT)


def _files(folder: Path, pattern: str = "*", recurse: bool = False) -> list[Path]:
    """The plain files in `folder`. Never enter a linked folder and never list a linked file (stat only)."""
    if not folder.is_dir() or _is_link(folder):
        return []
    found: list[Path] = []
    for path in folder.iterdir():
        if _is_link(path):
            continue
        if path.is_dir():
            if recurse:
                found.extend(_files(path, pattern, recurse))
        elif path.is_file() and path.match(pattern):
            found.append(path)
    return found


def _input_files(repo: Path) -> list[Path]:
    """The files the repo's collectors read from the working tree."""
    artifact = repo / ".caddis"
    if _is_link(artifact):
        return []
    files = _files(artifact / "roadmaps", recurse=True)
    plans = artifact / "plans"
    if not plans.is_dir():
        plans = repo / ".github" / "plans"  # the legacy folder, as caddis_todo reads it
    files.extend(_files(plans, "*.md"))
    files.extend(_files(artifact / "relay", "*.md"))
    return files


def git_common_dir(repo: Path) -> Path | None:
    """The git common dir, found with no subprocess: a `.git` folder, or a `.git` file (a worktree) whose `gitdir:`
    folder has a `commondir` file. None when the repo has no readable git dir."""
    dot_git = repo / ".git"
    if _is_link(dot_git):
        return None
    if dot_git.is_dir():
        return dot_git
    try:
        line = dot_git.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if not line.startswith("gitdir:"):
        return None
    gitdir = Path(line[len("gitdir:"):].strip())
    if not gitdir.is_absolute():
        gitdir = repo / gitdir
    try:
        common = (gitdir / "commondir").read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return gitdir if gitdir.is_dir() else None
    path = Path(common)
    return path if path.is_absolute() else gitdir / path


def _origin_ref_files(common: Path) -> list[Path]:
    """The ref files the roadmap reader gets its data from: packed-refs, origin/HEAD, every origin branch."""
    files = [p for p in (common / "packed-refs",) if p.is_file() and not _is_link(p)]
    # refs/remotes/origin/HEAD sits inside refs/remotes/origin/, so the walk covers it.
    return files + _files(common / "refs" / "remotes" / "origin", recurse=True)


def _runner_files(common: Path) -> list[Path]:
    """The roadmap runner's lock and last-stop files (R45): a runner start or stop must refresh the data."""
    return _files(common / RUNNER_DIR, recurse=True)


def fingerprint(repo: Path) -> str:
    """sha256 over the sorted (name, mtime_ns, size) of every input file and origin ref file. Empty list: still a hash.

    The roadmaps come from the origin refs (`git show origin/<default>:...`), so a fetch must change the hash."""
    repo = Path(repo)
    named = [(path.relative_to(repo).as_posix(), path) for path in _input_files(repo)]
    common = git_common_dir(repo)
    if common is not None:
        named.extend((f"git:{path.relative_to(common).as_posix()}", path) for path in _origin_ref_files(common))
        named.extend((f"git:{path.relative_to(common).as_posix()}", path) for path in _runner_files(common))
    rows = []
    for name, path in named:
        try:
            info = path.stat()
        except OSError:
            continue  # the file went away while we looked
        rows.append((name, info.st_mtime_ns, info.st_size))
    return hashlib.sha256(json.dumps(sorted(rows)).encode("utf-8")).hexdigest()


def collect_repo(path: str, kinds: tuple[str, ...]) -> dict:
    repo = Path(path)
    if not repo.is_dir():
        return {"path": path, "error": "not a folder"}
    entry: dict = {"path": path}
    try:
        entry["fingerprint"] = fingerprint(repo)
    except Exception as exc:  # a repo we cannot read must not stop the others
        return {"path": path, **_error(exc)}
    for kind in _REPO_KINDS:
        if kind not in kinds:
            continue
        try:
            entry[kind] = _REPO_COLLECTORS[kind](repo)
        except Exception as exc:
            entry[kind] = _error(exc)
    return entry


def collect(repos: list[str], kinds: tuple[str, ...]) -> dict:
    out: dict = {"schema": SCHEMA, "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "repos": [collect_repo(path, kinds) for path in repos]}
    for kind, call in (("spend", _spend_json), ("guide", _guide_json)):
        if kind not in kinds:
            continue
        try:
            out[kind] = call()
        except Exception as exc:
            out[kind] = _error(exc)
    return out


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # bad arguments exit 1, not argparse's 2
        self.print_usage(sys.stderr)
        print(f"caddis-hub-collect: {message}", file=sys.stderr)
        raise SystemExit(1)


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = _Parser(description=__doc__.splitlines()[0])
    parser.add_argument("--repos", nargs="+", required=True, metavar="PATH")
    parser.add_argument("--only", default=",".join(KINDS), help="comma list of: " + ", ".join(KINDS))
    parser.add_argument("--json", action="store_true", required=True)
    args = parser.parse_args(argv)
    kinds = tuple(k.strip() for k in args.only.split(",") if k.strip())
    unknown = [k for k in kinds if k not in KINDS]
    if unknown or not kinds:
        parser.error(f"unknown --only kind: {', '.join(unknown) or '(empty)'}; use {', '.join(KINDS)}")
    print(json.dumps(collect(args.repos, kinds), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
