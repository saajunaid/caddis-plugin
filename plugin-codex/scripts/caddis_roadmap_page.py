"""A local, read-only roadmap page: one static HTML file built from the files that are already the truth.

`caddis_roadmap.py render --roadmap <slug> [--out <file>]` writes it (default `~/.caddis/roadmap-pages/<repo>/<slug>.html`,
outside every checkout). Plan: `.caddis/plans/roadmap-page.md` (owner decisions, 17 Oct).

The hub: each default render writes `<slug>.body.html` (the page body) and `<slug>.json` (one summary row), and
rebuilds `~/.caddis/roadmap-pages/index.html` from every summary on this machine. `index.html` is the whole app: the
inbox, the gates, sessions and runners views, and one view per roadmap (its body). CSS shows one view at a time from
the URL's `#view`, so there is one nav and it is never stale. `<slug>.html` is a one-line redirect to its view. It
works as a local file and behind a static web server.

Sections, in order: Waiting for you (sessions that wait for input, and open owner-gate blockers), Plan on a page (a
swimlane: plans as lanes, milestones as columns, one tile per phase; open by default), then collapsed sections:
summary, now / next / later, gates and blockers, every milestone with its phase rows, and the runner.

The data is `status()` (roadmap.md and each plan's Tracker on origin), the plan headers (`### Phase <n> - <name>`,
`**Model:**`, `**Lane:**`, `**Risk:**`), the runner's local lock and last stop, and the local session-state folder
(`<sid>.waiting` markers from the Notification hook). No network, and one script only (id theme-toggle: the light/dark
toggle, the hub's inbox reload, the phone menu, `aria-current`, the app bar crumbs and the search box): collapsing uses
`<details>`. Icons are Lucide line icons from one inline sprite (`roadmap_assets/icons.svg`). Every text
from the files is escaped: a plan, a relay or a hook message can hold any text.
"""
from __future__ import annotations

import datetime
import functools
import hashlib
import html
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import time
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

def build(root: Path, slug: str, roadmap_mod, now: datetime.datetime | None = None, sessions: bool = True) -> dict:
    """status() plus per-phase Tracker cell, name, model, lane, risk and tile state; waiting sessions; the runner.
    The hub passes `sessions=False`: it has live sessions of its own, so the marker folder is not read."""
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
    model["sessions"] = (waiting_sessions(_artifact_dir(main_checkout(root)) / "session-state", now) if sessions else [])

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

# One colour set for every page: light = slate + blue, dark = Dracula (owner, 17 Oct): https://draculatheme.com/contribute
# Dark uses the full official palette for text, borders, links, focus and status (owner, 21 Oct). Two tones are not
# Dracula's own: --muted (#a4acd4, a lighter comment: #6272a4 is only ~3:1 on the background) and the tinted chip
# backgrounds. A test checks every text/background pair the CSS uses against WCAG AA (CONTRAST_PAIRS).
# Dark applies when the OS asks for it, unless the reader picked light; the toggle sets data-theme on <html>.
_PALETTE_LIGHT = '--bg:#f4f6f9;--panel:#fff;--panel2:#f8fafc;--fg:#0f172a;--muted:#475569;--line:#e2e8f0;--line2:#cbd5e1;--accent:#2563eb;--todo-bg:#f1f5f9;--todo-fg:#334155;--prog:#2563eb;--prog-bg:#dbeafe;--prog-fg:#1d4ed8;--done:#16a34a;--done-bg:#dcfce7;--done-fg:#15803d;--block:#d97706;--block-bg:#fef3c7;--block-fg:#92400e;--high:#dc2626;--wait-bg:#fee2e2;--wait-fg:#b91c1c;--wait-h:#b91c1c;--nav:#f8fafc;--nav-fg:#0f172a;--on-accent:#ffffff;--focus:#2563eb;--field:#64748b;--shadow:0 1px 3px rgba(15,23,42,.06);--elev:0 8px 20px rgba(15,23,42,.10);--ico-sun:none;--ico-moon:inline-block;--title:var(--fg);--summary:var(--fg);--code:var(--fg);--c0:#2563eb;--c1:#7c3aed;--c2:#0d9488;--c3:#ea580c;--c4:#db2777;--c5:#475569;--sans:"Atkinson Hyperlegible Next","Segoe UI Variable","Segoe UI",system-ui,sans-serif;--mono:"Maple Mono","Cascadia Mono",Consolas,ui-monospace,monospace;--head:"Maple Mono","Cascadia Mono",Consolas,ui-monospace,monospace;color-scheme:light;'
_PALETTE_DARK = '--bg:#282a36;--panel:#21222c;--panel2:#343746;--fg:#f8f8f2;--muted:#a4acd4;--line:#44475a;--line2:#6272a4;--accent:#8be9fd;--todo-bg:#44475a;--todo-fg:#f8f8f2;--prog:#bd93f9;--prog-bg:#3c3352;--prog-fg:#bd93f9;--done:#50fa7b;--done-bg:#2b4a36;--done-fg:#50fa7b;--block:#ffb86c;--block-bg:#4a3a2b;--block-fg:#ffb86c;--high:#ff5555;--wait-bg:#3a2028;--wait-fg:#ff5555;--wait-h:#ff5555;--nav:#21222c;--nav-fg:#f8f8f2;--on-accent:#282a36;--focus:#ff79c6;--field:#6272a4;--shadow:none;--elev:0 8px 22px rgba(0,0,0,.45);--ico-sun:inline-block;--ico-moon:none;--title:#bd93f9;--summary:#ff79c6;--code:#f1fa8c;--c0:#8be9fd;--c1:#bd93f9;--c2:#50fa7b;--c3:#ffb86c;--c4:#ff79c6;--c5:#6272a4;color-scheme:dark;'
_THEME_CSS = (":root{" + _PALETTE_LIGHT + "}" + '@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){'
              + _PALETTE_DARK + "}}" + ':root[data-theme="dark"]{' + _PALETTE_DARK + "}")

_BASE_CSS = """
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 var(--sans)}code{font:12px var(--mono);color:var(--code)}
main{max-width:1360px;margin:0 auto;padding:20px 16px 48px;display:grid;gap:16px}main>*{min-width:0}
h1,h2,h3,details.card>summary,.kpi b{font-family:var(--head)}h1{font-size:24px;margin:0;color:var(--title)}h2{font-size:16px;margin:0}.sub{color:var(--muted);margin:4px 0 0}
.card{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
details.card>summary{cursor:pointer;font-weight:700;font-size:16px;list-style:none;color:var(--summary)}
details.card>summary::-webkit-details-marker{display:none}details.card>summary::before{content:"\\25B8 ";color:var(--muted)}
details.card[open]>summary::before{content:"\\25BE "}details.card+details.card{margin-top:8px}
.wait{border-color:var(--high)}.wait h2{color:var(--wait-h)}.empty{color:var(--muted)}
table{border-collapse:collapse;width:100%}th,td{text-align:left;padding:7px 9px;border-top:1px solid var(--line);
vertical-align:top}th{font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);border-top:0}
.scroll{overflow-x:auto}.pill{display:inline-block;font-size:11px;font-weight:700;text-transform:uppercase;
padding:1px 8px;border-radius:999px;white-space:nowrap}
.s-todo{background:var(--todo-bg);color:var(--todo-fg)}.s-in-progress{background:var(--prog-bg);color:var(--prog-fg)}
.s-done,.s-moved,.s-not-needed{background:var(--done-bg);color:var(--done-fg)}.s-blocked{background:var(--block-bg);color:var(--block-fg)}
.s-code-done\\/data-pending{background:var(--block-bg);color:var(--block-fg)}
.lanes{display:grid}.lanes>div{border-top:1px solid var(--line);border-left:1px dashed var(--line);
padding:6px}.lanes .hd{background:var(--panel2);border-top:0;font-weight:700}.lanes .ln{position:sticky;left:0;z-index:1;
background:var(--panel);border-left:4px solid var(--lc,var(--line2));border-right:1px solid var(--line2);font-weight:600;overflow-wrap:anywhere}
.tile{display:flex;gap:5px;align-items:center;font-size:12px;padding:3px 5px;position:relative;margin:0 0 4px;border-radius:5px;
border:1px solid var(--line2);background:var(--panel);max-width:100%}.tile b{font:600 11px var(--mono)}
.tile span{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden;white-space:normal;overflow-wrap:anywhere}.tile.in-progress{background:var(--prog-bg);
border-color:var(--prog);color:var(--prog-fg)}.tile.done{background:var(--done-bg);border-color:var(--done);
color:var(--done-fg)}.tile.moved{background:repeating-linear-gradient(135deg,var(--done-bg) 0 5px,var(--panel) 5px 10px);
border-color:var(--done)}.tile.blocked{background:var(--block-bg);border-color:var(--block);color:var(--block-fg)}
.tile.hi::after{position:absolute;top:3px;right:3px;margin:0}
.ltile{display:flex;gap:8px;align-items:baseline;font-size:13px;padding:5px 8px;margin:0 0 4px;border-radius:6px;border:1px solid var(--line2);background:var(--panel)}.ltile b{font:600 11px var(--mono);white-space:nowrap}
.ltile.in-progress{background:var(--prog-bg);border-color:var(--prog);color:var(--prog-fg)}.ltile.done{background:var(--done-bg);border-color:var(--done);color:var(--done-fg)}
.ltile.moved{background:repeating-linear-gradient(135deg,var(--done-bg) 0 5px,var(--panel) 5px 10px);border-color:var(--done)}.ltile.blocked{background:var(--block-bg);border-color:var(--block);color:var(--block-fg)}
.bcount{display:inline-block;font-size:11px;font-weight:700;color:var(--block-fg);background:var(--block-bg);border:1px dashed var(--block);border-radius:6px;padding:0 6px;margin-top:3px}
.lane-list{display:none}.lane-list h3{margin:10px 0 6px}@media (max-width:900px){.timeline .scroll{display:none}.lane-list{display:block}}
.hi::after{content:"";width:7px;height:7px;border-radius:50%;background:var(--high);flex:none;margin-left:auto}
.gate{font-size:11px;color:var(--block-fg);background:var(--block-bg);border:1px dashed var(--block);border-radius:6px;
padding:3px 6px;margin:2px 0;white-space:normal;overflow-wrap:anywhere}.legend{display:flex;flex-wrap:wrap;gap:12px;font-size:12px;color:var(--muted);margin-top:8px}
.cols{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}@media (max-width:820px){.cols{grid-template-columns:1fr}}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.kpi b{font-size:22px;display:block}
.bar{height:8px;border-radius:99px;background:var(--todo-bg);overflow:hidden;min-width:120px;margin:4px 0}
.bar i{display:block;height:100%;background:var(--done)}a{color:var(--accent)}td.num{white-space:nowrap}
.theme-btn{display:inline-grid;place-items:center;flex:none;width:36px;height:36px;padding:0;border-radius:10px;border:1px solid var(--line);background:var(--panel2);color:var(--fg);cursor:pointer}
.theme-btn:hover{border-color:var(--accent);color:var(--accent)}.theme-btn .ic{width:18px;height:18px;vertical-align:0}.theme-btn .t-sun{display:var(--ico-sun)}.theme-btn .t-moon{display:var(--ico-moon)}
.hdr{display:flex;justify-content:space-between;align-items:flex-start;gap:12px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}.chip{border:1px solid var(--line);border-left:4px solid var(--lc);border-radius:8px;padding:5px 10px;background:var(--panel2);font-size:12.5px}.chip span{color:var(--muted);font-family:var(--mono)}
.flow{display:flex;gap:6px;align-items:stretch;min-width:max-content}.fnode{display:grid;gap:3px;padding:8px 10px;border:1px solid var(--line);border-radius:9px;background:var(--panel2);text-decoration:none;color:inherit;min-width:120px}.fnode span{font:11px var(--mono);color:var(--muted)}.fnode span.pill{font:700 11px var(--sans);justify-self:start}.arrow{align-self:center;color:var(--muted)}
.kind{font-size:10.5px;font-weight:700;text-transform:uppercase;padding:2px 8px;border-radius:6px;background:var(--block-bg);color:var(--block-fg)}.k-owner-gate{background:var(--wait-bg);color:var(--wait-fg)}
.note{color:var(--muted);font-weight:400;font-size:13px}.sec-h{display:flex;flex-wrap:wrap;gap:4px 10px;align-items:baseline;margin-bottom:8px}h3{font-size:14px;margin:0 0 8px}
.cols .rcard{margin-bottom:8px}.cols .rcard .bar{margin:0}
"""

_CSS = _THEME_CSS + _BASE_CSS

# The one script on a page: the reader's theme choice; on the hub only, a reload every 60 s while the inbox shows
# (an open roadmap view is never reset); the phone menu closes when the view changes; and the nav item of the
# shown view gets aria-current. No network.
_THEME_SCRIPT = ('<script id="theme-toggle">(function(){var k="caddis-roadmap-theme",d=document.documentElement;d.classList.add("js");try{var t=localStorage.getItem(k);if(t==="light"||t==="dark")d.dataset.theme=t}catch(e){}window.caddisTheme=function(){var c=d.dataset.theme||(matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light"),n=c==="dark"?"light":"dark";d.dataset.theme=n;try{localStorage.setItem(k,n)}catch(e){}};function shown(){var h=location.hash.slice(1),e=h&&document.getElementById(h),v=e&&e.closest(".view");return v?v.id:"inbox"}function cur(){var a=document.querySelectorAll(".nav a.nav-i");for(var i=0;i<a.length;i++){if(a[i].getAttribute("href")==="#"+shown())a[i].setAttribute("aria-current","page");else a[i].removeAttribute("aria-current")}}'
                 # The app bar crumbs follow the shown view (a roadmap view brings its own, its .view-crumbs).
                 'function bar(){var c=document.getElementById("ab-crumbs");if(!c||!document.getElementById("inbox"))return;var id=shown(),v=document.getElementById(id),p=v&&v.querySelector(".view-crumbs"),a=document.querySelector(\'.nav a.nav-i[href="#\'+id+\'"]\');if(p){c.innerHTML=p.innerHTML}else{c.innerHTML=\'<a href="#inbox">Roadmaps</a> \u203a <strong></strong>\';c.lastChild.textContent=a?a.getAttribute("data-label"):"Inbox"}}'
                 # Search: hide every [data-q] element that does not hold the text; open a matching milestone; count
                 # the [data-qn] hits of the shown view.
                 'function find(){var s=document.getElementById("q");if(!s)return;var v=s.value.trim().toLowerCase(),n=0,id=shown(),e=document.querySelectorAll("[data-q]");for(var i=0;i<e.length;i++){var x=e[i],hit=!v||(x.getAttribute("data-q")+" "+x.textContent).toLowerCase().indexOf(v)>=0;x.classList.toggle("q-miss",!hit);if(x.tagName==="DETAILS"){if(v&&hit){if(!x.hasAttribute("data-o"))x.setAttribute("data-o",x.open?"1":"0");x.open=true}else if(x.hasAttribute("data-o")){x.open=x.getAttribute("data-o")==="1";x.removeAttribute("data-o")}}var w=x.closest(".view");if(v&&hit&&x.hasAttribute("data-qn")&&(!w||w.id===id))n++}var o=document.getElementById("q-n");if(o)o.textContent=v?n+(n===1?" match":" matches"):""}'
                 'addEventListener("DOMContentLoaded",cur);addEventListener("DOMContentLoaded",function(){bar();var s=document.getElementById("q");if(s){s.addEventListener("input",find);s.addEventListener("keydown",function(ev){if(ev.key==="Escape"){s.value="";find()}})}});'
                 'addEventListener("keydown",function(ev){var s=document.getElementById("q"),f=document.activeElement;if(ev.key==="/"&&s&&f!==s&&!(f&&/^(INPUT|TEXTAREA|SELECT)$/.test(f.tagName))){ev.preventDefault();s.focus()}});'
                 'setInterval(function(){var s=document.getElementById("q");if(document.getElementById("inbox")&&document.visibilityState==="visible"&&shown()==="inbox"&&!(s&&s.value))location.reload()},60000);addEventListener("hashchange",function(){var b=document.getElementById("nav-cb");if(b)b.checked=false;cur();bar();find()})})();</script>')
# The shared copy is a static page: the inbox reload would only re-request it every minute, so it has no timer.
_SITE_THEME_SCRIPT = re.sub(r"setInterval\(function\(\)\{.*?\},60000\);", "", _THEME_SCRIPT)


def _fonts_link(base: str) -> str:
    """The one allowed <link>: bundled fonts. If it does not load, the font stacks fall back to system fonts."""
    return f'<link rel="stylesheet" href="{_e(base)}_assets/fonts.css">'

_SHELL_CSS = """
.app{display:grid;grid-template-columns:240px minmax(0,1fr);grid-template-rows:auto 1fr;min-height:100vh}
.nav{background:var(--nav);color:var(--nav-fg);border-right:1px solid var(--line);padding:6px 10px 14px;position:sticky;top:56px;height:calc(100vh - 56px);overflow-y:auto}
.nav-h{font-size:11px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:var(--muted);margin:14px 8px 4px}
.nav-repo{display:flex;align-items:center;gap:6px;font-size:12px;font-weight:600;color:var(--muted);margin:10px 8px 2px}.nav-repo .ic{width:14px;height:14px}
.nav-i{display:flex;align-items:center;gap:8px;padding:6px 8px;border-radius:7px;color:inherit;text-decoration:none;font-size:13px;transition:background .15s}
.nav-i:hover,.nav-i:focus-visible{background:var(--panel2)}.nav-i .ic{color:var(--muted)}.nav-i[aria-current] .ic{color:var(--prog-fg)}
.nav-i .n{margin-left:auto;font-family:var(--mono);font-size:11px;color:var(--muted)}.nav-rm{padding-left:16px}.nav-rm .ic{width:14px;height:14px}
.nav-sub{display:grid;padding:2px 0 6px 28px}.nav-sub a{font-size:12px;color:var(--muted);text-decoration:none;padding:3px 0}
.main{min-width:0}.top{grid-column:1/-1;display:flex;align-items:center;gap:14px;height:56px;padding:0 16px;border-bottom:1px solid var(--line);background:var(--panel);position:sticky;top:0;z-index:10;box-shadow:var(--shadow)}
.ab-brand{display:flex;align-items:center;gap:9px;flex:none;width:208px;font:700 15px var(--head);color:var(--title);text-decoration:none;white-space:nowrap}
.logo{display:inline-grid;place-items:center;flex:none;width:30px;height:30px;border-radius:9px;background:var(--accent);color:var(--on-accent)}.logo .ic{width:18px;height:18px;vertical-align:0}
.crumbs{flex:1;min-width:0;font-size:13px;color:var(--muted);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.crumbs a{color:var(--accent);text-decoration:none}.crumbs strong{color:var(--fg)}
.search{position:relative;flex:0 1 300px;min-width:0}.search .ic{position:absolute;left:10px;top:50%;margin-top:-8px;color:var(--muted);pointer-events:none}
.search input{width:100%;height:36px;padding:0 10px 0 34px;border-radius:10px;border:1px solid var(--field);background:var(--panel2);color:var(--fg);font:13px var(--sans)}
.search input::placeholder{color:var(--muted);opacity:1}.q-n{font:11px var(--mono);color:var(--muted);white-space:nowrap}.q-n:empty{display:none}
.gen{display:flex;align-items:center;gap:5px;font:11px var(--mono);color:var(--muted);white-space:nowrap}.gen .ic{width:13px;height:13px}
.js .view-crumbs{display:none}
main [id]{scroll-margin-top:60px}main>.view{scroll-margin-top:200px}
.view>*+*{margin-top:16px}.view{display:none}.view:target,.view:has(:target){display:block}main:not(:has(.view:target,.view :target))>#inbox{display:block}
.nav-sub{display:none}.view-crumbs{font-size:13px;color:var(--muted);margin:0 0 8px}
.nav-cb{display:none}.nav-btn,.nav-close,.nav-scrim{display:none}
.nav-cb:focus-visible~.app .nav-btn{outline:2px solid var(--accent);outline-offset:2px}
@media (max-width:900px){.app{grid-template-columns:1fr}.nav-cb{display:block;position:absolute;opacity:0;width:1px;height:1px;pointer-events:none}.nav{position:fixed;left:0;top:0;z-index:20;width:260px;height:100vh;transform:translateX(-100%);transition:transform .2s}.nav-cb:checked~.app .nav{transform:none}.nav-btn{display:inline-grid;place-items:center;cursor:pointer;width:32px;height:32px;color:var(--fg)}.nav-btn .ic,.nav-close .ic{width:20px;height:20px;vertical-align:0}.nav-close{display:block;text-align:right;cursor:pointer;padding:6px 8px;color:var(--fg)}.nav-cb:checked~.app .nav-scrim{display:block;position:fixed;inset:0;z-index:15;background:rgba(0,0,0,.4)}
.top{flex-wrap:wrap;height:auto;gap:6px 8px;padding:8px 10px}.ab-brand{width:auto}.ab-name,.gen{display:none}.search{flex:1 1 120px}.crumbs{order:5;flex-basis:100%}main [id]{scroll-margin-top:100px}}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px}
.rcard{display:grid;gap:8px;background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:14px 16px;color:inherit;text-decoration:none;box-shadow:var(--shadow)}
.dots{display:flex;flex-wrap:wrap;gap:4px}.dot{font:600 10.5px var(--mono);padding:1px 6px;border-radius:5px}
.kpi{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:12px 14px;box-shadow:var(--shadow)}
.ic{width:16px;height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:2;stroke-linecap:round;stroke-linejoin:round;vertical-align:-3px}
.sprite{position:absolute;width:0;height:0;overflow:hidden}
h2 .ic,h3 .ic{color:var(--accent);margin-right:7px}.wait h2 .ic{color:var(--wait-h)}
.pill .ic,.kind .ic{width:12px;height:12px;margin-right:4px;vertical-align:-2px}.rcard .ic{margin-right:4px}.rcard strong .ic{color:var(--accent)}.tile .ic,.ltile .ic{width:13px;height:13px;align-self:center}
:focus-visible{outline:2px solid var(--focus);outline-offset:2px}
.rcard,.kpi,.fnode{transition:transform .15s ease,box-shadow .15s ease,border-color .15s ease}
.rcard:hover,.rcard:focus-visible,.fnode:hover,.fnode:focus-visible{transform:translateY(-2px);box-shadow:var(--elev);border-color:var(--accent)}
.rcard[data-st]{border-left:4px solid var(--line2)}.rcard[data-st=done]{border-left-color:var(--done)}.rcard[data-st=prog]{border-left-color:var(--prog)}.rcard[data-st=block]{border-left-color:var(--block)}.rcard[data-st=wait]{border-left-color:var(--high)}
.kpi{position:relative;padding-right:56px}.kpi-ic{position:absolute;top:12px;right:12px;width:32px;height:32px;border-radius:9px;display:grid;place-items:center;background:var(--prog-bg);color:var(--prog-fg)}.kpi-ic .ic{width:18px;height:18px;vertical-align:0}
.kpi-ic.k-done{background:var(--done-bg);color:var(--done-fg)}.kpi-ic.k-block{background:var(--block-bg);color:var(--block-fg)}.kpi-ic.k-wait{background:var(--wait-bg);color:var(--wait-fg)}
.bar i{transform-origin:left;animation:fill .9s cubic-bezier(.2,.7,.2,1) both}@keyframes fill{from{transform:scaleX(0)}}
.q-miss,.nav-rm.q-miss+.nav-sub{display:none!important}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation:none!important;transition:none!important}.rcard:hover,.rcard:focus-visible,.fnode:hover,.fnode:focus-visible{transform:none}}
"""

_LABEL = {"todo": "to do", "in-progress": "in progress", "done": "done", "moved": "moved", "blocked": "blocked"}


def _e(value) -> str:
    return html.escape("" if value is None else str(value), quote=True)


@functools.lru_cache(maxsize=1)
def _sprite() -> str:
    """The Lucide sprite (`roadmap_assets/icons.svg`, made by build_roadmap_icons.py, with its licence comment), put
    inline once per page: Chrome and Edge do not let a `file://` page `<use>` a symbol from another file. Empty when
    the file is not shipped: the page then shows no icons, and nothing else changes."""
    try:
        return (ASSET_DIR / "icons.svg").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _icon(name: str, label: str | None = None, cls: str = "") -> str:
    """One Lucide icon from the inline sprite, tinted by `currentColor`. Decorative by default (hidden from screen
    readers); with `label` it is an image with that name, for an icon whose meaning no text beside it gives."""
    attrs = f'role="img" aria-label="{_e(label)}"' if label else 'aria-hidden="true" focusable="false"'
    return f'<svg class="ic{" " + cls if cls else ""}" {attrs}><use href="#ic-{name}"/></svg>'


_STATUS_ICON = {"done": "circle-check", "todo": "circle", "in-progress": "circle-dot", "blocked": "octagon-alert",
                "moved": "arrow-right-left", "not-needed": "circle-minus", "code-done/data-pending": "hourglass",
                "running": "play", "owner-gate": "user-check"}


def _pill(status: str) -> str:
    return (f'<span class="pill s-{_e(status)}">{_icon(_STATUS_ICON.get(status, "circle"))}'
            f'{_e(_LABEL.get(status, status))}</span>')


def _kind(kind: str) -> str:
    """A blocker type chip: owner gates get their own colour and icon."""
    icon = "user-check" if kind == "owner-gate" else "shield-alert"
    return f'<span class="kind k-{_e(kind)}">{_icon(icon)}{_e(kind)}</span>'


def _h2(icon: str, text: str) -> str:
    return f"<h2>{_icon(icon)}{_e(text)}</h2>"


def _kpi(icon: str, tone: str, value: str, label: str) -> str:
    """A KPI tile: `value` and `label` are already safe text."""
    return f'<div class="kpi"><span class="{f"kpi-ic {tone}".strip()}">{_icon(icon)}</span><b>{value}</b>{label}</div>'


def _theme_button() -> str:
    return ('<button type="button" class="theme-btn" onclick="caddisTheme()" aria-label="Switch between light and dark '
            'theme" title="Switch between light and dark theme">' + _icon("moon", cls="t-moon") + _icon("sun", cls="t-sun")
            + "</button>")


def _app_bar(base: str, crumbs: str, generated: str) -> str:
    """The top bar of every page: the phone menu button, the logo and name (a link to the inbox), the crumbs of the
    shown view (the script keeps them current on the hub), the search box, the generated time and the theme button."""
    home = f"{base}index.html#inbox" if base else "#inbox"
    gen = f'<span class="gen">{_icon("clock")}generated {_e(generated)}</span>' if generated else ""
    return ('<header class="top"><label for="nav-cb" class="nav-btn" aria-label="Open the menu">' + _icon("menu")
            + f'</label><a class="ab-brand" href="{_e(home)}"><span class="logo">{_icon("route")}</span>'
            '<span class="ab-name">caddis Roadmaps</span></a>'
            f'<div class="crumbs" id="ab-crumbs" role="navigation" aria-label="Breadcrumb">{crumbs}</div>'
            f'<div class="search" role="search">{_icon("search")}<input type="search" id="q" '
            'placeholder="Search roadmaps, milestones, phases" title="Press / to search" '
            'aria-label="Search roadmaps, milestones and phases" '
            'autocomplete="off" spellcheck="false"></div><span class="q-n" id="q-n" role="status" aria-live="polite"></span>'
            f"{gen}{_theme_button()}</header>")


def _shell(*, title: str, base: str, nav: str, crumbs: str, body: str, css: str = "",
           script: str | None = None, generated: str = "") -> str:
    """The app frame around every page: head, the icon sprite, the app bar, the left nav and the body.
    `nav`, `crumbs`, `body` and `css` are text the caller has already made safe; `title` and `generated` are plain
    text."""
    return "".join([
        '<!doctype html><html lang="en"><head><meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1">',
        f"<title>{_e(title)}</title>{_fonts_link(base)}<style>{_CSS}{_SHELL_CSS}{css}</style>{script or _THEME_SCRIPT}</head>",
        f'<body>{_sprite()}<input type="checkbox" id="nav-cb" class="nav-cb" aria-label="Toggle the navigation menu"><div class="app">',
        _app_bar(base, crumbs, generated),
        f'{nav}<label for="nav-cb" class="nav-scrim" aria-hidden="true"></label><div class="main">',
        f"<main>{body}</main></div></div></body></html>\n"])


def _crumbs(folder: str, slug: str) -> str:
    """`Roadmaps › <repo> › <slug>` for a roadmap page; the repo is the folder name without its `-<6hex>` tag."""
    repo = re.sub(r"-[0-9a-f]{6}$", "", folder or "")
    mid = f"{_e(repo)} › " if repo else ""
    return f'<a href="../index.html">Roadmaps</a> › {mid}<strong>{_e(slug)}</strong>'


def _sessions_of(group: list[dict]) -> list[dict]:
    """The newest summary of a checkout has its newest session marks."""
    return max(group, key=lambda r: str(r.get("generated_utc", ""))).get("sessions") or []


def _group_rows(rows: list[dict]) -> tuple[list[tuple[str, list[dict]]], list[tuple[str, list, list]], int]:
    """(order, need, count): the summaries per repo folder in repo-name order; per repo the asking sessions and the
    owner gates (repo, asking, gates), only for repos that have any; and how many items need the owner."""
    by_repo: dict[str, list[dict]] = {}
    for r in rows:
        by_repo.setdefault(r["folder"], []).append(r)
    order = sorted(by_repo.items(), key=lambda kv: (str(kv[1][0].get("repo", "")).lower(), kv[0]))
    need = []
    for _folder, group in order:
        asking = [s for s in _sessions_of(group) if s.get("asking")]
        gates = [(r, g) for r in group for g in r.get("owner_gates") or []]
        if asking or gates:
            need.append((group[0].get("repo"), asking, gates))
    count = sum(len(a) + len(g) for _, a, g in need)
    return order, need, count


def _nav(rows: list[dict], base: str, site: bool = False) -> str:
    """The left nav: Needs you (inbox, gates, sessions, runners), then every repo with its roadmaps. Every link opens a
    view of `index.html` (`#inbox`, `#<rid>`, ...); on the hub itself (`base` "") the link is the bare `#view`. The
    active item and its sub-links are shown by `_view_css`, so the nav needs no per-page copy. A `site` (shared copy)
    nav has no Sessions or Runners item, no idle-session note and no Runner sub-link: those show only on the owner's
    machine."""
    order, _need, count = _group_rows(rows)
    counts = {"inbox": count, "gates": sum(len(r.get("blockers") or r.get("owner_gates") or []) for r in rows),
              "sessions": sum(len(_sessions_of(group)) for _f, group in order),
              "runners": sum(1 for r in rows if r.get("runner") == "running")}
    hub = f"{base}index.html" if base else ""
    out = ['<nav class="nav" aria-label="Roadmaps">'
           f'<label for="nav-cb" class="nav-close" aria-label="Close the menu">{_icon("x")}</label>',
           '<p class="nav-h">Needs you</p>']
    for key, label in _NAV_ITEMS:
        if site and key in _LOCAL_VIEWS:
            continue
        out.append(f'<a class="nav-i" href="{_e(hub)}#{key}" data-label="{_e(label)}">{_icon(_NAV_ICON[key])}{_e(label)}'
                   f'<span class="n">{_e(counts[key])}</span></a>')
    out.append('<p class="nav-h">Repos</p>')
    for folder, group in order:
        idle = 0 if site else sum(1 for s in _sessions_of(group) if not s.get("asking"))
        idle_txt = f" · {idle} idle session(s)" if idle else ""
        out.append(f'<p class="nav-repo">{_icon("folder-git-2")}{_e(group[0].get("repo"))}{_e(idle_txt)}</p>')
        for r in sorted(group, key=lambda r: str(r["slug"])):
            rid = _rid(folder, r["slug"])
            if rid is None:
                continue
            total = _int(r.get("phases_total"))
            pct = int(round(100 * _int(r.get("phases_done")) / total)) if total else 0
            out.append(f'<a class="nav-i nav-rm" href="{_e(hub)}#{rid}" data-q="{_e(group[0].get("repo"))}" '
                       f'data-label="{_e(r["slug"])}">{_icon("map")}{_e(r["slug"])}<span class="n">{pct}%</span></a>'
                       f'<div class="nav-sub" data-rid="{rid}">'
                       + "".join(f'<a href="{_e(hub)}#{rid}-{anchor}">{_e(label)}</a>' for anchor, label in _PAGE_ANCHORS
                                 if not (site and anchor in _LOCAL_ANCHORS))
                       + "</div>")
    out.append("</nav>")
    return "".join(out)


_NAV_ITEMS = (("inbox", "Inbox"), ("gates", "Gates"), ("sessions", "Sessions"), ("runners", "Runners"))
_NAV_ICON = {"inbox": "inbox", "gates": "shield-alert", "sessions": "messages-square", "runners": "activity"}
_LOCAL_VIEWS = ("sessions", "runners")  # views of this machine's live state: a shared copy has neither
_LOCAL_ANCHORS = ("runner",)  # the section of a roadmap view that shows this machine's runner

_ON = "{background:var(--prog-bg);color:var(--prog-fg);font-weight:600}"


def _view_css(rids: list[str], site: bool = False) -> str:
    """Marks the nav item of the view that shows, and opens its sub-links. One rule per roadmap: CSS cannot take
    the target's id into a selector. Every rid comes from `_rid` (hex and slug characters only), so it is safe
    in a selector."""
    shown = ".view:target,.view :target"
    out = [f'body:not(:has({shown})) .nav a[href="#inbox"]{_ON}']
    for key, _label in _NAV_ITEMS:
        if site and key in _LOCAL_VIEWS:
            continue
        out.append(f'body:has(#{key}:target,#{key} :target) .nav a[href="#{key}"]{_ON}')
    for rid in rids:
        on = f"body:has(#{rid}:target,#{rid} :target)"
        out.append(f'{on} .nav a[href="#{rid}"]{_ON}{on} .nav-sub[data-rid="{rid}"]{{display:grid}}')
    return "".join(out)


def _waiting_section(model: dict, site: bool = False) -> str:
    """Sessions that wait for input, then the open owner gates. A shared copy (`site`) has the owner gates only: its
    sessions are not on the reader's machine, so a table of them would be empty for a wrong reason."""
    out = [f'<section id="waiting" class="card wait">{_h2("bell-ring", "Waiting for you")}']
    sessions, gates = ([] if site else model["sessions"]), model["waiting"]
    if not sessions and not gates:
        out.append('<p class="empty">' + ("No owner gate is waiting." if site else "Nothing is waiting for you.")
                   + "</p></section>")
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
    # The section has the class `timeline` as well as the id: the hub prefixes every id, so the phone CSS selects by class.
    out = ['<section class="card timeline" id="timeline"><div class="sec-h">' + _h2("chart-gantt", "Timeline") + '<span class="note">plans as '
           'lanes, milestones as columns in roadmap order, one tile per phase</span></div><div class="scroll">',
           f'<div class="lanes" style="grid-template-columns:150px repeat({cols},minmax(110px,1fr));width:100%;'
           f'min-width:{150 + cols * 110}px">',
           '<div class="hd ln">Plan / milestone</div>']
    for ms in milestones:
        dep = f"after {', '.join(ms['depends'])}" if ms["depends"] else "starts first"
        n = len(ms["blockers"])
        count = f' <span class="bcount">{n} gate(s)</span>' if n else ""
        out.append(f'<div class="hd">{_e(ms["id"])} {_pill(ms["status"])}<div class="empty" style="font-weight:400;'
                   f'font-size:11px">{_e(dep)}</div>{count}</div>')
    plan_lanes = lanes or ["-"]
    for i, lane in enumerate(plan_lanes):
        done = sum(1 for ms in milestones for ph in ms["phases"] if ph["plan"] == lane and ph["tile"] in ("done", "moved"))
        total = sum(1 for ms in milestones for ph in ms["phases"] if ph["plan"] == lane)
        out.append(f'<div class="ln" style="--lc:var(--c{i % 6})">{_e(lane)}<div class="empty" '
                   f'style="font-weight:400;font-size:11px">{done}/{total} done</div></div>')
        for ms in milestones:
            tiles = []
            for ph in ms["phases"]:
                if ph["plan"] != lane:
                    continue
                hi = " hi" if "high" in ph.get("risk", "").lower() else ""
                title = f"{ph['ref']} {ph['name']} | {ph['tracker'] or ph['state']}"
                tiles.append(f'<div class="tile {_e(ph["tile"])}{hi}" data-q="{_e(ms["id"])} {_e(ph["ref"])}" title="{_e(title)}">'
                             f'{_tile_icon(ph["tile"])}<b>{_e(ph["num"])}</b>'
                             f'<span>{_e(ph["name"] or ph["ref"])}</span></div>')
            out.append(f"<div>{''.join(tiles)}</div>")
    if any(ms["blockers"] for ms in milestones):  # the blockers get their own lane, so the column headers stay short
        out.append('<div class="ln">Owner and outside</div>')
        for ms in milestones:
            cells = []
            for b in ms["blockers"]:
                reason = str(b["reason"])
                short = reason if len(reason) <= 60 else reason[:60] + "…"
                cells.append(f'<div class="gate" title="{_e(reason)}">{_e(b["type"])}: {_e(short)}</div>')
            out.append(f"<div>{''.join(cells)}</div>")
    out.append('</div></div><div class="lane-list">')
    for ms in milestones:  # the phone list: the grid is hidden on a narrow screen
        out.append(f'<h3>{_e(ms["id"])} {_pill(ms["status"])}</h3>')
        for ph in ms["phases"]:
            hi = " hi" if "high" in ph.get("risk", "").lower() else ""
            out.append(f'<div class="ltile {_e(ph["tile"])}{hi}" data-q="{_e(ms["id"])} {_e(ph["ref"])}">{_tile_icon(ph["tile"])}'
                       f'<b>{_e(ph["plan"])} {_e(ph["num"])}</b>'
                       f'<span>{_e(ph["name"] or ph["ref"])}</span></div>')
    out.append('</div><div class="legend"><span>colour: to do · <b>in progress</b> · done · striped = moved · '
               'amber = blocked</span><span>red dot = Risk high (stops for review)</span></div></section>')
    return "".join(out)


def _summary(model: dict) -> str:
    phases = [ph for ms in model["milestones"] for ph in ms["phases"]]
    done = sum(1 for ph in phases if ph["tile"] in ("done", "moved"))
    building = [ph["ref"] for ph in phases if ph["tile"] == "in-progress"]
    high = sum(1 for ph in phases if "high" in ph.get("risk", "").lower())
    nxt = model.get("next") or {}
    nxt_txt = f"{nxt.get('milestone', '')} {nxt.get('plan', '')}#{nxt.get('phase', '')}" if nxt else "none ready"
    return ('<section class="kpis" id="overview" aria-label="Summary">'
            + _kpi("circle-check-big", "k-done", f"{_e(done)} / {_e(len(phases))}", "phases done")
            + _kpi("milestone", "k-done", f'{_e(model["done"])} / {_e(model["total"])}', "milestones done")
            + _kpi("loader-circle", "", _e(len(building)), f'in progress: {_e(", ".join(building) or "none")}')
            + _kpi("triangle-alert", "k-block" if high else "", _e(high), "high-risk phases")
            + _kpi("skip-forward", "", _e(nxt_txt), "next batch for the runner")
            + "</section>")


def _tile_icon(state: str) -> str:
    """The state of a timeline tile as a named icon: the tile's colour is not the only cue."""
    return _icon(_STATUS_ICON.get(state, "circle"), _LABEL.get(state, state))


def _ms_tone(ms: dict) -> str:
    """The accent of a milestone card: done, wait (an owner gate), block, prog or todo."""
    if ms["status"] in ("done", "not-needed"):
        return "done"
    if any(b.get("type") == "owner-gate" for b in ms["blockers"]):
        return "wait"
    if ms["blockers"] or ms["status"] == "blocked":
        return "block"
    return "prog" if ms["status"] == "in-progress" else "todo"


def _done_phases(ms: dict) -> int:
    return sum(1 for ph in ms["phases"] if ph["tile"] in ("done", "moved"))


def _flow(model: dict) -> str:
    """The milestones as a left-to-right chain in roadmap order; each node links to its milestone below."""
    nodes = []
    for ms in model["milestones"]:
        dep = f"after {', '.join(ms['depends'])}" if ms["depends"] else "starts first"
        nodes.append(f'<a class="fnode s-{_e(ms["status"])}" data-q="{_e(ms["id"])}" href="#ms-{_e(ms["id"])}"><b>{_e(ms["id"])}</b> '
                     f'{_pill(ms["status"])}<span>{_e(dep)} · {_e(_done_phases(ms))}/{_e(len(ms["phases"]))} ph</span></a>')
    chain = '<span class="arrow" aria-hidden="true">→</span>'.join(nodes)
    return (f'<section id="flow"><div class="sec-h">{_h2("workflow", "Flow")}<span class="note">milestones in roadmap order</span></div>'
            f'<div class="card scroll"><div class="flow">{chain}</div></div></section>')


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
        body = "".join(f'<a class="rcard" href="#ms-{_e(m["id"])}" data-q="{_e(m["id"])}" data-st="{_ms_tone(m)}">'
                       f'<span><strong>{_e(m["id"])}</strong> {_pill(m["status"])}</span>'
                       f'{_bar(_done_phases(m), len(m["phases"]))}'
                       + "".join(f'<span class="note">{_e(b["type"])}</span>' for b in m["blockers"])
                       + "</a>" for m in items)
        cols.append(f'<div><h3>{_e(title)}</h3>{body or "<p class=empty>none</p>"}</div>')
    return ('<section id="board"><div class="sec-h">' + _h2("square-kanban", "Now, next, later") +
            '<span class="note">which milestones can start</span></div>'
            f'<div class="cols">{"".join(cols)}</div></section>')


def _gates(model: dict) -> str:
    rows = [(ms["id"], b) for ms in model["milestones"] for b in ms["blockers"]]
    body = "".join(f"<tr><td><strong>{_e(mid)}</strong></td>"
                   f"<td>{_kind(str(b['type']))}</td><td>{_e(b['reason'])}</td>"
                   f"<td><code>{_e(b['check'])}</code></td></tr>" for mid, b in rows)
    return (f'<section class="card" id="gates"><div class="sec-h">{_h2("shield-alert", "Gates and blockers")}'
            f'<span class="note">{_e(len(rows))} open</span></div>'
            + (f'<div class="scroll"><table><tr><th>Milestone</th><th>Type</th><th>Reason</th><th>Check</th></tr>{body}'
               "</table></div>" if rows else '<p class="empty">No blockers.</p>') + "</section>")


def _milestones(model: dict) -> str:
    out = ['<section id="milestones"><div class="sec-h">' + _h2("milestone", "Milestones and phases") + '<span class="note">every phase with '
           'model, lane, risk and Tracker status</span></div>']
    for ms in model["milestones"]:
        rows = "".join(
            f"<tr data-q=\"{_e(ms['id'])} {_e(ph['ref'])}\" data-qn=\"1\"><td><code>{_e(ph['ref'])}</code></td><td>{_e(ph['name'])}</td>"
            f"<td>{_e(_short_model(ph['model']))}</td>"
            f"<td>{_e(ph['lane'].split(' ', 1)[0] if ph['lane'] else '-')}</td>"
            f"<td>{_e(ph['risk'] or '-')}</td><td>{_pill(ph['tile'])} {_e(ph['tracker'])}</td></tr>"
            for ph in ms["phases"])
        target = f" · target {_e(ms['target'])}" if ms.get("target") else ""
        out.append(f'<details class="card" id="ms-{_e(ms["id"])}" data-q="{_e(ms["id"])}" data-qn="1"><summary>{_e(ms["id"])} '
                   f'{_pill(ms["status"])} <span class="note">owner {_e(ms["owner"])}{target} · '
                   f'after {_e(", ".join(ms["depends"]) or "-")}</span></summary>'
                   '<div class="scroll"><table><tr><th>Phase</th><th>Name</th><th>Model</th><th>Lane</th><th>Risk</th>'
                   f'<th>Tracker</th></tr>{rows or "<tr><td colspan=6 class=empty>no build phases</td></tr>"}'
                   "</table></div></details>")
    out.append("</section>")
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
    return ('<section class="card" id="runner"><div class="sec-h">' + _h2("cpu", "Runner") +
            '<span class="note">roadmap-run state on this machine</span></div>' + "".join(parts) + "</section>")


# The sections of a roadmap view, in page order: the nav sub-links. `render_body` writes them in this order.
_PAGE_ANCHORS = [("waiting", "Waiting"), ("overview", "Overview"), ("flow", "Flow"), ("board", "Board"),
                 ("timeline", "Timeline"), ("gates", "Gates"), ("milestones", "Milestones"), ("runner", "Runner")]

def _rid(folder, slug) -> str | None:
    """The view id of a roadmap in `index.html`: `rm-<the folder's 6 hex>-<slug>` (the 6 hex keep two clones with
    one repo name apart), or None when the folder has no `-<6hex>` tag or the slug breaks the
    slug rule (such a row gets no view: its name is not safe in an id or a selector)."""
    m = re.fullmatch(r".+-([0-9a-f]{6})", str(folder or ""))
    if not m or not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        return None
    return f"rm-{m.group(1)}-{slug}"


def _prefix_ids(body: str, rid: str) -> str:
    """Every `id="x"` and `href="#x"` in a roadmap body becomes `<rid>-x`, so two roadmaps in one file never share an
    id. Safe on rendered HTML: every value from the files is escaped, so a `"` in it is `&quot;`."""
    body = re.sub(r' id="([A-Za-z][\w-]*)"', lambda m: f' id="{rid}-{m.group(1)}"', body)
    return re.sub(r' href="#(?!ic-)([A-Za-z][\w-]*)"', lambda m: f' href="#{rid}-{m.group(1)}"', body)


def _stub(rid: str, slug: str) -> str:
    """`<slug>.html`: one line that opens the roadmap's view in the hub, so an old link or bookmark still works."""
    target = f"../index.html#{rid}"
    return ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta http-equiv="refresh" content="0;url={_e(target)}"><title>Roadmap {_e(slug)}</title></head>'
            f'<body><p><a href="{_e(target)}">Open roadmap {_e(slug)}</a></p></body></html>\n')


def render_html(model: dict) -> str:
    """One self-contained roadmap page (an `--out` copy): the app shell with an empty repo tree, one theme script,
    one local font link, no network. Every value from the files is escaped."""
    slug = model["roadmap"]
    return _shell(title=f"Roadmap {slug}", base="../", nav=_nav([], "../"), crumbs=_crumbs("", slug),
                  body=render_body(model), generated=model.get("generated", ""))


def render_body(model: dict, site: bool = False) -> str:
    """Everything inside `<main>`: the header and the sections. `write_page` keeps it as `<slug>.body.html`; the
    hub puts it, with its ids prefixed, in `index.html` as the roadmap's view. A shared copy (`site`) leaves out the
    session tables and the Runner section."""
    title = f"Roadmap {model['roadmap']}"
    phases = [ph for ms in model["milestones"] for ph in ms["phases"]]
    done = sum(1 for ph in phases if ph["tile"] in ("done", "moved"))
    commit = f" · origin <code>{_e(model.get('origin_commit'))}</code>" if model.get("origin_commit") else ""
    chips = "".join(
        f'<span class="chip" style="--lc:var(--c{i % 6})"><b>{_e(plan)}</b> <span>'
        f'{_e(sum(1 for ph in phases if ph["plan"] == plan and ph["tile"] in ("done", "moved")))}/'
        f'{_e(sum(1 for ph in phases if ph["plan"] == plan))} phases</span></span>'
        for i, plan in enumerate(model["lanes"]))
    return "".join([
        f'<header class="hdr"><div><h1>{_e(title)}</h1><p class="sub">{_e(model["done"])} of {_e(model["total"])} '
        f'milestones · {_e(done)} of {_e(len(phases))} phases done · branch <code>{_e(model["branch"])}</code>'
        f'{commit} · generated {_e(model["generated"])}</p>'
        + (f'<div class="chips">{chips}</div>' if chips else "") + "</div></header>",
        _waiting_section(model, site), _summary(model), _flow(model), _now_next_later(model), _swimlane(model),
        _gates(model), _milestones(model), "" if site else _runner(model),
        '<p class="empty">Built from roadmap.md and the plan Trackers and headers on origin.</p>' if site else
        '<p class="empty">Built from roadmap.md, the plan Trackers and headers on origin, the runner state and the '
        "session-state folder. Re-rendered by the runner, /handoff, /pr-merge, /catchup and the waiting hooks.</p>"])


def default_page_path(root: Path, slug: str, home: Path | None = None, base: Path | None = None) -> Path:
    """`~/.caddis/roadmap-pages/<repo folder>-<6 hex>/<slug>.html`: outside every checkout, so a render never makes a
    repo dirty (17 Oct: the in-repo `.local/` folder is not gitignored in every repo). The folder is the MAIN
    checkout (a worktree shares its page); the 6 hex of its path keep two clones with one name apart. `base` (the
    shared copy's build folder) stands in for the pages root."""
    main = main_checkout(root)
    tag = hashlib.sha1(str(main).lower().encode("utf-8")).hexdigest()[:6]
    return (base if base is not None else pages_root(home)) / f"{main.name}-{tag}" / f"{slug}.html"


def write_page(root: Path, slug: str, out: Path | None, roadmap_mod, *, site_dir: Path | None = None) -> Path | None:
    """At the default path: `<slug>.body.html` (the page body, which the hub shows as a view of `index.html`), a
    one-line `<slug>.html` that opens that view, and `<slug>.json` (the one-row summary the hub is built from). An
    `--out` page is a one-off self-contained copy and stays out of the hub. None: a newer caddis wrote this page,
    so it is kept. `site_dir` (the shared copy's build folder) writes there instead, with no version gate, and
    leaves this machine's waiting sessions and runner out of the model before anything is rendered."""
    path = Path(out) if out else default_page_path(root, slug, base=site_dir)
    if out is None and site_dir is None and _owned_by_newer(slug, path.with_suffix(".json")):  # a skip does no work
        return None
    model = build(root, slug, roadmap_mod)
    if site_dir is not None:  # a CI run has no session marks and no runner: hide them, never show them as empty
        model["sessions"] = []
        model["runner"] = {"lock": None, "stale_lock": None, "last_stop": None, "errors": []}
    path.parent.mkdir(parents=True, exist_ok=True)
    if out is not None:
        _write_atomic(path, render_html(model))
        return path
    _write_atomic(path.with_suffix(".body.html"), render_body(model, site=site_dir is not None))
    rid = _rid(path.parent.name, model["roadmap"])
    _write_atomic(path, _stub(rid, model["roadmap"]) if rid else render_html(model))
    try:  # the summary feeds the hub only: the page is written, so a failure here never fails the render
        _write_atomic(path.with_suffix(".json"),
                      json.dumps(page_summary(model, main_checkout(root), path), indent=1))
    except Exception as exc:
        print(f"[ROADMAP] hub summary not written: {exc}", file=sys.stderr)
    return path


# ---- the version gate: a session on an old plugin never overwrites what a newer caddis wrote (robustness #8) -------

@functools.lru_cache(maxsize=8)
def generator_version(here: Path | None = None) -> str:
    """This caddis's version: the Claude plugin's `.claude-plugin/plugin.json` or the agy plugin's root
    `plugin.json` (both beside `scripts/`), else the source checkout's `caddis` entry in
    `.github/runtime-targets.json`, else "dev"."""
    base = Path(here or Path(__file__).resolve().parent).parent
    for manifest in (base / ".claude-plugin" / "plugin.json", base / "plugin.json"):
        data, _ = _read_json(manifest)
        if data and data.get("version"):
            return str(data["version"])
    data, _ = _read_json(base / ".github" / "runtime-targets.json")
    for target in (data or {}).get("targets") or []:
        plugin = target.get("plugin") if isinstance(target, dict) else None
        if isinstance(plugin, dict) and plugin.get("name") == "caddis" and plugin.get("version"):
            return str(plugin["version"])
    return "dev"


def _version_key(text) -> tuple[int, ...] | None:
    parts = str(text or "").strip().split(".")
    return tuple(int(p) for p in parts) if all(p.isdigit() for p in parts) else None


def is_newer(theirs, mine) -> bool:
    """True only when both are numeric versions and `theirs` is the higher one; "dev" or "" never blocks."""
    a, b = _version_key(theirs), _version_key(mine)
    return a is not None and b is not None and a > b


GENERATOR_OWNERSHIP_S = 1800  # a newer caddis owns a page only while it keeps writing it (review of #71)
# While the newer version is still INSTALLED on this machine, it owns the page much longer: an older session that is
# still open must not undo a release (20 Oct 2026: a 1.3.145 session re-rendered the 1.3.147 hub in the old layout
# 30 minutes after the release). A real downgrade removes the newer version, and the 30 minutes apply again.
INSTALLED_OWNERSHIP_S = 24 * 3600


def installed_versions(home: Path | None = None) -> set[str]:
    """The caddis versions installed on this machine: the Claude Code plugin cache folders and agy's plugin
    manifest. Empty when none can be read."""
    base = Path(home or Path.home())
    found: set[str] = set()
    try:
        for d in (base / ".claude" / "plugins" / "cache" / "caddis" / "caddis").iterdir():
            if d.is_dir() and _version_key(d.name) is not None:
                found.add(d.name)
    except OSError:
        pass
    data, _ = _read_json(base / ".gemini" / "config" / "plugins" / "caddis" / "plugin.json")
    if isinstance(data, dict) and _version_key(data.get("version")) is not None:
        found.add(str(data["version"]))
    return found


def _ownership_s(theirs: str, home: Path | None = None) -> int:
    """How long a newer caddis owns what it wrote: a day while it is installed under `home`, else
    GENERATOR_OWNERSHIP_S."""
    return INSTALLED_OWNERSHIP_S if theirs in installed_versions(home) else GENERATOR_OWNERSHIP_S


def _newer_owner(summary: Path) -> tuple[str, bool]:
    """(version, live): the newer caddis that wrote `summary` ("" when it is not newer), and whether it wrote it
    within its ownership window (`_ownership_s`). An unreadable time is not live: a downgrade must never freeze a
    page."""
    data, _ = _read_json(summary)
    theirs = str((data or {}).get("generator") or "")
    if not is_newer(theirs, generator_version()):
        return "", False
    age_h = _age_h(str((data or {}).get("generated_utc") or ""), datetime.datetime.now(datetime.timezone.utc))
    return theirs, age_h is not None and age_h * 3600 <= _ownership_s(theirs)


def _gate(label: str, theirs: str, live: bool) -> bool:
    """True: skip the write. Prints one line when a newer caddis owns it, or when this one takes it over."""
    if theirs and live:
        print(f"[ROADMAP] {label}: a newer caddis ({theirs}) owns this page; skipped")
        return True
    if theirs:
        print(f"[ROADMAP] {label}: taking over from caddis {theirs} (it has not written for "
              f"{_ownership_s(theirs) // 60} min)")
    return False


def _owned_by_newer(slug: str, summary: Path) -> bool:
    return _gate(slug, *_newer_owner(summary))


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


ASSET_DIR = Path(__file__).resolve().parent / "roadmap_assets"
ASSET_FILES = ("fonts.css", "OFL-MapleMono.txt", "OFL-Atkinson.txt", "LICENSE-Lucide.txt")
# icons.svg is shipped beside them but not copied: the sprite goes inline into each page (`_sprite`).


def install_assets(root_dir: Path) -> int:
    """Copy the bundled fonts (and their licences) to `<root_dir>/_assets/` when missing or changed. Text is compared
    as text, not bytes: `_write_atomic` writes CRLF on Windows, so a byte compare would rewrite every time. A source
    file that is not shipped is skipped. Returns the number of files written."""
    written = 0
    target_dir = root_dir / "_assets"
    for name in ASSET_FILES:
        src = ASSET_DIR / name
        if not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        dst = target_dir / name
        try:
            if dst.read_text(encoding="utf-8") == text:
                continue
        except FileNotFoundError:
            pass
        target_dir.mkdir(parents=True, exist_ok=True)
        _write_atomic(dst, text)
        written += 1
    return written


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
        "version": 2, "generator": generator_version(), "repo": main.name, "checkout": str(main), "folder": path.parent.name, "slug": model["roadmap"],
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
        "milestones": [{"id": ms["id"], "status": ms["status"]} for ms in model["milestones"]],
        "blockers": [{"milestone": ms["id"], "type": b["type"], "reason": b["reason"], "check": b["check"]}
                     for ms in model["milestones"] for b in ms["blockers"]
                     if ms["status"] not in ("done", "not-needed")],
        "runner_detail": {"lock": r.get("lock"), "stale_lock": bool(r.get("stale_lock")),
                          "last_stop": r.get("last_stop"), "errors": r.get("errors", [])},
    }


# The roadmap slug rule, copied from caddis_roadmap.SLUG_RE_TEXT (a test keeps the two equal): this module stays
# importable on its own, without the roadmap module and its git helpers. A slug never holds a dot, so `<slug>.body.html` can never be another
# roadmap's `<slug>.html`; files whose name breaks the rule are never pruned or shown as a view.
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")


def prune_folder(folder: Path, keep: set[str]) -> int:
    """Remove the page, body and summary of each roadmap that is no longer on origin. Only `<slug>.json` files and
    their `<slug>.html` and `<slug>.body.html` files are touched. Returns how many roadmaps were removed."""
    removed = 0
    if not folder.is_dir():
        return removed
    for js in folder.glob("*.json"):
        # a live newer caddis may know a roadmap this one cannot list
        if js.stem in keep or not _SLUG_RE.fullmatch(js.stem) or _newer_owner(js)[1]:
            continue
        for f in (js, js.with_suffix(".html"), js.with_suffix(".body.html")):
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
        for key in ("sessions", "owner_gates", "milestones", "blockers"):  # a hand-edited summary must not stop the hub for every repo
            items = data.get(key)
            data[key] = [i for i in items if isinstance(i, dict)] if isinstance(items, list) else []
        if not isinstance(data.get("in_progress"), list):
            data["in_progress"] = []
        if not isinstance(data.get("runner_detail"), dict):
            data["runner_detail"] = {}
        rows.append(data)
    return rows, errors


def read_bodies(root_dir: Path, rows: list[dict]) -> dict[str, str]:
    """{rid: body} for every row with a view id and a `<slug>.body.html`, read only. The path comes from
    `row["page"]` (set from the disk by `read_summaries`), never from the summary's own text, and only a file
    directly in a `<root_dir>/<folder>/` is read. One row that fails never stops the others."""
    root = Path(root_dir).resolve()
    bodies: dict[str, str] = {}
    for row in rows:
        rel, slug = row.get("page"), row.get("slug")
        rid = _rid(row.get("folder"), slug)
        if rid is None or not isinstance(rel, str) or slug != Path(rel).stem:
            continue
        try:
            page = (root / rel).resolve()
            body_file = page.with_suffix(".body.html")
            if page.parent.parent != root or page.suffix != ".html" or not body_file.is_file():
                continue
            bodies[rid] = body_file.read_text(encoding="utf-8")
        except Exception as exc:  # noqa: BLE001 - one bad row never stops the others (docstring)
            print(f"[ROADMAP] {Path(rel).with_suffix('').as_posix()}: body not read: {exc}", file=sys.stderr)
    return bodies


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


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _row_tone(r: dict) -> str:
    """The accent of a roadmap card on the inbox: wait (an owner gate), block, done, prog or todo."""
    total, done = _int(r.get("phases_total")), _int(r.get("phases_done"))
    if r.get("owner_gates"):
        return "wait"
    if _int(r.get("blocked")):
        return "block"
    if total and done >= total:
        return "done"
    return "prog" if r.get("in_progress") or done else "todo"


def _roadmap_link(r: dict, label=None) -> str:
    """The roadmap's name linked to its view; plain text for a row that has no view."""
    rid = _rid(r.get("folder"), r.get("slug"))
    text = _e(r.get("slug") if label is None else label)
    return f'<a href="#{rid}">{text}</a>' if rid else text


def _repo_slug_key(r: dict) -> tuple[str, str, str]:
    return (str(r.get("repo", "")).lower(), str(r.get("folder", "")), str(r.get("slug", "")))


def _table(head: list[str], body: list[str]) -> str:
    return ('<div class="scroll"><table><tr>' + "".join(f"<th>{_e(h)}</th>" for h in head) + "</tr>"
            + "".join(body) + "</table></div>")


def _gates_view(rows: list[dict]) -> str:
    items = []
    for r in rows:
        for b in r.get("blockers") or r.get("owner_gates") or []:  # a v1 summary has owner_gates only
            items.append((r, b))
    items.sort(key=lambda rb: (str(rb[1].get("type") or "owner-gate") != "owner-gate", *_repo_slug_key(rb[0]),
                               str(rb[1].get("milestone", ""))))
    body = []
    for r, b in items:
        rid, ms = _rid(r.get("folder"), r.get("slug")), str(b.get("milestone", ""))
        ms_text = _e(ms)
        if rid and re.fullmatch(r"[A-Za-z][\w-]*", ms):  # the id is prefixed by `_prefix_ids` only when it is plain
            ms_text = f'<a href="#{rid}-ms-{ms_text}">{ms_text}</a>'
        kind = str(b.get("type") or "owner-gate")
        body.append(f'<tr><td><strong>{_e(r.get("repo"))}</strong></td><td>{_roadmap_link(r)}</td><td>{ms_text}</td>'
                    f'<td>{_kind(kind)}</td><td>{_e(b.get("reason"))}</td>'
                    f'<td><code>{_e(b.get("check") or "-")}</code></td></tr>')
    if not body:
        return '<p class="empty">No open gates or blockers.</p>'
    return _table(["Repo", "Roadmap", "Milestone", "Type", "Reason", "Check"], body)


def _sessions_view(rows: list[dict]) -> str:
    out = []
    for _folder, group in _group_rows(rows)[0]:
        sessions = sorted(_sessions_of(group), key=lambda s: not s.get("asking"))  # asking first, then by mark order
        if not sessions:
            continue
        body = []
        for s in sessions:
            stale = " (stale?)" if s.get("stale") else ""
            body.append(f'<tr><td><code>{_e(s.get("session"))}</code></td>'
                        f'<td>{"asking" if s.get("asking") else "idle"}</td><td>{_e(s.get("message"))}</td>'
                        f'<td>{_e(s.get("since"))}{_e(stale)}</td></tr>')
        out.append(f'<div class="card"><h3>{_icon("folder-git-2")}{_e(group[0].get("repo"))}</h3>'
                   + _table(["Session", "Asking or idle", "Message", "Since"], body) + "</div>")
    return "".join(out) or '<p class="empty">No session is waiting.</p>'


def _runners_view(rows: list[dict]) -> str:
    body = []
    for r in sorted(rows, key=lambda r: (r.get("runner") != "running", *_repo_slug_key(r))):
        detail = r.get("runner_detail") if isinstance(r.get("runner_detail"), dict) else {}
        lock, stop = detail.get("lock"), detail.get("last_stop")
        batch = lock.get("batch") if isinstance(lock, dict) else None
        stop_text = " · ".join(str(v) for v in ((stop or {}).get("reason"), (stop or {}).get("utc")) if v)             if isinstance(stop, dict) else ""
        runner = str(r.get("runner") or "")
        pill, icon = (("s-in-progress", "play") if runner == "running" else ("s-blocked", "octagon-alert") if runner
                      else ("s-todo", "circle"))
        body.append(f'<tr><td><strong>{_e(r.get("repo"))}</strong></td><td>{_roadmap_link(r)}</td>'
                    f'<td><span class="pill {pill}">{_icon(icon)}{_e(runner or "idle")}</span></td><td>{_e(batch or "-")}</td>'
                    f'<td>{_e(stop_text or "-")}</td><td>{_e(r.get("next") or "-")}</td></tr>')
    if not body:
        return '<p class="empty">No roadmap pages yet.</p>'
    return _table(["Repo", "Roadmap", "Runner", "Batch", "Last stop", "Next"], body)


_VIEWS = {"gates": ("Gates", "Every open owner gate and blocker, across all repos. Owner gates come first.", _gates_view),
          "sessions": ("Sessions", "The newest session marks of each repo.", _sessions_view),
          "runners": ("Runners", "The roadmap runner of every roadmap on this machine.", _runners_view)}


def render_view(kind: str, rows: list[dict]) -> str:
    """`<section class="view" id="gates|sessions|runners">`: a cross-repo table over the page summaries. These sections
    sit outside any roadmap body, so their ids are not prefixed; links into a roadmap use its prefixed ids."""
    title, note, fn = _VIEWS[kind]
    return f'<section class="view" id="{kind}">{_h2(_NAV_ICON[kind], title)}<p class="sub">{_e(note)}</p>{fn(rows)}</section>'


_SITE_NOTE = "Shared copy — built by CI. Live sessions and runners show only on the owner's machine."
_SITE_CSS = (".site-banner{margin:0 0 12px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;"
             "border-left:4px solid var(--accent);background:var(--panel2);color:var(--fg);font-size:13px}")


def render_hub(rows: list[dict], errors: list[str], now: datetime.datetime,
               bodies: dict[str, str] | None = None, *, site: bool = False, banner: str = "") -> str:
    """The whole app in one file: the inbox and overview view, then one view per roadmap (its body from `bodies`,
    ids prefixed). CSS shows one view at a time, so the nav is the same for every view and is never stale. While the
    inbox shows, the page reloads itself every 60 s (the script), so an open tab follows the renders. A shared copy
    (`site`, built by CI) shows `banner` and leaves out everything of this machine: the sessions and the runners,
    in the nav, the inbox and the views. Owner gates stay: they come from git."""
    bodies = bodies or {}
    errors = list(errors)
    if site:  # whatever a summary holds of live state is dropped here too, not only at the writer
        rows = [{**r, "sessions": [], "runner": "", "runner_detail": {}} for r in rows]
    order, need, count = _group_rows(rows)
    phases_done = sum(_int(r.get("phases_done")) for r in rows)
    phases_total = sum(_int(r.get("phases_total")) for r in rows)
    live = sum(1 for r in rows if r.get("runner") == "running")
    blocked = sum(_int(r.get("blocked")) for r in rows)
    out = [f'<p class="site-banner" role="note">{_e(banner or _SITE_NOTE)}</p>' if site else "",
           '<section class="view" id="inbox"><section class="kpis">',
           _kpi("bell-ring", "k-wait" if count else "", _e(count), "Needs you"),
           _kpi("circle-check-big", "k-done", f"{_e(phases_done)} / {_e(phases_total)}",
                "Phases done" + _bar(phases_done, phases_total)),
           _kpi("octagon-alert", "k-block" if blocked else "", _e(blocked), "Blocked phases"),
           "" if site else _kpi("activity", "", _e(live), "Runners live"), "</section>",
           f'<p class="sub">{_e(len(order))} repos · {_e(len(rows))} roadmaps · {_e(count)} item(s) need you · '
           f'generated {_e(now.strftime("%Y-%m-%d %H:%M UTC"))}'
           + ("" if site else " · the inbox reloads every minute") + "</p>",
           f'<section id="needs" class="card wait">{_h2("bell-ring", "Needs you")}']
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
    out.append("</section>" + _h2("map", "Roadmaps"))
    if not rows:
        out.append('<p class="card empty">No roadmap page has been rendered on this machine yet. Run '
                   "<code>caddis_roadmap.py render --all</code> in a repo that has <code>.caddis/roadmaps/</code>.</p>")
    out.append('<div class="cards">')
    for r in sorted(rows, key=lambda r: (str(r.get("repo", "")).lower(), str(r["folder"]), str(r["slug"]))):
        age = _age_h(str(r.get("generated_utc", "")), now)
        old = " (not refreshed)" if age is not None and age > HUB_STALE_H else ""
        dots = "".join(f'<span class="dot s-{_e(m.get("status"))}">{_e(m.get("id"))}</span>'
                       for m in r.get("milestones") or [])
        rid = _rid(r.get("folder"), r.get("slug"))
        if rid is None:
            errors.append(f"{r.get('folder')}/{r.get('slug')}: the folder or slug name breaks the naming rule")
            continue
        ids = " ".join(str(m.get("id")) for m in r.get("milestones") or [])
        out.append(f'<a class="rcard" href="#{rid}" data-q="{_e(r["slug"])} {_e(r.get("repo"))} {_e(ids)}" data-qn="1" '
                   f'data-st="{_row_tone(r)}">'
                   f'<div><strong>{_icon("map")}{_e(r["slug"])}</strong> <span class="empty">{_e(r.get("repo"))} · '
                   f'{_icon("git-branch")}{_e(r.get("branch"))} · {_e(r.get("origin_commit"))}</span></div>'
                   f'<div>{_bar(_int(r.get("phases_done")), _int(r.get("phases_total")))} '
                   f'{_e(r.get("milestones_done"))}/{_e(r.get("milestones_total"))} milestones</div>'
                   f'<div class="dots">{dots}</div>'
                   f'<div class="empty">next: {_e(r.get("next") or "-")}'
                   + ("" if site else f' · runner: {_e(r.get("runner") or "idle")}') + f'{_e(old)}</div></a>')
    out.append("</div>")
    for err in errors:
        out.append(f'<p class="empty">Could not read {_e(err)}.</p>')
    out.append('<p class="empty">' + ("Built by CI from the roadmaps on origin." if site else
               "Built from the page summaries in this folder. Every roadmap page render rebuilds it.") + "</p></section>")
    rids = []
    for r in sorted(rows, key=lambda r: (str(r.get("repo", "")).lower(), str(r["folder"]), str(r["slug"]))):
        rid = _rid(r.get("folder"), r.get("slug"))
        if rid is None:
            continue
        rids.append(rid)
        body = bodies.get(rid)
        inner = (_prefix_ids(body, rid) if body is not None else
                 f'<p class="card empty">No page body yet for {_e(r["slug"])}: run <code>caddis_roadmap.py render</code> '
                 "in its repo.</p>")
        out.append(f'<section class="view" id="{rid}"><p class="view-crumbs"><a href="#inbox">Roadmaps</a> › '
                   f'{_e(r.get("repo"))} › <strong>{_e(r["slug"])}</strong></p>{inner}</section>')
    for kind in _VIEWS:
        if not (site and kind in _LOCAL_VIEWS):
            out.append(render_view(kind, rows))
    return _shell(title="Roadmaps", base="", nav=_nav(rows, "", site), body="".join(out),
                  crumbs='<a href="#inbox">Roadmaps</a> › <strong>Inbox</strong>',
                  generated=now.strftime("%Y-%m-%d %H:%M UTC"),
                  css=_view_css(rids, site) + (_SITE_CSS if site else ""),
                  script=_SITE_THEME_SCRIPT if site else None)


def write_hub(home: Path | None = None, now: datetime.datetime | None = None, *,
              site_dir: Path | None = None, banner: str = "") -> Path | None:
    """`~/.caddis/roadmap-pages/index.html`: every roadmap page on this machine, grouped per repo. None: a newer
    caddis wrote the hub (its version is in `.hub-generator`), so it is kept. `site_dir` (the shared copy's build
    folder) is written instead, with `banner`, with no live sessions or runners, and with no version gate and no
    stamp: CI is the only writer of that folder."""
    root_dir = pages_root(home) if site_dir is None else Path(site_dir)
    root_dir.mkdir(parents=True, exist_ok=True)
    stamp = root_dir / ".hub-generator"
    if site_dir is None:
        try:
            theirs = stamp.read_text(encoding="utf-8").strip()
            if not is_newer(theirs, generator_version()):
                theirs = ""
            live = bool(theirs) and time.time() - stamp.stat().st_mtime <= _ownership_s(theirs, home)
        except (OSError, UnicodeDecodeError):
            theirs, live = "", False
        if _gate("hub", theirs, live):
            return None
    try:
        install_assets(root_dir)
    except Exception as exc:  # a missing font file must never stop the hub
        print(f"[ROADMAP] assets not installed: {exc}", file=sys.stderr)
    rows, errors = read_summaries(root_dir)
    try:  # a hub without the roadmap bodies is better than no hub
        bodies = read_bodies(root_dir, rows)
    except Exception as exc:
        print(f"[ROADMAP] page bodies not read: {exc}", file=sys.stderr)
        bodies = {}
    path = root_dir / "index.html"
    now = now or datetime.datetime.now(datetime.timezone.utc)
    if site_dir is not None:
        _write_atomic(path, render_hub(rows, errors, now, bodies, site=True, banner=banner))
        return path
    _write_atomic(path, render_hub(rows, errors, now, bodies))
    _write_atomic(stamp, generator_version() + "\n")
    return path


# ---- the shared copy: `render --site <dir>` builds in <dir>/build and publishes an allow-list to <dir>/public -----

def _short_sha(root: Path) -> str:
    try:
        done = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=15,
                              creationflags=0x08000000 if os.name == "nt" else 0)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip() or "unknown" if done.returncode == 0 else "unknown"


def site_banner(root: Path, now: datetime.datetime | None = None, env=None) -> str:
    """The shared copy's banner (plain text; `render_hub` escapes it). CI names the repo and commit in
    `GITHUB_REPOSITORY` and `GITHUB_SHA`; on a local run they are the checkout's folder name and `git rev-parse`."""
    env = os.environ if env is None else env
    repo = (env.get("GITHUB_REPOSITORY") or "").strip() or main_checkout(Path(root)).name
    sha = (env.get("GITHUB_SHA") or "").strip()[:7] or _short_sha(Path(root))
    when = (now or datetime.datetime.now(datetime.timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    return (f"Shared copy — built by CI from {repo} at {sha}, {when}. "
            "Live sessions and runners show only on the owner's machine.")


def _is_link(path: Path) -> bool:
    """A symlink or a Windows junction: never followed by the export."""
    if path.is_symlink():
        return True
    try:
        return bool(os.lstat(path).st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)  # Windows only
    except (AttributeError, OSError):
        return False


def _plain_file(path: Path) -> bool:
    return path.is_file() and not _is_link(path)


def export_site(build: Path, public: Path) -> list[str]:
    """Copy the allow-list of `build` to a fresh `public` and return the published paths (sorted, `/` separated):
    `index.html`, every file under `_assets/` except `*.json`, `*.body.html` and dot files, and each
    `<folder>/<slug>.html` whose `<slug>.json` sits beside it and whose slug passes the slug rule. Nothing else is
    published: not a `*.json` (the local checkout path and session data), not a `*.body.html`, not `.locks/`, not
    `.hub-generator`, not a dot file or folder, and not a link. `public` is wiped first, but only a folder this
    function made (a marker beside it says so), or an empty one; a link, a file, `build` itself and a folder that
    holds `build` or sits in it are refused (ValueError)."""
    build, public = Path(build), Path(public)
    if public.name in ("", ".", ".."):
        raise ValueError(f"the public folder needs a plain folder name, not {str(public)!r}")
    if not build.is_dir() or _is_link(build):
        raise ValueError(f"the build folder is not a plain folder: {build}")
    b = build.resolve()
    p = public.parent.resolve() / public.name
    if _is_link(public) or (public.exists() and not public.is_dir()):
        raise ValueError(f"the public folder is a link or a file: {public}")
    if p == b or b in p.parents or p in b.parents:
        raise ValueError(f"the public folder and the build folder overlap: {public}")
    marker = public.parent / f".{public.name}.created-by-caddis"
    if public.exists():
        if not marker.exists() and any(public.iterdir()):
            raise ValueError(f"{public} exists and was not made by this command; remove it or choose another folder")
        shutil.rmtree(public)
    public.mkdir(parents=True)
    marker.write_text("made by caddis_roadmap.py render --site; wiped on each run\n", encoding="utf-8")
    out: list[str] = []

    def put(src: Path, rel: str) -> None:
        dst = public / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        out.append(rel)

    if _plain_file(build / "index.html"):
        put(build / "index.html", "index.html")
    assets = build / "_assets"
    if assets.is_dir() and not _is_link(assets):
        for dirpath, dirnames, filenames in os.walk(assets, followlinks=False):
            here = Path(dirpath)
            dirnames[:] = sorted(d for d in dirnames if not d.startswith(".") and not _is_link(here / d))
            for name in sorted(filenames):
                if name.startswith(".") or name.endswith((".json", ".body.html")) or not _plain_file(here / name):
                    continue
                put(here / name, (here / name).relative_to(build).as_posix())
    for folder in sorted(build.iterdir()):
        if folder.name.startswith(".") or folder.name == "_assets" or not folder.is_dir() or _is_link(folder):
            continue
        for page_file in sorted(folder.glob("*.html")):
            slug = page_file.stem
            if (page_file.suffix == ".html" and _SLUG_RE.fullmatch(slug) and _plain_file(page_file)
                    and _plain_file(folder / f"{slug}.json")):
                put(page_file, f"{folder.name}/{page_file.name}")
    return sorted(out)
