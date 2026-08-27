#!/usr/bin/env python
"""caddis status line — ONE renderer for every host agent.

Replaces the four scripts that used to do this job (two bash, one PowerShell, one
dead): `statusline-command.sh`, `statusline-command-agy.sh`, the user's hand-made
`~/.claude/statusline-custom.sh`, and `~/.gemini/statusline/statusline.ps1`. Those
four drifted because each new segment had to be written twice in two languages.

Both hosts already spawned `python` just to parse the status JSON, so doing the
whole render here costs no extra process.

Usage
-----
  caddis_statusline.py --profile claude    # reads Claude Code status JSON on stdin
  caddis_statusline.py --profile agy       # reads agy (Antigravity) status JSON on stdin
  caddis_statusline.py --install [--host claude|agy|both]
  caddis_statusline.py --check
  caddis_statusline.py --sample [--profile claude|agy]

Config
------
`~/.caddis/statusline.json` — a flat dict of toggles. Missing file = defaults.
See DEFAULT_CONFIG below. `--install` writes it if absent, and never overwrites it.

Payload note
------------
The two hosts send DIFFERENT field names. This is a renderer with two profiles, not
one schema. Claude Code field names were read off the shipped binary (v2.1.239); agy
field names off a live payload. Every lookup is defensive: a host that drops a field
loses one segment, never the line.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# --------------------------------------------------------------------------------------
# Config
# --------------------------------------------------------------------------------------

CONFIG_PATH = Path.home() / ".caddis" / "statusline.json"

DEFAULT_CONFIG = {
    "color": True,
    "icons": True,          # Unicode segment icons (no Nerd Font required)
    "progress_bar": True,   # context bar  [████░░░░]
    "bar_width": 8,
    "token_counts": True,   # ◉ 412k/1M  — off falls back to a bare ctx:41%
    "cached_tokens": True,  # ⚡38k cached — rendered LOUD, see render_claude()
    "ram": True,            # 💻 69% (44 GB)
    "clock": True,          # ◷ 03:41
    "relay": True,          # ⏺ relay  (a parked resume pointer exists)
    "rate_limits": True,    # 5h:12% 7d:40%
    "session_id": False,    # #a1b2c3d4
    "git": True,
    "separator": "|",
    "ram_min_width": 0,     # 0 = always show; else hide below this terminal width
}


def load_config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    try:
        raw = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            cfg.update({k: v for k, v in raw.items() if k in DEFAULT_CONFIG})
    except Exception:
        pass  # no config, bad JSON, unreadable — defaults are always valid
    return cfg


# --------------------------------------------------------------------------------------
# Colour + icons
# --------------------------------------------------------------------------------------

class C:
    """ANSI escapes. Zeroed out when colour is off, so call sites need no branches."""

    def __init__(self, enabled: bool = True) -> None:
        def e(code: str) -> str:
            return "\033[" + code + "m" if enabled else ""

        self.reset = e("0")
        self.bold = e("1")
        self.dim = e("90")
        self.cyan = e("96")
        self.yellow = e("93")
        self.green = e("92")
        self.magenta = e("95")
        self.blue = e("94")
        self.red = e("91")
        self.white = e("97")
        self.orange = e("38;5;208")
        self.neon_blue = e("38;5;39")
        self.neon_green = e("38;5;118")
        self.gray = e("38;5;244")
        # Context badge — reverse video, so it reads at a glance.
        self.ctx_low = e("30;106")
        self.ctx_med = e("30;103")
        self.ctx_high = e("97;101")


ICONS = {
    "dir": "⌂",        # ⌂
    "folder": "\U0001F4C1",  # 📁
    "branch": "⎇",     # ⎇
    "model": "◆",      # ◆
    "brain": "\U0001F9E0",   # 🧠
    "ctx": "◉",        # ◉
    "clock": "◷",      # ◷
    "relay": "⏺",      # ⏺
    "ram": "\U0001F4BB",     # 💻
    "bolt": "⚡",       # ⚡
    "circle": "●",     # ●
    "bar_full": "█",   # █
    "bar_empty": "░",  # ░
    "brand_l": "▛",    # ▛
    "brand_r": "▜",    # ▜
}


def icon(cfg: dict, name: str) -> str:
    """Icon plus its trailing space, or '' when icons are off."""
    return (ICONS[name] + " ") if cfg.get("icons", True) else ""


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------

def dig(data, *keys):
    """Nested .get() that never raises. Returns '' for missing/None/False/''."""
    cur = data
    for k in keys:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(k)
    if cur is None or cur is False or cur == "":
        return ""
    return cur


def as_int(value, default: int = 0) -> int:
    try:
        return int(round(float(value)))
    except (TypeError, ValueError):
        return default


def fmt_tokens(n) -> str:
    """48500 -> 48.5k;  1048576 -> 1M;  0 -> 0."""
    n = as_int(n)
    if n <= 0:
        return "0"
    if n >= 1_000_000:
        v = n / 1_000_000
        return ("%.1f" % v).rstrip("0").rstrip(".") + "M"
    if n >= 1_000:
        v = n / 1_000
        return ("%.1f" % v).rstrip("0").rstrip(".") + "k"
    return str(n)


def progress_bar(pct: float, width: int, cfg: dict) -> str:
    pct = max(0.0, min(100.0, float(pct)))
    filled = int(round(pct / 100.0 * width))
    full = ICONS["bar_full"] if cfg.get("icons", True) else "#"
    empty = ICONS["bar_empty"] if cfg.get("icons", True) else "."
    return full * filled + empty * (width - filled)


def term_width() -> int:
    try:
        return shutil.get_terminal_size(fallback=(120, 24)).columns
    except Exception:
        return 120


# --------------------------------------------------------------------------------------
# Host facts the payload does not carry
# --------------------------------------------------------------------------------------

def git_facts(cwd: str) -> dict:
    """One `git status --porcelain=v2 --branch` call -> branch, staged/unstaged/untracked,
    ahead/behind. The v2 format gives all of it in a single invocation, which is why the
    old bash line dropped its two-calls-plus-grep-plus-awk approach."""
    out = {"branch": "", "staged": 0, "unstaged": 0, "untracked": 0, "ahead": 0, "behind": 0}
    if not cwd or not os.path.isdir(cwd):
        return out
    try:
        proc = subprocess.run(
            ["git", "-C", cwd, "--no-optional-locks", "status", "--porcelain=v2", "--branch"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=2.0,
        )
        text = proc.stdout.decode("utf-8", "replace")
    except Exception:
        return out

    for line in text.splitlines():
        if line.startswith("# branch.head "):
            head = line.split(" ", 2)[2].strip()
            if head and head != "(detached)":
                out["branch"] = head
        elif line.startswith("# branch.ab "):
            parts = line.split()
            if len(parts) >= 4:
                out["ahead"] = as_int(parts[2].lstrip("+"))
                out["behind"] = as_int(parts[3].lstrip("-"))
        elif line[:2] in ("1 ", "2 "):
            xy = line.split(" ")[1]
            if len(xy) >= 2:
                if xy[0] != ".":
                    out["staged"] += 1
                if xy[1] != ".":
                    out["unstaged"] += 1
        elif line.startswith("u "):
            out["unstaged"] += 1
        elif line.startswith("? "):
            out["untracked"] += 1
    return out


def ram_facts():
    """(used_percent, used_gb) or None.

    Windows goes through ctypes GlobalMemoryStatusEx — an in-process call. The old agy
    PowerShell line used `Get-CimInstance Win32_OperatingSystem`, which costs roughly
    300 ms and ran on EVERY status-line render.
    """
    try:
        if sys.platform == "win32":
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                return None
            used = stat.ullTotalPhys - stat.ullAvailPhys
            return int(stat.dwMemoryLoad), used / (1024 ** 3)

        if sys.platform.startswith("linux"):
            total = avail = 0
            with open("/proc/meminfo", "r") as fh:
                for line in fh:
                    if line.startswith("MemTotal:"):
                        total = int(line.split()[1]) * 1024
                    elif line.startswith("MemAvailable:"):
                        avail = int(line.split()[1]) * 1024
                    if total and avail:
                        break
            if not total:
                return None
            used = total - avail
            return int(round(used / total * 100)), used / (1024 ** 3)

        if sys.platform == "darwin":
            total = int(subprocess.run(["sysctl", "-n", "hw.memsize"], stdout=subprocess.PIPE,
                                       timeout=1.0).stdout.strip())
            vm = subprocess.run(["vm_stat"], stdout=subprocess.PIPE, timeout=1.0)
            page = 4096
            free_pages = 0
            for line in vm.stdout.decode("utf-8", "replace").splitlines():
                if "page size of" in line:
                    page = int(line.split("page size of")[1].split()[0])
                for label in ("Pages free:", "Pages inactive:", "Pages speculative:"):
                    if line.startswith(label):
                        free_pages += int(line.split(":")[1].strip().rstrip("."))
            avail = free_pages * page
            used = total - avail
            return int(round(used / total * 100)), used / (1024 ** 3)
    except Exception:
        return None
    return None


def relay_present(cwd: str) -> bool:
    """A parked resume pointer exists for this repo. `.caddis/relay.md` is canonical;
    a bare `relay.md` at the root is the pre-rename legacy location."""
    if not cwd:
        return False
    return os.path.isfile(os.path.join(cwd, ".caddis", "relay.md")) or \
        os.path.isfile(os.path.join(cwd, "relay.md"))


def ctx_color(c: C, pct: float) -> str:
    if pct >= 80:
        return c.ctx_high
    if pct >= 60:
        return c.ctx_med
    return c.ctx_low


# --------------------------------------------------------------------------------------
# Shared segments
# --------------------------------------------------------------------------------------

def git_segment(c: C, cfg: dict, git: dict, repo: str, worktree: str, base_color: str) -> str:
    """`saajunaid/caddis ⎇ main +2 ●1 ?3 ↑1 ↓2` — the counts split by stage, which the
    stock single ±N count could not tell apart."""
    body = repo or ""
    if git["branch"]:
        body = (body + " " if body else "") + icon(cfg, "branch") + git["branch"]
    if not body:
        return ""
    if worktree:
        body += "[" + worktree + "]"
    if git["staged"]:
        body += " " + c.green + "+" + str(git["staged"]) + base_color
    if git["unstaged"]:
        body += " " + c.red + ICONS["circle"] + str(git["unstaged"]) + base_color
    if git["untracked"]:
        body += " " + c.blue + "?" + str(git["untracked"]) + base_color
    if git["ahead"]:
        body += " " + c.green + "↑" + str(git["ahead"]) + base_color
    if git["behind"]:
        body += " " + c.red + "↓" + str(git["behind"]) + base_color
    return base_color + body + c.reset


def context_segment(c: C, cfg: dict, used_tokens: int, max_tokens: int, pct: float) -> str:
    """`◉ 412k/1M [████░░░░] 41%` — the token counts and the bar are what Example 2 had
    and the Claude line did not."""
    parts = []
    label = icon(cfg, "ctx") if cfg.get("icons", True) else "ctx "
    color = ctx_color(c, pct)
    if cfg.get("token_counts", True) and max_tokens > 0:
        parts.append(c.white + c.bold + fmt_tokens(used_tokens) + c.reset +
                     c.dim + "/" + fmt_tokens(max_tokens) + c.reset)
    if cfg.get("progress_bar", True):
        parts.append("[" + color + progress_bar(pct, as_int(cfg.get("bar_width"), 8), cfg) + c.reset + "]")
    parts.append(color + " %d%% " % as_int(pct) + c.reset)
    return label + " ".join(parts)


def cached_segment(c: C, cfg: dict, cached: int) -> str:
    """LOUD by design. The old PowerShell line hid this behind `termWidth >= 130` and
    dimmed it, so the one number that tells you the prompt cache is working was the
    first thing to disappear. Here it is bold, bright, and never width-gated."""
    if not cfg.get("cached_tokens", True) or cached <= 0:
        return ""
    return c.bold + c.cyan + icon(cfg, "bolt") + fmt_tokens(cached) + " cached" + c.reset


def ram_segment(c: C, cfg: dict) -> str:
    if not cfg.get("ram", True):
        return ""
    min_w = as_int(cfg.get("ram_min_width"), 0)
    if min_w and term_width() < min_w:
        return ""
    facts = ram_facts()
    if not facts:
        return ""
    pct, gb = facts
    col = c.orange if pct > 85 else (c.yellow if pct > 70 else c.white)
    return icon(cfg, "ram") + col + "%d%%" % pct + c.reset + c.dim + " (%.0f GB)" % gb + c.reset


def clock_segment(c: C, cfg: dict) -> str:
    if not cfg.get("clock", True):
        return ""
    return c.dim + icon(cfg, "clock") + time.strftime("%H:%M") + c.reset


def join(c: C, cfg: dict, parts) -> str:
    sep = " " + c.dim + str(cfg.get("separator", "|")) + c.reset + " "
    return sep.join(p for p in parts if p)


# --------------------------------------------------------------------------------------
# Profile: Claude Code
# --------------------------------------------------------------------------------------

def render_claude(data: dict, cfg: dict) -> str:
    c = C(cfg.get("color", True))
    cwd = dig(data, "cwd") or dig(data, "workspace", "current_dir")
    owner = dig(data, "workspace", "repo", "owner")
    name = dig(data, "workspace", "repo", "name")
    repo = ("%s/%s" % (owner, name)) if owner and name else ""
    worktree = dig(data, "workspace", "git_worktree")

    git = {"branch": dig(data, "worktree", "branch") or "", "staged": 0, "unstaged": 0,
           "untracked": 0, "ahead": 0, "behind": 0}
    if cfg.get("git", True):
        found = git_facts(cwd)
        found["branch"] = git["branch"] or found["branch"]
        git = found

    parts = []

    if cwd:
        parts.append(c.cyan + icon(cfg, "dir") + os.path.basename(cwd.rstrip("/\\")) + c.reset)

    seg = git_segment(c, cfg, git, repo, worktree, c.yellow)
    if seg:
        parts.append(seg)

    model = dig(data, "model", "display_name")
    if model:
        version = dig(data, "version")
        parts.append(c.green + icon(cfg, "model") + model + (" v" + str(version) if version else "") + c.reset)

    cw = data.get("context_window") if isinstance(data.get("context_window"), dict) else {}
    if cw:
        usage = cw.get("current_usage") if isinstance(cw.get("current_usage"), dict) else {}
        cached = as_int(usage.get("cache_read_input_tokens"))
        used = (as_int(usage.get("input_tokens")) + cached +
                as_int(usage.get("cache_creation_input_tokens")))
        if used == 0:
            used = as_int(cw.get("total_input_tokens"))
        max_tokens = as_int(cw.get("context_window_size"))
        pct = float(as_int(cw.get("used_percentage")))
        parts.append(context_segment(c, cfg, used, max_tokens, pct))
        loud = cached_segment(c, cfg, cached)
        if loud:
            parts.append(loud)

    effort = dig(data, "effort", "level")
    if effort:
        parts.append(c.blue + "effort:" + str(effort) + c.reset)

    style = dig(data, "output_style", "name")
    if style and str(style).lower() != "default":
        parts.append(c.blue + "style:" + str(style) + c.reset)

    if dig(data, "thinking", "enabled") is True:
        parts.append(c.magenta + "thinking" + c.reset)

    if cfg.get("rate_limits", True):
        five = dig(data, "rate_limits", "five_hour", "used_percentage")
        seven = dig(data, "rate_limits", "seven_day", "used_percentage")
        bits = []
        if five != "":
            bits.append("5h:%d%%" % as_int(five))
        if seven != "":
            bits.append("7d:%d%%" % as_int(seven))
        if bits:
            parts.append(c.yellow + " ".join(bits) + c.reset)

    pr_num = dig(data, "pr", "number")
    if pr_num:
        state = dig(data, "pr", "review_state")
        parts.append(c.green + "PR#" + str(pr_num) + (("(" + str(state) + ")") if state else "") + c.reset)

    vim = dig(data, "vim", "mode")
    if vim:
        parts.append(c.white + "[" + str(vim) + "]" + c.reset)

    ram = ram_segment(c, cfg)
    if ram:
        parts.append(ram)

    if cfg.get("relay", True) and relay_present(cwd):
        parts.append(c.dim + icon(cfg, "relay") + "relay" + c.reset)

    session_name = dig(data, "session_name")
    if session_name:
        parts.append(c.dim + '"' + str(session_name) + '"' + c.reset)

    if cfg.get("session_id", False):
        sid = str(dig(data, "session_id") or "")
        if sid:
            parts.append(c.dim + "#" + sid[:8] + c.reset)

    clock = clock_segment(c, cfg)
    if clock:
        parts.append(clock)

    return join(c, cfg, parts)


# --------------------------------------------------------------------------------------
# Profile: agy (Antigravity)
# --------------------------------------------------------------------------------------

def render_agy(data: dict, cfg: dict) -> str:
    """agy sends different field names to Claude Code. This is a sibling, not a copy.
    Layout follows the agy line the user already had; the git detail, quota, relay and
    clock come across from the Claude line."""
    c = C(cfg.get("color", True))
    cwd = dig(data, "cwd") or dig(data, "workspace", "current_dir")

    parts = []

    # Brand mark, so an agy pane is never mistaken for a Claude Code pane.
    if cfg.get("icons", True):
        parts.append(c.neon_blue + ICONS["brand_l"] + c.neon_green + ICONS["brand_r"] +
                     " " + c.white + c.bold + "agy" + c.reset)
    else:
        parts.append(c.white + c.bold + "agy" + c.reset)

    state = str(dig(data, "agent_state") or dig(data, "execution_mode") or "").lower()
    if state:
        label, col = {
            "working": (icon(cfg, "bolt") + "working", c.green),
            "thinking": (icon(cfg, "brain") + "thinking", c.cyan),
            "idle": (icon(cfg, "circle") + "idle", c.gray),
        }.get(state, (state, c.gray))
        parts.append(col + label + c.reset)

    model = dig(data, "model", "display_name") or dig(data, "model", "id")
    if model:
        effort = dig(data, "model", "effort")
        parts.append(c.green + icon(cfg, "brain") + str(model) +
                     ((" (" + str(effort) + ")") if effort else "") + c.reset)

    git = {"branch": str(dig(data, "vcs", "branch") or ""), "staged": 0, "unstaged": 0,
           "untracked": 0, "ahead": 0, "behind": 0}
    if cfg.get("git", True):
        found = git_facts(cwd)
        found["branch"] = git["branch"] or found["branch"]
        git = found

    if cwd:
        parts.append(c.neon_blue + icon(cfg, "folder") + os.path.basename(cwd.rstrip("/\\")) + c.reset)
    seg = git_segment(c, cfg, git, "", "", c.yellow)
    if seg:
        parts.append(seg)

    cw = data.get("context_window") if isinstance(data.get("context_window"), dict) else {}
    if cw:
        usage = cw.get("current_usage") if isinstance(cw.get("current_usage"), dict) else {}
        cached = as_int(usage.get("cache_read_input_tokens"))
        used = (as_int(usage.get("input_tokens")) + cached +
                as_int(usage.get("cache_creation_input_tokens")))
        if used == 0:
            used = as_int(cw.get("total_input_tokens"))
        max_tokens = as_int(cw.get("context_window_size")) or 1_048_576
        pct = float(as_int(cw.get("used_percentage")))
        parts.append(context_segment(c, cfg, used, max_tokens, pct))
        loud = cached_segment(c, cfg, cached)
        if loud:
            parts.append(loud)

    # Quota: agy sends {pool_name: {remaining_fraction, ...}}. Show the BINDING pool —
    # the one with least left — because that is the one that will stop the session.
    quota = data.get("quota")
    if isinstance(quota, dict) and quota:
        fractions = [v.get("remaining_fraction") for v in quota.values()
                     if isinstance(v, dict) and isinstance(v.get("remaining_fraction"), (int, float))]
        if fractions:
            q = int(round(min(fractions) * 100))
            col = c.red if q <= 15 else (c.yellow if q <= 40 else c.green)
            parts.append(col + "q " + str(q) + "%" + c.reset)

    ram = ram_segment(c, cfg)
    if ram:
        parts.append(ram)

    if cfg.get("relay", True) and relay_present(cwd):
        parts.append(c.dim + icon(cfg, "relay") + "relay" + c.reset)

    if cfg.get("session_id", False):
        sid = str(dig(data, "session_id") or "")
        if sid:
            parts.append(c.dim + "#" + sid[:8] + c.reset)

    clock = clock_segment(c, cfg)
    if clock:
        parts.append(clock)

    return join(c, cfg, parts)


RENDERERS = {"claude": render_claude, "agy": render_agy}


# --------------------------------------------------------------------------------------
# Install / check
# --------------------------------------------------------------------------------------

INSTALL_DIR = Path.home() / ".caddis"
INSTALLED_SCRIPT = INSTALL_DIR / "statusline.py"

HOST_SETTINGS = {
    "claude": Path.home() / ".claude" / "settings.json",
    "agy": Path.home() / ".gemini" / "antigravity-cli" / "settings.json",
}


def python_command() -> str:
    """The interpreter NAME to write into settings — not an absolute path.

    Both hosts run the status-line command through a shell that inherits PATH, so a
    name survives a Python upgrade that moves the install directory. An absolute
    venv path would not.
    """
    for candidate in ("python", "python3"):
        if shutil.which(candidate):
            return candidate
    return "python"


def install(hosts, dry_run: bool = False) -> int:
    INSTALL_DIR.mkdir(parents=True, exist_ok=True)
    src = Path(__file__).resolve()

    # Copy the renderer to a STABLE path. Pointing settings at the plugin cache
    # (~/.claude/plugins/cache/caddis/caddis/<version>/) breaks on every upgrade,
    # because the version is in the path.
    if not dry_run and src != INSTALLED_SCRIPT.resolve():
        shutil.copyfile(str(src), str(INSTALLED_SCRIPT))
    print("renderer -> %s" % INSTALLED_SCRIPT)

    if not CONFIG_PATH.exists():
        if not dry_run:
            CONFIG_PATH.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
        print("config   -> %s (created)" % CONFIG_PATH)
    else:
        print("config   -> %s (kept, not overwritten)" % CONFIG_PATH)

    py = python_command()
    failures = 0
    for host in hosts:
        settings = HOST_SETTINGS[host]
        # QUOTING DIFFERS BY HOST, and getting it wrong breaks the line silently.
        #
        # Claude Code runs its statusLine command through a SHELL, so a quoted path is
        # correct and a path containing spaces works.
        #
        # agy does NOT. It splits the string itself, so quotes survive as literal path
        # characters and the result is resolved against the session cwd. Observed live
        # 2026-08-27: agy reported it could not open a file whose path was the session
        # cwd with the quoted absolute path appended inside it. The user own working agy
        # line had always been unquoted; mine was not.
        #
        # Consequence to be honest about: an agy install whose home contains a space
        # cannot be expressed this way. Detect it and say so, rather than writing a
        # command that fails at render time with a confusing message.
        target = str(INSTALLED_SCRIPT)
        if host == "agy":
            if " " in target:
                print("  !! agy    home path contains a space (%s)." % target)
                print("            agy does not parse statusLine through a shell, so the path")
                print("            cannot be quoted. Wire agy statusLine by hand. Skipped.")
                failures += 1
                continue
            command = "%s %s --profile %s" % (py, target, host)
        else:
            command = '%s "%s" --profile %s' % (py, target, host)
        try:
            failures += wire_host(host, settings, command, dry_run)
        except Exception as exc:  # never leave a half-written settings file unexplained
            print("  !! %s: %s" % (host, exc))
            failures += 1
    return failures


def wire_host(host: str, settings_path: Path, command: str, dry_run: bool) -> int:
    if not settings_path.parent.exists():
        print("  -- %-6s not installed (%s missing) — skipped" % (host, settings_path.parent))
        return 0

    data = {}
    if settings_path.exists():
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception as exc:
            print("  !! %s: %s is not valid JSON (%s) — refusing to write" % (host, settings_path, exc))
            return 1
        if not isinstance(data, dict):
            print("  !! %s: %s is not a JSON object — refusing to write" % (host, settings_path))
            return 1

    entry = {"type": "command", "command": command}
    if host == "agy":
        entry["enabled"] = True  # agy ignores a statusLine block without this

    if data.get("statusLine") == entry:
        print("  ok %-6s already wired" % host)
        return 0

    if not dry_run:
        if settings_path.exists():
            backup = settings_path.with_suffix(settings_path.suffix + ".bak-caddis-statusline")
            shutil.copyfile(str(settings_path), str(backup))
        data["statusLine"] = entry
        settings_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("  ok %-6s wired -> %s" % (host, settings_path))
    return 0


def check() -> int:
    print("renderer: %s %s" % (INSTALLED_SCRIPT, "(present)" if INSTALLED_SCRIPT.exists() else "(MISSING)"))
    print("config:   %s %s" % (CONFIG_PATH, "(present)" if CONFIG_PATH.exists() else "(defaults)"))
    bad = 0
    for host, settings_path in HOST_SETTINGS.items():
        if not settings_path.exists():
            print("  -- %-6s %s (not installed)" % (host, settings_path))
            continue
        try:
            data = json.loads(settings_path.read_text(encoding="utf-8"))
        except Exception:
            print("  !! %-6s %s is not valid JSON" % (host, settings_path))
            bad += 1
            continue
        entry = data.get("statusLine")
        if not isinstance(entry, dict):
            print("  !! %-6s no statusLine configured" % host)
            bad += 1
            continue
        cmd = str(entry.get("command", ""))
        if "statusline.py" in cmd and "--profile " + host in cmd:
            print("  ok %-6s %s" % (host, cmd))
        else:
            print("  !! %-6s points elsewhere: %s" % (host, cmd))
            bad += 1
    return bad


SAMPLES = {
    "claude": {
        "cwd": os.getcwd(),
        "session_id": "a1b2c3d4-0000-0000-0000-000000000000",
        "version": "2.1.239",
        "model": {"display_name": "Opus 5 (1M context)"},
        "workspace": {"current_dir": os.getcwd(), "repo": {"owner": "saajunaid", "name": "caddis"}},
        "output_style": {"name": "Plain"},
        "effort": {"level": "high"},
        "thinking": {"enabled": True},
        "context_window": {
            "context_window_size": 1000000,
            "total_input_tokens": 412000,
            "current_usage": {"input_tokens": 12000, "cache_read_input_tokens": 386000,
                              "cache_creation_input_tokens": 14000, "output_tokens": 3100},
            "used_percentage": 41.2,
        },
        "rate_limits": {"five_hour": {"used_percentage": 12}, "seven_day": {"used_percentage": 40}},
    },
    "agy": {
        "cwd": os.getcwd(),
        "session_id": "9f8e7d6c-0000-0000-0000-000000000000",
        "agent_state": "idle",
        "model": {"display_name": "Gemini 3.6 Flash (High)", "effort": "high"},
        "workspace": {"current_dir": os.getcwd()},
        "context_window": {
            "context_window_size": 1048576,
            "total_input_tokens": 48500,
            "current_usage": {"input_tokens": 8500, "cache_read_input_tokens": 40000},
            "used_percentage": 4.6,
        },
        "quota": {"gemini": {"remaining_fraction": 0.87}, "claude_gpt": {"remaining_fraction": 0.62}},
    },
}


# --------------------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="caddis status line — one renderer, every host.")
    parser.add_argument("--profile", choices=sorted(RENDERERS), default="claude",
                        help="which host's status JSON to expect on stdin")
    parser.add_argument("--install", action="store_true", help="wire the status line into the host settings")
    parser.add_argument("--host", choices=["claude", "agy", "both"], default="both",
                        help="with --install: which host(s) to wire")
    parser.add_argument("--check", action="store_true", help="report what is wired, change nothing")
    parser.add_argument("--sample", action="store_true", help="render a fake payload (preview / test)")
    parser.add_argument("--dry-run", action="store_true", help="with --install: print, write nothing")
    parser.add_argument("--no-color", action="store_true", help="render without ANSI colour")
    args = parser.parse_args(argv)

    # The line is Unicode. On Windows the default cp1252 stdout raises on ◆/⎇/█.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    if args.install:
        hosts = ["claude", "agy"] if args.host == "both" else [args.host]
        return 1 if install(hosts, args.dry_run) else 0

    if args.check:
        return 1 if check() else 0

    cfg = load_config()
    if args.no_color:
        cfg["color"] = False

    if args.sample:
        data = SAMPLES[args.profile]
    else:
        try:
            raw = sys.stdin.read()
        except Exception:
            raw = ""
        start = raw.find("{")  # strip a UTF-8 BOM or any leading noise
        try:
            data = json.loads(raw[start:]) if start >= 0 else {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}

    try:
        line = RENDERERS[args.profile](data, cfg)
    except Exception:
        # A status line must never break the host. Degrade to the directory name.
        line = os.path.basename(os.getcwd())

    print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
