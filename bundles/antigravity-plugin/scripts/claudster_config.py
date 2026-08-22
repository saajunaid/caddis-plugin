"""Shared identity + config reader for a repo's caddis artifact dir — fail-open, dependency-free.

Two jobs:

1. **Functional identity in ONE place.** The artifact dir name, the env-var prefix, and the
   repo/tarball URL are constants here, so a future rename edits a constant instead of sweeping
   the tree. Anything that needs them imports from this module.
2. **The optional per-repo ``config.toml`` reader**, so the doc-coverage checker and Dream Memory
   don't each reimplement it (the guard hook keeps its own tiny reader — it lives under hooks/ and
   is safety-critical, so it stays self-contained). Every function returns a safe default rather
   than raising: a missing file, a parse error, a missing section, or a wrong-typed value all
   degrade to the caller's default — the "degrade gracefully, never block" bar of the rest of caddis.

The per-repo artifact dir is always ``.caddis`` — use :func:`artifact_root` / :func:`artifact_read` /
:func:`artifact_write`. A repo still carrying a pre-rename ``.claudster/`` (there should be none left
in this fleet) can be converted with ``/caddis:migrate-dir`` (``scripts/caddis_migrate_dir.py``);
nothing renames a repo's dir behind its back.

Config schema (see ``.caddis/config.toml.example``)::

    [doc_coverage]
    route_tree = "frontend/src/routeTree.gen.ts"
    page_guide = "UI_PAGE_GUIDE.md"
    claude_md_budget = 200
    ignore_routes = ["/health"]

    [dream_memory]
    prune_age_days = 14
    max_facts = 200
    surface_limit = 5
"""

from __future__ import annotations

import os
from pathlib import Path

# ── functional identity (rename here, not everywhere) ────────────────────────
#: The per-repo artifact directory caddis writes into.
ARTIFACT_DIR = ".caddis"
#: Read-preference order for the artifact dir. Single-element tuple kept so importers that iterate
#: this (a future rename adds an element here, not at each call site) don't need to change shape.
ARTIFACT_DIRS: tuple[str, ...] = (ARTIFACT_DIR,)

#: Environment-variable prefix — every caddis env var is ``<ENV_PREFIX>_<SUFFIX>``.
ENV_PREFIX = "CADDIS"

#: The published plugin repo (mirror). Everything URL-shaped derives from this one slug.
REPO_SLUG = "saajunaid/caddis-plugin"
REPO_URL = f"https://github.com/{REPO_SLUG}"
TARBALL_URL = f"https://codeload.github.com/{REPO_SLUG}/tar.gz/refs/heads/main"


def env_name(suffix: str) -> str:
    """The current env-var name for ``suffix`` (e.g. ``"GUARD_DISABLED"`` → ``CADDIS_GUARD_DISABLED``)."""
    return f"{ENV_PREFIX}_{suffix}"


def env_get(suffix: str, default: str | None = None) -> str | None:
    """``$CADDIS_<suffix>``."""
    val = os.environ.get(env_name(suffix))
    return default if val is None else val


# ── artifact-dir resolution ───────────────────────────────────────────────────
def artifact_root(root) -> Path:
    """The artifact dir to WRITE into for ``root`` — always ``.caddis``.

    Returns a path that may not exist yet — callers ``mkdir`` as needed.
    """
    return Path(root) / ARTIFACT_DIR


def artifact_dir_name(root) -> str:
    """Just the directory NAME the repo lives in (``".caddis"``) — for messages."""
    return artifact_root(root).name


def artifact_read(root, *parts) -> Path:
    """``.caddis/<parts>`` — the path to read an artifact from."""
    return artifact_root(root).joinpath(*parts)


def artifact_write(root, *parts) -> Path:
    """Path under :func:`artifact_root` — where a NEW artifact should be written."""
    return artifact_root(root).joinpath(*parts)


def load_config(root, section: str) -> dict:
    """Return the ``[section]`` table from the repo's ``.caddis/config.toml``, or ``{}`` on any problem."""
    try:
        import tomllib  # Python 3.11+ stdlib
    except Exception:
        return {}
    cfg = artifact_read(root, "config.toml")
    if not cfg.is_file():
        return {}
    try:
        with open(cfg, "rb") as fh:
            data = tomllib.load(fh)
    except Exception:
        return {}
    sec = data.get(section, {})
    return sec if isinstance(sec, dict) else {}


def get_int(cfg: dict, key: str, default: int) -> int:
    """A positive int from ``cfg[key]``, else ``default`` (rejects bool, non-int, and < 1)."""
    v = cfg.get(key, default)
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        return default
    return v


def get_str(cfg: dict, key: str, default: str) -> str:
    """A non-empty string from ``cfg[key]``, else ``default``."""
    v = cfg.get(key, default)
    return v if isinstance(v, str) and v.strip() else default


def get_str_list(cfg: dict, key: str, default: list[str]) -> list[str]:
    """A list-of-strings from ``cfg[key]``, else ``default``."""
    v = cfg.get(key, default)
    if isinstance(v, list) and all(isinstance(x, str) for x in v):
        return v
    return default
