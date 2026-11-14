"""Plan phases as development stories: one plan phase is one sprint-sized story.

`render --plan <path> [--format md|storage]` prints the stories table of a plan, with no network.
`check [--plan <path>]` proves the Confluence login and that the plan's parent page can be read (GET only).
`sync --plan <path> [--dry-run]` writes the plan's section to the Epic page: the sub-page of `confluence_parent` whose
title is `jira_epic`. It creates the page when it is missing and replaces only the plan's marked section (anchor macros
`caddis-stories-<slug>-start-<hash8>` and `caddis-stories-<slug>-end`). Broken markers stop the sync with no write.

Keys: `CONFLUENCE_URL` (https only) and `CONFLUENCE_TOKEN` (a personal access token, sent as a Bearer header), from the
environment first, then `CADDIS_KEYS_FILE` or `~/.caddis/keys.env`. The token goes only to the `CONFLUENCE_URL` host
and never into output: every text from Confluence goes through `caddis_redact`.

Story rules (plan `confluence-stories.md`, Constraints): the summary is the phase name, the description is the first
sentence of its Goal, the acceptance criteria come from its Exit gate, the dependency from its Depends on line (else the
previous phase), the target sprint is its Milestone, the status comes from the plan Tracker, and the estimate is 2, 3
or 5 story points.
Exit codes: 0 clean, 1 Confluence refused or broken markers, 3 not configured or network failure, 4 bad input.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import html
import http.client
import json
import os
from pathlib import Path
import re
import sys
import urllib.error
from urllib.parse import parse_qs, quote, unquote_plus, urlencode, urlsplit
import urllib.request

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit

import caddis_redact
from caddis_frontmatter import split_document
from caddis_review import phase_risk, phase_section
from caddis_rows import split_cells
from caddis_status import status_state
from caddis_todo import tracker_table
from oss_model import _parse_keys_file

_FENCE_OPEN = re.compile(r"^\s*(`{3,}|~{3,})")
_FENCE_CLOSE = re.compile(r"^\s*(`{3,}|~{3,})\s*$")
_PHASE_HEADING = re.compile(r"^### Phase (\d+[a-z]?)\s*[-—–:]\s*(.+?)\s*$")
_MILESTONE_HEADING = re.compile(r"^### Milestone\s+(\S+)")
_ANY_HEADING = re.compile(r"^#{1,3} ")
_STATUS_MARKS = "✅⏳🔲❌⚠️🚧 \t"
_GOAL = re.compile(r"^\*\*Goal:\*\*\s*(.+)$", re.M)
_EXIT_GATE = re.compile(r"^\*\*Exit gate:\*\*\s*(.+)$", re.M)
_MILESTONE_LINE = re.compile(r"^\*\*Milestone:\*\*\s*(\S+)", re.M)
_DEPENDS = re.compile(r"^\*\*Depends on:\*\*(.*)$", re.M)
_FILES_LINE = re.compile(r"^\*\*(?:Touches|Files):\*\*(.*)$", re.M)
_CROSS_REVIEW = re.compile(r"^\*\*Cross-review:\*\*(.*)$", re.M)
_SMALL_TIER = re.compile(r"(?i)\btier\s*(0|1-small)\b")
_TITLE_SUFFIX = re.compile(r"\s+[-—]\s+Implementation Plan\s*$")
MAX_WORDS = 25
MAX_CRITERIA = 5
STATUS_WORDS = {"todo": "To do", "in-progress": "In progress", "blocked": "Blocked", "done": "Done", "moved": "Moved"}
COLUMNS = ("Story ID", "User Story / Deliverable", "Acceptance Criteria", "Estimate", "Dependency", "Target Sprint",
           "Status")


@dataclass
class Story:
    story_id: str
    phase: str
    summary: str
    description: str
    criteria: list[str]
    points: int
    dependency: str
    sprint: str
    status: str


@dataclass
class PlanInfo:
    path: Path
    slug: str
    title: str
    epic: str | None
    parent: str | None
    stories: list[Story]
    status: str | None = None


# ---------------------------------------------------------------- plan reading

def strip_fences(text: str) -> str:
    """`text` with every line inside a code fence (and the fence lines) blanked. Line numbers stay the same."""
    out: list[str] = []
    fence = ""
    for line in text.split("\n"):
        if not fence:
            m = _FENCE_OPEN.match(line)
            if m:
                fence = m.group(1)
                out.append("")
                continue
            out.append(line)
        else:
            m = _FENCE_CLOSE.match(line)
            if m and m.group(1)[0] == fence[0] and len(m.group(1)) >= len(fence):
                fence = ""
            out.append("")
    return "\n".join(out)


def _headings(text: str) -> list[tuple[int, str, str, str | None]]:
    """(line index, phase id, name, enclosing milestone id) for each phase heading outside a code fence."""
    found = []
    milestone = None
    for index, line in enumerate(strip_fences(text).split("\n")):
        m = _MILESTONE_HEADING.match(line)
        if m:
            milestone = m.group(1).rstrip(":.,")
            continue
        m = _PHASE_HEADING.match(line)
        if m:
            found.append((index, m.group(1), m.group(2).rstrip(_STATUS_MARKS), milestone))
    return found


def phase_headings(text: str) -> list[tuple[str, str, str | None]]:
    """(phase id, name, enclosing milestone id or None) for each `### Phase <id> - <name>` heading, in file order."""
    return [(pid, name, milestone) for _, pid, name, milestone in _headings(text)]


def plain(text: str) -> str:
    """Short plain text: no links, bold or backticks, no `(...)` group, no dash with spaces, one space between words.
    A code span keeps its brackets and dashes; only its backticks go. A `(...)` group that holds a code span still goes."""
    code: list[str] = []

    def hold(m: re.Match) -> str:
        span = m.group(2)
        if len(span) >= 2 and span[0] == span[-1] == " " and span.strip(" "):
            span = span[1:-1]  # CommonMark: one padding space each side
        code.append(span)
        return f"\x00{len(code) - 1}\x00"

    text = text.replace("\x00", "")
    text = re.sub(r"(?<!`)(`+)(?!`)(.*?)(?<!`)\1(?!`)", hold, text, flags=re.DOTALL)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("**", "").replace("`", "")
    text = re.sub(r"\([^()]*\)", "", text)
    text = re.sub(r"\s*[—–]\s*", " ", text)
    text = re.sub(r"\s+([,;:])(?=\s|$)", r"\1", text)
    text = re.sub(r"\x00(\d+)\x00", lambda m: code[int(m.group(1))], text)
    return re.sub(r"\s+", " ", text).strip()


def _cut(text: str, max_words: int) -> tuple[str, bool]:
    words = text.split()
    if len(words) > max_words:
        return " ".join(words[:max_words]) + " ...", True
    return text, False


def first_sentence(text: str, max_words: int = MAX_WORDS) -> str:
    """The first sentence of `text`, at most `max_words` words (a longer one is cut and ends with ` ...`)."""
    sentence = re.split(r"(?<=[.!?])\s+", text.strip(), maxsplit=1)[0]
    return _cut(sentence, max_words)[0]


def criteria(exit_gate: str | None) -> list[str]:
    """The acceptance criteria: one short clause per sentence or `;` part of the Exit gate, at most 5 lines."""
    if not exit_gate or not exit_gate.strip():
        return ["See the plan."]
    clauses = []
    for clause in re.split(r";\s+|(?<=[.!?])\s+", plain(exit_gate)):
        clause = clause.rstrip(" .;")
        if not clause:
            continue
        text, was_cut = _cut(clause, MAX_WORDS)
        clauses.append(text if was_cut else text + ".")
    if not clauses:
        return ["See the plan."]
    if len(clauses) > MAX_CRITERIA:
        return clauses[:MAX_CRITERIA - 1] + [f"and {len(clauses) - (MAX_CRITERIA - 1)} more in the plan."]
    return clauses


def _risk(plan: Path, phase_id: str) -> str:
    try:
        return phase_risk(plan, phase_id)
    except (OSError, ValueError):
        return "normal"


def story_points(plan: Path, phase_id: str, section: str) -> int:
    """5 for a programme phase, a high risk or more than 8 files; 2 for 1-3 files or a tier 0 / 1-small review; else 3."""
    files = set()
    for line in _FILES_LINE.findall(section):
        files |= {span for span in re.findall(r"`([^`]+)`", line)
                  if ("/" in span or "." in span) and " " not in span}
    programme = any(line.startswith("**Programme phase:**") for line in section.splitlines())
    if programme or len(files) > 8 or _risk(plan, phase_id) == "high":
        return 5
    review = _CROSS_REVIEW.search(section)
    if 1 <= len(files) <= 3 or (review and _SMALL_TIER.search(review.group(1))):
        return 2
    return 3


def dependency(section: str, previous: str | None) -> str:
    """Every `Phase <id>` on the Depends on line as `P<id>`; `None` when the line names no phase; else the previous phase."""
    m = _DEPENDS.search(section)
    if m is None:
        return f"P{previous}" if previous else "None"
    ids = list(dict.fromkeys(re.findall(r"Phase\s+(\d+[a-z]?)", m.group(1))))
    return ", ".join(f"P{i}" for i in ids) if ids else "None"


def _tracker_rows(stripped: str) -> dict[str, dict[str, str]]:
    """Tracker cells by phase id (lower case): {"status": ..., "milestone": ...}."""
    table = tracker_table(stripped)
    if table is None:
        return {}
    columns, lines = table
    rows: dict[str, dict[str, str]] = {}
    for line in lines:
        if not line.strip().startswith("|"):
            continue
        cells = split_cells(line)
        if not cells or all(re.fullmatch(r":?-+:?", c) for c in cells):
            continue
        cell = dict(zip(columns, cells))
        key = re.sub(r"^(phase\s*|p)", "", cell.get("phase", "").strip("*` "), flags=re.I).strip().lower()
        if key and key not in rows:
            rows[key] = cell
    return rows


def _section(path: Path, stripped_lines: list[str], index: int, phase_id: str) -> str:
    try:
        return phase_section(path, phase_id)
    except ValueError:
        end = next((i for i in range(index + 1, len(stripped_lines)) if _ANY_HEADING.match(stripped_lines[i])),
                   len(stripped_lines))
        return "\n".join(stripped_lines[index:end]).rstrip() + "\n"


def _slug(meta: dict, path: Path) -> str:
    raw = meta.get("feature") if isinstance(meta.get("feature"), str) and meta.get("feature") else path.stem
    return re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-") or "plan"


def _meta_text(meta: dict, name: str) -> str | None:
    value = meta.get(name)
    return value.strip() if isinstance(value, str) and value.strip() else None


def read_plan(path: Path) -> PlanInfo:
    """The plan's slug, title, Epic, parent page and one story per phase. Raises ValueError when no phase heading."""
    path = Path(path)
    text = path.read_text(encoding="utf-8")
    meta, _ = split_document(text)
    stripped = strip_fences(text)
    stripped_lines = stripped.split("\n")
    headings = _headings(text)
    if not headings:
        raise ValueError(f"no '### Phase <n> - <name>' heading in {path.name}")
    slug = _slug(meta, path)
    title_match = re.search(r"^# (.+)$", stripped, re.M)
    title = _TITLE_SUFFIX.sub("", title_match.group(1)).strip() if title_match else slug
    tracker = _tracker_rows(stripped)
    out: list[Story] = []
    previous = None
    for index, pid, name, heading_milestone in headings:
        section = _section(path, stripped_lines, index, pid)
        row = tracker.get(pid.lower(), {})
        goal = _GOAL.search(section)
        gate = _EXIT_GATE.search(section)
        line_milestone = _MILESTONE_LINE.search(section)
        sprint = (line_milestone.group(1) if line_milestone else None) or heading_milestone \
            or plain(row.get("milestone", "")) or "-"
        out.append(Story(
            story_id=f"{slug}-P{pid}",
            phase=pid,
            summary=plain(name),
            description=first_sentence(plain(goal.group(1))) if goal else "-",
            criteria=criteria(gate.group(1) if gate else None),
            points=story_points(path, pid, section),
            dependency=dependency(section, previous),
            sprint=sprint,
            status=STATUS_WORDS[status_state(row.get("status", ""))],
        ))
        previous = pid
    return PlanInfo(path=path, slug=slug, title=title, epic=_meta_text(meta, "jira_epic"),
                    parent=_meta_text(meta, "confluence_parent"), stories=out, status=_meta_text(meta, "status"))


# ---------------------------------------------------------------- rendering

def _md_cell(text: str) -> str:
    return text.replace("|", "\\|")


def render_markdown(info: PlanInfo) -> str:
    """The stories as a markdown table: header, rule, one row per story."""
    lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
    for s in info.stories:
        cells = (s.story_id, f"{s.summary}: {s.description}", " ".join(s.criteria), str(s.points), s.dependency,
                 s.sprint, s.status)
        lines.append("| " + " | ".join(_md_cell(c) for c in cells) + " |")
    return "\n".join(lines) + "\n"


def _anchor(name: str) -> str:
    return (f'<p><ac:structured-macro ac:name="anchor"><ac:parameter ac:name="">{name}</ac:parameter>'
            f'</ac:structured-macro></p>')


def section_hash(inner: str) -> str:
    """The first 8 hex characters of the sha256 of the section text between the two markers."""
    return hashlib.sha256(inner.encode("utf-8")).hexdigest()[:8]


def _esc(text: str) -> str:
    return html.escape(text, quote=True)


def storage_section(info: PlanInfo) -> str:
    """The plan's section in Confluence storage format: start marker (with the hash), heading, intro, table, end marker."""
    status = f" (plan status: {info.status})" if info.status else ""
    parts = [f"<h2>Development stories: {_esc(info.title + status)}</h2>",
             f"<p>caddis writes this section from the plan file {_esc(info.path.name)}. Do not edit it. "
             f"The next sync replaces it.</p>",
             "<table><tbody><tr>" + "".join(f"<th>{_esc(c)}</th>" for c in COLUMNS) + "</tr>"]
    for s in info.stories:
        items = "".join(f"<li>{_esc(c)}</li>" for c in s.criteria)
        parts.append(f"<tr><td>{_esc(s.story_id)}</td><td><strong>{_esc(s.summary)}</strong><br/>"
                     f"{_esc(s.description)}</td><td><ul>{items}</ul></td><td>{s.points}</td>"
                     f"<td>{_esc(s.dependency)}</td><td>{_esc(s.sprint)}</td><td>{_esc(s.status)}</td></tr>")
    parts.append("</tbody></table>")
    inner = "".join(parts)
    return (_anchor(f"caddis-stories-{info.slug}-start-{section_hash(inner)}") + inner
            + _anchor(f"caddis-stories-{info.slug}-end"))


# ---------------------------------------------------------------- the marked section on a page

class MarkerError(ValueError):
    """The plan's markers on the page are broken (a start with no end, an end before the start, two starts)."""


def _marker_re(slug: str, kind: str) -> re.Pattern:
    """A start or end anchor macro of `slug`, with or without its `<p>` wrapper and with any added attributes."""
    name = f"caddis-stories-{re.escape(slug)}-{kind}" + (r"(?:-([0-9a-f]{8}))?" if kind == "start" else "")
    macro = (r'<ac:structured-macro\b[^>]*\sac:name="anchor"[^>]*>\s*'
             r'<ac:parameter\b[^>]*\sac:name=""[^>]*>\s*' + name + r'\s*</ac:parameter>\s*</ac:structured-macro>')
    return re.compile(r"<p(?:\s[^>]*)?>\s*" + macro + r"\s*</p>|" + macro)


def find_section(body: str, slug: str) -> tuple[int, int, str | None] | None:
    """(start offset, end offset, stored hash) of the plan's section, or None when the page has none of its markers.

    Raises MarkerError when the markers are broken, so a sync never guesses where the section ends."""
    starts = list(_marker_re(slug, "start").finditer(body))
    ends = list(_marker_re(slug, "end").finditer(body))
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1:
        raise MarkerError(f"{len(starts)} start and {len(ends)} end markers for {slug}")
    start, end = starts[0], ends[0]
    if end.start() < start.end():
        raise MarkerError(f"the end marker of {slug} is before its start marker")
    return start.start(), end.end(), start.group(1) or start.group(2)


def replace_section(body: str, slug: str, section: str) -> tuple[str, str]:
    """(new body, action): `add` appends the section, `update` replaces the old one in place, `unchanged` keeps the
    body when the stored hash equals the new one. Every byte outside the plan's markers stays the same."""
    found = find_section(body, slug)
    if found is None:
        return body + section, "add"
    start, end, stored = found
    own = find_section(section, slug)
    if own is not None and stored is not None and stored == own[2]:
        return body, "unchanged"
    return body[:start] + section + body[end:], "update"


# ---------------------------------------------------------------- Confluence keys and parent page

DEFAULT_KEYS_FILE = "~/.caddis/keys.env"


class ConfigError(Exception):
    """CONFLUENCE_URL or CONFLUENCE_TOKEN is missing or not usable. The text names the variable, never its value."""


@dataclass
class Config:
    base_url: str
    token: str

    def __repr__(self) -> str:  # never show the token in a traceback or a log
        return f"Config(base_url={self.base_url!r}, token='***')"


def load_config(env: Mapping[str, str]) -> Config:
    """CONFLUENCE_URL and CONFLUENCE_TOKEN: the environment first, then the keys file."""
    keys_path = env.get("CADDIS_KEYS_FILE") or DEFAULT_KEYS_FILE
    try:
        file_keys = _parse_keys_file(keys_path)
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read the keys file {keys_path}: {type(exc).__name__}") from None
    values = {}
    for name in ("CONFLUENCE_URL", "CONFLUENCE_TOKEN"):
        value = (env.get(name) or "").strip() or (file_keys.get(name) or "").strip()
        if not value:
            raise ConfigError(f"{name} is not set (environment or {keys_path})")
        values[name] = value
    base_url = values["CONFLUENCE_URL"].rstrip("/")
    parts = urlsplit(base_url)
    if parts.scheme != "https" or not parts.hostname:
        raise ConfigError("CONFLUENCE_URL must use the https scheme and name a host")
    return Config(base_url=base_url, token=values["CONFLUENCE_TOKEN"])


@dataclass
class ParentRef:
    page_id: str | None
    space: str | None
    title: str | None


def _host(url: str) -> tuple[str, int | None]:
    parts = urlsplit(url)
    return (parts.hostname or "").lower(), parts.port


def parse_parent(url: str, base_url: str) -> ParentRef:
    """The parent page from its URL: `?pageId=<n>`, `/spaces/<KEY>/pages/<n>/...` or `/display/<KEY>/<Title+Words>`.

    Raises ValueError when the URL is not https on the `base_url` host, or no form matches."""
    url = url.strip()
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or _host(url) != _host(base_url):
        raise ValueError("confluence_parent is not an https URL on the CONFLUENCE_URL host")
    page_id = parse_qs(parts.query).get("pageId", [None])[0]
    if page_id and page_id.isdigit():
        return ParentRef(page_id, None, None)
    m = re.search(r"/spaces/([^/]+)/pages/(\d+)(?:/|$)", parts.path)
    if m:
        return ParentRef(m.group(2), unquote_plus(m.group(1)), None)
    m = re.search(r"/display/([^/]+)/([^/]+)/?$", parts.path)
    if m:
        return ParentRef(None, unquote_plus(m.group(1)), unquote_plus(m.group(2)))
    raise ValueError("confluence_parent has no page id and no /display/<space>/<title> form")


# ---------------------------------------------------------------- Confluence REST client

_PAGE_EXPAND = "body.storage,version,space,ancestors"
MAX_ERROR_TEXT = 300


class ConfluenceError(Exception):
    """A Confluence call failed. `status` is the HTTP status, or None for a network failure or a timeout.
    `message` is already redacted and cut: it never holds the token."""

    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status
        self.message = message

    def __str__(self) -> str:
        return self.message


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """A redirect is an error: the Authorization header must never follow it to another URL."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


_OPENER = urllib.request.build_opener(_NoRedirect)


def _default_send(req: urllib.request.Request, timeout: float) -> tuple[int, bytes]:
    """urllib transport: (status, body). An HTTP error status is returned, not raised. Network errors raise."""
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except (OSError, http.client.HTTPException):
            body = b""
        return exc.code, body


class Confluence:
    """Confluence Server REST calls with a Bearer personal access token. The token is sent only in the header."""

    def __init__(self, base_url: str, token: str, timeout: float = 20.0, send: Callable | None = None):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self._send = send or _default_send
        secrets = caddis_redact.load_secrets(Path.home())
        if token:
            secrets = secrets + [token]
        self._secrets = sorted(set(secrets), key=len, reverse=True)

    def __repr__(self) -> str:
        return f"Confluence(base_url={self.base_url!r})"

    def _clean(self, text: str) -> str:
        return caddis_redact.redact(text, self._secrets)[:MAX_ERROR_TEXT]

    def request(self, method: str, path: str, query: dict | None = None, body: dict | None = None) -> dict:
        url = self.base_url + path + ("?" + urlencode(query) if query else "")
        data = json.dumps(body).encode("utf-8") if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self._token}")
        req.add_header("Accept", "application/json")
        req.add_header("X-Atlassian-Token", "no-check")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            status, raw = self._send(req, self.timeout)
        except ConfluenceError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            reason = self._clean(f"{type(exc).__name__}: {exc}")
            raise ConfluenceError(None, f"network error {method} {path}: {reason}") from None
        text = (raw or b"").decode("utf-8", errors="replace")
        if not 200 <= status < 300:
            raise ConfluenceError(status, f"HTTP {status} {method} {path}: {self._clean(text)}")
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except ValueError:
            raise ConfluenceError(status, f"HTTP {status} {method} {path}: the answer is not JSON") from None

    def current_user(self) -> str:
        data = self.request("GET", "/rest/api/user/current")
        return str(data.get("username") or data.get("displayName") or "")

    def get_page(self, page_id: str) -> dict:
        return self.request("GET", f"/rest/api/content/{quote(str(page_id), safe='')}", {"expand": _PAGE_EXPAND})

    def find_page(self, space: str, title: str) -> dict | None:
        data = self.request("GET", "/rest/api/content", {"spaceKey": space, "title": title, "expand": _PAGE_EXPAND})
        results = data.get("results") or []
        return results[0] if results else None

    def create_page(self, space: str, parent_id: str, title: str, storage: str) -> dict:
        return self.request("POST", "/rest/api/content", body={
            "type": "page", "title": title, "space": {"key": space}, "ancestors": [{"id": parent_id}],
            "body": {"storage": {"value": storage, "representation": "storage"}}})

    def update_page(self, page: dict, storage: str) -> dict:
        """PUT the new body with version + 1. Confluence answers 409 when someone saved the page in between."""
        return self.request("PUT", f"/rest/api/content/{quote(str(page['id']), safe='')}", body={
            "id": page["id"], "type": "page", "title": page["title"], "space": {"key": page["space"]["key"]},
            "version": {"number": page["version"]["number"] + 1},
            "body": {"storage": {"value": storage, "representation": "storage"}}})


# ---------------------------------------------------------------- sync

@dataclass
class SyncResult:
    action: str  # create-page | add | update | unchanged
    page_id: str | None
    version: int | None
    warnings: list[str]


def _version(page: dict) -> int | None:
    number = (page.get("version") or {}).get("number")
    return number if isinstance(number, int) else None


def _body(page: dict) -> str:
    return ((page.get("body") or {}).get("storage") or {}).get("value") or ""


def sync_plan(info: PlanInfo, client: Confluence, base_url: str, dry_run: bool) -> SyncResult:
    """Write the plan's section to the Epic page under the parent page: create the page when it is missing, else
    replace only the plan's marked section. A dry run reads only. On a 409 the page is read again and written once more.
    """
    warnings: list[str] = []
    parent = resolve_parent(client, parse_parent(info.parent or "", base_url))
    parent_id = str(parent["id"])
    space = parent["space"]["key"]
    section = storage_section(info)
    page = client.find_page(space, info.epic)
    if page is None:
        if dry_run:
            return SyncResult("create-page", None, None, warnings)
        created = client.create_page(space, parent_id, info.epic, section)
        return SyncResult("create-page", str(created.get("id")), _version(created), warnings)
    if parent_id not in {str(a.get("id")) for a in page.get("ancestors") or []}:
        warnings.append(f"page {info.epic} is not under the parent page")
    new_body, action = replace_section(_body(page), info.slug, section)
    if action == "unchanged" or dry_run:
        return SyncResult(action, str(page["id"]), _version(page), warnings)
    try:
        updated = client.update_page(page, new_body)
    except ConfluenceError as err:
        if err.status != 409:
            raise
        page = client.get_page(str(page["id"]))
        new_body, action = replace_section(_body(page), info.slug, section)
        if action == "unchanged":
            return SyncResult(action, str(page["id"]), _version(page), warnings)
        updated = client.update_page(page, new_body)
    return SyncResult(action, str(page["id"]), _version(updated), warnings)


# ---------------------------------------------------------------- command line

def _load(plan: str) -> PlanInfo | None:
    try:
        return read_plan(Path(plan))
    except (OSError, ValueError) as exc:
        print(f"cannot read plan: {exc}", file=sys.stderr)
        return None


def cmd_render(args) -> int:
    info = _load(args.plan)
    if info is None:
        return caddis_exit.ERROR
    sys.stdout.write(storage_section(info) + "\n" if args.format == "storage" else render_markdown(info))
    return caddis_exit.CLEAN


def resolve_parent(client: Confluence, ref: ParentRef) -> dict:
    """The parent page: by id, else by space and title. ConfluenceError 404 when it is not found."""
    if ref.page_id:
        return client.get_page(ref.page_id)
    page = client.find_page(ref.space or "", ref.title or "")
    if page is None:
        raise ConfluenceError(404, "parent page not found")
    return page


def _confluence_failed(err: ConfluenceError) -> int:
    if err.status is None:
        print(f"Confluence not reached: {err}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    print(f"Confluence refused: {err}", file=sys.stderr)
    return caddis_exit.BLOCKED


def cmd_check(args, env: Mapping[str, str], client_factory=Confluence) -> int:
    """Read-only: the login user and, with --plan, the plan's parent page. Every check of input runs before a request."""
    try:
        config = load_config(env)
    except ConfigError as exc:
        print(f"NOT CONFIGURED: {exc}")
        return caddis_exit.NOT_RUN
    ref = None
    if getattr(args, "plan", None):
        info = _load(args.plan)
        if info is None:
            return caddis_exit.ERROR
        if not info.parent:
            print(f"NOT CONFIGURED: {info.path.name} needs confluence_parent")
            return caddis_exit.NOT_RUN
        try:
            ref = parse_parent(info.parent, config.base_url)
        except ValueError as exc:
            print(f"bad input: {exc}", file=sys.stderr)
            return caddis_exit.ERROR
    client = client_factory(config.base_url, config.token)
    try:
        print(f"USER: {client.current_user()}")
        if ref is not None:
            parent = resolve_parent(client, ref)
            space = (parent.get("space") or {}).get("key", ref.space or "?")
            print(f"PARENT: {parent.get('title', '?')} ({parent.get('id', '?')}) in space {space}")
    except ConfluenceError as err:
        return _confluence_failed(err)
    return caddis_exit.CLEAN


_EPIC_KEY = re.compile(r"^[A-Z][A-Z0-9]+-\d+$")


def cmd_sync(args, env: Mapping[str, str], client_factory=Confluence) -> int:
    """Write the plan's stories section to its Epic page. Every check of input runs before the first request."""
    info = _load(args.plan)
    if info is None:
        return caddis_exit.ERROR
    if not info.epic or not info.parent:
        print(f"NOT CONFIGURED: {info.path.name} needs jira_epic and confluence_parent")
        return caddis_exit.NOT_RUN
    if not _EPIC_KEY.match(info.epic):
        print(f"bad input: jira_epic '{info.epic}' is not a Jira key such as ABC-123", file=sys.stderr)
        return caddis_exit.ERROR
    try:
        config = load_config(env)
    except ConfigError as exc:
        print(f"NOT CONFIGURED: {exc}")
        return caddis_exit.NOT_RUN
    try:
        parse_parent(info.parent, config.base_url)
    except ValueError as exc:
        print(f"bad input: {exc}", file=sys.stderr)
        return caddis_exit.ERROR
    client = client_factory(config.base_url, config.token)
    try:
        result = sync_plan(info, client, config.base_url, dry_run=bool(getattr(args, "dry_run", False)))
    except MarkerError:
        print(f"markers broken on page {info.epic}; fix the page by hand", file=sys.stderr)
        return caddis_exit.BLOCKED
    except ConfluenceError as err:
        return _confluence_failed(err)
    for warning in result.warnings:
        print(f"WARN: {warning}", file=sys.stderr)
    print(f"ACTION: {result.action}")
    if result.page_id is None:
        print(f"PAGE: {info.epic} (new)")
    else:
        print(f"PAGE: {info.epic} ({result.page_id}) v{result.version if result.version is not None else '?'}")
    if getattr(args, "dry_run", False):
        print("DRY RUN: nothing written")
        print(storage_section(info))
    return caddis_exit.CLEAN


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="caddis_stories.py", description="Plan phases as development stories.")
    sub = parser.add_subparsers(dest="command", required=True)
    render = sub.add_parser("render", help="print the stories table of a plan (no network)")
    render.add_argument("--plan", required=True)
    render.add_argument("--format", choices=("md", "storage"), default="md")
    check = sub.add_parser("check", help="read-only: the Confluence login and the plan's parent page")
    check.add_argument("--plan")
    sync = sub.add_parser("sync", help="write the plan's stories section to its Epic page")
    sync.add_argument("--plan", required=True)
    sync.add_argument("--dry-run", action="store_true", help="read only; print the action and the section")
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
        return cmd_sync(args, os.environ)
    return caddis_exit.ERROR


if __name__ == "__main__":
    raise SystemExit(main())
