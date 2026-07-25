"""Dream Memory — caddis's short-term, self-maintaining per-repo fact store (fann Phase 5a).

Ports the dedupe / reinforce / prune / conflict logic of fann-core's
``src/memory/consolidator.ts`` into caddis's hooks-and-scripts world. This module is the
**pure consolidation engine** — the genuinely portable, fully-testable core. It owns the fact
schema and the four pure functions the design names (``merge`` / ``prune`` / ``conflicts`` /
``rank_for_surfacing``), plus thin, fail-open filesystem glue to load/save the JSONL store.

Mental model (see ``.claudster/plans/dream-memory-design.md``): Dream Memory is *short-term working
memory* — automatic, structured facts that get **reinforced** when they recur and **decay** when
they don't. It complements (never replaces) the curated layers: ``relay.md`` (session handoff),
``.claudster/kb/*.md`` (curated code docs), and the central ``.claude`` MEMORY.md (cross-repo
durable facts). A fact that proves durable is *promoted* up into a curated store and then allowed
to decay out here.

Design split mirrors ``check_doc_coverage.py``: a filesystem-free pure core (text/dicts in →
dicts out, unit-tested without a tree) and a small glue layer (``load_facts`` / ``save_facts`` /
the CLI) that does all I/O and **fails open & silent** — Dream Memory must never block or slow a
turn.

A fact (one JSON object per line in ``.claudster/memory.jsonl``)::

    {
      "kind":     "failure-mode | rejected-approach | repo-fact | workflow-success",
      "key":      "pytest::import-error",     # normalized dedup key (kind-scoped)
      "summary":  "pytest fails on a cold checkout — run `alembic upgrade` first",
      "hitCount": 3,
      "firstSeen": "2026-07-01T09:00:00Z",
      "lastSeen":  "2026-07-01T15:00:00Z",
      "source":   "auto | knowledge-transfer | manual",
      "evidence": "tests/test_api.py"          # optional, short
    }

Fingerprint = ``kind + ":" + normalize(key)``. The file holds **consolidated** facts (not raw
events) — it self-compacts each cycle (``merge`` then ``prune``).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# Schema constants. Tunables live here (a per-repo ``.claudster/config.toml``
# override is a deliberate fast-follow, matching check_doc_coverage / guard).
# --------------------------------------------------------------------------- #
KINDS: tuple[str, ...] = ("failure-mode", "rejected-approach", "repo-fact", "workflow-success")
SOURCES: tuple[str, ...] = ("auto", "knowledge-transfer", "manual")

# The "don't repeat this" kinds — weighted up when surfacing (they cost the most to relearn).
WEIGHTED_KINDS: frozenset[str] = frozenset({"failure-mode", "rejected-approach"})

PRUNE_AGE_DAYS = 14          # single-hit facts older than this decay out
MAX_FACTS = 200              # hard cap on the store; oldest-by-recency overflow drops first
SURFACE_LIMIT = 5            # SessionStart shows at most this many (context-economy-safe)

DEFAULT_STORE = ".claudster/memory.jsonl"

_REQUIRED_FIELDS = ("kind", "key", "summary", "hitCount", "firstSeen", "lastSeen", "source")
_EPOCH = datetime.min.replace(tzinfo=timezone.utc)


# --------------------------------------------------------------------------- #
# Pure helpers (no filesystem) — the testable core.
# --------------------------------------------------------------------------- #
def normalize_key(value: str) -> str:
    """Lowercase, trim, and collapse internal whitespace — the dedup-key canonical form."""
    return " ".join((value or "").strip().lower().split())


def fingerprint(fact: dict) -> str:
    """The dedup identity. Prefers an explicit ``fp`` (a hash of the FULL command, set at capture) so two
    distinct commands that share a truncated 80-char head don't collapse into one inflated ``hitCount``;
    falls back to ``kind:normalize(key)`` for facts written before ``fp`` existed (and for non-command facts)."""
    fp = fact.get("fp")
    if isinstance(fp, str) and fp:
        return f"{fact.get('kind', '')}:{fp}"
    basis = fact.get("key") or fact.get("summary") or ""
    return f"{fact.get('kind', '')}:{normalize_key(basis)}"


def _parse_iso(value) -> datetime:
    """Parse an ISO-8601 timestamp to an aware datetime; unparseable/empty → the epoch floor.

    Tolerant by design (the store may be hand-edited): a bad timestamp must never crash a cycle,
    it just sorts as oldest. Accepts a trailing ``Z`` (Python <3.11 ``fromisoformat`` rejects it).
    """
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    s = (value or "").strip()
    if not s:
        return _EPOCH
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return _EPOCH
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def make_fact(
    kind: str,
    key: str,
    summary: str,
    observed_at: str,
    *,
    source: str = "auto",
    evidence: str | None = None,
    fp: str | None = None,
) -> dict:
    """Construct a well-formed single-hit fact (``hitCount=1``, first==last==observed).

    ``fp`` (optional) is the full-command dedup fingerprint; when set it overrides the key-based
    fingerprint so distinct commands sharing a truncated display key don't merge."""
    fact = {
        "kind": kind,
        "key": key,
        "summary": summary,
        "hitCount": 1,
        "firstSeen": observed_at,
        "lastSeen": observed_at,
        "source": source,
    }
    if evidence:
        fact["evidence"] = evidence
    if fp:
        fact["fp"] = fp
    return fact


def is_valid_fact(fact) -> bool:
    """True if ``fact`` has every required field, a known ``kind``, and a positive int hitCount.

    Used to reject malformed/hand-broken lines when loading and to validate capture candidates.
    """
    if not isinstance(fact, dict):
        return False
    if any(f not in fact for f in _REQUIRED_FIELDS):
        return False
    if fact["kind"] not in KINDS:
        return False
    hc = fact["hitCount"]
    if not isinstance(hc, int) or isinstance(hc, bool) or hc < 1:
        return False
    return bool(str(fact["summary"]).strip())


def _hit(fact: dict) -> int:
    try:
        n = int(fact.get("hitCount", 1))
    except (TypeError, ValueError):
        return 1
    return n if n >= 1 else 1


# --------------------------------------------------------------------------- #
# The four pure consolidation functions the design names. Filesystem-free.
# --------------------------------------------------------------------------- #
def merge(facts: list[dict]) -> list[dict]:
    """Group by fingerprint into consolidated facts (insertion order of first appearance).

    For each group: sum ``hitCount``; ``firstSeen`` = min, ``lastSeen`` = max; the **newest**
    (latest ``lastSeen``) member's ``summary`` / ``source`` / ``evidence`` win. This is the
    reinforce step — re-running it over (existing ⧺ new candidates) accretes hit counts. Each
    returned fact is a fresh dict; inputs are never mutated.
    """
    merged: dict[str, dict] = {}
    order: list[str] = []

    for f in facts:
        fp = fingerprint(f)
        if fp not in merged:
            first = f.get("firstSeen") or f.get("lastSeen") or ""
            last = f.get("lastSeen") or f.get("firstSeen") or ""
            g = dict(f)
            g["hitCount"] = _hit(f)
            g["firstSeen"] = first
            g["lastSeen"] = last
            merged[fp] = g
            order.append(fp)
            continue

        g = merged[fp]
        g["hitCount"] += _hit(f)

        f_first = f.get("firstSeen") or f.get("lastSeen") or ""
        if _parse_iso(f_first) < _parse_iso(g["firstSeen"]):
            g["firstSeen"] = f_first

        f_last = f.get("lastSeen") or f.get("firstSeen") or ""
        # >= so a later-in-list tie counts as "newest wins" (last writer for same timestamp).
        if _parse_iso(f_last) >= _parse_iso(g["lastSeen"]):
            g["lastSeen"] = f_last
            if f.get("summary"):
                g["summary"] = f["summary"]
            if f.get("source"):
                g["source"] = f["source"]
            if f.get("evidence"):
                g["evidence"] = f["evidence"]

    return [merged[fp] for fp in order]


def prune(facts: list[dict], now, *, max_age_days: int = PRUNE_AGE_DAYS, cap: int = MAX_FACTS) -> list[dict]:
    """Decay then cap.

    1. Drop ``hitCount <= 1`` facts whose ``lastSeen`` is older than ``max_age_days`` (one-hit
       noise fades on its own). Reinforced facts (hitCount >= 2) are never aged out.
    2. Keep the top ``cap`` by ``(hitCount desc, lastSeen desc)`` — overflow drops the
       least-reinforced, oldest facts first.

    ``now`` may be an ISO string or a datetime. Returns a new list; inputs are never mutated.
    """
    now_dt = _parse_iso(now)
    cutoff = now_dt - timedelta(days=max_age_days)

    kept = [
        f for f in facts
        if not (_hit(f) <= 1 and _parse_iso(f.get("lastSeen")) < cutoff)
    ]
    kept.sort(key=lambda f: (_hit(f), _parse_iso(f.get("lastSeen"))), reverse=True)
    return kept[:cap]


def conflicts(facts: list[dict]) -> list[dict]:
    """Flag fingerprints carrying materially different summaries — don't auto-resolve, surface.

    "Materially different" = distinct after :func:`normalize_key`. Returns one entry per
    conflicting fingerprint: ``{"kind", "key", "summaries": [...]}`` with the distinct summaries
    in first-seen order. Intended to run over (existing ⧺ incoming) *before* merge collapses them.
    """
    by_fp: dict[str, list[dict]] = {}
    for f in facts:
        by_fp.setdefault(fingerprint(f), []).append(f)

    out: list[dict] = []
    for group in by_fp.values():
        distinct: list[str] = []
        seen_norm: set[str] = set()
        for f in group:
            summary = str(f.get("summary", ""))
            norm = normalize_key(summary)
            if norm and norm not in seen_norm:
                seen_norm.add(norm)
                distinct.append(summary)
        if len(distinct) > 1:
            out.append({
                "kind": group[0].get("kind", ""),
                "key": group[0].get("key", ""),
                "summaries": distinct,
            })
    return out


def rank_for_surfacing(facts: list[dict], n: int = SURFACE_LIMIT, *, now=None) -> list[dict]:
    """Top ``n`` facts to show at SessionStart — score ≈ ``weight × hitCount × recency``.

    ``failure-mode`` / ``rejected-approach`` (the "don't repeat this" kinds) are weighted up. If
    ``now`` is given, recency decays continuously with age; otherwise facts are ordered by
    ``lastSeen`` directly (a now-free, deterministic proxy). Stable: ties break by ``lastSeen``
    desc then fingerprint. Returns a new list; inputs are never mutated.
    """
    now_dt = _parse_iso(now) if now is not None else None

    def score(f: dict) -> float:
        weight = 2.0 if f.get("kind") in WEIGHTED_KINDS else 1.0
        if now_dt is None:
            return weight * _hit(f)
        age_days = max(0.0, (now_dt - _parse_iso(f.get("lastSeen"))).total_seconds() / 86400.0)
        recency = 1.0 / (1.0 + age_days)  # 1.0 today, halves after a day, decays smoothly
        return weight * _hit(f) * recency

    ranked = sorted(
        facts,
        key=lambda f: (score(f), _parse_iso(f.get("lastSeen")), fingerprint(f)),
        reverse=True,
    )
    return ranked[:n]


def consolidate(facts: list[dict], now, *, max_age_days: int = PRUNE_AGE_DAYS, cap: int = MAX_FACTS) -> list[dict]:
    """One full cycle: ``merge`` (reinforce + dedup) then ``prune`` (decay + cap). Pure."""
    return prune(merge(facts), now, max_age_days=max_age_days, cap=cap)


# --------------------------------------------------------------------------- #
# Filesystem glue — fail-open & silent. All I/O lives here, mirroring
# check_doc_coverage's pure-core / glue split. Never raises into a hook.
# --------------------------------------------------------------------------- #
def load_facts(path: Path) -> list[dict]:
    """Read the JSONL store, skipping blank/malformed/invalid lines. Missing file → ``[]``.

    Tolerant by design: a hand-edited or partially-written store must never crash a turn.
    """
    path = Path(path)
    if not path.exists():
        return []
    facts: list[dict] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        if is_valid_fact(obj):
            facts.append(obj)
    return facts


def save_facts(path: Path, facts: list[dict]) -> bool:
    """Write facts as JSONL (one compact object per line). Returns True on success, never raises.

    Writes via a temp file + atomic replace so a crash mid-write can't corrupt the store.
    """
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        lines = [json.dumps(f, ensure_ascii=False, sort_keys=True) for f in facts]
        tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        tmp.replace(path)
        return True
    except OSError:
        return False


def load_tunables(root) -> dict:
    """Read ``[dream_memory]`` overrides from ``<root>/.claudster/config.toml``; defaults otherwise.

    Returns ``{"prune_age_days", "max_facts", "surface_limit"}``. Fail-open — a missing config, a
    missing helper, or a bad value degrades to the baked-in default, never raising into a hook.
    """
    defaults = {"prune_age_days": PRUNE_AGE_DAYS, "max_facts": MAX_FACTS, "surface_limit": SURFACE_LIMIT}
    try:
        from claudster_config import get_int, load_config
        cfg = load_config(root, "dream_memory")
        return {
            "prune_age_days": get_int(cfg, "prune_age_days", PRUNE_AGE_DAYS),
            "max_facts": get_int(cfg, "max_facts", MAX_FACTS),
            "surface_limit": get_int(cfg, "surface_limit", SURFACE_LIMIT),
        }
    except Exception:
        return defaults


def _repo_root() -> Path:
    """Git top-level if available, else cwd — location-independent (matches the caddis hooks)."""
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=5,
        )
        if out.returncode == 0 and out.stdout.strip():
            return Path(out.stdout.strip())
    except Exception:
        pass
    return Path.cwd()


def _format_surface(facts: list[dict]) -> list[str]:
    """Render ranked facts as the ≤5 SessionStart lines (the surfacing hook reuses this in 5c)."""
    lines: list[str] = []
    for f in facts:
        mark = "⚠ " if f.get("kind") in WEIGHTED_KINDS else "  "
        hits = _hit(f)
        suffix = f"  (×{hits})" if hits > 1 else ""
        lines.append(f"  {mark}{f.get('kind')}: {f.get('summary')}{suffix}")
    return lines


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")  # Windows cp1252 can't encode ⚠/× glyphs
    parser = argparse.ArgumentParser(
        description="Inspect / consolidate the Dream Memory fact store (.claudster/memory.jsonl).",
    )
    parser.add_argument(
        "--consolidate",
        action="store_true",
        help="Run a merge+prune cycle and rewrite the store (no-op if it would not change).",
    )
    parser.add_argument(
        "--now",
        default=None,
        help="ISO timestamp to use as 'now' for decay/ranking (default: current UTC).",
    )
    args = parser.parse_args()

    now = args.now or datetime.now(timezone.utc).isoformat()
    root = _repo_root()
    store = root / DEFAULT_STORE
    tune = load_tunables(root)
    facts = load_facts(store)

    if not facts:
        print("[memory] no facts yet.")
        return

    if args.consolidate:
        consolidated = consolidate(facts, now, max_age_days=tune["prune_age_days"], cap=tune["max_facts"])
        save_facts(store, consolidated)
        print(f"[memory] consolidated: {len(facts)} → {len(consolidated)} facts.")
        facts = consolidated

    top = rank_for_surfacing(facts, tune["surface_limit"], now=now)
    print("[memory] reinforced facts for this repo (auto; fades if not seen):")
    for line in _format_surface(top):
        print(line)
    issues = conflicts(facts)
    if issues:
        print(f"\n[memory] {len(issues)} conflicting fact(s) — review:")
        for c in issues:
            print(f"  {c['kind']}: {c['key']} → {len(c['summaries'])} differing summaries")


if __name__ == "__main__":
    main()
