#!/usr/bin/env python3
"""gate_scope.py - what the pre-push hook hands to ruff, mypy and pytest.

The project's own scope, never the whole tree. Prints a reason line
starting with "# ", then one argument per line. Exit 0 = run the tool
with those arguments (possibly none). Exit 3 = nothing to check, skip.

    python gate_scope.py --tool ruff|mypy|pytest      (default: mypy)

Per tool, in order:
  1. The project states its scope in its own config - mypy `files`,
     pytest `testpaths` - so the bare tool reads it, exactly as CI does.
  2. Otherwise, the top-level roots of git-TRACKED Python (for pytest,
     of tracked test files). A push can carry nothing else.
  3. Not a git repository -> the old whole-tree behaviour.

In 1 and 2, untracked .py files are excluded, each in the syntax its
tool understands: mypy a regex --exclude, ruff glob --extend-exclude,
pytest --ignore. mypy keeps a config `exclude` instead, because a CLI
--exclude REPLACES it and could re-include what the project excluded.

Why (2026-09-11): the hooks ran `mypy .`, `ruff check .` and `pytest -q`,
so one untracked scratch file blocked every push in that repo, while CI
(`mypy src/`, `ruff check src/ tests/`, `pytest tests/` across the
fleet's app repos) never saw it. A hook stricter than the gate it stands in
for trains people to --no-verify it.

This file carries NO noqa: it ships into consumer repos, and no noqa
form survives every rule set (PGH004 rejects a bare one, RUF100 an
unused coded one). The hook excludes .github/hooks from its ruff run
instead, and caddis lints this file strictly at the source
(scripts/tests/test_gate_scope.py).

Standard library only, and no tomllib, because a consumer's venv may be
older than 3.11. Output is LF-only: a POSIX shell reads it, and on
Windows a CR would ride along inside every argument.
"""

from __future__ import annotations

import argparse
import configparser
import re
import subprocess
import sys
from pathlib import Path

SKIP = 3
HOOKS_DIR = ".github/hooks"
PY_GLOBS = ("*.py", "*.pyi")


def _git_files(root: Path, *args: str) -> list[str] | None:
    """Paths from `git ls-files -z ...`, or None outside a git repository.

    NUL-separated, so a name git would otherwise quote arrives intact.
    """
    cmd = ["git", "ls-files", "-z", *args]
    try:
        # A fixed git command: no shell, no user input.
        r = subprocess.run(
            cmd, cwd=str(root), capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = r.stdout.decode("utf-8", errors="replace")
    return [p for p in out.split("\0") if p]


def _toml_table_keys(text: str, table: str) -> set[str] | None:
    """Top-level keys of a TOML table, or None when it is absent.

    A line scan, not a parser: the only question is which keys the table
    sets, and any header line ends it - [[x.overrides]] included.
    """
    keys: set[str] | None = None
    inside = False
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("["):
            inside = line == table
            if inside:
                keys = set()
            continue
        if inside and keys is not None and "=" in line and not line.startswith("#"):
            keys.add(line.split("=", 1)[0].strip().strip('"'))
    return keys


def _ini_section_keys(path: Path, section: str) -> set[str] | None:
    cp = configparser.ConfigParser()
    try:
        cp.read(path, encoding="utf-8")
    except configparser.Error:
        return None
    return set(cp[section].keys()) if cp.has_section(section) else None


def mypy_config(root: Path) -> tuple[str, set[str]]:
    """(source file, keys) from the config mypy itself would read.

    mypy's order: mypy.ini, .mypy.ini, pyproject.toml ([tool.mypy]),
    setup.cfg ([mypy]).
    """
    for name in ("mypy.ini", ".mypy.ini"):
        if (root / name).is_file():
            return name, _ini_section_keys(root / name, "mypy") or set()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        keys = _toml_table_keys(text, "[tool.mypy]")
        if keys is not None:
            return "pyproject.toml", keys
    setup_cfg = root / "setup.cfg"
    if setup_cfg.is_file():
        keys = _ini_section_keys(setup_cfg, "mypy")
        if keys is not None:
            return "setup.cfg", keys
    return "", set()


def pytest_config(root: Path) -> tuple[str, set[str]]:
    """(source file, keys) from the config pytest itself would read.

    pytest's order: pytest.ini, pyproject.toml
    ([tool.pytest.ini_options]), tox.ini ([pytest]), setup.cfg
    ([tool:pytest]).
    """
    if (root / "pytest.ini").is_file():
        return "pytest.ini", _ini_section_keys(root / "pytest.ini", "pytest") or set()
    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        text = pyproject.read_text(encoding="utf-8", errors="ignore")
        keys = _toml_table_keys(text, "[tool.pytest.ini_options]")
        if keys is not None:
            return "pyproject.toml", keys
    for name, section in (("tox.ini", "pytest"), ("setup.cfg", "tool:pytest")):
        if (root / name).is_file():
            keys = _ini_section_keys(root / name, section)
            if keys is not None:
                return name, keys
    return "", set()


def _is_test_file(path: str) -> bool:
    """pytest's default naming, judged on the BASENAME.

    Not a git pathspec: `test_*.py` there is matched against the whole
    path, so it never matched tests/test_a.py - measured 2026-09-11,
    which made the hook skip pytest in a repo full of tests.
    """
    name = path.rsplit("/", 1)[-1]
    return name.startswith("test_") or name.endswith("_test.py")


def _roots_and_untracked(
    root: Path, *, tests_only: bool = False
) -> tuple[list[str], list[str]] | None:
    """(top-level roots of tracked files, untracked files inside them)."""
    tracked = _git_files(root, "--", *PY_GLOBS)
    if tracked is None:
        return None
    keep = _is_test_file if tests_only else bool
    tracked = [t for t in tracked if keep(t)]
    roots = sorted({t.split("/", 1)[0] for t in tracked})
    others = _all_untracked(root, tests_only=tests_only)
    inside = sorted(
        u for u in others if "/" in u and u.split("/", 1)[0] in roots
    )
    return roots, inside


def _all_untracked(root: Path, *, tests_only: bool = False) -> list[str]:
    found = _git_files(root, "--others", "--exclude-standard", "--", *PY_GLOBS)
    keep = _is_test_file if tests_only else bool
    return sorted(f for f in found or [] if keep(f))


def _mypy_scope(root: Path) -> tuple[int, list[str], str]:
    source, keys = mypy_config(root)
    own_exclude = "exclude" in keys
    if "files" in keys:
        skip = [] if own_exclude else _all_untracked(root)
        args = _mypy_exclude(skip)
        note = f"from {source} `files`, as CI runs it"
        return 0, args, note + _skipped(skip, own_exclude, source)
    found = _roots_and_untracked(root)
    if found is None:
        return 0, ["."], "not a git repository - checking the whole tree"
    roots, inside = found
    if not roots:
        return SKIP, [], "no tracked Python files"
    skip = [] if own_exclude else inside
    args = [*roots, *_mypy_exclude(skip)]
    note = "tracked Python only: " + ", ".join(roots)
    note += _skipped(skip, own_exclude, source)
    return 0, args, note + ". Set `files` in your mypy config to match CI."


def _mypy_exclude(paths: list[str]) -> list[str]:
    if not paths:
        return []
    return ["--exclude", "^(" + "|".join(re.escape(p) for p in paths) + ")$"]


def _ruff_scope(root: Path) -> tuple[int, list[str], str]:
    found = _roots_and_untracked(root)
    if found is None:
        return 0, [".", "--extend-exclude", HOOKS_DIR], "not a git repository"
    roots, inside = found
    if not roots:
        return SKIP, [], "no tracked Python files"
    # Globs, comma-separated - ruff's syntax. --extend-exclude ADDS to the
    # project's own excludes; --exclude would replace them.
    excluded = [HOOKS_DIR, *inside]
    args = [*roots, "--extend-exclude", ",".join(excluded)]
    note = "tracked Python only: " + ", ".join(roots)
    if inside:
        note += f"; {len(inside)} untracked file(s) excluded"
    return 0, args, note + f"; {HOOKS_DIR} is caddis's own"


def _pytest_scope(root: Path) -> tuple[int, list[str], str]:
    source, keys = pytest_config(root)
    if "testpaths" in keys:
        # Still ignore untracked tests: `testpaths = ["tests"]` collects an
        # untracked failing test inside tests/, which CI never sees.
        skip = _all_untracked(root, tests_only=True)
        note = f"from {source} `testpaths`, as CI runs it"
        if skip:
            note += f"; {len(skip)} untracked test file(s) ignored"
        return 0, [f"--ignore={p}" for p in skip], note
    found = _roots_and_untracked(root, tests_only=True)
    if found is None:
        return 0, [], "not a git repository - collecting as usual"
    roots, inside = found
    if not roots:
        return SKIP, [], "no tracked test files"
    args = [*roots, *[f"--ignore={p}" for p in inside]]
    note = "tracked tests only: " + ", ".join(roots)
    if inside:
        note += f"; {len(inside)} untracked test file(s) ignored"
    return 0, args, note + ". Set `testpaths` in your pytest config to match CI."


def _skipped(paths: list[str], own_exclude: bool, source: str) -> str:
    if own_exclude:
        return f"; the {source} `exclude` stands, untracked files are kept"
    if paths:
        return f"; {len(paths)} untracked file(s) excluded"
    return ""


def scope(root: Path, tool: str = "mypy") -> tuple[int, list[str], str]:
    """(exit code, arguments, reason) for one tool."""
    root = Path(root)
    if tool == "ruff":
        return _ruff_scope(root)
    if tool == "pytest":
        return _pytest_scope(root)
    return _mypy_scope(root)


def main(argv: list[str] | None = None) -> int:
    """Print the reason line and the arguments, LF-only; return the code."""
    ap = argparse.ArgumentParser(description="scope for a pre-push gate")
    ap.add_argument("--tool", default="mypy", choices=("ruff", "mypy", "pytest"))
    a = ap.parse_args(argv)
    code, args, note = scope(Path.cwd(), a.tool)
    lines = [f"# {a.tool} scope: {note}", *args]
    # Bytes, not print(): text mode on Windows writes CRLF, and the sh hook
    # then passed "--exclude\r" to mypy, which rejected it.
    sys.stdout.buffer.write(("\n".join(lines) + "\n").encode("utf-8"))
    sys.stdout.flush()
    return code


if __name__ == "__main__":
    raise SystemExit(main())
