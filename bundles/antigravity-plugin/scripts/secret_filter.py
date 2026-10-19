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
   assignments). A hit on an ADDED line refuses the ENTIRE review (not just that file) — a
   secret slipping past the path denylist is exactly the case this second layer exists for, and
   the safe response to "something here looks like a credential" is "send nothing", not "guess
   which part is safe".

What counts as a refusal (the rest is a WARN, or nothing):
  - Added line: any rule refuses.
  - Removed line: only the high-confidence rules refuse (`HIGH_CONFIDENCE_RULES`). The two
    assignment heuristics do not: the text is leaving the code, and they guess.
  - Context line: a high-confidence hit refuses too (the line would be SENT to the provider,
    and a real key must not leave the machine). A hit of an assignment heuristic only goes to
    `FilterResult.warnings`; the caller prints a WARN line, because the line is already in the
    repo and the heuristic guesses.
  - `env-assignment` (an unquoted `NAME_TOKEN=value`) runs only on env-like files (`.env*`,
    `*.env`, shell, ini, yaml, tfvars, service, Dockerfile, files with no extension, ...). In
    code, that shape is an ordinary assignment (`tokens = _ga_tokens(text)`). The quoted
    `assignment` rule still runs on every file.
  - An unquoted value in an env-like file is exempt only as a shell variable or substitution
    (`$VAR` as the whole value, `${VAR}`, `$(cmd)`, a backtick command, or `$(...)` / `${...}`
    anywhere in the value) or as a placeholder. Code shape proves nothing there: `SECRET=YWJj==.sig`,
    `SAS=sv=2022-11-02&sig=abc123` and `PASS=ab#cdefgh12` are secrets. A quoted value is exempt
    only as a placeholder, or as a CSS custom-property block (`--bg:#282a36;--fg:#f8f8f2`).
  - A trailing `# caddis: not-secret` or `// caddis: not-secret` comment exempts that line from
    the two assignment rules only. It is ignored inside a string and never exempts a
    high-confidence rule.

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
    "*.env",  # prod.env, config/app.env: a leading `*` matches at any depth
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
    ("github-pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{22,}")),
    ("aws-session-key", re.compile(r"\bASIA[0-9A-Z]{16}\b")),
    ("openai-key", re.compile(r"\bsk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,}")),
    ("anthropic-key", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{20,}")),
    ("google-api-key", re.compile(r"\bAIza[0-9A-Za-z_-]{35}")),
    ("npm-token", re.compile(r"\bnpm_[A-Za-z0-9]{36}\b")),
    ("slack-webhook", re.compile(r"https://hooks\.slack\.com/services/[A-Za-z0-9_/]+")),
    # user:password@host in a URL. `value` is the password; placeholders are exempted in code.
    # Both rules below start a match only at the start of a run of the characters their first part takes (the
    # lookbehind). A match that starts inside the run finds the same value from the run start too, and without the
    # lookbehind each character of a long word started a new scan: quadratic, minutes on one long line.
    ("url-credentials", re.compile(
        r"(?<![a-z0-9+.-])[0-9+.-]*[a-z][a-z0-9+.-]*://[^/\s:@]*:(?P<value>[^/\s@]{3,})@", re.I)),
    # `name = "v"`, `name: "v"`, and a quoted key: `"name": "v"`, `'name': 'v'`.
    ("assignment", re.compile(
        r"(?i)(?<![A-Za-z0-9_])[A-Za-z0-9_]*(password|passwd|secret|api[_-]?key|token)[A-Za-z0-9_]*['\"]?\s*[:=]\s*"
        r"['\"](?P<value>[^'\"\s]{8,})['\"]"
    )),
    ("env-assignment", re.compile(
        r"^\s*(?:export\s+)?[A-Za-z0-9_]*(?:PASSWORD|PASSWD|SECRET|API_KEY|APIKEY|TOKEN|PRIVATE_KEY)"
        r"[A-Za-z0-9_]*\s*=\s*(?P<value>[^\s'\"]{8,})", re.I
    )),
]

# Rules that match a fixed credential format. These refuse on added, removed AND context lines
# and ignore the `caddis: not-secret` marker. The two assignment rules are heuristics and get none
# of that.
ASSIGNMENT_RULES = frozenset({"assignment", "env-assignment"})
HIGH_CONFIDENCE_RULES = frozenset({
    "private-key", "aws-key", "github-token", "slack-token", "jwt",
    "github-pat", "aws-session-key", "openai-key", "anthropic-key", "google-api-key",
    "npm-token", "slack-webhook", "url-credentials",
})

# A trailing comment only: `# caddis: not-secret` or `// caddis: not-secret` at the end of the
# line, and not inside a string (see `_has_not_secret_marker`).
_TRAILING_MARKER = re.compile(r"(?:#|//)\s*caddis:\s*not-secret\s*$", re.I)

# `env-assignment` runs only on these files (matched on the file name, not the directory).
_ENV_LIKE_SUFFIXES = frozenset({
    ".sh", ".bash", ".zsh", ".ps1", ".psm1", ".bat", ".cmd", ".ini", ".cfg", ".conf", ".toml",
    ".yaml", ".yml", ".properties", ".env", ".tfvars", ".service",
})


def _is_env_like(path: str) -> bool:
    name = path.replace("\\", "/").rsplit("/", 1)[-1].lower()
    if name.startswith((".env", "dockerfile")):
        return True
    suffix = Path(name).suffix
    return suffix == "" or suffix in _ENV_LIKE_SUFFIXES


def _inside_string(prefix: str) -> bool:
    """True when `prefix` ends inside an open '...' or "..." string."""
    quote = None
    i = 0
    while i < len(prefix):
        c = prefix[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if c == quote:
                quote = None
        elif c in "'\"":
            quote = c
        i += 1
    return quote is not None


def _has_not_secret_marker(content: str) -> bool:
    match = _TRAILING_MARKER.search(content)
    return bool(match) and not _inside_string(content[:match.start()])


# `--bg:#282a36;--fg:#f8f8f2`: a CSS custom-property block held in a quoted string.
_CSS_DECLARATIONS = re.compile(r"(?:--[A-Za-z0-9_-]+:[^;\s]+;?)+")
# $(cmd) `cmd` ${VAR}. A bare `$VAR` is exempt only as the WHOLE value, through
# `_is_placeholder`: a value that merely starts with `$` (`$ecretP@ss`, `$argon2id$...`) is a secret.
_SHELL_START = re.compile(r"\$\(|`|\$\{")
_SHELL_SUBSTITUTION = re.compile(r"\$\([^)]*\)|\$\{[^}]*\}")  # $(...) or ${...} anywhere


def _is_not_secret_value(value: str, *, quoted: bool) -> bool:
    """True when the value is a CSS block (quoted) or a shell variable or substitution (unquoted).

    A QUOTED value is a string literal, so code shape proves nothing: `"Sec;ret(1)"` and
    `"P@ssw0rd#2026!"` are passwords. Only a CSS custom-property block is exempt (the
    placeholder check happens in the caller).

    An UNQUOTED value reaches this rule only in an env-like file, where values are not code:
    `SECRET=YWJj==.sig`, `SAS=sv=2022-11-02&sig=abc123`, `PASS=ab#cdefgh12` and
    `KEY=correct_horse` are secrets. Only a shell reference is exempt: a value that starts with
    `$(`, a backtick or `${`, or holds `$(...)` / `${...}` in any position. A bare `$name` is
    exempt only as the whole value (a placeholder); `$argon2id$v=19$...` is a hash.
    """
    if quoted:
        return bool(_CSS_DECLARATIONS.fullmatch(value))
    return bool(_SHELL_START.match(value) or _SHELL_SUBSTITUTION.search(value))


_URL_PASSWORD_PLACEHOLDERS = frozenset({"password", "pass", "passwd", "pwd", "secret", "token"})


def _is_url_password_placeholder(value: str) -> bool:
    return (_is_placeholder(value) or value.lower() in _URL_PASSWORD_PLACEHOLDERS
            or bool(re.fullmatch(r"\{[^}]*\}|%s|%\([^)]*\)s", value)))


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
    # Context-line matches: already in the repo, so reported (WARN) but never a refusal.
    warnings: list[tuple[str, int, str]] = field(default_factory=list)


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


def _line_matches(content: str, env_like: bool) -> list[str]:
    """Names of the rules that match one line of content, after every exemption.

    Every match of a rule is checked, so a real secret that follows a placeholder on the same
    line (a JSON object with a placeholder key first and a real one second) is still caught.
    """
    marked = _has_not_secret_marker(content)
    names: list[str] = []
    for rule_name, pattern in SECRET_RULES:
        if rule_name in ASSIGNMENT_RULES and marked:
            continue
        if rule_name == "env-assignment" and not env_like:
            continue
        for match in pattern.finditer(content):
            if rule_name in ASSIGNMENT_RULES:
                value = match.group("value")
                if _is_placeholder(value) or _is_not_secret_value(
                        value, quoted=rule_name == "assignment"):
                    continue
            elif rule_name == "url-credentials" and _is_url_password_placeholder(
                    match.group("value")):
                continue
            names.append(rule_name)
            break
    return names


def _scan_block(block: str, path: str, env_like: bool) -> tuple[list[tuple[str, int, str]],
                                                                  list[tuple[str, int, str]]]:
    """Scan all hunk lines; return (hits, warnings). Removed hits use old-file line numbers."""
    hits: list[tuple[str, int, str]] = []
    warnings: list[tuple[str, int, str]] = []
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
            for rule_name in _line_matches(content, env_like):
                if context:
                    # A real key on a context line is still SENT to the provider.
                    if rule_name in HIGH_CONFIDENCE_RULES:
                        hits.append((path, new_line, f"{rule_name}, context line"))
                    else:
                        warnings.append((path, new_line, f"{rule_name}, context line"))
                elif removed:
                    if rule_name in HIGH_CONFIDENCE_RULES:
                        hits.append((path, old_line, f"{rule_name}, removed line"))
                else:
                    hits.append((path, new_line, rule_name))
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
    return hits, warnings


def _scan_added_lines(block: str, path: str,
                      env_assignment_everywhere: bool = False) -> list[tuple[str, int, str]]:
    """The refusing hits of `_scan_block` (kept for callers that want only those)."""
    return _scan_block(block, path, env_assignment_everywhere or _is_env_like(path))[0]


def filter_diff(diff_text: str, deny_globs: list[str], allow_globs: list[str],
                env_assignment_everywhere: bool = False) -> FilterResult:
    """Drop denylisted-path file blocks, then scan the hunk lines in kept blocks.

    `env_assignment_everywhere` runs `env-assignment` on every file type. Use it for text that
    is not a diff of real files (the relay note is prose in a synthetic `.md` file).
    """
    dropped_paths: list[str] = []
    hits: list[tuple[str, int, str]] = []
    warnings: list[tuple[str, int, str]] = []
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
        block_hits, block_warnings = _scan_block(
            block, path, env_assignment_everywhere or _is_env_like(path))
        hits.extend(block_hits)
        warnings.extend(block_warnings)
        kept_parts.append(block)
    return FilterResult(kept_diff="".join(kept_parts), dropped_paths=dropped_paths, hits=hits,
                        warnings=warnings)


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
