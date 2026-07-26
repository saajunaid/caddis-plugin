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

**The dual-path rule** (the ``.claudster`` → ``.caddis`` transition, one version then dropped):

* READS try ``.caddis`` first, then legacy ``.claudster`` — use :func:`artifact_read`.
* WRITES go **where the repo already lives**: ``.caddis`` if it exists, else ``.claudster`` if
  *that* exists (an unmigrated repo keeps its dir — we never scatter a second one), else ``.caddis``
  for a fresh repo — use :func:`artifact_root` / :func:`artifact_write`.

Migrate a repo with ``/caddis:migrate-dir`` (``scripts/caddis_migrate_dir.py``); nothing renames
a repo's dir behind its back.

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
#: The pre-rename directory, still READ as a one-version fallback (dropped after the fleet soak).
LEGACY_ARTIFACT_DIR = ".claudster"
#: Read-preference order for the artifact dir. First hit wins.
ARTIFACT_DIRS: tuple[str, ...] = (ARTIFACT_DIR, LEGACY_ARTIFACT_DIR)

#: Environment-variable prefix — every caddis env var is ``<ENV_PREFIX>_<SUFFIX>``.
ENV_PREFIX = "CADDIS"
#: The pre-rename prefix, still read as a one-version fallback.
LEGACY_ENV_PREFIX = "CLAUDSTER"

#: The published plugin repo (mirror). Everything URL-shaped derives from this one slug.
REPO_SLUG = "saajunaid/caddis-plugin"
REPO_URL = f"https://github.com/{REPO_SLUG}"
TARBALL_URL = f"https://codeload.github.com/{REPO_SLUG}/tar.gz/refs/heads/main"


def env_name(suffix: str) -> str:
    """The current env-var name for ``suffix`` (e.g. ``"GUARD_DISABLED"`` → ``CADDIS_GUARD_DISABLED``)."""
    return f"{ENV_PREFIX}_{suffix}"


def env_get(suffix: str, default: str | None = None) -> str | None:
    """``$CADDIS_<suffix>``, falling back to ``$CLAUDSTER_<suffix>`` (one-version back-compat)."""
    val = os.environ.get(env_name(suffix))
    if val is None:
        val = os.environ.get(f"{LEGACY_ENV_PREFIX}_{suffix}")
    return default if val is None else val


# ── artifact-dir resolution (the dual-path rule) ─────────────────────────────
def artifact_root(root) -> Path:
    """The artifact dir to WRITE into for ``root`` — "write where the repo lives".

    ``.caddis`` when it exists; else legacy ``.claudster`` when *that* exists (an unmigrated repo
    keeps using its own dir rather than growing a second one); else ``.caddis`` (fresh repo).
    Returns a path that may not exist yet — callers ``mkdir`` as needed.
    """
    base = Path(root)
    for name in ARTIFACT_DIRS:
        if (base / name).is_dir():
            return base / name
    return base / ARTIFACT_DIR


def artifact_dir_name(root) -> str:
    """Just the directory NAME the repo lives in (``".caddis"`` / ``".claudster"``) — for messages."""
    return artifact_root(root).name


def artifact_read(root, *parts) -> Path:
    """First existing of ``.caddis/<parts>`` then ``.claudster/<parts>``; else the write-side path.

    The non-existent fallback keeps callers' ``is_file()`` guards working unchanged, and points at
    the dir the repo lives in so an error message names the right place.
    """
    base = Path(root)
    for name in ARTIFACT_DIRS:
        cand = base.joinpath(name, *parts)
        if cand.exists():
            return cand
    return artifact_root(base).joinpath(*parts)


def artifact_write(root, *parts) -> Path:
    """Path under :func:`artifact_root` — where a NEW artifact should be written."""
    return artifact_root(root).joinpath(*parts)


def legacy_artifact_dir(root) -> Path | None:
    """``<root>/.claudster`` when the repo still has one AND has already grown a ``.caddis`` — i.e.
    a half-migrated repo (the straggler case). ``None`` otherwise. Used for nudges/diagnostics."""
    base = Path(root)
    legacy = base / LEGACY_ARTIFACT_DIR
    if legacy.is_dir() and (base / ARTIFACT_DIR).is_dir():
        return legacy
    return None


def load_config(root, section: str) -> dict:
    """Return the ``[section]`` table from the repo's ``config.toml``, or ``{}`` on any problem.

    Dual-read: ``.caddis/config.toml`` wins, legacy ``.claudster/config.toml`` is the fallback.
    """
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
