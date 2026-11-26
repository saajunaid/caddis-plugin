"""Confluence tracker page section from a repo roadmap or plan.

Subcommands:
- `render` prints the Confluence storage-format tracker section from committed git state, with no network.
- `check` verifies the Confluence login and target or parent page with GET requests only.
- `sync` updates or creates only the source's marked tracker section on Confluence and records local sync state.
- `sync-all` syncs every opted-in roadmap or plan whose source files changed since its last sync.
- `stale` checks local sync state against git history with no network call.

Exit codes (`caddis_exit`): 0 clean, 1 Confluence refused / broken markers / stale drift, 3 not configured / network /
git failure, 4 bad input.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import html
import json
import os
from pathlib import Path
import re
import subprocess
import sys

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit

import caddis_roadmap
import caddis_stories
from caddis_frontmatter import split_document
from caddis_status import is_done, status_state

SIDE_KEYS = (
    "schema",
    "title",
    "jira_epic",
    "confluence_tracker",
    "confluence_tracker_parent",
    "decider",
    "lanes",
    "decisions",
    "estimates",
    "step_parts",
)
LOZENGE_COLOURS = {
    "DONE": "Green",
    "IN PROGRESS": "Blue",
    "WAITING": "Yellow",
    "BLOCKED": "Red",
    "NEXT": "Grey",
}
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
_STEP_COLOURS = ("blue", "yellow", "grey", "green")
_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
_GIT_TIMEOUT = 60

_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*(.*?)[ \t]*$")
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_PLAN_PATH_RE = re.compile(r"^\.caddis/plans/[^/\\]+\.md$")
_ROADMAP_TRACKER_RE = re.compile(r"^\.caddis/roadmaps/([^/]+)/tracker\.md$")
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TrackerInputError(ValueError):
    """Invalid side file, roadmap, plan or command option."""


class TrackerGitError(Exception):
    """Git is missing, times out, or the root or ref is not a git commit."""


@dataclass
class Estimate:
    label: str
    range: str
    note: str = ""


@dataclass
class StepPart:
    part: str
    minutes: int


@dataclass
class SideFile:
    title: str | None = None
    jira_epic: str | None = None
    confluence_tracker: str | None = None
    confluence_tracker_parent: str | None = None
    decider: str = "owner"
    lanes: list[tuple[str, list[str]]] = field(default_factory=list)
    decisions: dict[str, dict[str, str]] = field(default_factory=dict)
    estimates: list[Estimate] = field(default_factory=list)
    step_parts: list[StepPart] = field(default_factory=list)


@dataclass
class Item:
    key: str
    name: str
    status: str
    target: str
    steps: tuple[int, int] | None = None
    blocked: list[tuple[str, str]] = field(default_factory=list)


@dataclass
class Lane:
    name: str
    items: list[Item]


@dataclass
class Decision:
    decision: str
    who: str
    unblocks: str


@dataclass
class Page:
    title: str
    unit: str
    lanes: list[Lane]
    decisions: list[Decision]
    estimates: list[Estimate] = field(default_factory=list)
    step_parts: list[StepPart] = field(default_factory=list)


@dataclass
class Source:
    kind: str
    name: str
    slug: str
    page: Page
    jira_epic: str | None
    page_url: str | None
    parent_url: str | None
    title: str | None
    paths: list[str]


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def _closes_fence(line: str, fence: str) -> bool:
    closed = _FENCE_CLOSE_RE.match(line)
    return bool(closed) and closed.group(1)[0] == fence[0] and len(closed.group(1)) >= len(fence)


def json_block(text: str) -> object:
    """Parse the first fenced block whose info string is `json`."""
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        opened = _FENCE_OPEN_RE.match(lines[i])
        if not opened:
            i += 1
            continue
        fence, rest = opened.group(1), opened.group(2)
        if fence[0] == "`" and "`" in rest:
            i += 1
            continue
        info = rest.split()[0].lower() if rest else ""
        body: list[str] = []
        i += 1
        while i < len(lines) and not _closes_fence(lines[i], fence):
            body.append(lines[i])
            i += 1
        if i >= len(lines):
            if info == "json":
                raise TrackerInputError("the json block in tracker.md has no closing fence")
            break
        i += 1
        if info == "json":
            try:
                return json.loads("\n".join(body))
            except ValueError as exc:
                raise TrackerInputError(f"the json block in tracker.md does not parse: {exc}") from exc
    raise TrackerInputError("tracker.md has no fenced json block")


def _non_empty_str(value: object, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TrackerInputError(f"{where} must be a non-empty string")
    return value.strip()


def read_side_file(text: str) -> SideFile:
    """Validate and parse a `tracker.md` side file."""
    raw = json_block(text)
    if not isinstance(raw, dict):
        raise TrackerInputError("the json block in tracker.md must be a json object")
    schema = raw.get("schema")
    if isinstance(schema, bool) or schema != 1:
        raise TrackerInputError("schema must be 1")
    for key in raw:
        if key not in SIDE_KEYS:
            raise TrackerInputError(f"unknown key '{key}'")

    scalars: dict[str, str] = {}
    for key in ("title", "jira_epic", "confluence_tracker", "confluence_tracker_parent", "decider"):
        if key in raw:
            scalars[key] = _non_empty_str(raw[key], key)
    if "confluence_tracker" in scalars and "confluence_tracker_parent" in scalars:
        raise TrackerInputError("set confluence_tracker or confluence_tracker_parent, not both")

    lanes: list[tuple[str, list[str]]] = []
    if "lanes" in raw:
        raw_lanes = raw["lanes"]
        if not isinstance(raw_lanes, list):
            raise TrackerInputError("lanes must be a list")
        for idx, item in enumerate(raw_lanes):
            where = f"lanes[{idx}]"
            if not isinstance(item, dict):
                raise TrackerInputError(f"{where} must be a json object")
            for k in item:
                if k not in ("name", "milestones"):
                    raise TrackerInputError(f"unknown key '{k}' in {where}")
            name = _non_empty_str(item.get("name"), f"{where}.name")
            ms = item.get("milestones")
            if not isinstance(ms, list) or not all(isinstance(m, str) and m.strip() for m in ms):
                raise TrackerInputError(f"{where}.milestones must be a list of strings")
            lanes.append((name, [m.strip() for m in ms]))

    decisions: dict[str, dict[str, str]] = {}
    if "decisions" in raw:
        raw_decisions = raw["decisions"]
        if not isinstance(raw_decisions, dict):
            raise TrackerInputError("decisions must be a json object")
        for mid, entry in raw_decisions.items():
            if not isinstance(mid, str) or not mid.strip():
                raise TrackerInputError("decisions keys must be non-empty strings")
            where = f"decisions.{mid}"
            if not isinstance(entry, dict):
                raise TrackerInputError(f"{where} must be a json object")
            for k in entry:
                if k not in ("decision", "who"):
                    raise TrackerInputError(f"unknown key '{k}' in {where}")
            out_entry: dict[str, str] = {}
            for k in ("decision", "who"):
                if k in entry:
                    val = entry[k]
                    if not isinstance(val, str):
                        raise TrackerInputError(f"{where}.{k} must be a string")
                    out_entry[k] = val.strip()
            decisions[mid] = out_entry

    estimates: list[Estimate] = []
    if "estimates" in raw:
        raw_estimates = raw["estimates"]
        if not isinstance(raw_estimates, list):
            raise TrackerInputError("estimates must be a list")
        for idx, item in enumerate(raw_estimates):
            where = f"estimates[{idx}]"
            if not isinstance(item, dict):
                raise TrackerInputError(f"{where} must be a json object")
            for k in item:
                if k not in ("label", "range", "note"):
                    raise TrackerInputError(f"unknown key '{k}' in {where}")
            est_label = _non_empty_str(item.get("label"), f"{where}.label")
            est_range = _non_empty_str(item.get("range"), f"{where}.range")
            note = item.get("note", "")
            if not isinstance(note, str):
                raise TrackerInputError(f"{where}.note must be a string")
            estimates.append(Estimate(est_label, est_range, note.strip()))

    step_parts: list[StepPart] = []
    if "step_parts" in raw:
        raw_parts = raw["step_parts"]
        if not isinstance(raw_parts, list):
            raise TrackerInputError("step_parts must be a list")
        for idx, item in enumerate(raw_parts):
            where = f"step_parts[{idx}]"
            if not isinstance(item, dict):
                raise TrackerInputError(f"{where} must be a json object")
            for k in item:
                if k not in ("part", "minutes"):
                    raise TrackerInputError(f"unknown key '{k}' in {where}")
            part = _non_empty_str(item.get("part"), f"{where}.part")
            minutes = item.get("minutes")
            if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes <= 0:
                raise TrackerInputError(f"{where}.minutes must be a whole number above 0")
            step_parts.append(StepPart(part, minutes))

    return SideFile(
        title=scalars.get("title"),
        jira_epic=scalars.get("jira_epic"),
        confluence_tracker=scalars.get("confluence_tracker"),
        confluence_tracker_parent=scalars.get("confluence_tracker_parent"),
        decider=scalars.get("decider", "owner"),
        lanes=lanes,
        decisions=decisions,
        estimates=estimates,
        step_parts=step_parts,
    )


def item_status(status_cell: str, blocker_types: Sequence[str]) -> str | None:
    """Map a roadmap Status or plan Tracker cell and open blocker types to a lozenge name, or None when left off."""
    cleaned = (status_cell or "").strip().strip("*`").strip().lower()
    if cleaned == "not-needed":
        return None
    state = status_state(status_cell)
    if state == "moved":
        return None
    if state == "done":
        return "DONE"
    if state == "in-progress":
        return "IN PROGRESS"
    if "owner-gate" in blocker_types:
        return "WAITING"
    if blocker_types or state == "blocked":
        return "BLOCKED"
    return "NEXT"


def day_label(day: date) -> str:
    return f"{day.day} {MONTHS[day.month - 1]}"


def week_monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def week_label(monday: date) -> str:
    friday = monday + timedelta(days=4)
    if monday.month == friday.month:
        return f"{monday.day}-{friday.day} {MONTHS[monday.month - 1]}"
    return f"{day_label(monday)}-{day_label(friday)}"


def label(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\|", "|").replace("**", "").replace("`", "")).strip()


# ---------------------------------------------------------------- page model and storage render

def _build_lanes(
    unit: str,
    all_ids: Sequence[str],
    items_by_id: Mapping[str, Item],
    raw_lanes: Sequence[tuple[str, Sequence[str]]],
) -> list[Lane]:
    known = set(all_ids)
    counts: dict[str, int] = {}
    for lane_name, ids in raw_lanes:
        for item_id in ids:
            if item_id not in known:
                raise TrackerInputError(f"lane '{lane_name}' names unknown {unit} {item_id}")
            counts[item_id] = counts.get(item_id, 0) + 1
    for item_id in all_ids:
        if item_id in items_by_id:
            count = counts.get(item_id, 0)
            if count == 0:
                raise TrackerInputError(f"{unit} {item_id} is in no lane")
            if count > 1:
                raise TrackerInputError(f"{unit} {item_id} is in more than one lane")
    lanes: list[Lane] = []
    for lane_name, ids in raw_lanes:
        lane_items = [items_by_id[i] for i in ids if i in items_by_id]
        if lane_items:
            lanes.append(Lane(name=lane_name, items=lane_items))
    return lanes


def roadmap_page(
    rm: caddis_roadmap.Roadmap,
    side: SideFile,
    steps: Mapping[str, tuple[int, int]] | None = None,
) -> Page:
    if rm.errors:
        raise TrackerInputError(f"roadmap has {len(rm.errors)} error(s): {rm.errors[0]}")
    all_ids = [ms.id for ms in rm.milestones]
    known = set(all_ids)
    for mid in side.decisions:
        if mid not in known:
            raise TrackerInputError(f"decisions names unknown milestone {mid}")

    items_by_id: dict[str, Item] = {}
    decisions: list[Decision] = []
    step_map = steps or {}
    for ms in rm.milestones:
        blockers = rm.blockers_of(ms.id)
        st = item_status(ms.status, [b.type for b in blockers])
        if st is None:
            continue
        non_og = [(b.type, b.reason) for b in blockers if b.type != "owner-gate"]
        ms_label = label(ms.name)
        items_by_id[ms.id] = Item(
            key=ms.id,
            name=ms_label,
            status=st,
            target=ms.target,
            steps=step_map.get(ms.id),
            blocked=non_og,
        )
        og_reasons = [b.reason for b in blockers if b.type == "owner-gate"]
        if st != "DONE" and og_reasons:
            override = side.decisions.get(ms.id, {})
            dec_text = override.get("decision") or "; ".join(og_reasons)
            who = override.get("who") or side.decider
            decisions.append(Decision(decision=dec_text, who=who, unblocks=ms_label))

    lanes = _build_lanes("milestone", all_ids, items_by_id, side.lanes)
    if not lanes:
        raise TrackerInputError("nothing to show: no milestone is left after not-needed ones")
    return Page(
        title=side.title or "",
        unit="milestone",
        lanes=lanes,
        decisions=decisions,
        estimates=list(side.estimates),
        step_parts=list(side.step_parts),
    )


def plan_title(text: str) -> str:
    _, body = split_document(text)
    stripped = caddis_stories.strip_fences(body)
    match = re.search(r"^# (.+)$", stripped, re.M)
    return caddis_stories.TITLE_SUFFIX.sub("", match.group(1)).strip() if match else ""


def plan_page(plan_text: str, side: SideFile | None) -> Page:
    _, body = split_document(plan_text)
    headings = caddis_stories.phase_headings(body)
    if not headings:
        raise TrackerInputError("no '### Phase <n> - <name>' heading in the plan")
    rows = caddis_stories.tracker_rows(caddis_stories.strip_fences(body))
    all_ids: list[str] = []
    items_by_id: dict[str, Item] = {}
    for pid, raw_name, _milestone in headings:
        all_ids.append(pid)
        row = rows.get(pid.lower(), {})
        status_cell = row.get("status", "")
        raw_target = row.get("target", "").strip()
        target = "" if raw_target == "-" else raw_target
        st = item_status(status_cell, [])
        if st is not None:
            items_by_id[pid] = Item(key=pid, name=label(raw_name), status=st, target=target)

    p_title = plan_title(plan_text)
    if side is not None and side.lanes:
        lanes = _build_lanes("phase", all_ids, items_by_id, side.lanes)
    else:
        lane_items = [items_by_id[pid] for pid in all_ids if pid in items_by_id]
        lanes = [Lane(name=p_title, items=lane_items)] if lane_items else []
    if not lanes:
        raise TrackerInputError("nothing to show: no phase is left after moved ones")
    title = side.title if side and side.title else p_title
    return Page(
        title=title,
        unit="phase",
        lanes=lanes,
        decisions=[],
        estimates=list(side.estimates) if side else [],
        step_parts=list(side.step_parts) if side else [],
    )


def column_key(item: Item) -> str:
    if item.status == "DONE":
        return "done"
    parsed = caddis_roadmap.iso_date(item.target)
    if parsed is not None:
        return week_monday(parsed).isoformat()
    return "nodate"


def columns(page: Page, today: date) -> list[tuple[str, str, str]]:
    keys = {column_key(item) for lane in page.lanes for item in lane.items}
    out: list[tuple[str, str, str]] = [("done", "Done", "green")]
    this_monday = week_monday(today)
    for wk in sorted(k for k in keys if k not in ("done", "nodate")):
        monday = date.fromisoformat(wk)
        colour = "blue" if monday == this_monday else ("red" if monday < this_monday else "grey")
        out.append((wk, week_label(monday), colour))
    if "nodate" in keys:
        out.append(("nodate", "No date yet", "grey"))
    return out


def is_late(item: Item, today: date) -> bool:
    if item.status == "DONE":
        return False
    parsed = caddis_roadmap.iso_date(item.target)
    return parsed is not None and parsed < today


def item_text(item: Item, today: date) -> str:
    parts = [item.name]
    if item.steps is not None:
        done_steps, total_steps = item.steps
        parts.append(f" ({done_steps} of {total_steps} steps)")
    if is_late(item, today):
        target_date = caddis_roadmap.iso_date(item.target)
        assert target_date is not None
        parts.append(f" - late, target was {day_label(target_date)}")
    if column_key(item) == "nodate" and item.target:
        parts.append(f" (target {item.target})")
    if item.blocked:
        parts.append(" - blocked: " + "; ".join(f"{t} - {r}" for t, r in item.blocked))
    return "".join(parts)


def lozenge(status: str) -> str:
    colour = LOZENGE_COLOURS[status]
    return (
        f'<ac:structured-macro ac:name="status"><ac:parameter ac:name="colour">{colour}</ac:parameter>'
        f'<ac:parameter ac:name="title">{status}</ac:parameter></ac:structured-macro>'
    )


def render_inner(page: Page, today: date) -> str:
    all_items = [item for lane in page.lanes for item in lane.items]
    done = sum(1 for item in all_items if item.status == "DONE")
    total = len(all_items)
    pct = round(100 * done / total) if total else 0

    est_html = ""
    if page.estimates:
        est_items = [
            f"<li><strong>{_esc(est.label)}:</strong> {_esc(est.range.rstrip('.'))}. {_esc(est.note)}</li>"
            if est.note
            else f"<li><strong>{_esc(est.label)}:</strong> {_esc(est.range)}</li>"
            for est in page.estimates
        ]
        est_html = "<ul>" + "".join(est_items) + "</ul>"

    out: list[str] = [
        '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
        f"<p><strong>{done} of {total} {page.unit}s done ({pct}%).</strong></p>"
        "<p><strong>Target dates are estimates, not commitments.</strong></p>"
        f"{est_html}"
        "</ac:rich-text-body></ac:structured-macro>",
        "<h2>Overall progress</h2>",
        "<table><tbody><tr>"
        + '<td class="highlight-green" data-highlight-colour="green">&nbsp;</td>' * done
        + '<td class="highlight-grey" data-highlight-colour="grey">&nbsp;</td>' * (total - done)
        + "</tr></tbody></table>",
        f"<p>Each block is one {page.unit}. Green = done ({done}), grey = to do ({total - done}).</p>",
        "<h2>Swimlanes</h2>",
        "<p>" + " ".join(lozenge(s) for s in LOZENGE_COLOURS) + "</p>",
    ]

    cols = columns(page, today)
    head = (
        "<tr><th>Workstream</th>"
        + "".join(
            f'<th class="highlight-{colour}" data-highlight-colour="{colour}">{_esc(col_label)}</th>'
            for _, col_label, colour in cols
        )
        + "<th>Target (estimate)</th></tr>"
    )
    rows: list[str] = []
    for lane in page.lanes:
        lane_done = sum(1 for i in lane.items if i.status == "DONE")
        cells = [f"<td><strong>{_esc(lane.name)}</strong><br/>{lane_done} of {len(lane.items)} done</td>"]
        for col_key, _, _ in cols:
            entries = [
                f"<p>{lozenge(i.status)} {_esc(item_text(i, today))}</p>"
                for i in lane.items
                if column_key(i) == col_key
            ]
            cells.append(f"<td>{''.join(entries) or '<p>&nbsp;</p>'}</td>")
        open_dates = [
            d
            for i in lane.items
            if i.status != "DONE" and (d := caddis_roadmap.iso_date(i.target)) is not None
        ]
        lane_target = day_label(max(open_dates)) if open_dates else "-"
        cells.append(f"<td><strong>{_esc(lane_target)}</strong></td>")
        rows.append("<tr>" + "".join(cells) + "</tr>")
    out.append(f"<table><tbody>{head}{''.join(rows)}</tbody></table>")

    out.append("<h2>Decisions we are waiting for</h2>")
    n_dec = len(page.decisions)
    if n_dec == 0:
        out.append("<p>No open decisions.</p>")
    else:
        out.append(f"<p>{n_dec} open decision{'s' if n_dec != 1 else ''}.</p>")
        dec_rows = "".join(
            f"<tr><td>{lozenge('WAITING')} {_esc(d.decision)}</td><td>{_esc(d.who)}</td><td>{_esc(d.unblocks)}</td></tr>"
            for d in page.decisions
        )
        out.append(
            "<table><tbody><tr><th>Decision</th><th>Who decides</th><th>What it unblocks</th></tr>"
            + dec_rows
            + "</tbody></table>"
        )

    if page.step_parts:
        out.append("<h2>One step of work</h2>")
        step_cells = []
        for idx, part in enumerate(page.step_parts):
            colour = _STEP_COLOURS[idx % len(_STEP_COLOURS)]
            colspan = max(1, part.minutes // 5)
            step_cells.append(
                f'<td colspan="{colspan}" class="highlight-{colour}" data-highlight-colour="{colour}">'
                f"<strong>{_esc(part.part)}</strong><br/>about {part.minutes} min</td>"
            )
        out.append("<table><tbody><tr>" + "".join(step_cells) + "</tr></tbody></table>")
        total_min = sum(p.minutes for p in page.step_parts)
        out.append(f"<p>One step takes about {total_min} minutes from start to live (estimate).</p>")

    return "".join(out)


def anchor(name: str) -> str:
    return (
        f'<p><ac:structured-macro ac:name="anchor"><ac:parameter ac:name="">{name}</ac:parameter>'
        f"</ac:structured-macro></p>"
    )


def render_section(page: Page, slug: str, today: date, sha: str) -> str:
    inner = render_inner(page, today)
    h = caddis_stories.section_hash(inner)
    short_sha = (sha or "")[:8] or "unknown"
    footer = (
        f"<p><em>Generated by caddis from commit {short_sha} on {today.isoformat()}. Do not edit this "
        f"section: the next sync replaces it. Add a comment instead.</em></p>"
    )
    return anchor(f"caddis-tracker-{slug}-start-{h}") + inner + footer + anchor(f"caddis-tracker-{slug}-end")


# ---------------------------------------------------------------- git reads, step counts and CLI

def git_out(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_CEILING_DIRECTORIES"] = str(Path(root).resolve().parent)
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=_NO_WINDOW,
            timeout=_GIT_TIMEOUT,
        )
    except FileNotFoundError as exc:
        raise TrackerGitError("git is not installed or not on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        cmd = args[0] if args else "command"
        raise TrackerGitError(f"git {cmd} timed out after {_GIT_TIMEOUT} s") from exc


def ref_ok(root: Path, ref: str) -> bool:
    if not ref or ref.startswith("-"):
        return False
    return git_out(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}").returncode == 0


def git_show(root: Path, ref: str, path: str) -> str | None:
    proc = git_out(root, "show", f"{ref}:{path}")
    if proc.returncode != 0:
        return None
    return proc.stdout.decode("utf-8", errors="replace").replace("\r\n", "\n")


def git_files(root: Path, ref: str, prefix: str) -> list[str]:
    proc = git_out(root, "ls-tree", "-r", "--name-only", ref, "--", prefix)
    if proc.returncode != 0:
        return []
    return sorted(line for line in proc.stdout.decode("utf-8", errors="replace").splitlines() if line)


def source_sha(root: Path, ref: str, paths: Sequence[str]) -> str:
    if not paths:
        return ""
    proc = git_out(root, "log", "-1", "--format=%H", ref, "--", *paths)
    if proc.returncode != 0:
        return ""
    return proc.stdout.decode("utf-8", errors="replace").strip()


def common_dir(root: Path) -> str:
    proc = git_out(root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    if proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise TrackerGitError(err or f"{root} is not a git repository")
    return proc.stdout.decode("utf-8", errors="replace").strip()


def milestone_steps(root: Path, ref: str, rm: caddis_roadmap.Roadmap) -> tuple[dict[str, tuple[int, int]], list[str]]:
    steps: dict[str, tuple[int, int]] = {}
    plan_paths: list[str] = []
    cache: dict[str, dict[int, str]] = {}
    for ms in rm.milestones:
        if not ms.phases:
            continue
        done_count = 0
        for r in ms.phases:
            match = caddis_roadmap.REF_RE.match(r)
            if not match:
                raise TrackerInputError(f"{ms.id}: invalid phase ref {r}")
            plan_name, phase_str = match.group(1), match.group(2)
            if plan_name not in cache:
                rel = f".caddis/plans/{plan_name}.md"
                text = git_show(root, ref, rel)
                if text is None:
                    rel = f".caddis/plans/done/{plan_name}.md"
                    text = git_show(root, ref, rel)
                if text is None:
                    raise TrackerInputError(
                        f"{ms.id}: unknown phase ref {r} (no plan .caddis/plans/{plan_name}.md at {ref})"
                    )
                cache[plan_name] = caddis_roadmap.parse_tracker(text)
                plan_paths.append(rel)
            tracker_map = cache[plan_name]
            phase_num = int(phase_str)
            if phase_num not in tracker_map:
                raise TrackerInputError(f"{ms.id}: unknown phase ref {r} (no Tracker row)")
            if is_done(tracker_map[phase_num]):
                done_count += 1
        steps[ms.id] = (done_count, len(ms.phases))
    return steps, sorted(set(plan_paths))


def _meta_str(meta: Mapping[str, object], key: str) -> str | None:
    value = meta.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def load_source(root: Path, ref: str, roadmap: str | None = None, plan: str | None = None) -> Source:
    if (roadmap is None) == (plan is None):
        raise TrackerInputError("give exactly one of roadmap or plan")
    root = Path(root)
    if not ref_ok(root, ref):
        raise TrackerGitError(f"{ref} is not a commit in {root}")

    if roadmap is not None:
        if not caddis_roadmap.SLUG_RE.match(roadmap):
            raise TrackerInputError(f"bad roadmap slug '{roadmap}'")
        rm_rel = caddis_roadmap.roadmap_path(roadmap)
        side_rel = f".caddis/roadmaps/{roadmap}/tracker.md"
        rm_text = git_show(root, ref, rm_rel)
        if rm_text is None:
            raise TrackerInputError(f"{rm_rel} not found at {ref}")
        side_text = git_show(root, ref, side_rel)
        if side_text is None:
            raise TrackerInputError(f"{side_rel} not found at {ref}")
        rm = caddis_roadmap.parse_roadmap(rm_text)
        if rm.errors:
            raise TrackerInputError(f"roadmap has {len(rm.errors)} error(s): {rm.errors[0]}")
        side = read_side_file(side_text)
        steps, plan_paths = milestone_steps(root, ref, rm)
        page = roadmap_page(rm, side, steps)
        paths = sorted({rm_rel, side_rel, *plan_paths})
        return Source(
            kind="roadmap",
            name=roadmap,
            slug=f"roadmap-{roadmap}",
            page=page,
            jira_epic=side.jira_epic,
            page_url=side.confluence_tracker,
            parent_url=side.confluence_tracker_parent,
            title=side.title,
            paths=paths,
        )

    assert plan is not None
    if not _PLAN_PATH_RE.match(plan):
        raise TrackerInputError(f"plan path '{plan}' must match .caddis/plans/<name>.md")
    plan_text = git_show(root, ref, plan)
    if plan_text is None:
        raise TrackerInputError(f"{plan} not found at {ref}")
    meta, _ = split_document(plan_text)
    p_slug = caddis_stories.plan_slug(meta, Path(plan))
    slug = f"plan-{p_slug}"
    side_rel = f".caddis/trackers/{p_slug}.md"
    side_text = git_show(root, ref, side_rel)
    side_obj: SideFile | None = None
    paths = [plan]
    if side_text is not None:
        side_obj = read_side_file(side_text)
        if side_obj.jira_epic or side_obj.confluence_tracker or side_obj.confluence_tracker_parent:
            raise TrackerInputError(
                "a plan's tracker side file must not hold jira_epic, confluence_tracker or "
                "confluence_tracker_parent; put them in the plan front matter"
            )
        paths.append(side_rel)
    jira_epic = _meta_str(meta, "jira_epic")
    page_url = _meta_str(meta, "confluence_tracker")
    parent_url = _meta_str(meta, "confluence_tracker_parent")
    if page_url and parent_url:
        raise TrackerInputError("set confluence_tracker or confluence_tracker_parent in plan front matter, not both")
    page = plan_page(plan_text, side_obj)
    return Source(
        kind="plan",
        name=plan,
        slug=slug,
        page=page,
        jira_epic=jira_epic,
        page_url=page_url,
        parent_url=parent_url,
        title=side_obj.title if side_obj else None,
        paths=sorted(set(paths)),
    )


def discover(root: Path, ref: str) -> list[tuple[str, str]]:
    """List opted-in tracker sources at `ref`: roadmaps first, then top-level plans."""
    root = Path(root)
    if not ref_ok(root, ref):
        raise TrackerGitError(f"{ref} is not a commit in {root}")
    roadmaps: list[str] = []
    for path in git_files(root, ref, ".caddis/roadmaps"):
        match = _ROADMAP_TRACKER_RE.match(path)
        if match:
            roadmaps.append(match.group(1))
    out: list[tuple[str, str]] = [("roadmap", slug) for slug in sorted(roadmaps)]
    for path in git_files(root, ref, ".caddis/plans"):
        if not _PLAN_PATH_RE.match(path):
            continue
        text = git_show(root, ref, path)
        if text is None:
            continue
        meta, _ = split_document(text)
        if _meta_str(meta, "confluence_tracker") or _meta_str(meta, "confluence_tracker_parent"):
            out.append(("plan", path))
    return out


# ---------------------------------------------------------------- sync and local state

TRACKER_PREFIX = "caddis-tracker"


def page_title(source: Source) -> str:
    return source.title or f"{source.jira_epic} tracker"


def _page_version(page: Mapping[str, object]) -> int | None:
    version = page.get("version")
    number = version.get("number") if isinstance(version, Mapping) else None
    return number if isinstance(number, int) and not isinstance(number, bool) else None


def sync_source(
    source: Source,
    section: str,
    client,
    base_url: str,
    dry_run: bool,
) -> caddis_stories.SyncResult:
    warnings: list[str] = []
    if source.page_url:
        page = caddis_stories.resolve_parent(
            client,
            caddis_stories.parse_parent(source.page_url, base_url),
        )
        action, version = caddis_stories.update_section(
            client,
            page,
            source.slug,
            section,
            dry_run,
            prefix=TRACKER_PREFIX,
        )
        return caddis_stories.SyncResult(action, str(page["id"]), version, warnings)

    if not source.parent_url:
        raise TrackerInputError(f"{source.name} needs confluence_tracker or confluence_tracker_parent")

    parent = caddis_stories.resolve_parent(
        client,
        caddis_stories.parse_parent(source.parent_url, base_url),
    )
    parent_id = str(parent["id"])
    space = parent["space"]["key"]
    title = page_title(source)
    page = client.find_page(space, title)
    if page is None:
        if dry_run:
            return caddis_stories.SyncResult("create-page", None, None, warnings)
        created = client.create_page(space, parent_id, title, section)
        created_id = created.get("id")
        return caddis_stories.SyncResult(
            "create-page",
            str(created_id) if created_id is not None else None,
            _page_version(created),
            warnings,
        )
    ancestors = {
        str(a.get("id"))
        for a in (page.get("ancestors") or [])
        if isinstance(a, Mapping) and a.get("id") is not None
    }
    if parent_id not in ancestors:
        warnings.append(f"page {title} is not under the parent page")
    action, version = caddis_stories.update_section(
        client,
        page,
        source.slug,
        section,
        dry_run,
        prefix=TRACKER_PREFIX,
    )
    return caddis_stories.SyncResult(action, str(page["id"]), version, warnings)


def state_path(home: Path, slug: str) -> Path:
    return Path(home) / ".caddis" / "tracker-sync" / f"{slug}.json"


def read_state(home: Path, slug: str) -> dict | None:
    path = state_path(home, slug)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def write_state(home: Path, slug: str, data: dict) -> None:
    path = state_path(home, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _norm_root(path: str) -> str:
    return os.path.normcase(os.path.normpath(path))


def is_stale(root: Path, ref: str, source: Source, home: Path) -> bool:
    """True when local sync state is missing, from another checkout, or behind `source.paths` at `ref`."""
    state = read_state(home, source.slug)
    if state is None:
        return True
    saved_root = state.get("root")
    if not isinstance(saved_root, str) or not saved_root.strip():
        return True
    root_path = Path(root)
    if _norm_root(saved_root) != _norm_root(common_dir(root_path)):
        return True
    saved_sha = state.get("sha")
    current_sha = source_sha(root_path, ref, source.paths)
    if not isinstance(saved_sha, str) or not saved_sha or not current_sha:
        return True
    return saved_sha != current_sha


def _parse_today(raw: str | date | None) -> date:
    if raw is None:
        return datetime.now(timezone.utc).date()
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if not isinstance(raw, str) or not _ISO_DATE_RE.match(raw):
        raise TrackerInputError(f"--today '{raw}' must be YYYY-MM-DD")
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise TrackerInputError(f"--today '{raw}' is not a valid calendar date") from exc


def resolve_ref(args: argparse.Namespace) -> str:
    ref = getattr(args, "ref", None)
    if ref is not None:
        return ref
    return f"origin/{caddis_roadmap.fetch(Path(args.root))}"


def prepare(args: argparse.Namespace, env: Mapping[str, str]) -> tuple[Source, str, caddis_stories.Config] | int:
    try:
        _parse_today(getattr(args, "today", None))
        ref = resolve_ref(args)
        source = load_source(
            Path(args.root),
            ref,
            roadmap=getattr(args, "roadmap", None),
            plan=getattr(args, "plan", None),
        )
    except TrackerInputError as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return caddis_exit.ERROR
    except TrackerGitError as exc:
        print(f"git: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    except caddis_roadmap.RoadmapError as exc:
        print(f"git: {exc}", file=sys.stderr)
        return exc.code

    if not source.jira_epic or (not source.page_url and not source.parent_url):
        print(
            f"NOT CONFIGURED: {source.name} needs jira_epic and "
            f"confluence_tracker or confluence_tracker_parent"
        )
        return caddis_exit.NOT_RUN

    if not caddis_stories.EPIC_KEY.match(source.jira_epic):
        print(
            f"bad input: jira_epic '{source.jira_epic}' is not a Jira key such as ABC-123",
            file=sys.stderr,
        )
        return caddis_exit.ERROR

    try:
        config = caddis_stories.load_config(env)
    except caddis_stories.ConfigError as exc:
        print(f"NOT CONFIGURED: {exc}")
        return caddis_exit.NOT_RUN

    try:
        caddis_stories.parse_parent(source.page_url or source.parent_url or "", config.base_url)
    except ValueError as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return caddis_exit.ERROR

    return source, ref, config


def _confluence_failed(err: caddis_stories.ConfluenceError) -> int:
    if err.status is None:
        print(f"Confluence not reached: {err}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    print(f"Confluence refused: {err}", file=sys.stderr)
    return caddis_exit.BLOCKED


def cmd_render(args: argparse.Namespace) -> int:
    try:
        today = _parse_today(args.today)
        root = Path(args.root)
        source = load_source(root, args.ref, roadmap=args.roadmap, plan=args.plan)
        sha = source_sha(root, args.ref, source.paths)
    except TrackerInputError as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return caddis_exit.ERROR
    except TrackerGitError as exc:
        print(f"git: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    print(render_section(source.page, source.slug, today, sha))
    return caddis_exit.CLEAN


def cmd_check(args: argparse.Namespace, env: Mapping[str, str], client_factory=caddis_stories.Confluence) -> int:
    prepared = prepare(args, env)
    if isinstance(prepared, int):
        return prepared
    source, _ref, config = prepared
    title = page_title(source)
    client = client_factory(config.base_url, config.token)
    try:
        print(f"USER: {client.current_user()}")
        if source.page_url:
            page_ref = caddis_stories.parse_parent(source.page_url, config.base_url)
            page = caddis_stories.resolve_parent(client, page_ref)
            ver = _page_version(page)
            print(f"PAGE: {title} ({page.get('id', '?')}) v{ver if ver is not None else '?'}")
        else:
            parent_ref = caddis_stories.parse_parent(source.parent_url or "", config.base_url)
            parent = caddis_stories.resolve_parent(client, parent_ref)
            space = (parent.get("space") or {}).get("key", parent_ref.space or "?")
            print(f"PARENT: {parent.get('title', '?')} ({parent.get('id', '?')}) in space {space}")
            page = client.find_page(space, title)
            if page is None:
                print(f"PAGE: {title} (new)")
            else:
                ver = _page_version(page)
                print(f"PAGE: {title} ({page.get('id', '?')}) v{ver if ver is not None else '?'}")
    except caddis_stories.ConfluenceError as err:
        return _confluence_failed(err)
    return caddis_exit.CLEAN


def cmd_sync(
    args: argparse.Namespace,
    env: Mapping[str, str],
    client_factory=caddis_stories.Confluence,
    home: Path | None = None,
) -> int:
    prepared = prepare(args, env)
    if isinstance(prepared, int):
        return prepared
    source, ref, config = prepared
    today = _parse_today(getattr(args, "today", None))
    root = Path(args.root)
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        sha = source_sha(root, ref, source.paths)
        git_common = "" if dry_run else common_dir(root)
    except TrackerGitError as exc:
        print(f"git: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN

    section = render_section(source.page, source.slug, today, sha)
    title = page_title(source)
    client = client_factory(config.base_url, config.token)
    try:
        result = sync_source(source, section, client, config.base_url, dry_run=dry_run)
    except caddis_stories.MarkerError:
        print(f"markers broken on page {title}; fix the page by hand", file=sys.stderr)
        return caddis_exit.BLOCKED
    except caddis_stories.ConfluenceError as err:
        return _confluence_failed(err)

    for warning in result.warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    print(f"ACTION: {result.action}")
    if result.page_id is None:
        print(f"PAGE: {title} (new)")
    else:
        ver = result.version if result.version is not None else "?"
        print(f"PAGE: {title} ({result.page_id}) v{ver}")
    if dry_run:
        print("DRY RUN: nothing written")
        print(section)
        return caddis_exit.CLEAN

    state_home = Path.home() if home is None else Path(home)
    _record_state(state_home, git_common, source, sha, result)
    return caddis_exit.CLEAN


def _first_line(text: object) -> str:
    lines = str(text).splitlines()
    return lines[0].strip() if lines else ""


def _record_state(
    home: Path,
    git_common: str,
    source: Source,
    sha: str,
    result: caddis_stories.SyncResult,
) -> None:
    synced = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    write_state(
        home,
        source.slug,
        {
            "schema": 1,
            "root": git_common,
            "source": f"{source.kind} {source.name}",
            "sha": sha,
            "page_id": result.page_id,
            "action": result.action,
            "synced": synced,
        },
    )


def cmd_sync_all(
    args: argparse.Namespace,
    env: Mapping[str, str],
    client_factory=caddis_stories.Confluence,
    home: Path | None = None,
) -> int:
    state_home = Path.home() if home is None else Path(home)
    root = Path(args.root)
    dry_run = bool(getattr(args, "dry_run", False))
    try:
        today = _parse_today(getattr(args, "today", None))
        ref = resolve_ref(args)
        if not ref_ok(root, ref):
            raise TrackerGitError(f"{ref} is not a commit in {root}")
        found = discover(root, ref)
    except TrackerInputError as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return caddis_exit.ERROR
    except TrackerGitError as exc:
        print(f"git: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    except caddis_roadmap.RoadmapError as exc:
        print(f"git: {exc}", file=sys.stderr)
        return exc.code

    if not found:
        print("TRACKER: none")
        return caddis_exit.CLEAN

    worst = caddis_exit.CLEAN
    config: caddis_stories.Config | None = None
    config_failed = False
    client = None
    git_common: str | None = None

    for kind, target in found:
        src_label = f"roadmap-{target}" if kind == "roadmap" else target
        try:
            source = (
                load_source(root, ref, roadmap=target)
                if kind == "roadmap"
                else load_source(root, ref, plan=target)
            )
        except TrackerInputError as exc:
            print(f"TRACKER {src_label}: FAILED exit {caddis_exit.ERROR} - {_first_line(exc)}")
            worst = max(worst, caddis_exit.ERROR)
            continue
        except TrackerGitError as exc:
            print(f"TRACKER {src_label}: FAILED exit {caddis_exit.NOT_RUN} - {_first_line(exc)}")
            worst = max(worst, caddis_exit.NOT_RUN)
            continue

        try:
            sha = source_sha(root, ref, source.paths)
            stale = is_stale(root, ref, source, state_home)
        except TrackerGitError as exc:
            print(f"TRACKER {source.slug}: FAILED exit {caddis_exit.NOT_RUN} - {_first_line(exc)}")
            worst = max(worst, caddis_exit.NOT_RUN)
            continue

        if not stale:
            print(f"TRACKER {source.slug}: current at {sha[:8] or 'unknown'}")
            continue

        if not source.jira_epic or (not source.page_url and not source.parent_url):
            msg = f"{source.name} needs jira_epic and confluence_tracker or confluence_tracker_parent"
            print(f"TRACKER {source.slug}: FAILED exit {caddis_exit.NOT_RUN} - {msg}")
            worst = max(worst, caddis_exit.NOT_RUN)
            continue

        if not caddis_stories.EPIC_KEY.match(source.jira_epic):
            msg = f"jira_epic '{source.jira_epic}' is not a Jira key such as ABC-123"
            print(f"TRACKER {source.slug}: FAILED exit {caddis_exit.ERROR} - {msg}")
            worst = max(worst, caddis_exit.ERROR)
            continue

        if config is None and not config_failed:
            try:
                config = caddis_stories.load_config(env)
            except caddis_stories.ConfigError as exc:
                config_failed = True
                print(f"NOT CONFIGURED: {exc}")
        if config_failed or config is None:
            print(f"TRACKER {source.slug}: FAILED exit {caddis_exit.NOT_RUN} - not configured")
            worst = max(worst, caddis_exit.NOT_RUN)
            continue

        try:
            caddis_stories.parse_parent(source.page_url or source.parent_url or "", config.base_url)
        except ValueError as exc:
            print(f"TRACKER {source.slug}: FAILED exit {caddis_exit.ERROR} - {_first_line(exc)}")
            worst = max(worst, caddis_exit.ERROR)
            continue

        if not dry_run and git_common is None:
            try:
                git_common = common_dir(root)
            except TrackerGitError as exc:
                print(f"TRACKER {source.slug}: FAILED exit {caddis_exit.NOT_RUN} - {_first_line(exc)}")
                worst = max(worst, caddis_exit.NOT_RUN)
                continue

        section = render_section(source.page, source.slug, today, sha)
        title = page_title(source)
        if client is None:
            client = client_factory(config.base_url, config.token)
        try:
            result = sync_source(source, section, client, config.base_url, dry_run=dry_run)
        except caddis_stories.MarkerError:
            msg = f"markers broken on page {title}; fix the page by hand"
            print(f"TRACKER {source.slug}: FAILED exit {caddis_exit.BLOCKED} - {msg}")
            worst = max(worst, caddis_exit.BLOCKED)
            continue
        except caddis_stories.ConfluenceError as err:
            code = caddis_exit.NOT_RUN if err.status is None else caddis_exit.BLOCKED
            print(f"TRACKER {source.slug}: FAILED exit {code} - {_first_line(err)}")
            worst = max(worst, code)
            continue

        for warning in result.warnings:
            print(f"WARN: {warning}", file=sys.stderr)
        if result.page_id is None:
            print(f"TRACKER {source.slug}: {result.action} page new")
        else:
            ver = result.version if result.version is not None else "?"
            print(f"TRACKER {source.slug}: {result.action} page {result.page_id} v{ver}")
        if not dry_run:
            assert git_common is not None
            _record_state(state_home, git_common, source, sha, result)

    return worst


def cmd_stale(args: argparse.Namespace, home: Path | None = None) -> int:
    state_home = Path.home() if home is None else Path(home)
    root = Path(args.root)
    raw_ref = getattr(args, "ref", None)
    ref = raw_ref if raw_ref is not None else "origin/HEAD"
    try:
        if not ref_ok(root, ref):
            if raw_ref is None:
                if git_out(root, "rev-parse", "--git-dir").returncode != 0:
                    print(f"git: {root} is not a git repository", file=sys.stderr)
                else:
                    print(
                        "git: origin/HEAD is not set; run: git remote set-head origin --auto",
                        file=sys.stderr,
                    )
            else:
                print(f"git: {ref} is not a commit", file=sys.stderr)
            return caddis_exit.NOT_RUN
        found = discover(root, ref)
        if not found:
            print("TRACKER: none")
            return caddis_exit.CLEAN
        git_common = common_dir(root)
    except TrackerGitError as exc:
        print(f"git: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN

    any_failed_4 = False
    any_git_3 = False
    any_stale = False
    for kind, target in found:
        src_label = f"roadmap-{target}" if kind == "roadmap" else target
        try:
            source = (
                load_source(root, ref, roadmap=target)
                if kind == "roadmap"
                else load_source(root, ref, plan=target)
            )
            sha = source_sha(root, ref, source.paths)
        except TrackerInputError as exc:
            print(f"TRACKER {src_label}: FAILED exit {caddis_exit.ERROR} - {_first_line(exc)}")
            any_failed_4 = True
            continue
        except TrackerGitError as exc:
            print(f"TRACKER {src_label}: FAILED exit {caddis_exit.NOT_RUN} - {_first_line(exc)}")
            any_git_3 = True
            continue

        state = read_state(state_home, source.slug)
        if state is None:
            print(f"TRACKER {source.slug}: never synced")
            any_stale = True
            continue

        saved_root = state.get("root")
        if (
            not isinstance(saved_root, str)
            or not saved_root.strip()
            or _norm_root(saved_root) != _norm_root(git_common)
        ):
            print(f"TRACKER {source.slug}: stale (synced from another checkout)")
            any_stale = True
            continue

        saved_sha = state.get("sha")
        if not isinstance(saved_sha, str) or not saved_sha or saved_sha != sha:
            old8 = (saved_sha if isinstance(saved_sha, str) else "")[:8] or "unknown"
            new8 = (sha or "")[:8] or "unknown"
            print(f"TRACKER {source.slug}: stale (synced {old8}, source {new8})")
            any_stale = True
            continue

        print(f"TRACKER {source.slug}: current")

    if any_failed_4:
        return caddis_exit.ERROR
    if any_git_3:
        return caddis_exit.NOT_RUN
    if any_stale:
        return caddis_exit.BLOCKED
    return caddis_exit.CLEAN


def _add_source_args(subparser: argparse.ArgumentParser, default_ref: str | None) -> None:
    src = subparser.add_mutually_exclusive_group(required=True)
    src.add_argument("--roadmap", metavar="SLUG")
    src.add_argument("--plan", metavar="PATH")
    subparser.add_argument("--root", default=".", metavar="DIR")
    subparser.add_argument("--ref", default=default_ref, metavar="REF")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="caddis_tracker.py",
        description="Confluence tracker page section from a repo roadmap or plan.",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render", help="print the Confluence storage-format tracker section (no network)")
    _add_source_args(render, default_ref="HEAD")
    render.add_argument("--today", default=None, metavar="YYYY-MM-DD")

    check = sub.add_parser("check", help="verify Confluence login and target or parent page (GET only)")
    _add_source_args(check, default_ref=None)

    sync = sub.add_parser("sync", help="write the source's marked tracker section to Confluence")
    _add_source_args(sync, default_ref=None)
    sync.add_argument("--dry-run", action="store_true", help="read only; print the action and section")

    sync_all = sub.add_parser(
        "sync-all",
        help="sync every opted-in roadmap or plan whose source files changed since its last sync",
    )
    sync_all.add_argument("--root", default=".", metavar="DIR")
    sync_all.add_argument("--ref", default=None, metavar="REF")
    sync_all.add_argument("--dry-run", action="store_true", help="read only; print the actions without writing")

    stale = sub.add_parser("stale", help="check local sync state against git history (no network)")
    stale.add_argument("--root", default=".", metavar="DIR")
    stale.add_argument("--ref", default=None, metavar="REF")
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except (OSError, ValueError):
                pass
    args = _parser().parse_args(argv)
    if args.command == "render":
        return cmd_render(args)
    if args.command == "check":
        return cmd_check(args, os.environ)
    if args.command == "sync":
        return cmd_sync(args, os.environ, home=Path.home())
    if args.command == "sync-all":
        return cmd_sync_all(args, os.environ, home=Path.home())
    if args.command == "stale":
        return cmd_stale(args, home=Path.home())
    return caddis_exit.ERROR


if __name__ == "__main__":
    raise SystemExit(main())
