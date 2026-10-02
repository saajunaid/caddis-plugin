"""Local, independent workstream relays with compare-and-swap writes."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    from caddis_file_lock import atomic_write, locked_path
    from caddis_frontmatter import parse, split_document
except ModuleNotFoundError as exc:
    if exc.name not in {"caddis_file_lock", "caddis_frontmatter"}:
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    from caddis_file_lock import atomic_write, locked_path
    from caddis_frontmatter import parse, split_document


_NAME = re.compile(r"(?:[a-z0-9][a-z0-9_-]{0,99}|branch(?:\.[a-z0-9_-]+)+(?:\+[0-9a-f]{12})?)\Z")
_CLEAN_BRANCH = re.compile(r"[a-z0-9_-]+(?:/[a-z0-9_-]+)*\Z")
_PLAIN_NAME = re.compile(r"[a-z0-9][a-z0-9_-]{0,99}\Z")
_BAD_REF = re.compile(r"[\x00-\x20\x7f~^:?*\[\\]")
_NEXT = re.compile(r"^## Next step[^\n]*\n(.*?)(?=^## |\Z)", re.MULTILINE | re.DOTALL)
_MAX_INDEX = 800
_INDEX_MARKER = "<!-- caddis-workstream-index-v1 -->\n"


@dataclass(frozen=True)
class WriteResult:
    status: str
    content_hash: str | None
    diff: str = ""


def _name(value: str) -> str:
    if (not isinstance(value, str) or not _NAME.fullmatch(value)
            or value.upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}):
        raise ValueError("workstream name must be a safe flat name")
    return value


def _plain_name(value: str) -> str:
    if not isinstance(value, str):
        raise TypeError("plan or suggestion must be text")
    name = _name(value.lower())
    if not _PLAIN_NAME.fullmatch(name):
        raise ValueError("plan or suggestion may not use the branch namespace")
    return name


def _artifact(root: Path) -> Path:
    project = Path(root).resolve()
    artifact = Path(root) / ".caddis"
    if not artifact.resolve().is_relative_to(project) or artifact.is_symlink():
        raise ValueError("artifact root escapes project")
    return artifact


def _branch(value: str) -> str:
    if not isinstance(value, str) or not value or len(value.encode("utf-8")) > 100 or value.startswith("-"):
        raise ValueError("invalid branch name")
    if (_BAD_REF.search(value) or value == "@" or "@{" in value or ".." in value
            or "//" in value or value.startswith("/") or value.endswith(("/", "."))
            or any(part.startswith(".") or part.endswith((".", ".lock")) for part in value.split("/"))):
        raise ValueError("invalid Git branch name")
    return value


def resolve_workstream(
    plan_slug: str | None, branch: str | None, default_branch: str | None,
    suggested_name: str | None,
) -> str | None:
    """Select the explicit plan, branch, or accepted suggestion, in that order.

    Branch names stay readable for ``/catchup <name>``: ``feat/x`` becomes
    ``branch.feat.x``. A branch with any other character (upper case, dots) is
    slugged and gets ``+`` and 12 hex digits of its SHA-256. A slugged name never
    equals a clean one (clean names contain no ``+``); two slugged names collide
    only if their 48-bit digests do. A branch can never collide
    with a plan/suggested name because those cannot contain the reserved ``.``.
    """
    if plan_slug:
        return _plain_name(plan_slug)
    if branch:
        _branch(branch)
        if default_branch is not None:
            _branch(default_branch)
        if branch != default_branch:
            return _branch_name(branch)
    return _plain_name(suggested_name) if suggested_name else None


def _branch_name(branch: str) -> str:
    if _CLEAN_BRANCH.fullmatch(branch):
        return _name("branch." + branch.replace("/", "."))
    parts = (re.sub(r"[^a-z0-9_-]+", "-", part.lower()).strip("-") or "x" for part in branch.split("/"))
    digest = hashlib.sha256(branch.encode("utf-8")).hexdigest()[:12]
    return _name("branch." + ".".join(parts) + "+" + digest)


def _path(root: Path, name: str) -> tuple[Path, Path]:
    artifact = _artifact(root)
    return artifact, artifact / "relay" / (_name(name) + ".md")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_relay(root: Path, name: str) -> tuple[str, str | None]:
    artifact, path = _path(root, name)
    if not path.resolve().is_relative_to(artifact.resolve()) or path.is_symlink():
        raise ValueError("relay path escapes artifact root")
    try:
        text = path.read_bytes().decode("utf-8")
    except FileNotFoundError:
        return "", None
    return text, _hash(text)


def _validate_relay(name: str, text: str) -> None:
    if not isinstance(text, str) or not text.startswith("---\n"):
        raise ValueError("relay requires frontmatter")
    if split_document(text)[1] == text:  # no closing "---" line
        raise ValueError("relay requires complete frontmatter")
    metadata = parse(text)
    if metadata.get("type") != "relay" or metadata.get("workstream") != name:
        raise ValueError("relay type/workstream mismatch")
    for field in ("branch", "session_id"):
        if not isinstance(metadata.get(field), str) or not metadata[field]:
            raise ValueError(f"relay requires {field}")
    # A branch-only workstream has no plan: the key must exist, but may be empty or "none".
    # The shared reader turns an empty "plan:" into {}.
    plan = metadata.get("plan")
    if not (isinstance(plan, str) or plan == {}):
        raise ValueError("relay requires plan (empty when no plan)")
    generated = metadata.get("generated")
    if not isinstance(generated, dict) or not isinstance(generated.get("at"), str) or not generated["at"]:
        raise ValueError("relay requires generated.at")
    try:
        datetime.fromisoformat(generated["at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("relay requires ISO generated.at") from exc


def write_relay(root: Path, name: str, text: str, expected_hash: str | None) -> WriteResult:
    """Return an explicit blocked result on conflict; never overwrite that file."""
    artifact, path = _path(root, name)
    _validate_relay(name, text)
    if expected_hash is not None and not re.fullmatch(r"[0-9a-f]{64}", expected_hash):
        raise ValueError("expected_hash must be a SHA-256 hex digest or None")
    with locked_path(path, root=artifact):
        try:
            current, actual_hash = read_relay(root, name)
        except (UnicodeDecodeError, IsADirectoryError, PermissionError):
            # Unreadable existing relay: never overwrite what we cannot show the caller.
            return WriteResult("blocked", None, "Existing relay is unreadable; it was left untouched.")
        if actual_hash != expected_hash:
            diff = "".join(difflib.unified_diff(
                current.splitlines(keepends=True), text.splitlines(keepends=True),
                fromfile="current relay", tofile="caller relay",
            ))
            if not diff:
                diff = "Content is identical, but the expected version does not match."
            return WriteResult("blocked", actual_hash, diff)
        atomic_write(path, text, root=artifact)
        return WriteResult("written", _hash(text))


def _free_backup(path: Path) -> Path:
    """``path`` if unused, else the first free ``<stem>.<n><suffix>``: a backup never overwrites one."""
    if not os.path.lexists(path):
        return path
    for n in range(1, 1000):
        candidate = path.with_name(f"{path.stem}.{n}{path.suffix}")
        if not os.path.lexists(candidate):
            return candidate
    raise ValueError(f"too many backups next to {path.name}")


def _header_text(meta: dict) -> str:
    """Relay header lines in the shape caddis_frontmatter.parse reads back: scalars, one nested
    map or one list per key. Every value is folded to one line, so no value can add a field."""
    def flat(value: object) -> str:
        return " ".join(str(value).split())

    lines = []
    for key, value in meta.items():
        if isinstance(value, dict):
            lines.append(f"{key}:")
            lines.extend(f"  {sub}: {flat(val)}" for sub, val in value.items())
        elif isinstance(value, list):
            lines.append(f"{key}:")
            lines.extend(f"  - {flat(item)}" for item in value)
        else:
            lines.append(f"{key}: {flat(value)}")
    return "\n".join(lines) + "\n"


def _single_line(text: str, limit: int) -> str:
    clean = " ".join(text.split())
    return clean if len(clean) <= limit else clean[:limit - 1].rstrip() + "…"


def _next_step(text: str) -> str:
    match = _NEXT.search(text)
    if not match:
        return "next step unrecorded"
    return _single_line(match.group(1), 120) or "next step unrecorded"


def _age(when: datetime, now: datetime) -> str:
    seconds = max(0, int((now - when).total_seconds()))
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def render_index(root: Path, session_id: str | None, branch: str | None) -> str:
    """Write and return the bounded startup index from current local files."""
    artifact = _artifact(root)
    index = artifact / "relay.md"
    now = datetime.now(timezone.utc)
    if index.is_symlink():  # locked_path refuses this too; stated here so the rule is local
        raise ValueError("refusing symlinked relay index")
    with locked_path(index, root=artifact):
        if index.exists() and not index.read_text(encoding="utf-8-sig").startswith(_INDEX_MARKER):
            raise ValueError("legacy relay.md must be migrated before index generation")
        rows: list[tuple[float, str]] = []
        claimed_sessions: set[str] = set()
        directory = artifact / "relay"
        if directory.exists() and not directory.resolve().is_relative_to(artifact.resolve()):
            raise ValueError("relay directory escapes artifact root")
        for path in directory.glob("*.md") if directory.is_dir() else ():
            if path.is_symlink():
                continue
            try:
                name = _name(path.stem)
                content, _ = read_relay(root, name)
                meta = parse(content)
                if meta.get("type") != "relay" or meta.get("workstream") != name:
                    continue
                generated = meta.get("generated")
                at = datetime.fromisoformat(generated["at"].replace("Z", "+00:00"))
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                claimed_sessions.add(str(meta.get("session_id", "")))
                label = _single_line(name, 80)
                branch_label = _single_line(str(meta.get("branch", "?")), 50)
                rows.append((at.timestamp(), f"- {label} ({branch_label}, {_age(at, now)}): {_next_step(content)}"))
            except (ValueError, KeyError, TypeError, AttributeError, OSError, UnicodeError):
                continue
        unnamed: list[tuple[datetime, str, str, str]] = []
        states = artifact / "session-state"
        if states.exists() and not states.resolve().is_relative_to(artifact.resolve()):
            raise ValueError("session-state directory escapes artifact root")
        for path in states.glob("*.md") if states.is_dir() else ():
            if path.is_symlink() or path.stem in claimed_sessions:
                continue
            try:
                modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
                if (now - modified).total_seconds() > 7 * 86400:
                    continue
                content = path.read_text(encoding="utf-8")
                request = re.search(r"^## Last thing you asked\s*\n\s*>\s*(.+)$", content, re.MULTILINE)
                state_branch = re.search(r"\*\*Branch:\*\*[ \t]*([^·\n]+)", content)
                label = _single_line(path.stem, 60)
                # A system notice (e.g. "<task-notification>") is not something the user asked.
                asked = request.group(1).strip() if request else ""
                note = _single_line(asked, 80) if asked and not asked.startswith("<") else "recent session"
                branch_label = _single_line(state_branch.group(1), 40) if state_branch else "unknown branch"
                if session_id and path.stem == session_id:
                    rows.append((modified.timestamp(), f"- this session, no relay yet ({branch_label}): {note}"))
                else:
                    unnamed.append((modified, label, branch_label, note))
            except (OSError, UnicodeError):
                continue
        if unnamed:
            # One line for every other session without a relay: a forked, peer or never-handed-off
            # session is repeated text at every session start and buries the real workstreams.
            unnamed.sort(key=lambda item: (-item[0].timestamp(), item[1]))
            newest, label, _branch_label, note = unnamed[0]
            count = len(unnamed)
            noun = "session" if count == 1 else "sessions"
            rows.append((newest.timestamp(),
                         f"- {count} other {noun} without a relay (newest {label}, {_age(newest, now)}): "
                         f"{note}; see .caddis/session-state/"))
        rows.sort(key=lambda item: (-item[0], item[1]))
        heading = _INDEX_MARKER + "# Workstream index\n"
        if session_id or branch:
            heading += f"Session: {_single_line(session_id or '?', 50)} · branch: {_single_line(branch or '?', 50)}\n"
        prompt = "\nRun /catchup <name> to read one workstream.\n"
        selected: list[str] = []
        for _, row in rows:
            omitted = len(rows) - len(selected) - 1
            suffix = f"… {omitted} more omitted.\n" if omitted else ""
            candidate = heading + "\n" + "\n".join(selected + [row]) + "\n" + suffix + prompt
            if len(candidate) > _MAX_INDEX:
                break
            selected.append(row)
        omitted = len(rows) - len(selected)
        body = "\n".join(selected) if selected else ("No workstream fits the budget." if rows else "No named workstreams.")
        suffix = f"\n… {omitted} more omitted." if omitted else ""
        result = heading + "\n" + body + suffix + prompt
        atomic_write(index, result, root=artifact)
        return result


class MigrationReport(dict):
    """Report describing the outcome of a legacy migration."""

    @property
    def status(self) -> str:
        return self["status"]

    @property
    def migrated(self) -> list[str]:
        return self["migrated"]

    @property
    def conflicts(self) -> list[str]:
        return self["conflicts"]

    @property
    def backups(self) -> list[str]:
        return self["backups"]


def migrate_legacy(root: Path) -> MigrationReport:
    """Run the locked migration, then make sure an index exists when there was nothing to do.

    A previous run (or a racing session) may have removed the legacy files and then failed
    to write the index. render_index takes the index lock itself, so this check runs here,
    after the migration has released that lock.
    """
    report = _migrate_legacy_locked(root)
    if report.status == "clean":
        artifact = _artifact(root)
        relay_dir = artifact / "relay"
        if (not os.path.lexists(artifact / "relay.md") and relay_dir.is_dir()
                and any(relay_dir.glob("*.md"))):
            render_index(root, None, None)
    return report


def _migrate_legacy_locked(root: Path) -> MigrationReport:
    """Migrate legacy workstreams.json and single relay.md into per-topic relays.

    Locked and read-once. Leaves local .bak backups of migrated files.
    Aborts on conflicting target relays and preserves the old relay until all imports validate.
    """
    artifact = _artifact(root)
    legacy_ws = artifact / "workstreams.json"
    index_file = artifact / "relay.md"
    relay_dir = artifact / "relay"

    has_legacy_ws = legacy_ws.is_file() and not legacy_ws.is_symlink()
    has_legacy_relay = False
    if index_file.is_file() and not index_file.is_symlink():
        try:
            head = index_file.read_text(encoding="utf-8-sig", errors="ignore")
            has_legacy_relay = not head.startswith(_INDEX_MARKER)
        except OSError:
            has_legacy_relay = False

    if not has_legacy_ws and not has_legacy_relay:
        return MigrationReport(status="clean", migrated=[], conflicts=[], backups=[])

    with locked_path(index_file, root=artifact):
        # Re-check within lock
        has_legacy_ws = legacy_ws.is_file() and not legacy_ws.is_symlink()
        has_legacy_relay = False
        if index_file.is_file() and not index_file.is_symlink():
            try:
                head = index_file.read_text(encoding="utf-8-sig", errors="ignore")
                has_legacy_relay = not head.startswith(_INDEX_MARKER)
            except OSError:
                has_legacy_relay = False

        if not has_legacy_ws and not has_legacy_relay:
            return MigrationReport(status="clean", migrated=[], conflicts=[], backups=[])

        candidates: dict[str, str] = {}
        conflicts: list[str] = []

        # 1. Process legacy relay.md
        if has_legacy_relay:
            try:
                raw_relay = index_file.read_text(encoding="utf-8-sig")  # a BOM must not hide the header
            except UnicodeDecodeError:
                # Report, never guess: a lossy decode would migrate damaged text.
                return MigrationReport(status="conflict", migrated=[],
                                       conflicts=["legacy-relay-not-utf8"], backups=[])
            relay_meta = parse(raw_relay)
            relay_name = relay_meta.get("workstream")
            if not relay_name:
                plan_val = relay_meta.get("plan")
                if isinstance(plan_val, str) and plan_val:
                    relay_name = Path(plan_val.replace("\\", "/")).name.removesuffix(".md")
                else:
                    relay_name = "legacy"
            try:
                relay_name = _name(str(relay_name).lower())
            except ValueError:
                relay_name = "legacy"

            candidate_text = raw_relay
            # No header, or an opening --- with no closing one: keep the whole file as the body.
            header_closed = split_document(candidate_text)[1] != candidate_text
            if not candidate_text.startswith("---\n") or not header_closed:
                now_iso = datetime.now(timezone.utc).isoformat()
                candidate_text = (
                    f"---\ntype: relay\nworkstream: {relay_name}\nbranch: main\n"
                    f"session_id: legacy-migrated\nplan:\ngenerated:\n  at: {now_iso}\n---\n\n"
                    f"# Relay — {relay_name}\n\n## Next step (exact)\n{raw_relay}\n"
                )
            else:
                meta = parse(candidate_text)
                modified = False
                if meta.get("type") != "relay":
                    meta["type"] = "relay"
                    modified = True
                if meta.get("workstream") != relay_name:  # e.g. "Alpha" is stored as alpha.md
                    meta["workstream"] = relay_name
                    modified = True
                if not meta.get("branch"):
                    meta["branch"] = "main"
                    modified = True
                if not meta.get("session_id"):
                    meta["session_id"] = "legacy-migrated"
                    modified = True
                if "plan" not in meta:
                    meta["plan"] = ""
                    modified = True
                if not isinstance(meta.get("generated"), dict) or not meta["generated"].get("at"):
                    # Keep the original time from an inline "{ by: x, at: y }" map; else now.
                    inline = re.search(r"\bat:\s*([0-9][0-9T:.+\-Z]+)", str(meta.get("generated", "")))
                    meta["generated"] = {"at": inline.group(1) if inline else datetime.now(timezone.utc).isoformat()}
                    modified = True
                if modified:
                    # Plain writer: the plugin ships no YAML library, and this runs in user installs.
                    body = split_document(candidate_text)[1].lstrip("\n")
                    candidate_text = "---\n" + _header_text(meta) + "---\n\n" + body

            try:
                _validate_relay(relay_name, candidate_text)
            except Exception as exc:
                return MigrationReport(status="conflict", migrated=[], conflicts=[f"invalid-legacy-relay: {exc}"], backups=[])

            target_path = relay_dir / f"{_name(relay_name)}.md"
            if target_path.is_file() and not target_path.is_symlink():
                # Unreadable bytes compare unequal, so a corrupt target is a conflict, never overwritten.
                existing_text = target_path.read_text(encoding="utf-8", errors="replace")
                if existing_text.strip() != candidate_text.strip():
                    conflicts.append(relay_name)
            if relay_name not in conflicts:
                candidates[relay_name] = candidate_text

        # 2. Process legacy workstreams.json
        if has_legacy_ws:
            try:
                ws_data = json.loads(legacy_ws.read_text(encoding="utf-8-sig"))
            except Exception as exc:
                return MigrationReport(status="conflict", migrated=[], conflicts=[f"invalid-workstreams-json: {exc}"], backups=[])
            if not isinstance(ws_data, dict):
                return MigrationReport(status="conflict", migrated=[], conflicts=["workstreams-json-not-dict"], backups=[])
            if "stack" not in ws_data:
                return MigrationReport(status="conflict", migrated=[],
                                       conflicts=["workstreams-json-has-no-stack"], backups=[])
            stack = ws_data["stack"]
            if not isinstance(stack, list):
                return MigrationReport(status="conflict", migrated=[], conflicts=["workstreams-stack-not-list"], backups=[])

            for frame in stack:
                if not isinstance(frame, dict):
                    continue
                plan = frame.get("plan")
                if plan:
                    stem = Path(str(plan).replace("\\", "/")).name.removesuffix(".md")
                else:
                    stem = "legacy"
                try:
                    frame_name = _name(stem.lower())
                except ValueError:
                    frame_name = "legacy"

                branch = frame.get("branch") or "main"
                session_id = frame.get("session_id") or "legacy-migrated"
                resume = frame.get("resumePointer") or "next step unrecorded"
                pushed = frame.get("pushedAt") or datetime.now(timezone.utc).isoformat()
                try:
                    datetime.fromisoformat(str(pushed).replace("Z", "+00:00"))
                except ValueError:
                    pushed = datetime.now(timezone.utc).isoformat()

                # _header_text folds every value to one line: a newline in workstreams.json
                # must not add or break header fields.
                header = _header_text({"type": "relay", "workstream": frame_name, "branch": str(branch),
                                       "session_id": str(session_id), "plan": str(plan or ""),
                                       "generated": {"at": str(pushed)}})
                candidate_text = (f"---\n{header}---\n\n# Relay — {frame_name}\n\n"
                                  f"## Next step (exact)\n{' '.join(str(resume).split())}\n")
                try:
                    _validate_relay(frame_name, candidate_text)
                except Exception as exc:
                    conflicts.append(f"invalid-frame-{frame_name}: {exc}")
                    continue

                target_path = relay_dir / f"{_name(frame_name)}.md"
                if target_path.is_file() and not target_path.is_symlink():
                    # Unreadable bytes compare unequal, so a corrupt target is a conflict, never overwritten.
                    existing_text = target_path.read_text(encoding="utf-8", errors="replace")
                    if existing_text.strip() != candidate_text.strip():
                        conflicts.append(frame_name)
                if frame_name in candidates and candidates[frame_name].strip() != candidate_text.strip():
                    conflicts.append(frame_name)
                if frame_name not in conflicts:
                    candidates[frame_name] = candidate_text

        # Abort on conflicting target relays
        if conflicts:
            return MigrationReport(status="conflict", migrated=[], conflicts=sorted(set(conflicts)), backups=[])

        # Write candidates
        relay_dir.mkdir(parents=True, exist_ok=True)
        migrated: list[str] = []
        for name, text in candidates.items():
            # Locked compare-and-swap on the target: a session that wrote this relay after the
            # conflict check above wins, and the legacy files are kept for a re-run.
            # Expect "absent": the conflict check above only let absent or identical targets through.
            try:
                current, current_hash = read_relay(root, name)
                if current_hash is not None and current.strip() == text.strip():
                    migrated.append(name)  # already identical: nothing to write
                    continue
                written = write_relay(root, name, text, None).status == "written"
            except (OSError, ValueError) as exc:
                return MigrationReport(status="conflict", migrated=migrated,
                                       conflicts=[f"{name}: cannot write relay ({type(exc).__name__})"],
                                       backups=[])
            if not written:
                return MigrationReport(status="conflict", migrated=migrated,
                                       conflicts=[f"{name}: written by another session during migration"],
                                       backups=[])
            migrated.append(name)

        backups: list[str] = []
        if has_legacy_ws:
            bak_path = _free_backup(artifact / "workstreams.json.bak")
            bak_path.write_bytes(legacy_ws.read_bytes())
            legacy_ws.unlink()
            backups.append(bak_path.name)

        if has_legacy_relay:
            bak_path = _free_backup(artifact / "relay.md.bak")
            bak_path.write_bytes(index_file.read_bytes())
            index_file.unlink()
            backups.append(bak_path.name)

    # Render index outside the lock so render_index can acquire its own lock
    render_index(root, None, None)
    return MigrationReport(status="migrated", migrated=migrated, conflicts=[], backups=backups)


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Workstream relay management")
    sub = parser.add_subparsers(dest="command")

    resolve_p = sub.add_parser("resolve", help="print the workstream name, or nothing")
    resolve_p.add_argument("--plan")
    resolve_p.add_argument("--branch")
    resolve_p.add_argument("--default-branch")
    resolve_p.add_argument("--suggest")

    read_p = sub.add_parser("read")
    read_p.add_argument("name")
    read_p.add_argument("--root", type=Path, default=Path("."))

    hash_p = sub.add_parser("hash", help="print the stored relay's hash, or 'none' when absent")
    hash_p.add_argument("name")
    hash_p.add_argument("--root", type=Path, default=Path("."))

    write_p = sub.add_parser("write")
    write_p.add_argument("name")
    write_p.add_argument("file", type=Path)
    write_p.add_argument("--expected-hash", help="hash from `hash`; 'none' when the relay must not exist yet")
    write_p.add_argument("--root", type=Path, default=Path("."))

    render_p = sub.add_parser("render-index")
    render_p.add_argument("--session-id")
    render_p.add_argument("--branch")
    render_p.add_argument("--root", type=Path, default=Path("."))

    mig_p = sub.add_parser("migrate-legacy")
    mig_p.add_argument("--root", type=Path, default=Path("."))

    args = parser.parse_args(argv)
    if args.command == "resolve":
        name = resolve_workstream(args.plan, args.branch, args.default_branch, args.suggest)
        if name:
            print(name)
        return 0
    if args.command == "read":
        text, _ = read_relay(args.root, args.name)
        sys.stdout.write(text)
        return 0
    elif args.command == "hash":
        print(read_relay(args.root, args.name)[1] or "none")
        return 0
    elif args.command == "write":
        content = args.file.read_text(encoding="utf-8")
        expected = None if args.expected_hash in (None, "none") else args.expected_hash
        res = write_relay(args.root, args.name, content, expected)
        if res.status != "written":
            # The caller must see what changed; nothing was written.
            sys.stdout.write(res.diff + ("\n" if not res.diff.endswith("\n") else ""))
            sys.stderr.write("relay not written: the stored relay changed since you read it (diff above)\n")
            return 1
        print(res.content_hash)
        return 0
    elif args.command == "render-index":
        render_index(args.root, args.session_id, args.branch)
        return 0
    elif args.command == "migrate-legacy":
        report = migrate_legacy(args.root)
        print(f"Migration status: {report.status}")
        for conflict in report.conflicts:
            print(f"  conflict: {conflict}")
        return 0 if report.status in ("clean", "migrated") else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
