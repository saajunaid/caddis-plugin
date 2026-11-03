#!/usr/bin/env python3
"""caddis_run.py: run a caddis script by its bare name, from the plugin that is installed NOW.

Usage: python "<home>/.caddis/bin/caddis_run.py" <script.py> [args...]

Why it exists: Claude Code expands `${CLAUDE_PLUGIN_ROOT}` to a folder with the plugin version in its name
(`~/.claude/plugins/cache/caddis/caddis/1.3.165/`). A restart prompt, relay or restart sheet that copies that
expanded path fails after the next update, because the old version folder is gone. Text that a LATER session reads
names this launcher instead. The SessionStart hook keeps the copy in `~/.caddis/bin/` fresh (`install_launcher`).

The launcher finds the install in `~/.claude/plugins/installed_plugins.json` (key `caddis@caddis`), else the highest
version folder under `~/.claude/plugins/cache/caddis/caddis/`. It runs `<install>/scripts/<script.py>` with the
same Python, and passes stdout, stderr and the exit code through.

Exit codes: the script's own; 2 = bad usage or a script name that is not a bare `.py` file name; 3 = no caddis
install found, or the script is not in it.

Standard library only. This file is copied alone to `~/.caddis/bin/`: it imports no sibling script.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

EXIT_USAGE, EXIT_NOT_FOUND = 2, 3
PLUGIN_KEY = "caddis@caddis"
LAUNCHER_NAME = "caddis_run.py"

# A path into the versioned plugin cache: `.../plugins/cache/caddis/caddis/1.3.165/...`. Gone after the next update.
VERSIONED_PATH = re.compile(r"[/\\]caddis[/\\]caddis[/\\]\d")
VERSIONED_PATH_HELP = ("it names a versioned plugin path (.../caddis/caddis/<version>/...), which breaks at the next "
                       f'update: write python "<home>/.caddis/bin/{LAUNCHER_NAME}" <script> ... instead')

_BARE_PY = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.py")
_VERSION = re.compile(r"\d+(\.\d+)*")


def valid_script_name(name: str) -> bool:
    """A bare file name ending `.py`: no folder part, no `..`, no drive, no space."""
    return bool(_BARE_PY.fullmatch(name)) and ".." not in name


def _install_paths(home: Path) -> list[Path]:
    """The `installPath` values of `caddis@caddis` in installed_plugins.json: a list of entries or one object."""
    try:
        data = json.loads((home / ".claude" / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    plugins = data.get("plugins", data)
    entry = plugins.get(PLUGIN_KEY) if isinstance(plugins, dict) else None
    entries = entry if isinstance(entry, list) else [entry]
    return [Path(e["installPath"]) for e in entries if isinstance(e, dict) and isinstance(e.get("installPath"), str)]


def _cache_dir(home: Path) -> Path:
    return home / ".claude" / "plugins" / "cache" / "caddis" / "caddis"


def _newest_cached(home: Path) -> Path | None:
    """The version folder with the highest version, compared as tuples of ints (1.3.99 < 1.3.172)."""
    try:
        found = [(tuple(int(p) for p in d.name.split(".")), d) for d in _cache_dir(home).iterdir()
                 if d.is_dir() and _VERSION.fullmatch(d.name) and (d / "scripts").is_dir()]
    except OSError:
        return None
    return max(found, key=lambda pair: pair[0])[1] if found else None


def find_install(home: Path) -> Path | None:
    """The installed caddis plugin folder, or None."""
    for path in _install_paths(home):
        if (path / "scripts").is_dir():
            return path
    return _newest_cached(home)


def main(argv: list[str], home: Path | None = None) -> int:
    home = home or Path.home()
    if not argv:
        sys.stderr.write(f'usage: python "<home>/.caddis/bin/{LAUNCHER_NAME}" <script.py> [args...]\n')
        return EXIT_USAGE
    name, rest = argv[0], argv[1:]
    if not valid_script_name(name):
        sys.stderr.write(f"{LAUNCHER_NAME}: the script must be a bare file name that ends .py (no folder, no ..): {name!r}\n")
        return EXIT_USAGE
    install = find_install(home)
    if install is None:
        sys.stderr.write(f"{LAUNCHER_NAME}: no caddis plugin found: looked for key {PLUGIN_KEY} in "
                         f"{home / '.claude' / 'plugins' / 'installed_plugins.json'} and for a version folder in "
                         f"{_cache_dir(home)}\n")
        return EXIT_NOT_FOUND
    script = install / "scripts" / name
    if not script.is_file():
        sys.stderr.write(f"{LAUNCHER_NAME}: {name} is not in {install / 'scripts'}\n")
        return EXIT_NOT_FOUND
    return subprocess.call([sys.executable, str(script), *rest])


# -- the stable text, and the copy that keeps the launcher fresh -------------------------------------------------------


def _base(home: Path | None) -> Path:
    """`~` for the launcher copy: the `home` argument beats CADDIS_HOME, which beats the user's home folder
    (the rule of caddis_created.py and setup_project_ai.py: a test or sandbox points CADDIS_HOME at a temp folder)."""
    return Path(home) if home else Path(os.environ.get("CADDIS_HOME") or Path.home())


def launcher_path(home: Path | None = None) -> Path:
    return _base(home) / ".caddis" / "bin" / LAUNCHER_NAME


def stable_prefix(home: Path | None = None) -> str:
    """`python "<home>/.caddis/bin/caddis_run.py"`: put a bare script name and its arguments after it."""
    return f'python "{launcher_path(home).as_posix()}"'


def stable_command(script: str, home: Path | None = None) -> str:
    """`python "<home>/.caddis/bin/caddis_run.py" <script>`: the form for TEXT THAT A LATER SESSION READS.
    Forward slashes, so the same text works in bash and PowerShell. Machine-local on purpose."""
    if not valid_script_name(script):
        raise ValueError(f"not a bare .py file name: {script!r}")
    return f"{stable_prefix(home)} {script}"


def install_launcher(src: str | os.PathLike, home: Path | None = None) -> bool:
    """Copy `src` to `~/.caddis/bin/caddis_run.py` when the content differs. True when it wrote.

    A temp file in the same folder, then os.replace: a reader never sees a half-written launcher. Raises on error;
    the SessionStart hook catches it, because a launcher that cannot be refreshed must never stop a session."""
    data = Path(src).read_bytes()
    dest = launcher_path(home)
    try:
        if dest.read_bytes() == data:
            return False
    except OSError:
        pass
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=".caddis_run-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp, dest)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return True


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
