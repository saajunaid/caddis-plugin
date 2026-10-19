"""A local, read-only roadmap page: one static HTML file built from the files that are already the truth.

`caddis_roadmap.py render --roadmap <slug> [--out <file>]` writes it (default `~/.caddis/roadmap-pages/<repo>/<slug>.html`,
outside every checkout). Plan: `.caddis/plans/roadmap-page.md` (owner decisions, 17 Oct).

The hub: each default render also writes `<slug>.json` (one summary row) beside the page, and rebuilds
`~/.caddis/roadmap-pages/index.html` from every summary on this machine, one section per repo. The hub links to
the pages by relative path, so it works as a local file and behind a static web server (Phase 4).

Sections, in order: Waiting for you (sessions that wait for input, and open owner-gate blockers), Plan on a page (a
swimlane: plans as lanes, milestones as columns, one tile per phase; open by default), then collapsed sections:
summary, now / next / later, gates and blockers, every milestone with its phase rows, and the runner.

The data is `status()` (roadmap.md and each plan's Tracker on origin), the plan headers (`### Phase <n> - <name>`,
`**Model:**`, `**Lane:**`, `**Risk:**`), the runner's local lock and last stop, and the local session-state folder
(`<sid>.waiting` markers from the Notification hook). No script, no network: collapsing uses `<details>`. Every text
from the files is escaped: a plan, a relay or a hook message can hold any text.
"""
from __future__ import annotations

import datetime
import hashlib
import html
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path

PHASE_HEADER = re.compile(r"^###\s+Phase\s+(\d+)[a-z]?\s*[-–—:]\s*(.+?)\s*(?:[✅⏳\U0001F532].*)?$",
                          re.MULTILINE)
_FACT = re.compile(r"\*\*(Model|Lane|Risk):\*\*\s*([^\n]+?)\s*(?=\*\*(?:Model|Lane|Risk):\*\*|$)",
                   re.MULTILINE)
WAITING_MAX_AGE_H = 24  # a marker older than this, with no session end recorded, is shown as "stale?"


# ---- reading ---------------------------------------------------------------------------------------------------

def _read_json(path: Path | None):
    """(data, error): data is a dict or None; error names a file that exists but cannot be read."""
    if path is None:
        return None, ""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, ""
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{Path(path).name}: {getattr(exc, 'strerror', None) or exc}"
    try:
        data = json.loads(raw)
    except ValueError:
        return None, f"{Path(path).name}: not JSON"
    return (data, "") if isinstance(data, dict) else (None, f"{Path(path).name}: not a JSON object")


def phase_facts(plan_text: str | None) -> dict[int, dict]:
    """Phase number -> {name, model, lane, risk} from the plan's `### Phase <n> - <name>` sections."""
    if not plan_text:
        return {}
    heads = list(PHASE_HEADER.finditer(plan_text))
    out: dict[int, dict] = {}
    for i, m in enumerate(heads):
        body = plan_text[m.end():heads[i + 1].start() if i + 1 < len(heads) else len(plan_text)]
        body = body.split("\n## ", 1)[0]  # stop at the next level-2 section (Tracker, Risks, ...)
        facts = {k.lower(): v.strip() for k, v in _FACT.findall(body)}
        out.setdefault(int(m.group(1)), {"name": m.group(2).strip(), "model": facts.get("model", ""),
                                         "lane": facts.get("lane", ""), "risk": facts.get("risk", "")})
    return out


def phase_names(plan_text: str | None) -> dict[int, str]:
    return {n: f["name"] for n, f in phase_facts(plan_text).items()}


def tile_state(tracker_cell: str, state: str) -> str:
    """todo | in-progress | done | moved | blocked, from the Tracker cell (origin), falling back to status()."""
    cell = (tracker_cell or "").strip().lstrip("*").strip().lower()
    if cell.startswith("moved") or "moved" in cell.split(" - ", 1)[0]:
        return "moved"
    if cell.startswith(("done", "✅", "merged")):
        return "done"
    if cell.startswith(("blocked", "halt", "waiting")):
        return "blocked"
    if cell.startswith(("in progress", "in-progress", "active", "building", "built", "⏳")):
        return "in-progress"
    return "done" if state == "done" else "todo"


def _short_model(model: str) -> str:
    m = model.lower()
    for key, label in (("opus", "Opus"), ("sonnet", "Sonnet"), ("haiku", "Haiku"), ("argon", "agy Argon"),
                       ("agy", "agy"), ("gemini", "agy")):
        if key in m:
            return label
    return model.split(" - ", 1)[0].split("(", 1)[0].strip()[:24]


def waiting_sessions(state_dir: Path, now: datetime.datetime) -> list[dict]:
    """Sessions whose Notification hook wrote `<sid>.waiting` and that have not ended (`<sid>.ended`)."""
    out = []
    if not state_dir.is_dir():
        return out
    for marker in sorted(state_dir.glob("*.waiting")):
        sid = marker.stem
        ended = state_dir / f"{sid}.ended"
        try:  # an end mark counts only when it is newer than the waiting mark (a resumed session can ask again)
            if ended.exists() and ended.stat().st_mtime >= marker.stat().st_mtime:
                continue
        except OSError:
            continue
        data, err = _read_json(marker)
        data = data or {}
        name = ""
        try:
            name = (state_dir / f"{sid}.name").read_text(encoding="utf-8").split("\n", 1)[0].split("\t")[0].strip()
        except (OSError, UnicodeDecodeError):
            pass
        since = str(data.get("utc") or "")
        stale = False
        try:
            when = datetime.datetime.fromisoformat(since.replace("Z", "+00:00"))
            if when.tzinfo is None:
                when = when.replace(tzinfo=datetime.timezone.utc)
            stale = (now - when).total_seconds() > WAITING_MAX_AGE_H * 3600
        except (ValueError, TypeError):
            pass
        out.append({"session": name or sid[:8], "id": sid, "message": data.get("message") or err or "waiting",
                    "since": since, "cwd": data.get("cwd") or "", "kind": data.get("kind") or "", "stale": stale})
    return out


def main_checkout(root: Path) -> Path:
    """The main checkout of `root` (a linked worktree maps to it), so every worktree shares one page and one
    session-state folder; the waiting hook writes its marks there too."""
    try:
        out = subprocess.run(["git", "-C", str(root), "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
                             creationflags=0x08000000 if os.name == "nt" else 0)
        common = Path(out.stdout.strip()) if out.returncode == 0 and out.stdout.strip() else None
    except (OSError, subprocess.SubprocessError):
        common = None
    if common is not None and common.name == ".git":
        return common.parent.resolve()
    return Path(root).resolve()


def _artifact_dir(root: Path) -> Path:
    try:
        import claudster_config
        return Path(claudster_config.artifact_root(root))
    except Exception:  # the page must render without the harness on the path
        return Path(root) / ".caddis"


# ---- the model -------------------------------------------------------------------------------------------------

def build(root: Path, slug: str, roadmap_mod, now: datetime.datetime | None = None) -> dict:
    """status() plus per-phase Tracker cell, name, model, lane, risk and tile state; waiting sessions; the runner."""
    root = Path(root)
    now = now or datetime.datetime.now(datetime.timezone.utc)
    model = roadmap_mod.status(root, slug)
    plans: dict[str, tuple[dict[int, str], dict[int, dict]]] = {}
    lanes: list[str] = []
    for ms in model["milestones"]:
        for ph in ms["phases"]:
            m = roadmap_mod.REF_RE.match(ph["ref"])
            ph.update(plan="", num=0, tracker="", name="", model="", lane="", risk="")
            if not m:
                ph["tile"] = "todo"
                continue
            plan, num = m.group(1), int(m.group(2))
            if plan not in plans:
                text = roadmap_mod.show(root, model["branch"], f".caddis/plans/{plan}.md")
                if text is None:
                    text = roadmap_mod.show(root, model["branch"], f".caddis/plans/done/{plan}.md")
                plans[plan] = (roadmap_mod.parse_tracker(text) if text else {}, phase_facts(text))
                lanes.append(plan)
            rows, facts = plans[plan]
            ph.update(plan=plan, num=num, tracker=rows.get(num, ""), **{k: v for k, v in facts.get(num, {}).items()})
            ph["tile"] = tile_state(ph["tracker"], ph["state"])
    model["lanes"] = lanes
    model["waiting"] = [{"milestone": ms["id"], "reason": b["reason"], "check": b["check"]}
                        for ms in model["milestones"] for b in ms["blockers"]
                        if b["type"] == "owner-gate" and ms["status"] not in roadmap_mod.FINISHED]
    model["sessions"] = waiting_sessions(_artifact_dir(main_checkout(root)) / "session-state", now)

    lock_path = roadmap_mod.runner_lock_path(root, "roadmap", slug)
    lock, lock_err = _read_json(lock_path)
    if lock is not None and not all(lock.get(k) not in (None, "") for k in ("batch", "pid", "started_utc")):
        lock_err = lock_err or f"{Path(lock_path).name}: missing batch, pid or started_utc"
        lock = None
    live = False
    if lock is not None and lock_path is not None:
        try:
            live = roadmap_mod.runner_lock_stale(lock_path) is False
        except Exception:  # a judgement that cannot be made is not "running"
            live = False
    stop, stop_err = _read_json(roadmap_mod.last_stop_path(root, "roadmap", slug))
    model["runner"] = {"lock": lock if live else None, "stale_lock": lock if (lock and not live) else None,
                       "last_stop": stop, "errors": [e for e in (lock_err, stop_err) if e]}
    model["generated"] = now.strftime("%Y-%m-%d %H:%M UTC")
    try:
        model["origin_commit"] = roadmap_mod._git(root, "rev-parse", "--short", f"origin/{model['branch']}",
                                                  check=False).stdout.strip()
    except Exception:
        model["origin_commit"] = ""
    return model


# ---- rendering -------------------------------------------------------------------------------------------------

_CSS = """
:root{--bg:#f4f6f9;--panel:#fff;--panel2:#f8fafc;--fg:#0f172a;--muted:#475569;--line:#e2e8f0;--line2:#cbd5e1;
--accent:#2563eb;--todo-bg:#f1f5f9;--todo-fg:#334155;--prog:#2563eb;--prog-bg:#dbeafe;--prog-fg:#1d4ed8;
--done:#16a34a;--done-bg:#dcfce7;--done-fg:#15803d;--block:#d97706;--block-bg:#fef3c7;--block-fg:#92400e;
--high:#dc2626;--wait-bg:#fee2e2;--wait-fg:#b91c1c}
@media (prefers-color-scheme:dark){:root{--bg:#0b0f17;--panel:#111827;--panel2:#161f30;--fg:#f1f5f9;--muted:#94a3b8;
--line:#1e293b;--line2:#334155;--accent:#60a5fa;--todo-bg:#1e293b;--todo-fg:#cbd5e1;--prog:#60a5fa;--prog-bg:#172554;
--prog-fg:#93c5fd;--done:#22c55e;--done-bg:#052e16;--done-fg:#86efac;--block:#f59e0b;--block-bg:#451a03;
--block-fg:#fcd34d;--high:#f87171;--wait-bg:#450a0a;--wait-fg:#fca5a5}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}code{font:12px ui-monospace,Consolas,monospace}
main{max-width:1360px;margin:0 auto;padding:20px 16px 48px;display:grid;gap:16px}main>*{min-width:0}
h1{font-size:24px;margin:0}h2{font-size:16px;margin:0}.sub{color:var(--muted);margin:4px 0 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
details.card>summary{cursor:pointer;font-weight:700;font-size:16px;list-style:none}
details.card>summary::-webkit-details-marker{display:none}details.card>summary::before{content:"\\25B8 ";color:var(--muted)}
details.card[open]>summary::before{content:"\\25BE "}details.card>summary span{color:var(--muted);font-weight:400;font-size:13px}
.wait{border-color:var(--high)}.wait h2{color:var(--wait-fg)}.empty{color:var(--muted)}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:7px 9px;border-top:1px solid var(--line);
vertical-align:top}th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);border-top:0}
.scroll{overflow-x:auto}.pill{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;
padding:1px 8px;border-radius:999px;white-space:nowrap}
.s-todo{background:var(--todo-bg);color:var(--todo-fg)}.s-in-progress{background:var(--prog-bg);color:var(--prog-fg)}
.s-done,.s-moved,.s-not-needed{background:var(--done-bg);color:var(--done-fg)}.s-blocked{background:var(--block-bg);color:var(--block-fg)}
.s-code-done\\/data-pending{background:var(--block-bg);color:var(--block-fg)}
.lanes{display:grid;width:max-content}.lanes>div{border-top:1px solid var(--line);border-left:1px dashed var(--line);
padding:6px}.lanes .hd{background:var(--panel2);border-top:0;font-weight:700}.lanes .ln{position:sticky;left:0;z-index:1;
background:var(--panel);border-left:0;border-right:1px solid var(--line2);font-weight:600;min-width:170px}
.tile{display:flex;gap:6px;align-items:center;font-size:12px;padding:3px 6px;margin:0 0 4px;border-radius:5px;
border:1px solid var(--line2);background:var(--panel);max-width:100%}.tile b{font:600 11px ui-monospace,Consolas,monospace}
.tile span{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.tile.in-progress{background:var(--prog-bg);
border-color:var(--prog);color:var(--prog-fg)}.tile.done{background:var(--done-bg);border-color:var(--done);
color:var(--done-fg)}.tile.moved{background:repeating-linear-gradient(135deg,var(--done-bg) 0 5px,var(--panel) 5px 10px);
border-color:var(--done)}.tile.blocked{background:var(--block-bg);border-color:var(--block);color:var(--block-fg)}
.hi::after{content:"";width:7px;height:7px;border-radius:50%;background:var(--high);flex:none;margin-left:auto}
.gate{font-size:11px;color:var(--block-fg);background:var(--block-bg);border:1px dashed var(--block);border-radius:6px;
padding:3px 6px;margin:2px 0;white-space:normal;overflow-wrap:anywhere}.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted);margin-top:8px}
.cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}@media (max-width:820px){.cols{grid-template-columns:1fr}}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.kpi b{font-size:22px;display:block}
"""

_LABEL = {"todo": "to do", "in-progress": "in progress", "done": "done", "moved": "moved", "blocked": "blocked"}


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


def _pill(status: str) -> str:
    return f'<span class="pill s-{_e(status)}">{_e(_LABEL.get(status, status))}</span>'


def _waiting_section(model: dict) -> str:
    out = ['<section class="card wait"><h2>Waiting for you</h2>']
    sessions, gates = model["sessions"], model["waiting"]
    if not sessions and not gates:
        out.append('<p class="empty">Nothing is waiting for you.</p></section>')
        return "".join(out)
    # A question or a permission first; a session that only finished its turn and sits idle comes after it.
    asking = [s for s in sessions if not str(s.get("kind", "")).startswith("idle")]
    idle = [s for s in sessions if str(s.get("kind", "")).startswith("idle")]
    for title, group in (("Needs an answer", asking), ("Idle, waiting for your next message", idle)):
        if not group:
            continue
        out.append(f'<div class="scroll"><table><tr><th>{_e(title)}</th><th>Message</th><th>Since</th><th>Folder</th></tr>')
        for s in group:
            stale = " (stale?)" if s["stale"] else ""
            out.append(f"<tr><td><strong>{_e(s['session'])}</strong></td><td>{_e(s['message'])}</td>"
                       f"<td>{_e(s['since'])}{_e(stale)}</td><td><code>{_e(s['cwd'])}</code></td></tr>")
        out.append("</table></div>")
    if gates:
        out.append('<div class="scroll"><table><tr><th>Owner gate</th><th>What it needs</th><th>Check</th></tr>')
        for g in gates:
            out.append(f"<tr><td><strong>{_e(g['milestone'])}</strong></td><td>{_e(g['reason'])}</td>"
                       f"<td><code>{_e(g['check'])}</code></td></tr>")
        out.append("</table></div>")
    out.append("</section>")
    return "".join(out)


def _swimlane(model: dict) -> str:
    milestones, lanes = model["milestones"], model["lanes"]
    cols = len(milestones)
    out = ['<details class="card" open><summary>Plan on a page <span>plans as lanes, milestones as columns in '
           'roadmap order, one tile per phase</span></summary><div class="scroll">',
           f'<div class="lanes" style="grid-template-columns:170px repeat({cols},190px)">',
           '<div class="hd ln">Plan / milestone</div>']
    for ms in milestones:
        dep = f"after {', '.join(ms['depends'])}" if ms["depends"] else "starts first"
        gates = "".join(f'<div class="gate">{_e(b["type"])}: {_e(b["reason"])}</div>' for b in ms["blockers"])
        out.append(f'<div class="hd">{_e(ms["id"])} {_pill(ms["status"])}<div class="empty" style="font-weight:400;'
                   f'font-size:11px">{_e(dep)} · {_e(ms["owner"])}</div>{gates}</div>')
    for lane in lanes or ["-"]:
        done = sum(1 for ms in milestones for ph in ms["phases"] if ph["plan"] == lane and ph["tile"] in ("done", "moved"))
        total = sum(1 for ms in milestones for ph in ms["phases"] if ph["plan"] == lane)
        out.append(f'<div class="ln">{_e(lane)}<div class="empty" style="font-weight:400;font-size:11px">'
                   f'{done}/{total} done</div></div>')
        for ms in milestones:
            tiles = []
            for ph in ms["phases"]:
                if ph["plan"] != lane:
                    continue
                hi = " hi" if "high" in ph.get("risk", "").lower() else ""
                title = f"{ph['ref']} {ph['name']} | {ph['tracker'] or ph['state']}"
                tiles.append(f'<div class="tile {_e(ph["tile"])}{hi}" title="{_e(title)}"><b>{_e(ph["num"])}</b>'
                             f'<span>{_e(ph["name"] or ph["ref"])}</span></div>')
            out.append(f"<div>{''.join(tiles)}</div>")
    out.append('</div></div><div class="legend"><span>colour: to do · <b>in progress</b> · done · striped = moved · '
               'amber = blocked</span><span>red dot = Risk high (stops for review)</span></div></details>')
    return "".join(out)


def _summary(model: dict) -> str:
    phases = [ph for ms in model["milestones"] for ph in ms["phases"]]
    done = sum(1 for ph in phases if ph["tile"] in ("done", "moved"))
    building = [ph["ref"] for ph in phases if ph["tile"] == "in-progress"]
    high = sum(1 for ph in phases if "high" in ph.get("risk", "").lower())
    nxt = model.get("next") or {}
    nxt_txt = f"{nxt.get('milestone', '')} {nxt.get('plan', '')}#{nxt.get('phase', '')}" if nxt else "none ready"
    return ('<details class="card"><summary>Summary <span>progress, current work, next batch</span></summary>'
            '<div class="kpis">'
            f'<div class="kpi"><b>{_e(done)} / {_e(len(phases))}</b>phases done</div>'
            f'<div class="kpi"><b>{_e(model["done"])} / {_e(model["total"])}</b>milestones done</div>'
            f'<div class="kpi"><b>{_e(len(building))}</b>in progress: {_e(", ".join(building) or "none")}</div>'
            f'<div class="kpi"><b>{_e(high)}</b>high-risk phases</div>'
            f'<div class="kpi"><b>{_e(nxt_txt)}</b>next batch for the runner</div>'
            "</div></details>")


def _now_next_later(model: dict) -> str:
    ms_all = model["milestones"]
    status = {ms["id"]: ms["status"] for ms in ms_all}
    groups: dict[str, list[dict]] = {"Now": [], "Next": [], "Later": []}
    for ms in ms_all:
        if ms["status"] in ("done", "not-needed"):
            continue
        ready = all(status.get(d) in ("done", "not-needed") for d in ms["depends"])
        if ms["status"] == "in-progress" or (ready and not ms["blockers"]):
            groups["Now"].append(ms)
        elif any(d in [m["id"] for m in groups["Now"]] for d in ms["depends"]):
            groups["Next"].append(ms)
        else:
            groups["Later"].append(ms)
    cols = []
    for title, items in groups.items():
        body = "".join(f'<p><strong>{_e(m["id"])}</strong> {_pill(m["status"])} '
                       f'{_e(sum(1 for p in m["phases"] if p["tile"] in ("done", "moved")))}/{_e(len(m["phases"]))}'
                       f' phases{"".join(" · " + _e(b["type"]) for b in m["blockers"])}</p>' for m in items)
        cols.append(f'<div><h2>{_e(title)}</h2>{body or "<p class=empty>none</p>"}</div>')
    return ('<details class="card"><summary>Now, next, later <span>which milestones can start</span></summary>'
            f'<div class="cols">{"".join(cols)}</div></details>')


def _gates(model: dict) -> str:
    rows = [(ms["id"], b) for ms in model["milestones"] for b in ms["blockers"]]
    body = "".join(f"<tr><td><strong>{_e(mid)}</strong></td><td>{_e(b['type'])}</td><td>{_e(b['reason'])}</td>"
                   f"<td><code>{_e(b['check'])}</code></td></tr>" for mid, b in rows)
    return (f'<details class="card"><summary>Gates and blockers <span>{_e(len(rows))} open</span></summary>'
            + (f'<div class="scroll"><table><tr><th>Milestone</th><th>Type</th><th>Reason</th><th>Check</th></tr>{body}'
               "</table></div>" if rows else '<p class="empty">No blockers.</p>') + "</details>")


def _milestones(model: dict) -> str:
    out = ['<details class="card"><summary>Milestones and phases <span>every phase with model, lane, risk and '
           'Tracker status</span></summary>']
    for ms in model["milestones"]:
        rows = "".join(
            f"<tr><td><code>{_e(ph['ref'])}</code></td><td>{_e(ph['name'])}</td><td>{_e(_short_model(ph['model']))}</td>"
            f"<td>{_e(ph['lane'].split(' ', 1)[0] if ph['lane'] else '-')}</td>"
            f"<td>{_e(ph['risk'] or '-')}</td><td>{_pill(ph['tile'])} {_e(ph['tracker'])}</td></tr>"
            for ph in ms["phases"])
        target = f" · target {_e(ms['target'])}" if ms.get("target") else ""
        out.append(f"<h2 style=\"margin-top:12px\">{_e(ms['id'])} {_pill(ms['status'])} "
                   f"<span class=\"empty\" style=\"font-weight:400;font-size:13px\">owner {_e(ms['owner'])}{target} · "
                   f"after {_e(', '.join(ms['depends']) or '-')}</span></h2>")
        out.append('<div class="scroll"><table><tr><th>Phase</th><th>Name</th><th>Model</th><th>Lane</th><th>Risk</th>'
                   f'<th>Tracker</th></tr>{rows or "<tr><td colspan=6 class=empty>no build phases</td></tr>"}'
                   "</table></div>")
    out.append("</details>")
    return "".join(out)


def _runner(model: dict) -> str:
    r = model["runner"]
    parts = []
    if r["lock"]:
        lk = r["lock"]
        parts.append(f"<p>Running batch <code>{_e(lk.get('batch'))}</code> since {_e(lk.get('started_utc'))} "
                     f"(host {_e(lk.get('host'))}, pid {_e(lk.get('pid'))}).</p>")
    else:
        parts.append('<p class="empty">No runner holds this roadmap now.</p>')
    if r["stale_lock"]:
        parts.append(f"<p>A stale runner lock remains (batch <code>{_e(r['stale_lock'].get('batch'))}</code>): "
                     "the runner that held it is gone.</p>")
    stop = r["last_stop"]
    if stop:
        if str(stop.get("reason")) == "running":
            parts.append("<p>Last stop record: running now.</p>")
        else:
            code = f" (exit {_e(stop.get('exit'))})" if stop.get("exit") is not None else ""
            parts.append(f"<p>Last stop {_e(stop.get('utc'))}: {_e(stop.get('reason'))}{code}.</p>")
    for err in r["errors"]:
        parts.append(f"<p>Could not read {_e(err)}.</p>")
    nxt = model.get("next")
    if nxt:
        parts.append(f"<p>Next batch: <code>{_e(nxt.get('milestone'))} {_e(nxt.get('plan'))}#{_e(nxt.get('phase'))}"
                     "</code></p>")
    return ('<details class="card"><summary>Runner <span>roadmap-run state on this machine</span></summary>'
            + "".join(parts) + "</details>")


def render_html(model: dict) -> str:
    """Self-contained HTML: no script, no network. Every value from the files is escaped."""
    title = f"Roadmap {model['roadmap']}"
    phases = [ph for ms in model["milestones"] for ph in ms["phases"]]
    done = sum(1 for ph in phases if ph["tile"] in ("done", "moved"))
    commit = f" · origin <code>{_e(model.get('origin_commit'))}</code>" if model.get("origin_commit") else ""
    return "".join([
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_e(title)}</title><style>{_CSS}</style></head><body><main>",
        f'<header><h1>{_e(title)}</h1><p class="sub">{_e(model["done"])} of {_e(model["total"])} milestones · '
        f'{_e(done)} of {_e(len(phases))} phases done · branch <code>{_e(model["branch"])}</code>{commit} · '
        f"generated {_e(model['generated'])}</p></header>",
        _waiting_section(model), _swimlane(model), _summary(model), _now_next_later(model), _gates(model),
        _milestones(model), _runner(model),
        '<p class="empty">Built from roadmap.md, the plan Trackers and headers on origin, the runner state and the '
        "session-state folder. Re-rendered by the runner, /handoff, /pr-merge, /catchup and the waiting hooks.</p>",
        "</main></body></html>\n"])


def default_page_path(root: Path, slug: str, home: Path | None = None) -> Path:
    """`~/.caddis/roadmap-pages/<repo folder>-<6 hex>/<slug>.html`: outside every checkout, so a render never makes a
    repo dirty (17 Oct: the in-repo `.local/` folder is not gitignored in every repo). The folder is the MAIN
    checkout (a worktree shares its page); the 6 hex of its path keep two clones with one name apart."""
    main = main_checkout(root)
    tag = hashlib.sha1(str(main).lower().encode("utf-8")).hexdigest()[:6]
    return pages_root(home) / f"{main.name}-{tag}" / f"{slug}.html"


def write_page(root: Path, slug: str, out: Path | None, roadmap_mod) -> Path:
    """The page. At the default path it also writes `<slug>.json`, the one-row summary the hub is built from; an
    `--out` page is a one-off copy and stays out of the hub."""
    model = build(root, slug, roadmap_mod)
    path = Path(out) if out else default_page_path(root, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    _write_atomic(path, render_html(model))
    if out is None:
        try:  # the summary feeds the hub only: the page is written, so a failure here never fails the render
            _write_atomic(path.with_suffix(".json"),
                          json.dumps(page_summary(model, main_checkout(root), path), indent=1))
        except Exception as exc:
            print(f"[ROADMAP] hub summary not written: {exc}", file=sys.stderr)
    return path


# ---- the hub: one page over every roadmap page on this machine, grouped per repo ---------------------------------

HUB_STALE_H = 24  # a summary older than this is marked "not refreshed"


def _write_atomic(path: Path, text: str) -> None:
    """Write then rename, so a reader (a browser, nginx, a second render) never sees half a file."""
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(text, encoding="utf-8")
        for attempt in range(5):  # Windows: a reader (browser, nginx, another render) can hold the target briefly
            try:
                os.replace(tmp, path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.1 * (attempt + 1))
    finally:
        try:
            tmp.unlink()
        except FileNotFoundError:
            pass


def pages_root(home: Path | None = None) -> Path:
    return Path(home or Path.home()) / ".caddis" / "roadmap-pages"


def page_summary(model: dict, main: Path, path: Path) -> dict:
    """The hub's row for one roadmap. Waiting sessions belong to the checkout, not to one roadmap, so the hub shows
    them once per repo."""
    phases = [ph for ms in model["milestones"] for ph in ms["phases"]]
    r = model["runner"]
    stop = r.get("last_stop") or {}
    runner = ("running" if r.get("lock") or str(stop.get("reason")) == "running"
              else f"stopped: {stop.get('reason')}" if stop.get("reason") else "")
    nxt = model.get("next") or {}
    return {
        "version": 1, "repo": main.name, "checkout": str(main), "folder": path.parent.name, "slug": model["roadmap"],
        "branch": model["branch"], "origin_commit": model.get("origin_commit", ""),
        "generated_utc": model["generated"],
        "milestones_done": model["done"], "milestones_total": model["total"],
        "phases_done": sum(1 for ph in phases if ph["tile"] in ("done", "moved")), "phases_total": len(phases),
        "in_progress": [ph["ref"] for ph in phases if ph["tile"] == "in-progress"],
        "blocked": sum(1 for ph in phases if ph["tile"] == "blocked"),
        "owner_gates": [{"milestone": g["milestone"], "reason": g["reason"]} for g in model["waiting"]],
        "sessions": [{"session": s["session"], "message": s["message"], "since": s["since"],
                      "asking": not str(s.get("kind", "")).startswith("idle"), "stale": s["stale"]}
                     for s in model["sessions"]],
        "runner": runner,
        "next": f"{nxt.get('milestone', '')} {nxt.get('plan', '')}#{nxt.get('phase', '')}" if nxt else "",
    }


def prune_folder(folder: Path, keep: set[str]) -> int:
    """Remove the page and summary of each roadmap that is no longer on origin. Only `<slug>.json` files and their
    `<slug>.html` pages are touched. Returns how many roadmaps were removed."""
    removed = 0
    if not folder.is_dir():
        return removed
    for js in folder.glob("*.json"):
        if js.stem in keep:
            continue
        for f in (js, js.with_suffix(".html")):
            try:
                f.unlink()
            except FileNotFoundError:
                pass
        removed += 1
    return removed


def read_summaries(root_dir: Path) -> tuple[list[dict], list[str]]:
    """Every `<repo>-<hex>/<slug>.json` whose page still exists. An unreadable summary is named, not hidden."""
    rows, errors = [], []
    if not root_dir.is_dir():
        return rows, errors
    for js in sorted(root_dir.glob("*/*.json")):
        if not js.with_suffix(".html").exists():
            continue
        data, err = _read_json(js)
        if not isinstance(data, dict) or not data.get("slug"):
            errors.append(err or f"{js.parent.name}/{js.name}: not a roadmap summary")
            continue
        data["page"] = f"{js.parent.name}/{js.with_suffix('.html').name}"  # the link comes from the disk, not the file
        data["folder"] = js.parent.name
        data.setdefault("repo", js.parent.name.rsplit("-", 1)[0])
        for key in ("sessions", "owner_gates"):  # a hand-edited summary must not stop the hub for every repo
            items = data.get(key)
            data[key] = [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
        if not isinstance(data.get("in_progress"), list):
            data["in_progress"] = []
        rows.append(data)
    return rows, errors


def _age_h(utc_text: str, now: datetime.datetime) -> float | None:
    try:
        when = datetime.datetime.strptime(utc_text, "%Y-%m-%d %H:%M UTC").replace(tzinfo=datetime.timezone.utc)
    except (ValueError, TypeError):
        return None
    return (now - when).total_seconds() / 3600


def _bar(done: int, total: int) -> str:
    pct = int(round(100 * done / total)) if total else 0
    return (f'<div class="bar" title="{_e(done)} of {_e(total)} phases done"><i style="width:{pct}%"></i></div>'
            f'<span class="empty">{_e(done)}/{_e(total)} phases · {pct}%</span>')


# The hub's dark theme is Dracula (owner, 17 Oct): https://draculatheme.com/contribute - background #282a36,
# current line #44475a, foreground #f8f8f2, comment #6272a4, cyan, green, orange, pink, purple, red, yellow.
_HUB_CSS = _CSS + """
@media (prefers-color-scheme:dark){:root{--bg:#282a36;--panel:#21222c;--panel2:#343746;--fg:#f8f8f2;--muted:#6272a4;
--line:#44475a;--line2:#6272a4;--accent:#8be9fd;--todo-bg:#44475a;--todo-fg:#f8f8f2;--prog:#bd93f9;--prog-bg:#3c3352;
--prog-fg:#bd93f9;--done:#50fa7b;--done-bg:#2b4a36;--done-fg:#50fa7b;--block:#ffb86c;--block-bg:#4a3a2b;
--block-fg:#ffb86c;--high:#ff5555;--wait-bg:#4a2b33;--wait-fg:#ff5555}
h1{color:#bd93f9}.card summary{color:#ff79c6}code{color:#f1fa8c}}
.bar{height:8px;border-radius:99px;background:var(--todo-bg);overflow:hidden;min-width:120px;margin:4px 0}
.bar i{display:block;height:100%;background:var(--done)}a{color:var(--accent)}td.num{white-space:nowrap}
"""


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def render_hub(rows: list[dict], errors: list[str], now: datetime.datetime) -> str:
    """Self-contained HTML, no script. It reloads itself every 60 s, so an open tab follows the renders."""
    by_repo: dict[str, list[dict]] = {}
    for r in rows:
        by_repo.setdefault(r["folder"], []).append(r)

    def sessions_of(group):  # the newest summary of a checkout has its newest session marks
        return max(group, key=lambda r: str(r.get("generated_utc", ""))).get("sessions") or []

    order = sorted(by_repo.items(), key=lambda kv: (str(kv[1][0].get("repo", "")).lower(), kv[0]))
    need = []
    for _folder, group in order:
        asking = [s for s in sessions_of(group) if s.get("asking")]
        gates = [(r, g) for r in group for g in r.get("owner_gates") or []]
        if asking or gates:
            need.append((group[0].get("repo"), asking, gates))
    count = sum(len(a) + len(g) for _, a, g in need)
    out = ['<!doctype html><html lang="en"><head><meta charset="utf-8">',
           '<meta name="viewport" content="width=device-width,initial-scale=1"><meta http-equiv="refresh" content="60">',
           f"<title>Roadmaps</title><style>{_HUB_CSS}</style></head><body><main>",
           f'<header><h1>Roadmaps</h1><p class="sub">{_e(len(by_repo))} repos · {_e(len(rows))} roadmaps · '
           f'{_e(count)} item(s) need you · generated {_e(now.strftime("%Y-%m-%d %H:%M UTC"))} · '
           "reloads every minute</p></header>",
           '<section class="card wait"><h2>Needs you</h2>']
    if not need:
        out.append('<p class="empty">Nothing is waiting for you.</p>')
    else:
        out.append('<div class="scroll"><table><tr><th>Repo</th><th>What</th><th>Detail</th></tr>')
        for repo, asking, gates in need:
            for s in asking:
                stale = " (stale?)" if s.get("stale") else ""
                out.append(f"<tr><td><strong>{_e(repo)}</strong></td><td>session {_e(s.get('session'))}</td>"
                           f"<td>{_e(s.get('message'))} · since {_e(s.get('since'))}{_e(stale)}</td></tr>")
            for r, g in gates:
                out.append(f"<tr><td><strong>{_e(repo)}</strong></td><td>owner gate {_e(r.get('slug'))} "
                           f"{_e(g.get('milestone'))}</td><td>{_e(g.get('reason'))}</td></tr>")
        out.append("</table></div>")
    out.append("</section>")
    if not rows:
        out.append('<p class="card empty">No roadmap page has been rendered on this machine yet. Run '
                   "<code>caddis_roadmap.py render --all</code> in a repo that has <code>.caddis/roadmaps/</code>.</p>")
    for _folder, group in order:
        first = group[0]
        idle = sum(1 for s in sessions_of(group) if not s.get("asking"))
        idle_txt = f" · {idle} idle session(s)" if idle else ""
        out.append(f'<details class="card" open><summary>{_e(first.get("repo"))} <span>{_e(len(group))} roadmap(s)'
                   f'{_e(idle_txt)} · <code>{_e(first.get("checkout", ""))}</code></span></summary>'
                   '<div class="scroll"><table><tr><th>Roadmap</th><th>Progress</th><th>Milestones</th>'
                   "<th>In progress</th><th>Blocked</th><th>Runner</th><th>Next</th><th>Updated</th></tr>")
        for r in sorted(group, key=lambda r: str(r["slug"])):
            age = _age_h(str(r.get("generated_utc", "")), now)
            old = " (not refreshed)" if age is not None and age > HUB_STALE_H else ""
            href = _e(urllib.parse.quote(r["page"]))
            out.append(f'<tr><td><a href="{href}"><strong>{_e(r["slug"])}</strong></a></td>'
                       f'<td>{_bar(_int(r.get("phases_done")), _int(r.get("phases_total")))}</td>'
                       f'<td class="num">{_e(r.get("milestones_done"))} / {_e(r.get("milestones_total"))}</td>'
                       f'<td>{_e(", ".join(map(str, r.get("in_progress") or [])) or "-")}</td>'
                       f'<td class="num">{_e(_int(r.get("blocked")))}</td><td>{_e(r.get("runner") or "-")}</td>'
                       f'<td><code>{_e(r.get("next") or "-")}</code></td>'
                       f'<td class="num">{_e(r.get("generated_utc"))}{_e(old)}</td></tr>')
        out.append("</table></div></details>")
    for err in errors:
        out.append(f'<p class="empty">Could not read {_e(err)}.</p>')
    out.append('<p class="empty">Built from the page summaries in this folder. Every roadmap page render rebuilds it.'
               "</p></main></body></html>\n")
    return "".join(out)


def write_hub(home: Path | None = None, now: datetime.datetime | None = None) -> Path:
    """`~/.caddis/roadmap-pages/index.html`: every roadmap page on this machine, grouped per repo."""
    root_dir = pages_root(home)
    root_dir.mkdir(parents=True, exist_ok=True)
    rows, errors = read_summaries(root_dir)
    path = root_dir / "index.html"
    _write_atomic(path, render_hub(rows, errors, now or datetime.datetime.now(datetime.timezone.utc)))
    return path
