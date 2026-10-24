#!/usr/bin/env python3
"""Turn a from,to,count edge list into a first-draft Mermaid flowchart.

The draft applies the count and layout rules of the flow-chart-from-counts skill:

- counts go in quoted brackets on arrows: |"(1,234)"|
- paths under --min are not drawn; the note names how many and how big they were
- the chart is drawn as a TREE: each box keeps one parent edge (the biggest path into it); every other
  path into it becomes a small dashed stub under its own source, "to X (n)". Shared targets are what
  make the layout cross lines. --no-tree keeps shared targets as real edges.
- each source that ends gets its own end box, so no long lines cross the chart to one shared box
- a loop back to an earlier step becomes a "back to X (n)" stub, not an edge
- edges and nodes are written largest first: the layout takes that as its first guess for left to right
- duplicate from,to rows are added together into one path
- node types become classDefs named t_<type> (they never clash with the built-in classes endn, stub and
  startn); --in-scope types get a thick border, --optional types a dashed one

It is a draft. Read the rendered chart and fix the layout by hand (SKILL.md, "Layout fixes").

Usage:
    python edges_to_mermaid.py edges.csv [--nodes nodes.csv] [--min 25] [--in-scope T1,T2]
                               [--optional T3] [--direction TD] [--end-label "Ends"] [--no-tree]
                               [--out chart.mmd] [--strict]

edges.csv columns: from,to,count, where count is DISTINCT cases per pair (also accepted: from_step,
to_step,case_count). Do not feed it path occurrences (COUNT(*)): see references/edge-list-sql.md.
nodes.csv columns: name,type[,count]; count is the distinct cases in that box.
The Mermaid source goes to --out FILE (written as UTF-8) or, without --out, to stdout (also UTF-8).
The note on hidden paths and any warning go to stderr. With --strict, any self-check warning gives exit 1
(the chart is still written). Exit codes: 0 ok, 1 strict warning, 2 bad input.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

START = "START"
END = "END"

# Light fills with dark text: they keep contrast on a light canvas in both page themes.
PALETTE = [
    ("#dbe4ee", "#475569"),
    ("#bbf7d0", "#15803d"),
    ("#f6e7d6", "#b45309"),
    ("#e9d5ff", "#7e22ce"),
    ("#fde68a", "#a16207"),
    ("#cffafe", "#0e7490"),
    ("#fecdd3", "#be123c"),
]
TEXT = "#1c1917"


@dataclass(frozen=True)
class Edge:
    src: str
    dst: str
    count: int


@dataclass
class Result:
    mermaid: str
    hidden_paths: int
    hidden_total: int
    note: str
    warnings: list[str] = field(default_factory=list)


def node_id(name: str) -> str:
    """A stable Mermaid id: a readable slug plus a 6-character hash.

    A collision is very unlikely but not impossible. convert() checks for one and raises ValueError.
    """
    if name == START:
        return "start"
    slug = re.sub(r"[^A-Za-z0-9]+", "_", name).strip("_").lower()[:24] or "node"
    digest = hashlib.sha1(name.encode("utf-8")).hexdigest()[:6]
    return f"n_{slug}_{digest}"


def _label(text: str) -> str:
    """Escape a name for a quoted Mermaid label. '#' goes first: it starts every entity code."""
    text = " ".join(text.splitlines())
    for raw, code in (("#", "#35;"), ('"', "#quot;"), ("<", "#lt;"), (">", "#gt;"), ("[", "#91;"), ("]", "#93;"), ("&", "#amp;")):
        text = text.replace(raw, code)
    return text


def merge_edges(edges: list[Edge]) -> list[Edge]:
    """Add the counts of duplicate (from, to) pairs. First-seen order is kept."""
    total: dict[tuple[str, str], int] = {}
    for e in edges:
        total[(e.src, e.dst)] = total.get((e.src, e.dst), 0) + e.count
    return [Edge(a, b, n) for (a, b), n in total.items()]


def _n(count: int) -> str:
    return f"{count:,}"


def _order_sources(edges: list[Edge]) -> list[str]:
    """Sources in breadth-first order from START, then any left over, so the text reads top-down."""
    out: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        out[e.src].append(e)
    roots = [START] if START in out else sorted({e.src for e in edges} - {e.dst for e in edges})
    seen: list[str] = []
    queue = list(roots)
    while queue:
        cur = queue.pop(0)
        if cur in seen or cur == END:
            continue
        seen.append(cur)
        queue.extend(e.dst for e in sorted(out.get(cur, []), key=lambda x: -x.count))
    seen += sorted(s for s in out if s not in seen)
    return [s for s in seen if s in out]


def _back_edges(edges: list[Edge], roots: list[str]) -> set[Edge]:
    """Edges that point to a step still open on the depth-first path: the loop-backs."""
    out: dict[str, list[Edge]] = defaultdict(list)
    for e in edges:
        out[e.src].append(e)
    back: set[Edge] = set()
    state: dict[str, int] = {}  # 1 = on the path, 2 = done

    def visit(node: str) -> None:
        state[node] = 1
        for e in sorted(out.get(node, []), key=lambda x: -x.count):
            if e.dst == END:
                continue
            if state.get(e.dst) == 1:
                back.add(e)
            elif e.dst not in state:
                visit(e.dst)
        state[node] = 2

    for r in roots:
        if r not in state:
            visit(r)
    for s in list(out):
        if s not in state:
            visit(s)
    return back


def _reachable(edges: list[Edge], roots: list[str]) -> set[str]:
    out: dict[str, list[str]] = defaultdict(list)
    for e in edges:
        out[e.src].append(e.dst)
    seen: set[str] = set()
    stack = list(roots)
    while stack:
        cur = stack.pop()
        if cur in seen:
            continue
        seen.add(cur)
        stack.extend(out.get(cur, []))
    return seen


def convert(
    edges: list[Edge],
    min_count: int = 1,
    box_counts: dict[str, int] | None = None,
    node_types: dict[str, str] | None = None,
    in_scope: set[str] | frozenset[str] = frozenset(),
    optional: set[str] | frozenset[str] = frozenset(),
    direction: str = "TD",
    end_label: str = "Ends",
    tree: bool = True,
) -> Result:
    box_counts = box_counts or {}
    node_types = node_types or {}
    edges = merge_edges(edges)
    seen_ids: dict[str, str] = {}
    for name in {n for e in edges for n in (e.src, e.dst) if n != END}:
        other = seen_ids.setdefault(node_id(name), name)
        if other != name:
            raise ValueError(f"{other!r} and {name!r} would get the same id; rename one of them")

    small = [e for e in edges if e.count < min_count]
    kept = [e for e in edges if e.count >= min_count]
    has_start = any(e.src == START for e in edges)
    roots = [START] if has_start else sorted({e.src for e in edges} - {e.dst for e in edges})
    live = _reachable(kept, roots)
    orphaned = [e for e in kept if e.src not in live]
    kept = [e for e in kept if e.src in live]

    back = _back_edges(kept, roots)
    # Tree mode: the biggest forward path into a box is its one parent edge; the rest become stubs.
    stubbed: set[Edge] = set()
    if tree:
        into: dict[str, list[Edge]] = defaultdict(list)
        for e in kept:
            if e.dst != END and e not in back:
                into[e.dst].append(e)
        for incoming in into.values():
            incoming.sort(key=lambda x: (-x.count, x.src))
            stubbed.update(incoming[1:])
    layout = [e for e in kept if e not in back and e not in stubbed]
    lines = [f"flowchart {direction}"]

    # Declare nodes in the same largest-first order as the edges: Mermaid places the first-declared
    # child of a rank on the left, so declaration order is part of the layout.
    names: list[str] = []
    ordered = sorted(layout, key=lambda x: -x.count)
    for src in _order_sources(layout):
        for n in [src] + [e.dst for e in ordered if e.src == src]:
            if n != END and n not in names:
                names.append(n)
    for e in kept:
        for n in (e.src, e.dst):
            if n != END and n not in names:
                names.append(n)
    start_total = sum(e.count for e in kept if e.src == START) + sum(e.count for e in small if e.src == START)
    for name in names:
        if name == START:
            lines.append(f'  start(["Start<br/>({_n(start_total)})"])')
            continue
        text = _label(name)
        if name in box_counts:
            text += f"<br/>({_n(box_counts[name])})"
        lines.append(f'  {node_id(name)}["{text}"]')

    by_src: dict[str, list[Edge]] = defaultdict(list)
    for e in kept:
        by_src[e.src].append(e)
    end_ids: list[str] = []
    stub_ids: list[str] = []
    sources = _order_sources(layout)
    sources += [s for s in _order_sources(kept) if s not in sources]
    for src in sources:
        sid = node_id(src)
        for e in sorted(by_src[src], key=lambda x: -x.count):
            arrow = f'{sid} -->|"({_n(e.count)})"|'
            if e.dst == END:
                eid = f"end_{sid}"
                end_ids.append(eid)
                lines.append(f'  {arrow} {eid}(["{_label(end_label)}"])')
            elif e in back or e in stubbed:
                word = "back to" if e in back else "to"
                bid = f"{word.split()[0]}_{sid}_{node_id(e.dst)}"
                stub_ids.append(bid)
                lines.append(f'  {sid} --> {bid}(["{word} {_label(e.dst)} ({_n(e.count)})"])')
            else:
                lines.append(f"  {arrow} {node_id(e.dst)}")

    types = []
    for name in names:
        t = node_types.get(name)
        if t and t not in types:
            types.append(t)
    for i, t in enumerate(types):
        fill, stroke = PALETTE[i % len(PALETTE)]
        extra = ""
        if t in in_scope:
            extra = ",stroke-width:3px"
        elif t in optional:
            extra = ",stroke-width:2px,stroke-dasharray:6 4"
        lines.append(f"  classDef t_{t} fill:{fill},stroke:{stroke},color:{TEXT}{extra};")
    if end_ids:
        lines.append(f"  classDef endn fill:#eceae6,stroke:#78716c,color:{TEXT};")
    if stub_ids:
        lines.append("  classDef stub fill:#ffffff,stroke:#a8a29e,stroke-dasharray:3 3,color:#57534e;")
    if has_start and START in names:
        lines.append(f"  classDef startn fill:#ffffff,stroke:#57534e,stroke-width:2px,color:{TEXT};")
    for t in types:
        ids = [node_id(n) for n in names if node_types.get(n) == t]
        lines.append(f"  class {','.join(ids)} t_{t};")
    if end_ids:
        lines.append(f"  class {','.join(end_ids)} endn;")
    if stub_ids:
        lines.append(f"  class {','.join(stub_ids)} stub;")
    if has_start and START in names:
        lines.append("  class start startn;")

    hidden_total = sum(e.count for e in small)
    note_parts = []
    if small:
        note_parts.append(
            f"Not drawn: {len(small)} paths with fewer than {_n(min_count)} each "
            f"({_n(hidden_total)} in total): "
            + "; ".join(f"{e.src} to {e.dst} ({_n(e.count)})" for e in sorted(small, key=lambda x: -x.count))
            + "."
        )
    if orphaned:
        note_parts.append(f"Also not drawn: {len(orphaned)} paths that start from a step that is not drawn.")
    note = " ".join(note_parts)
    if note:
        lines.append(f"  %% {note}")
    # Self-check: an arrow counts distinct cases, so it can never be larger than the box at either end.
    # When it is, the edge list counts path occurrences (COUNT(*)), not cases.
    warnings = []
    for e in kept:
        for end in (e.src, e.dst):
            if end in box_counts and e.count > box_counts[end]:
                warnings.append(
                    f"{e.src} to {e.dst} ({_n(e.count)}) is larger than the box {end} ({_n(box_counts[end])}): "
                    "the edge list counts path occurrences, not distinct cases"
                )
    return Result("\n".join(lines) + "\n", len(small), hidden_total, note, warnings)


def build(edges: list[Edge], **kwargs) -> str:
    return convert(edges, **kwargs).mermaid


def _col(row: dict[str, str], *names: str, where: str = "csv") -> str:
    lower = {k.strip().lower(): v for k, v in row.items() if k}
    for n in names:
        if n in lower:
            if lower[n] is None:
                raise ValueError(f"{where}: the row has no value for {n!r} (the row is shorter than the header)")
            return lower[n].strip()
    raise ValueError(f"{where}: missing column, expected one of {names}; got {sorted(lower)}")


def read_edges(path: Path) -> list[Edge]:
    edges = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for line_no, row in enumerate(csv.DictReader(fh), start=2):
            where = f"{path}:{line_no}"
            raw = _col(row, "count", "case_count", "n", where=where)
            try:
                count = int(raw.replace(",", ""))
            except ValueError as exc:
                raise ValueError(f"{path}:{line_no}: count is not a whole number: {raw!r}") from exc
            edges.append(
                Edge(_col(row, "from", "from_step", "src", where=where), _col(row, "to", "to_step", "dst", where=where), count)
            )
    return merge_edges(edges)


def read_nodes(path: Path) -> tuple[dict[str, str], dict[str, int]]:
    types: dict[str, str] = {}
    counts: dict[str, int] = {}
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for line_no, row in enumerate(csv.DictReader(fh), start=2):
            where = f"{path}:{line_no}"
            name = _col(row, "name", "step", "node", where=where)
            t = _col(row, "type", "kind", where=where)
            if t:
                types[name] = re.sub(r"[^A-Za-z0-9_]", "_", t)
            lower = {k.strip().lower(): v for k, v in row.items() if k}
            raw = (lower.get("count") or lower.get("case_count") or "").strip()
            if raw:
                try:
                    counts[name] = int(raw.replace(",", ""))
                except ValueError as exc:
                    raise ValueError(f"{where}: count is not a whole number: {raw!r}") from exc
    return types, counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("edges", type=Path)
    ap.add_argument("--nodes", type=Path)
    ap.add_argument("--min", type=int, default=1, dest="min_count")
    ap.add_argument("--in-scope", default="")
    ap.add_argument("--optional", default="")
    ap.add_argument("--direction", default="TD", choices=["TD", "LR"])
    ap.add_argument("--end-label", default="Ends")
    ap.add_argument("--no-tree", action="store_true", help="keep shared targets as real edges, no stubs")
    ap.add_argument("--out", type=Path, help="write the Mermaid source to this file as UTF-8 (default: stdout)")
    ap.add_argument("--strict", action="store_true", help="exit 1 when the self-check finds an arrow larger than a box")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")

    try:
        edges = read_edges(args.edges)
        types, counts = read_nodes(args.nodes) if args.nodes else ({}, {})
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    split = lambda s: {x.strip() for x in s.split(",") if x.strip()}
    try:
        result = convert(
            edges,
            min_count=args.min_count,
            box_counts=counts,
            node_types=types,
            in_scope=split(args.in_scope),
            optional=split(args.optional),
            direction=args.direction,
            end_label=args.end_label,
            tree=not args.no_tree,
        )
        if args.out:
            args.out.write_text(result.mermaid, encoding="utf-8", newline="\n")
        else:
            sys.stdout.write(result.mermaid)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if result.note:
        print(result.note, file=sys.stderr)
    for w in result.warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.strict and result.warnings:
        print(f"error: --strict: {len(result.warnings)} self-check warning(s)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
