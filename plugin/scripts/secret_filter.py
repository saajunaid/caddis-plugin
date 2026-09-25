#!/usr/bin/env python3
"""Pre-send secret filter for `oss_review.py`.

Everything `oss_review.py` sends to an external review vendor (DeepSeek/GLM/OpenRouter/etc.)
passes through `filter_diff()` first. It does two independent things, both fail-closed:

1. **Path denylist** — a whole file's diff block is dropped when its path matches a deny glob
   (`.env`, `secrets.yaml`, `id_rsa`, a private key, ...) and no allow glob re-admits it. This
   is silent-by-default: the file simply never reaches the model, and the caller is told which
   paths were excluded so the drop is visible, not invisible.
2. **Content rules** — every hunk line of a file that was NOT dropped is scanned against
   `SECRET_RULES` (AWS keys, GitHub/Slack tokens, JWTs, PEM private keys, `key = "..."`-shaped
   assignments). A hit refuses the ENTIRE review (not just that file) — a secret slipping past
   the path denylist is exactly the case this second layer exists for, and the safe response to
   "something here looks like a credential" is "send nothing", not "guess which part is safe".

Deliberately out of scope, by design (see the plan's "Design (decided)"):
  - Removed-line hits use old-file line numbers and are marked `removed line`.
  - `+++`/`---` file headers never fire because they precede the first hunk.
  - Content rules run only on files the path denylist did NOT already drop; a dropped file's
    block is never scanned (nothing in it reaches the model either way).

Nothing here ever prints a matched secret value: hits are reported as (path, line, rule name)
only. Stdlib-only (`tomllib` needs Python 3.11+, matching the rest of caddis's `.github/tools/`).
"""
from __future__ import annotations

import fnmatch
import re
import subprocess
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

# ── path denylist ─────────────────────────────────────────────────────────────
#
# fnmatch's `*` matches `/` too (it is not a directory-aware glob), which cuts both ways and
# is the reason for the paired entries below:
#   - "*.pem" / "*.key" / "*.pfx" / "*.p12" already match at ANY depth (root or nested) because
#     the leading `*` freely absorbs any prefix, slashes included.
#   - ".env" (a literal, no wildcard) matches ONLY a root ".env" — fnmatch requires an exact
#     whole-string match when there is no wildcard, and "config/.env" is a different string.
#   - "**/.env" matches ONLY a nested path — translated to a regex it requires a literal "/"
#     immediately before ".env", so a root ".env" (no slash anywhere) does NOT match it.
#   - "id_rsa*" / "secrets.*" / "keys.env" are anchored at the start of the string (no leading
#     wildcard), so — like ".env" — they match only at the repo root; "**/id_rsa*" etc. cover
#     the nested case.
# Every root-only pattern therefore needs an explicit "**/" sibling, or a nested secret file
# of that shape is invisible to this filter. Verified live, not assumed — see
# scripts/tests/test_secret_filter.py.
DEFAULT_DENY_GLOBS: list[str] = [
    ".env", ".env.*", "**/.env", "**/.env.*",
    "*.pem", "*.key", "*.pfx", "*.p12",
    "id_rsa*", "**/id_rsa*",
    "secrets.*", "**/secrets.*",
    "keys.env", "**/keys.env",
]

# `.env.example` / `.env.sample` / `.env.template` / `.env.dist` are template files with no
# real values in them and are conventionally committed and reviewed like any other source file.
# Checked BEFORE the deny glob match, so it wins even though ".env.*" would otherwise catch it.
ENV_EXAMPLE = re.compile(r"\.env\.(example|sample|template|dist)$", re.I)

# ── content rules ───────────────────────────────────────────────────────────
#
# Each pattern is checked against the content of each changed line in a kept file.
SECRET_RULES: list[tuple[str, re.Pattern]] = [
    ("private-key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("aws-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36,}\b")),
    ("slack-token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}\b")),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("assignment", re.compile(
        r"(?i)[A-Za-z0-9_]*(password|passwd|secret|api[_-]?key|token)[A-Za-z0-9_]*\s*[:=]\s*['\"](?P<value>[^'\"\s]{8,})['\"]"
    )),
    ("env-assignment", re.compile(
        r"^\s*(?:export\s+)?[A-Za-z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|APIKEY|TOKEN|PRIVATE_KEY)"
        r"[A-Za-z0-9_]*\s*=\s*(?P<value>[^\s'\"#]{8,})", re.I
    )),
]


def _is_placeholder(value: str) -> bool:
    """Exclude obvious template values from both assignment rules."""
    lowered = value.lower()
    return (
        lowered in {"your_key_here", "your-api-key", "changeme", "placeholder", "example"}
        or bool(re.fullmatch(r"x+", lowered))
        or bool(re.fullmatch(r"<[^>]*>", value))
        or bool(re.fullmatch(r"\$\{[^}]*\}", value))
        or bool(re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", value))
        or value.startswith("***")
        or lowered.startswith(("your_", "your-"))
    )


@dataclass
class FilterResult:
    kept_diff: str
    dropped_paths: list[str] = field(default_factory=list)
    hits: list[tuple[str, int, str]] = field(default_factory=list)  # (path, side's line, rule/removed marker)


# A new file block starts at a line beginning "diff --git a/..." (the common, unquoted case)
# or "diff --git "a/..." (git double-quotes a path that needs escaping — spaces alone do NOT
# trigger quoting, but non-ASCII characters, embedded quotes/backslashes, and control
# characters do). Matched at line start only, never mid-line.
_BLOCK_START_RE = re.compile(r'^diff --git (?:"|a/)')

# The common (non-rename) case: "diff --git a/<P> b/<P>" with the OLD and NEW path identical.
# A backreference handles a path containing spaces correctly (the naive "split on ' b/'"
# approach is ambiguous when the path itself contains " b/"-shaped substrings and can't tell
# unquoted-with-a-space apart from a genuine rename without this).
_IDENTICAL_HEADER_RE = re.compile(r'^a/(.+) b/\1$')

# Both sides double-quoted (git always quotes both together, never just one).
_QUOTED_HEADER_RE = re.compile(r'^"((?:[^"\\]|\\.)*)" "((?:[^"\\]|\\.)*)"$')

_HUNK_RE = re.compile(r'^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@')


def _unescape_git_quoted(s: str) -> str:
    """Undo git's C-style quoting: \\", \\\\, \\t, \\n, and \\NNN octal byte escapes.

    git quotes a path by escaping each byte that needs it; multi-byte (UTF-8) characters come
    out as a run of \\NNN octal escapes, one per byte, so the escapes are collected as raw
    bytes and decoded as UTF-8 at the end rather than character-by-character.
    """
    out = bytearray()
    i, n = 0, len(s)
    while i < n:
        c = s[i]
        if c == "\\" and i + 1 < n:
            nxt = s[i + 1]
            if nxt in ('"', "\\"):
                out.append(ord(nxt))
                i += 2
            elif nxt == "n":
                out.append(10)
                i += 2
            elif nxt == "t":
                out.append(9)
                i += 2
            elif "0" <= nxt <= "7":
                j, digits = i + 1, 0
                val = 0
                while j < n and digits < 3 and "0" <= s[j] <= "7":
                    val = val * 8 + int(s[j])
                    j += 1
                    digits += 1
                out.append(val & 0xFF)
                i = j
            else:
                out.append(ord(nxt))
                i += 2
        else:
            out.extend(c.encode("utf-8", "surrogatepass"))
            i += 1
    return out.decode("utf-8", "replace")


def _extract_paths(header_line: str) -> tuple[str | None, str | None]:
    """Return old and new paths from a git diff header."""
    line = header_line.rstrip("\r\n")
    if not line.startswith("diff --git "):
        return (None, None)
    rest = line[len("diff --git "):]
    m = _QUOTED_HEADER_RE.match(rest)
    if m:
        a_path, b_path = (_unescape_git_quoted(part) for part in m.groups())
        return (a_path[2:] if a_path.startswith("a/") else a_path,
                b_path[2:] if b_path.startswith("b/") else b_path)
    m = _IDENTICAL_HEADER_RE.match(rest)
    if m:
        return (m.group(1), m.group(1))
    # Rename/copy to a genuinely different, unquoted path: paths with spaces are ambiguous
    # here in principle, but git does not quote for a space alone, so this is best-effort for
    # the common no-space rename case (e.g. "diff --git a/x b/.env").
    idx = rest.rfind(" b/")
    if idx != -1:
        return (rest[2:idx], rest[idx + 3:])
    return (None, None)


def _extract_new_path(header_line: str) -> str | None:
    return _extract_paths(header_line)[1]


def _split_into_file_blocks(diff_text: str) -> list[str]:
    if not diff_text:
        return []
    blocks: list[str] = []
    current: list[str] = []
    for line in diff_text.splitlines(keepends=True):
        if _BLOCK_START_RE.match(line) and current:
            blocks.append("".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        blocks.append("".join(current))
    return blocks


def _is_denied(path: str, deny_globs: list[str], allow_globs: list[str]) -> bool:
    if ENV_EXAMPLE.search(path):
        return False
    # fnmatchcase, not fnmatch: fnmatch() runs os.path.normcase() first, which on Windows
    # lowercases AND rewrites "/" to "\\" — silently breaking every POSIX-style glob above.
    # fnmatchcase never touches the string, so matching is identical on every OS.
    if not any(fnmatch.fnmatchcase(path, glob) for glob in deny_globs):
        return False
    return not any(fnmatch.fnmatchcase(path, glob) for glob in allow_globs)


def _scan_added_lines(block: str, path: str) -> list[tuple[str, int, str]]:
    """Scan all hunk lines; removed hits use old-file line numbers."""
    hits: list[tuple[str, int, str]] = []
    new_line: int | None = None
    old_line: int | None = None
    for line in block.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            old_line, new_line = int(m.group(1)), int(m.group(2))
            continue
        if new_line is None:
            continue  # still in the file header (index/mode/---/+++ lines), before any hunk
        if line.startswith("\\"):
            continue  # "\ No newline at end of file" — not a line, does not advance the count
        if line.startswith(("+", "-", " ")):
            content = line[1:]
            removed = line.startswith("-")
            context = line.startswith(" ")
            for rule_name, pattern in SECRET_RULES:
                match = pattern.search(content)
                if match and not (rule_name in {"assignment", "env-assignment"}
                                  and _is_placeholder(match.group("value"))) and not (
                                      rule_name == "env-assignment" and
                                      re.fullmatch(r"[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)+",
                                                   match.group("value"))):
                    marker = (f"{rule_name}, removed line" if removed else
                              f"{rule_name}, context line" if context else rule_name)
                    hits.append((path, old_line if removed else new_line, marker))
            if removed:
                old_line += 1
            elif not context:
                new_line += 1
            else:
                old_line += 1
                new_line += 1
        else:
            old_line += 1
            new_line += 1  # context line exists in both files
    return hits


def filter_diff(diff_text: str, deny_globs: list[str], allow_globs: list[str]) -> FilterResult:
    """Drop denylisted-path file blocks, then scan changed lines in kept blocks."""
    dropped_paths: list[str] = []
    hits: list[tuple[str, int, str]] = []
    kept_parts: list[str] = []
    for block in _split_into_file_blocks(diff_text):
        first_line = block.splitlines()[0] if block else ""
        old_path, new_path = _extract_paths(first_line)
        path = new_path or old_path or "(unparseable path)"
        denied = next((candidate for candidate in (old_path, new_path)
                       if candidate and _is_denied(candidate, deny_globs, allow_globs)), None)
        if denied:
            dropped_paths.append(denied)
            continue
        hits.extend(_scan_added_lines(block, path))
        kept_parts.append(block)
    return FilterResult(kept_diff="".join(kept_parts), dropped_paths=dropped_paths, hits=hits)


def load_config(repo: Path) -> tuple[list[str], list[str]]:
    """`[review] deny_paths` / `allow_paths` from `<repo>/.caddis/config.toml`.

    A missing file, a missing `[review]` table, or a malformed TOML file all yield `([], [])`
    — this is additive configuration layered onto DEFAULT_DENY_GLOBS, never the sole source of
    truth, so failing to read it must never silently widen what gets sent.
    """
    cfg_path = Path(repo) / ".caddis" / "config.toml"
    if not cfg_path.is_file():
        return ([], [])
    try:
        with cfg_path.open("rb") as f:
            return _parse_config(f.read())
    except (tomllib.TOMLDecodeError, OSError, UnicodeError):
        return ([], [])


def _parse_config(contents: bytes) -> tuple[list[str], list[str]]:
    data = tomllib.loads(contents.decode("utf-8"))
    review = data.get("review") if isinstance(data, dict) else None
    if not isinstance(review, dict):
        return ([], [])
    deny = review.get("deny_paths", [])
    allow = review.get("allow_paths", [])
    deny_out = [str(p) for p in deny] if isinstance(deny, list) else []
    allow_out = [str(p) for p in allow] if isinstance(allow, list) else []
    return (deny_out, allow_out)


def load_head_deny_paths(repo: Path) -> list[str]:
    """Read the committed deny list; a missing or unreadable HEAD config contributes nothing."""
    try:
        out = subprocess.run(
            ["git", "show", "HEAD:.caddis/config.toml"], cwd=repo,
            capture_output=True, timeout=30,
        )
        if out.returncode == 0:
            return _parse_config(out.stdout)[0]
    except (OSError, subprocess.TimeoutExpired, UnicodeError, tomllib.TOMLDecodeError):
        pass
    return []
