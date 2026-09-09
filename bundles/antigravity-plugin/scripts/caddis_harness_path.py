#!/usr/bin/env python3
"""Find the caddis SOURCE checkout from anywhere, so friction can be parked where it belongs.

Almost every insight about the harness is noticed while NOT working on the harness — a session in
an app repo hits friction and is in the wrong place to do anything about it. Today's options are
all bad: park it locally where the maintainer never looks, say it in chat where it dies with the
session, switch repos mid-task (nobody does), or remember it later (this is the one that actually
happens, and later is usually never).

So harness improvement is whatever someone recalls at the end of a session. The observations that
survive are not a random sample: small, frequent friction — the kind that would most improve daily
use — is exactly what does not survive, because it is not dramatic enough to recall.

This resolves the target so `/caddis:park --harness` is a flag rather than a context switch.

NOT the installed plugin. `CLAUDE_PLUGIN_ROOT` points at a read-only copy that is replaced on
every update; an item written there is gone at the next `claude plugin update`. The maintainer
works in the source checkout, so that is what this finds.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

EXIT_OK, EXIT_NOT_FOUND = 0, 1

ENV_VAR = "CADDIS_HARNESS_ROOT"
POINTER = Path.home() / ".caddis" / "harness-root"

# A source checkout has BOTH of these. The installed plugin has neither pair, and an app repo
# scaffolded by caddis has `.caddis/parking-lot/` but no `claude-harness/` — which is the
# distinction that matters, because writing into an app repo is the exact failure to avoid.
SIGNATURE = ("claude-harness", os.path.join(".caddis", "parking-lot"))


def looks_like_harness(path: Path) -> bool:
    try:
        return all((path / part).is_dir() for part in SIGNATURE)
    except OSError:
        return False


def resolve_harness_root(cwd: Path | None = None,
                         env: dict | None = None,
                         pointer: Path | None = None) -> tuple[Path | None, str]:
    """(path, how-it-was-found) or (None, why-not).

    Order is deliberate: an explicit answer beats a remembered one, and a remembered one beats a
    guess. The search is last and is deliberately narrow.
    """
    env = os.environ if env is None else env
    pointer = POINTER if pointer is None else pointer

    raw = (env.get(ENV_VAR) or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if looks_like_harness(p):
            return p, f"{ENV_VAR}"
        return None, (f"{ENV_VAR} is set to {raw!r}, which is not a caddis source checkout "
                      f"(needs both {SIGNATURE[0]}/ and {SIGNATURE[1]}/). Fix or unset it — an "
                      "explicit setting is never silently ignored.")

    try:
        noted = pointer.read_text(encoding="utf-8").strip()
    except OSError:
        noted = ""
    if noted:
        p = Path(noted).expanduser()
        if looks_like_harness(p):
            return p, str(pointer)
        return None, (f"{pointer} points at {noted!r}, which is no longer a caddis source "
                      "checkout. Re-run with --set <path>.")

    # Last resort: siblings of the current repo, then siblings of its parent. Every project on a
    # given machine tends to live under one or two roots, so the checkout is usually a sibling of
    # whatever repo noticed the friction. Deliberately shallow — a filesystem-wide search would
    # be slow and would eventually find a stale clone.
    start = (cwd or Path.cwd()).resolve()
    seen: set[Path] = set()
    for base in (start, *start.parents):
        parent = base.parent
        if parent in seen or parent == base:
            continue
        seen.add(parent)
        try:
            candidates = sorted(d for d in parent.iterdir() if d.is_dir())
        except OSError:
            continue
        for d in candidates:
            if looks_like_harness(d):
                return d, f"found beside {base.name}"
        if len(seen) >= 3:
            break

    return None, ("no caddis source checkout found. Set it once and it is remembered:"
                  f"{os.linesep}    python caddis_harness_path.py --set <path-to-checkout>"
                  f"{os.linesep}  or export {ENV_VAR}. NOT the installed plugin — an item written "
                  "there is discarded by the next `claude plugin update`.")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--set", dest="set_to", default=None,
                    help="remember this path as the caddis source checkout")
    ap.add_argument("--cwd", default=".", help="resolve as if from here")
    a = ap.parse_args(argv)

    if a.set_to:
        p = Path(a.set_to).expanduser().resolve()
        if not looks_like_harness(p):
            sys.stderr.write(f"[harness] {p} is not a caddis source checkout — needs both "
                             f"{SIGNATURE[0]}/ and {SIGNATURE[1]}/{os.linesep}")
            return EXIT_NOT_FOUND
        POINTER.parent.mkdir(parents=True, exist_ok=True)
        POINTER.write_text(str(p) + "\n", encoding="utf-8")
        print(f"[harness] remembered {p} in {POINTER}")
        return EXIT_OK

    root, how = resolve_harness_root(Path(a.cwd).resolve())
    if root is None:
        # FAIL LOUDLY. Silently writing into the local repo is the failure this exists to prevent:
        # the item would sit in an app repo the maintainer never reads, which is the status quo.
        sys.stderr.write("[harness] " + how + os.linesep)
        return EXIT_NOT_FOUND
    print(str(root))
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
