#!/usr/bin/env python3
"""caddis /preload-review: how big is what loads before the first prompt?

Reads files only. Measures (estimated tokens, chars / 4):
  user rules       ~/.claude/CLAUDE.md and ~/AGENTS.md, with their @imports
  enabled skills   name + description of every skill in the enabled plugins (plugin cache) and ~/.claude/skills
  MCP server names from ~/.claude.json and <repo>/.mcp.json (names only, never a value)
  per repo         root rules (+ @imports) and the MEMORY.md index = start-up cost;
                   nested CLAUDE.md / AGENTS.md load on demand, so they are reported apart

Secrets: `~/.claude/settings.json` is read for the `enabledPlugins` key only. `~/.claude.json` is read for
server names only. A file that does not parse is reported by error class name, never by message.

CLI: caddis_preload_review.py [--root PATH] [--home PATH] [--json] [--limit-repo-startup N]
                              [--limit-memory N] [--stamp]
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_reconfig = getattr(sys.stdout, "reconfigure", None)
if _reconfig:
    with contextlib.suppress(OSError, ValueError):
        _reconfig(encoding="utf-8")

MAX_IMPORT_DEPTH = 4
# Folders the nested-rules walk never enters.
SKIP_DIRS = frozenset({"node_modules", ".git", ".worktrees", ".venv", "venv", "__pycache__", "dist", "build", ".next"})
RULE_NAMES = ("CLAUDE.md", "AGENTS.md")
_IMPORT_RE = re.compile(r"^\s*@(\S+)")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")


# ── data ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class PluginSkills:
    plugin: str
    version: str
    count: int
    chars: int


@dataclass(frozen=True)
class RepoRow:
    name: str
    rules_chars: int
    memory_index_chars: int
    memory_index_lines: int
    memory_files: int
    memory_chars: int
    nested_files: int
    nested_chars: int
    project_skills: int
    has_mcp_json: bool


@dataclass(frozen=True)
class UserRow:
    rules_chars: int
    skills: list[PluginSkills] = field(default_factory=list)
    mcp: list[str] = field(default_factory=list)
    enabled_known: bool = True


# ── measure ──────────────────────────────────────────────────────────────────


def est_tokens(chars: int) -> int:
    """Token estimate: chars / 4. An estimate only."""
    return round(chars / 4)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _import_target(ref: str, importer: Path, home: Path) -> Path:
    if ref == "~" or ref.startswith(("~/", "~\\")):
        return home / ref[2:]
    target = Path(ref)
    return target if target.is_absolute() else importer.parent / target


def _import_refs(text: str) -> list[str]:
    """`@path` lines outside fenced code blocks."""
    refs: list[str] = []
    fence = ""
    for line in text.splitlines():
        m = _FENCE_RE.match(line)
        if m:
            marker = m.group(1)
            if not fence:
                fence = marker
            elif marker[0] == fence[0] and len(marker) >= len(fence):
                fence = ""
            continue
        if fence:
            continue
        m = _IMPORT_RE.match(line)
        if m:
            refs.append(m.group(1))
    return refs


def rules_chars(path: Path, home: Path, _seen: set[Path] | None = None, _depth: int = 0) -> int:
    """Chars of a rules file plus the files it imports with `@path` (depth 4, each file once)."""
    seen = _seen if _seen is not None else set()
    if _depth > MAX_IMPORT_DEPTH:
        return 0
    try:
        key = path.resolve()
    except OSError:
        return 0
    if key in seen or not path.is_file():
        return 0
    text = _read_text(path)
    if text is None:
        return 0
    seen.add(key)
    total = len(text)
    for ref in _import_refs(text):
        total += rules_chars(_import_target(ref, path, home), home, seen, _depth + 1)
    return total


def _load_json_keys(path: Path) -> tuple[dict | None, str | None]:
    """(parsed object, None), or (None, error class name). Never returns an error message."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, type(e).__name__
    return (data, None) if isinstance(data, dict) else (None, "NotAnObject")


def enabled_plugins(home: Path) -> set[str] | None:
    """`plugin@marketplace` keys set to true in settings.json `enabledPlugins`. None = unknown."""
    data, _err = _load_json_keys(home / ".claude" / "settings.json")
    if data is None:
        return None
    plugins = data.get("enabledPlugins")
    if not isinstance(plugins, dict):
        return None
    return {k for k, v in plugins.items() if v is True}


def _version_key(name: str) -> tuple[int, tuple[int, ...]]:
    """Numeric versions compare as int tuples; anything else sorts below every numeric version."""
    parts = name.split(".")
    if all(p.isdigit() for p in parts):
        return (1, tuple(int(p) for p in parts))
    return (0, ())


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def _skill_chars(skill_md: Path) -> int:
    """len(name) + len(description) from the SKILL.md frontmatter: what the skill list carries."""
    text = _read_text(skill_md)
    if text is None:
        return 0
    m = re.match(r"---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return 0
    fm = m.group(1)
    name = re.search(r"^name:[ \t]*(.*)$", fm, re.MULTILINE)
    desc = re.search(r"^description:[ \t]*(.*?)(?=^[\w-]+:|\Z)", fm, re.DOTALL | re.MULTILINE)
    return len(_strip_quotes(name.group(1)) if name else "") + len(_strip_quotes(desc.group(1)) if desc else "")


def _skills_in(base: Path) -> tuple[int, int]:
    files = sorted(base.glob("skills/*/SKILL.md"))
    return len(files), sum(_skill_chars(f) for f in files)


def skill_listing(home: Path, enabled: set[str] | None) -> list[PluginSkills]:
    """Skills per plugin from the plugin cache (newest version only), then user skills.

    `enabled` None counts every cached plugin. A cache folder is `<marketplace>/<plugin>/<version>`.
    """
    out: list[PluginSkills] = []
    cache = home / ".claude" / "plugins" / "cache"
    if cache.is_dir():
        for market in sorted(p for p in cache.iterdir() if p.is_dir()):
            for plugin in sorted(p for p in market.iterdir() if p.is_dir()):
                if enabled is not None and f"{plugin.name}@{market.name}" not in enabled:
                    continue
                versions = [v for v in plugin.iterdir() if v.is_dir()]
                if not versions:
                    continue
                newest = max(versions, key=lambda v: (_version_key(v.name), v.name))
                count, chars = _skills_in(newest)
                if count:
                    out.append(PluginSkills(plugin.name, newest.name, count, chars))
    user_skills = home / ".claude"
    count, chars = _skills_in(user_skills)
    if count:
        out.append(PluginSkills("user", "", count, chars))
    return out


def _norm(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def mcp_names(home: Path, repo: Path | None) -> list[str]:
    """MCP server names only. A value, URL, argument or env var is never read into the result.

    Sources: `~/.claude.json` `mcpServers` (user), its `projects[*].mcpServers` (the repo's entry, or all of
    them when `repo` is None) and `<repo>/.mcp.json`. A file that does not parse adds `<unreadable: ErrorClass>`.
    """
    names: list[str] = []
    data, err = _load_json_keys(home / ".claude.json")
    if data is None:
        if (home / ".claude.json").exists():
            names.append(f"<unreadable ~/.claude.json: {err}>")
    else:
        servers = data.get("mcpServers")
        if isinstance(servers, dict):
            names += [str(n) for n in servers]
        projects = data.get("projects")
        if isinstance(projects, dict):
            for proj_path, proj in projects.items():
                if repo is not None and _norm(proj_path) != _norm(repo):
                    continue
                if isinstance(proj, dict) and isinstance(proj.get("mcpServers"), dict):
                    label = Path(proj_path).name
                    names += [f"{n} ({label})" for n in proj["mcpServers"]]
    if repo is not None:
        mcp_json = repo / ".mcp.json"
        pdata, perr = _load_json_keys(mcp_json)
        if pdata is None:
            if mcp_json.exists():
                names.append(f"<unreadable .mcp.json: {perr}>")
        elif isinstance(pdata.get("mcpServers"), dict):
            names += [f"{n} (.mcp.json)" for n in pdata["mcpServers"]]
    return list(dict.fromkeys(names))


def project_memory_dir(home: Path, repo: Path) -> Path:
    """`~/.claude/projects/<repo path with every non-alphanumeric char as '-'>/memory`."""
    return home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(repo)) / "memory"


def _top_rule_files(root: Path) -> list[Path]:
    return [root / "CLAUDE.md", root / "AGENTS.md", root / ".claude" / "CLAUDE.md", root / "CLAUDE.local.md"]


def _nested_rules(repo: Path) -> tuple[int, int]:
    files = chars = 0
    for dirpath, dirnames, filenames in os.walk(repo):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        if Path(dirpath) == repo:
            continue
        for fname in filenames:
            # <repo>/.claude/CLAUDE.md is a start-up file (counted in rules_chars), not a nested one
            if fname in RULE_NAMES and Path(dirpath) != repo / ".claude":
                text = _read_text(Path(dirpath) / fname)
                if text is not None:
                    files += 1
                    chars += len(text)
    return files, chars


def scan_repo(home: Path, repo: Path) -> RepoRow:
    seen: set[Path] = set()
    rules = sum(rules_chars(f, home, seen) for f in _top_rule_files(repo))
    mem = project_memory_dir(home, repo)
    index = _read_text(mem / "MEMORY.md") or ""
    others = [f for f in sorted(mem.glob("*.md")) if f.name != "MEMORY.md"] if mem.is_dir() else []
    mem_chars = sum(len(_read_text(f) or "") for f in others)
    nested_files, nested_chars = _nested_rules(repo)
    return RepoRow(
        name=repo.name,
        rules_chars=rules,
        memory_index_chars=len(index),
        memory_index_lines=len(index.splitlines()),
        memory_files=len(others),
        memory_chars=mem_chars,
        nested_files=nested_files,
        nested_chars=nested_chars,
        project_skills=len(list(repo.glob(".claude/skills/*/SKILL.md"))),
        has_mcp_json=(repo / ".mcp.json").is_file(),
    )


def scan_user(home: Path) -> UserRow:
    seen: set[Path] = set()
    rules = sum(rules_chars(f, home, seen) for f in (home / ".claude" / "CLAUDE.md", home / "AGENTS.md"))
    enabled = enabled_plugins(home)
    return UserRow(
        rules_chars=rules,
        skills=skill_listing(home, enabled),
        mcp=mcp_names(home, None),
        enabled_known=enabled is not None,
    )


# ── stamp ────────────────────────────────────────────────────────────────────

STAMP_NAME = ".last-preload-review"


@dataclass(frozen=True)
class Stamp:
    date: dt.date
    plugins: str


def plugins_hash(enabled: set[str] | None) -> str:
    """sha256 hex of the sorted enabled plugin keys; the fixed text `unknown` when the set is unknown."""
    if enabled is None:
        return "unknown"
    return hashlib.sha256("\n".join(sorted(enabled)).encode("utf-8")).hexdigest()


def _stamp_path(repo: Path) -> Path:
    return repo / ".caddis" / STAMP_NAME


def read_stamp(repo: Path) -> Stamp | None:
    """The stamp of `repo`, or None when the file is missing or malformed."""
    text = _read_text(_stamp_path(repo))
    if text is None:
        return None
    fields: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep:
            fields[key.strip()] = value.strip()
    try:
        when = dt.date.fromisoformat(fields["date"])
    except (KeyError, ValueError):
        return None
    plugins = fields.get("plugins", "")
    return Stamp(when, plugins) if plugins else None


def write_stamp(repo: Path, enabled: set[str] | None, today: dt.date) -> None:
    """Write `<repo>/.caddis/.last-preload-review`: two lines, the date and the plugin-set hash."""
    path = _stamp_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"date: {today.isoformat()}\nplugins: {plugins_hash(enabled)}\n", encoding="utf-8", newline="\n")


# ── report ───────────────────────────────────────────────────────────────────

CONTEXT_NOTE = (
    "Exact MCP tool lists, and skills that do not come from the plugin cache, need one /context run in a "
    "session. Compare it with this table."
)


@dataclass(frozen=True)
class Limits:
    repo_startup: int = 8000
    rules_file: int = 6000
    memory_tokens: int = 2000
    memory_lines: int = 200
    plugin_skills: int = 10


def startup_chars(row: RepoRow) -> int:
    return row.rules_chars + row.memory_index_chars


def _sorted_rows(rows: list[RepoRow]) -> list[RepoRow]:
    return sorted(rows, key=lambda r: (-startup_chars(r), r.name))


def cut_candidates(user: UserRow, rows: list[RepoRow], limits: Limits) -> list[str]:
    """Advice lines. Each names one action; the command changes nothing."""
    out: list[str] = []
    if est_tokens(user.rules_chars) > limits.rules_file:
        out.append(
            f"User rules: about {est_tokens(user.rules_chars):,} tokens (limit {limits.rules_file:,}). "
            "Run caddis:claude-md-curator on the user rules."
        )
    for s in user.skills:
        if s.plugin != "caddis" and s.count > limits.plugin_skills:
            action = (
                "Move unused skills out of ~/.claude/skills."
                if s.plugin == "user"
                else "Turn the plugin off if you do not use it."
            )
            out.append(f"Plugin {s.plugin}: {s.count} skills (limit {limits.plugin_skills}). {action}")
    for r in _sorted_rows(rows):
        start = est_tokens(startup_chars(r))
        if start > limits.repo_startup:
            out.append(
                f"{r.name}: start-up about {start:,} tokens (limit {limits.repo_startup:,}). "
                "Run caddis:claude-md-curator on its rules file."
            )
        rules = est_tokens(r.rules_chars)
        if rules > limits.rules_file:
            out.append(
                f"{r.name}: rules about {rules:,} tokens with imports (limit {limits.rules_file:,}). "
                "Move how-to text into a doc that loads on demand."
            )
        index_tokens = est_tokens(r.memory_index_chars)
        if index_tokens > limits.memory_tokens or r.memory_index_lines > limits.memory_lines:
            out.append(
                f"{r.name}: memory index about {index_tokens:,} tokens, {r.memory_index_lines} lines "
                f"(limits {limits.memory_tokens:,} tokens, {limits.memory_lines} lines). Shorten the index lines."
            )
    return out


def _skills_chars(user: UserRow) -> int:
    return sum(s.chars for s in user.skills)


def render_markdown(user: UserRow, rows: list[RepoRow], limits: Limits, root: Path) -> str:
    skills_tokens = est_tokens(_skills_chars(user))
    lines = [
        "# Start-up size (estimates, chars ÷ 4)",
        "",
        f"Root: `{root}`",
        "",
        "## User level (same in every repo)",
        "",
        f"- Rules: about {est_tokens(user.rules_chars):,} tokens (estimate)",
        f"- Skills (name + description): about {skills_tokens:,} tokens, {sum(s.count for s in user.skills)} skills (estimate)",
    ]
    if not user.enabled_known:
        lines.append("- enabledPlugins unknown: counted every cached plugin")
    lines.append(f"- MCP servers (names only): {', '.join(user.mcp) if user.mcp else 'none'}")
    lines.append(f"- User-level total: about {est_tokens(user.rules_chars + _skills_chars(user)):,} tokens (estimate)")
    if user.skills:
        lines += ["", "| plugin | version | skills | tokens (estimate) |", "|---|---|---|---|"]
        lines += [
            f"| {s.plugin} | {s.version or '-'} | {s.count} | {est_tokens(s.chars):,} |"
            for s in sorted(user.skills, key=lambda s: -s.chars)
        ]
    lines += [
        "",
        "## Repos (tokens are estimates)",
        "",
        "START = rules + memory index. Nested files load only when Claude works in that folder.",
        "",
        "| repo | rules | memory index | START | memory files | nested files | nested tokens |",
        "|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r.name} | {est_tokens(r.rules_chars):,} | {est_tokens(r.memory_index_chars):,} "
        f"| {est_tokens(startup_chars(r)):,} | {r.memory_files} | {r.nested_files} | {est_tokens(r.nested_chars):,} |"
        for r in _sorted_rows(rows)
    ]
    candidates = cut_candidates(user, rows, limits)
    lines += ["", "## Cut candidates", ""]
    lines += [f"- {c}" for c in candidates] if candidates else ["none over the limits"]
    lines += ["", CONTEXT_NOTE, ""]
    return "\n".join(lines)


def render_json(user: UserRow, rows: list[RepoRow], limits: Limits) -> str:
    data = {
        "estimate": True,
        "user": {
            "rules_chars": user.rules_chars,
            "rules_tokens": est_tokens(user.rules_chars),
            "skills": [{**asdict(s), "tokens": est_tokens(s.chars)} for s in user.skills],
            "skills_tokens": est_tokens(_skills_chars(user)),
            "mcp": user.mcp,
            "enabled_known": user.enabled_known,
        },
        "repos": [
            {
                **asdict(r),
                "rules_tokens": est_tokens(r.rules_chars),
                "memory_index_tokens": est_tokens(r.memory_index_chars),
                "startup_tokens": est_tokens(startup_chars(r)),
                "nested_tokens": est_tokens(r.nested_chars),
            }
            for r in _sorted_rows(rows)
        ],
        "candidates": cut_candidates(user, rows, limits),
        "limits": asdict(limits),
    }
    return json.dumps(data, indent=2, ensure_ascii=False)


# ── cli ──────────────────────────────────────────────────────────────────────


def today() -> dt.date:
    return dt.datetime.now().astimezone().date()


def find_repo(start: Path) -> Path | None:
    """The nearest folder at or above `start` that holds `.git` (a folder, or a file in a worktree)."""
    for folder in (start, *start.parents):
        if (folder / ".git").exists():
            return folder
    return None


def default_root(cwd: Path) -> Path:
    """Parent of the git repo that holds `cwd`; `cwd` itself when it is not in a repo."""
    repo = find_repo(cwd)
    return repo.parent if repo else cwd


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Show what loads before the first prompt. Reads files only.")
    ap.add_argument("--root", help="folder that holds the repos (default: parent of the current git repo)")
    ap.add_argument("--home", help="home folder to read (default: the user home; tests use a fake one)")
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    ap.add_argument("--limit-repo-startup", type=int, default=Limits.repo_startup, metavar="N")
    ap.add_argument("--limit-memory", type=int, default=Limits.memory_tokens, metavar="N")
    ap.add_argument("--stamp", action="store_true", help="after the report, record the date and the plugin set")
    args = ap.parse_args(argv)

    cwd = Path.cwd()
    home = Path(args.home).expanduser() if args.home else Path.home()
    root = (Path(args.root).expanduser() if args.root else default_root(cwd)).resolve()
    if not root.is_dir():
        print(f"error: root is not a folder: {root}", file=sys.stderr)
        return 2
    limits = Limits(repo_startup=args.limit_repo_startup, memory_tokens=args.limit_memory)

    user = scan_user(home)
    rows = [scan_repo(home, d) for d in sorted(root.iterdir()) if d.is_dir() and not d.name.startswith(".")]
    print(render_json(user, rows, limits) if args.json else render_markdown(user, rows, limits, root))

    if args.stamp:
        repo = find_repo(cwd)
        if repo is None:
            print("no git repo here: stamp not written", file=sys.stderr)
        else:
            write_stamp(repo, enabled_plugins(home), today())
    return 0


if __name__ == "__main__":
    sys.exit(main())
