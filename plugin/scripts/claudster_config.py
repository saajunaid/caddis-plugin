"""Shared reader for the per-repo ``.claudster/config.toml`` — fail-open, dependency-free.

One place to parse the optional config so the doc-coverage checker and Dream Memory don't each
reimplement it (the guard hook keeps its own tiny reader — it lives under hooks/ and is
safety-critical, so it stays self-contained). Every function returns a safe default rather than
raising: a missing file, a parse error, a missing section, or a wrong-typed value all degrade to
the caller's default. This mirrors the "degrade gracefully, never block" bar of the rest of caddis.

Config schema (see ``.claudster/config.toml.example``)::

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

from pathlib import Path


def load_config(root, section: str) -> dict:
    """Return the ``[section]`` table from ``<root>/.claudster/config.toml``, or ``{}`` on any problem."""
    try:
        import tomllib  # Python 3.11+ stdlib
    except Exception:
        return {}
    cfg = Path(root) / ".claudster" / "config.toml"
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
