"""Fleet handoff rules: session names, acks, the roster and the restart sheet.

Plan: .caddis/plans/fleet-handoff.md (Phase 4). `/caddis:fleet-close` and `/caddis:fleet-open` only call
this script, so every fleet rule lives here and has a test.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit

ACK_FIELDS = ("name", "role", "machine", "folder", "relay", "tasks", "mode", "owns-watchers", "worktrees")
NO_ACK = "no ack"
NO_NEW_SESSION = ("keeps-running", "nothing", NO_ACK)
TASKS_HEADER = "| Old # | Status | Subject |"

_STAMP = re.compile(r"-\d{4}-\d{2}$")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ACK_LINE = re.compile(r"^\s*FLEET-ACK\s+(.*)$", re.MULTILINE)
_PAIR = re.compile(r"([a-z][a-z-]*)=(.*?)(?=\s+[a-z][a-z-]*=|\s*$)")
_SHARED_MARKER = re.compile(r"^Shared checkout:\s*yes\b", re.IGNORECASE | re.MULTILINE)


class AckError(ValueError):
    """An ack that cannot be used; the message names the missing or bad field."""


@dataclass
class Ack:
    name: str
    role: str
    machine: str
    folder: str
    relay: str
    tasks: str
    mode: str
    owns_watchers: bool
    worktrees: str
    prompt: str = ""
    tasks_inline: str = ""


# ---- names ------------------------------------------------------------------------------------

def role_of(name: str) -> str:
    """The name without a trailing `-MMDD-HH`; a name without it is its own role."""
    return _STAMP.sub("", name)


def new_name(role: str, now: datetime) -> str:
    return f"{role}-{now:%m%d}-{now:%H}"


def newest(role: str, names: list[str]) -> str | None:
    """The name of `role` with the largest `MMDD-HH`; a bare `role` ranks lowest.

    Across a year end (`1231-23` vs `0101-00`) this compares wrong; accepted, the roster holds the
    true name.
    """
    pattern = re.compile(r"^" + re.escape(role) + r"-(\d{4}-\d{2})$")
    best: tuple[str, str] | None = None
    for name in names:
        name = name.strip()
        if name == role:
            key = ""
        else:
            m = pattern.match(name)
            if not m:
                continue
            key = m.group(1)
        if best is None or key > best[0]:
            best = (key, name)
    return best[1] if best else None


# ---- acks -------------------------------------------------------------------------------------

def _split_prompt(body: str) -> tuple[str, str]:
    """Pull an inline tasks table (remote sessions) out of the resume prompt."""
    lines = body.splitlines()
    for i, line in enumerate(lines):
        if line.strip() == TASKS_HEADER:
            end = i + 1
            while end < len(lines) and lines[end].strip().startswith("|"):
                end += 1
            table = "\n".join(lines[i:end])
            prompt = "\n".join(lines[:i] + lines[end:])
            return prompt.strip(), table
    return body.strip(), ""


def parse_ack(text: str) -> Ack:
    """Read a `FLEET-ACK` block and the resume prompt after it (all text after the fenced block)."""
    m = _ACK_LINE.search(text)
    if not m:
        raise AckError("no FLEET-ACK line")
    fields = {k: v.strip() for k, v in _PAIR.findall(m.group(1))}
    for key in ACK_FIELDS:
        if not fields.get(key):
            raise AckError(f"missing field: {key}")
    mode = fields["mode"]
    if mode not in ("new", "keeps-running", "nothing") and not re.fullmatch(r"restore-on:\S+", mode):
        raise AckError(f"bad field: mode={mode} (new, keeps-running, restore-on:<machine> or nothing)")
    watchers = fields["owns-watchers"].lower()
    if watchers not in ("yes", "no"):
        raise AckError(f"bad field: owns-watchers={fields['owns-watchers']} (yes or no)")
    if not _SAFE_NAME.match(fields["name"]):
        raise AckError(f"bad field: name={fields['name']}")
    rest = text[m.end():]
    fence = rest.find("```")
    body = rest
    if fence >= 0:  # skip the closing fence line of the FLEET-ACK block
        after = rest[fence:]
        body = after.split("\n", 1)[1] if "\n" in after else ""
    prompt, inline = _split_prompt(body)
    return Ack(
        name=fields["name"], role=fields["role"], machine=fields["machine"], folder=fields["folder"],
        relay=fields["relay"], tasks=fields["tasks"], mode=mode, owns_watchers=watchers == "yes",
        worktrees=fields["worktrees"], prompt=prompt, tasks_inline=inline,
    )


def no_ack(name: str) -> Ack:
    """A roster row for a session that never acked."""
    return Ack(name=name, role=role_of(name), machine="-", folder="-", relay="-", tasks="-", mode=NO_ACK,
               owns_watchers=False, worktrees="-")


# ---- order, roster, sheet ---------------------------------------------------------------------

def _norm_folder(folder: str) -> str:
    return folder.replace("\\", "/").rstrip("/").lower()


def _group(ack: Ack, coord_folder: str | None) -> int:
    """1 owns watchers; 2 coordinator's repo; 3 other repos; 4 restore-on; 5 no new session.

    A session that needs no new session is group 5 even when it owns watchers: its watchers keep running.
    """
    if ack.mode in NO_NEW_SESSION:
        return 5
    if ack.owns_watchers:
        return 1
    if ack.mode.startswith("restore-on:"):
        return 4
    if coord_folder is not None and _norm_folder(ack.folder) == coord_folder:
        return 2
    return 3


def order(acks: list[Ack], coordinator: str) -> list[Ack]:
    coord = next((a for a in acks if a.name == coordinator), None)
    coord_folder = _norm_folder(coord.folder) if coord else None
    return sorted(acks, key=lambda a: (_group(a, coord_folder), a.name != coordinator, a.name))


def _cell(value: str) -> str:
    return value.replace("|", "\\|")


def render_roster(acks: list[Ack], coordinator: str) -> str:
    lines = [
        f"# Fleet roster (coordinator {coordinator})",
        "",
        "| Role | Current name | Machine | Folder | Relay | Tasks file | Mode | Worktrees |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for a in order(acks, coordinator):
        cells = (a.role, a.name, a.machine, a.folder, a.relay, a.tasks, a.mode, a.worktrees)
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def _fenced(text: str) -> str:
    longest = max((len(r) for r in re.findall(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}text\n{text}\n{fence}"


def start_line(ack: Ack, stamp: datetime) -> str:
    """The one line the owner pastes into a new terminal (works in PowerShell and bash): go to the row's folder, start
    claude named for the role at the sheet's hour, with `/caddis:fleet-open <role>` as the first prompt.

    No permission or Remote Control flags: every start reads `defaultMode` and `remoteControlAtStartup` from the
    owner's settings (owner, 16 Oct). caddis starts no process; the owner does (`claude --bg` decided against)."""
    return f'cd "{ack.folder}"; claude --name {new_name(ack.role, stamp)} "/caddis:fleet-open {ack.role}"'


def render_sheet(acks: list[Ack], coordinator: str, stamp: datetime) -> str:
    ordered = order(acks, coordinator)
    coord = next((a for a in acks if a.name == coordinator), None)
    coord_folder = _norm_folder(coord.folder) if coord else None
    lines = [
        f"# Restart sheet (coordinator {coordinator}, {stamp:%Y-%m-%d %H:%M})",
        "",
        "| Order | Role | Start claude in | Start line |",
        "|---|---|---|---|",
    ]
    for i, a in enumerate(ordered, 1):
        where = a.folder if not a.mode.startswith("restore-on:") else f"{a.mode[len('restore-on:'):]}: {a.folder}"
        first = "no new session" if _group(a, coord_folder) == 5 else f"`{start_line(a, stamp)}`"
        lines.append(f"| {i} | {_cell(a.role)} | {_cell(where)} | {first} |")
    for i, a in enumerate(ordered, 1):
        lines += ["", f"### {i}. {a.role}", ""]
        if a.mode == NO_ACK:
            lines.append(f"No ack from {a.name}: run `/caddis:handoff` in that session by hand.")
            continue
        if _group(a, coord_folder) == 5:
            lines.append(f"Mode `{a.mode}`: no new session.")
            lines.append("")
        lines.append(_fenced(a.prompt))
        if a.tasks_inline:
            lines += ["", "Tasks (inline, remote session):", "", a.tasks_inline]
    return "\n".join(lines) + "\n"


# ---- check ------------------------------------------------------------------------------------

def _roster_rows(roster_text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in roster_text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().replace("\\|", "|") for c in re.split(r"(?<!\\)\|", line.strip())[1:-1]]
        if header is None:
            header = cells
            continue
        if all(set(c) <= {"-"} for c in cells):
            continue
        rows.append(dict(zip(header, cells)))
    return rows


def _sheet_prompts(sheet_text: str) -> dict[str, str]:
    """Role -> the text of the first fenced block in its `### <n>. <role>` section."""
    prompts: dict[str, str] = {}
    sections = re.split(r"^### \d+\. ", sheet_text, flags=re.MULTILINE)[1:]
    for section in sections:
        role, _, body = section.partition("\n")
        m = re.search(r"^(`{3,})[^\n]*\n(.*?)\n\1\s*$", body, re.MULTILINE | re.DOTALL)
        prompts[role.strip()] = m.group(2).strip() if m else ""
    return prompts


def _is_shared(folder: str, folder_counts: dict[str, int]) -> bool:
    """Shared when the folder's AGENTS.md says so, or two sessions that restart both work in it."""
    if folder_counts.get(_norm_folder(folder), 0) > 1:
        return True
    try:
        return bool(_SHARED_MARKER.search((Path(folder) / "AGENTS.md").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return False


def check_sheet(sheet_text: str, roster_text: str) -> list[str]:
    rows = [r for r in _roster_rows(roster_text)
            if r.get("Mode") == "new" or r.get("Mode", "").startswith("restore-on:")]
    prompts = _sheet_prompts(sheet_text)
    counts: dict[str, int] = {}
    for r in rows:
        key = _norm_folder(r.get("Folder", ""))
        counts[key] = counts.get(key, 0) + 1
    errors: list[str] = []
    for r in rows:
        role = r.get("Role", "")
        prompt = prompts.get(role, "")
        if not prompt:
            errors.append(f"{role}: no resume prompt on the sheet")
            continue
        tasks = r.get("Tasks file", "none")
        if tasks not in ("none", "-", "") and tasks not in prompt:
            errors.append(f"{role}: the resume prompt does not load {tasks}")
        if "is now" not in prompt:
            errors.append(f"{role}: the resume prompt does not greet peers with `is now`")
        if _is_shared(r.get("Folder", ""), counts) and "origin/main" not in prompt:
            errors.append(f"{role}: shared checkout, but the resume prompt does not say origin/main")
    return errors


# ---- session presence -------------------------------------------------------------------------

def _name_file(session_id: str, root: Path) -> Path:
    """`<artifacts>/session-state/<sid>.name`, the file `whoami` writes."""
    slug = "".join(c for c in session_id if c.isalnum() or c in "-_")[:64]
    if not slug:
        raise ValueError("empty session id")
    try:
        from claudster_config import artifact_root
        art = Path(artifact_root(str(root)))
    except Exception:
        art = root / ".caddis"
    return art / "session-state" / f"{slug}.name"


def session_name(session_id: str, root: Path) -> tuple[str, bool]:
    """The session's display name and whether `whoami` recorded it; else the first 8 characters of the id."""
    try:
        line = _name_file(session_id, root).read_text(encoding="utf-8").split("\n", 1)[0].split("\t")[0].strip()
    except (OSError, UnicodeDecodeError, ValueError):
        line = ""
    return (line, True) if line else (session_id[:8], False)


def whoami(session_id: str, name: str, root: Path) -> Path:
    """Write `<artifacts>/session-state/<sid>.name`: one tab-separated line `name  repo root  branch`."""
    out = _name_file(session_id, root)
    branch = "-"
    for cmd in (["symbolic-ref", "--short", "-q", "HEAD"], ["rev-parse", "--short", "HEAD"]):  # branch, else detached
        proc = subprocess.run(["git", "-C", str(root), *cmd], capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        if proc.returncode == 0 and proc.stdout.strip():
            branch = proc.stdout.strip()
            break
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(f"{name}\t{root}\t{branch}\n", encoding="utf-8")
    return out


# ---- resume block -----------------------------------------------------------------------------

class ResumeError(ValueError):
    """The relay has no usable `## Resume prompt`."""


_RESUME_SECTION = re.compile(r"^## Resume prompt[^\n]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
_FENCE_OPEN = re.compile(r"^(`{3,}|~{3,})[^\n`]*$")


def resume_prompt(relay_text: str) -> str:
    """The text inside the first fenced block of the relay's `## Resume prompt` section, verbatim."""
    m = _RESUME_SECTION.search(relay_text)
    if not m:
        raise ResumeError("relay has no ## Resume prompt section")
    body: list[str] = []
    fence: str | None = None
    for line in m.group(1).splitlines():
        if fence is None:
            opened = _FENCE_OPEN.match(line.strip())
            if opened:
                fence = opened.group(1)
            continue
        if line.strip().startswith(fence) and not line.strip().strip(fence[0]):
            break  # the closing fence
        body.append(line)
    else:
        if fence is None:
            raise ResumeError("## Resume prompt section has no fenced block")
        raise ResumeError("## Resume prompt fenced block is not closed")
    prompt = "\n".join(body).strip("\n")
    if not prompt.strip():
        raise ResumeError("## Resume prompt fenced block is empty")
    return prompt


def shell_arg(text: str) -> str:
    """One word that PowerShell and bash read the same: one line, inside single quotes (no expansion in either).
    A `'` would end the word in bash and a `"` is dropped by Windows PowerShell 5.1, so both become typographic."""
    one_line = " ".join(text.split())
    return "'" + one_line.replace("'", "’").replace('"', "”") + "'"


def render_resume(session: str, session_id: str, workstream: str, prompt: str, role: str, stamp: datetime,
                  fleet_mode: bool = False) -> str:
    """The last output of `/caddis:handoff`. In a fleet close the restart sheet holds the only start line."""
    if fleet_mode:
        start = "Start line: from the restart sheet"
    else:
        start = f"Start line:\nclaude --name {new_name(role, stamp)} {shell_arg(prompt)}"
    return (f"=== RESUME ===\nSession: {session} ({session_id})\nWorkstream: {workstream}\n"
            f"{_fenced(prompt)}\n{start}\n")

# ---- CLI --------------------------------------------------------------------------------------

def _load_acks(fleet_dir: Path) -> list[Ack]:
    acks_dir = fleet_dir / "acks"
    if not acks_dir.is_dir():
        return []
    return [parse_ack(p.read_text(encoding="utf-8")) for p in sorted(acks_dir.glob("*.md"))]


def _resume_block_cli(args: argparse.Namespace) -> int:
    try:
        import caddis_workstreams
    except ModuleNotFoundError as exc:
        if exc.name != "caddis_workstreams":
            raise
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import caddis_workstreams
    root = args.root.resolve()
    try:
        text, digest = caddis_workstreams.read_relay(root, args.name)
        if digest is None:
            raise ResumeError(f"relay {args.name!r} not found")
        prompt = resume_prompt(text)
    except (ValueError, OSError) as exc:  # ResumeError is a ValueError; a bad relay name is one too
        sys.stderr.write(f"resume-block failed: {exc}\n")
        return caddis_exit.BLOCKED
    session, known = session_name(args.session_id, root)
    role = args.role or (role_of(session) if known else args.name)
    if not _SAFE_NAME.match(role):  # the role goes unquoted into the start line
        sys.stderr.write(f"resume-block failed: bad role {role!r}\n")
        return caddis_exit.BLOCKED
    print(render_resume(session, args.session_id, args.name, prompt, role, datetime.now(), args.fleet), end="")
    return caddis_exit.CLEAN


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="caddis_fleet.py", description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("role-of", help="the role of a session name")
    p.add_argument("name")
    p = sub.add_parser("new-name", help="<role>-<MMDD>-<HH> for now, local time")
    p.add_argument("role")
    p = sub.add_parser("newest", help="the newest name of a role")
    p.add_argument("role")
    p.add_argument("--names-file", required=True, type=Path, help="one session name per line")
    ack_p = sub.add_parser("ack", help="acks from closing sessions")
    ack_sub = ack_p.add_subparsers(dest="ack_cmd", required=True)
    p = ack_sub.add_parser("add", help="validate an ack and save it as acks/<name>.md")
    p.add_argument("--dir", required=True, type=Path)
    p.add_argument("--text-file", required=True, type=Path)
    p = sub.add_parser("write", help="write roster.md and restart-sheet.md, print the sheet")
    p.add_argument("--dir", required=True, type=Path)
    p.add_argument("--coordinator", required=True)
    p.add_argument("--no-ack", action="append", default=[], metavar="NAME",
                   help="a session that never acked (repeatable)")
    p = sub.add_parser("check", help="check the restart sheet against the roster")
    p.add_argument("--dir", required=True, type=Path)
    p = sub.add_parser("whoami", help="record this session's name, repo root and branch")
    p.add_argument("--session-id", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--root", default=".", type=Path)
    p = sub.add_parser("resume-block", help="print the session name and the relay's resume prompt (last step of handoff)")
    p.add_argument("--name", required=True, help="the relay's workstream name")
    p.add_argument("--session-id", required=True)
    p.add_argument("--root", default=".", type=Path)
    p.add_argument("--role", help="role for the new session's name (default: the session name's role, else the relay name)")
    p.add_argument("--fleet", action="store_true", help="fleet close: print no start line (the restart sheet has it)")
    args = parser.parse_args(argv)

    if args.cmd == "role-of":
        print(role_of(args.name))
        return caddis_exit.CLEAN
    if args.cmd == "new-name":
        print(new_name(args.role, datetime.now()))
        return caddis_exit.CLEAN
    if args.cmd == "newest":
        try:
            names = args.names_file.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            sys.stderr.write(f"cannot read {args.names_file}: {exc}\n")
            return caddis_exit.NOT_RUN
        found = newest(args.role, names)
        if found is None:
            return caddis_exit.BLOCKED
        print(found)
        return caddis_exit.CLEAN
    if args.cmd == "ack":
        try:
            text = args.text_file.read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"cannot read {args.text_file}: {exc}\n")
            return caddis_exit.NOT_RUN
        try:
            ack = parse_ack(text)
        except AckError as exc:
            print(f"[FLEET] bad ack: {exc}")
            return caddis_exit.BLOCKED
        out = args.dir / "acks" / f"{ack.name}.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"[FLEET] ack saved: {ack.name} ({ack.mode}) -> {out}")
        return caddis_exit.CLEAN
    if args.cmd == "write":
        try:
            acks = _load_acks(args.dir)
        except AckError as exc:
            print(f"[FLEET] bad saved ack: {exc}")
            return caddis_exit.BLOCKED
        known = {a.name for a in acks}
        acks += [no_ack(n) for n in args.no_ack if n not in known]
        if not acks:
            print(f"[FLEET] no acks in {args.dir / 'acks'}")
            return caddis_exit.NOT_RUN
        sheet = render_sheet(acks, args.coordinator, datetime.now())
        args.dir.mkdir(parents=True, exist_ok=True)
        (args.dir / "roster.md").write_text(render_roster(acks, args.coordinator), encoding="utf-8")
        (args.dir / "restart-sheet.md").write_text(sheet, encoding="utf-8")
        print(sheet, end="")
        return caddis_exit.CLEAN
    if args.cmd == "check":
        try:
            sheet = (args.dir / "restart-sheet.md").read_text(encoding="utf-8")
            roster = (args.dir / "roster.md").read_text(encoding="utf-8")
        except OSError as exc:
            sys.stderr.write(f"cannot read the fleet files in {args.dir}: {exc}\n")
            return caddis_exit.NOT_RUN
        errors = check_sheet(sheet, roster)
        for error in errors:
            print(error)
        if errors:
            return caddis_exit.BLOCKED
        print("[FLEET] sheet ok")
        return caddis_exit.CLEAN
    if args.cmd == "resume-block":
        return _resume_block_cli(args)
    # whoami
    try:
        out = whoami(args.session_id, args.name, args.root.resolve())
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"whoami failed: {exc}\n")
        return caddis_exit.NOT_RUN
    print(f"[FLEET] {args.name} -> {out}")
    return caddis_exit.CLEAN


if __name__ == "__main__":
    _reconfig = getattr(sys.stdout, "reconfigure", None)
    if _reconfig:
        try:
            _reconfig(encoding="utf-8")
        except Exception:
            pass
    sys.exit(main())
