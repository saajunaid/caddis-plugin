"""Jira for the AI Software Factory: one adapter seam, Data Center live, Cloud contract-tested.

`check [--json]` proves the Jira login: it reads `/serverInfo` and `/myself` and prints the mode, the server version
and the deployment type. It never prints a token, an e-mail address or a display name.
`read <KEY> [--comments] [--children] [--discover-schema] [--json]` reads one issue: type, status, a redacted summary
and description snippet, the workflow transitions, and (on request) the comments, the child issues of an Epic (counts
of types and statuses only, never their summaries) and the field schema (Epic Link, Epic Name, Story Points, Sprint ids
and the issue types the project allows).
`epic --plan <path>` prints `EPIC: <KEY>` for a plan with `jira_epic:`, or `SKIPPED: no jira_epic` (exit 0) for a plan
without one. Jira is opt-in: a hotfix, a standalone PR or a plan with no `jira_epic:` never needs Jira.

Phase 2 adds the writes, each behind its own gate:
`qa-draft --epic <KEY> [--question ...]` writes `.caddis/qa/<KEY>-round-<N>.draft.md` (a person edits it) and the
ledger `.caddis/qa/<KEY>.yaml` (JSON, which is valid YAML: ids Q1.. never reused, OPEN | ANSWERED | DEFAULTED |
PARKED, at most 7 OPEN per round). `qa-post --epic <KEY> --round <N>` previews the comment and prints its sha256;
`--approve <8 or 64 hex>` posts it only when the hash matches the text now and the leak lint is clean. qa-post is
refused whenever CADDIS_HEADLESS is set. `qa-pull` reads replies (GET only); `qa-status --gate` exits 1 while a
blocking question is OPEN. `sync-stories --plan <p> [--issue-type T] [--granularity phase|milestone] [--component C]
[--dry-run]` makes one Story per plan phase, idempotent by the label `caddis-<plan>-p<n>`, and never deletes. With
`--granularity milestone` (or `--by-milestone`, or `jira_granularity: milestone` in the plan) it makes one Story per
deliverable milestone of the plan's Tracker, labelled `caddis-<plan>-m-<milestone>`. A component is optional: it is
sent only when `--component` or `jira_component:` names one, and `components` is absent from the request otherwise.
`transition <KEY> --to <status>` moves an issue; `transition-milestone --plan <p> --milestone <ID> --to <status>
[--fix-version <tag>]` moves the Story of one milestone.
`dashboard-setup` (Phase 2b) builds four saved JQL filters and a dev dashboard for any scope (project, component,
Epics, label or raw JQL): it previews and prints a sha256, and `--approve <hash>` writes (never with CADDIS_HEADLESS).
A Jira that refuses the dashboard or gadget calls gets a printed gadget blueprint instead; the filters stay.
`JiraAdapter.request` stays GET only; a write goes through `JiraAdapter.write`, which refuses until the command arms
it, allows only POST/PUT on the REST paths in `_WRITE_ROUTES` and never DELETE.

Keys (the environment first, then `CADDIS_KEYS_FILE` or `~/.caddis/keys.env`):
- `JIRA_URL` (https only) and `JIRA_TOKEN`;
- `JIRA_MODE`: `dc` (the default: a Bearer personal access token, REST v2) or `cloud` (Basic `JIRA_EMAIL` + API token,
  REST v3, ADF bodies);
- field ids, when discovery by schema type is not enough: `JIRA_EPIC_LINK_FIELD`, `JIRA_EPIC_NAME_FIELD`,
  `JIRA_EPIC_STATUS_FIELD`, `JIRA_STORY_POINTS_FIELD`, `JIRA_SPRINT_FIELD`, or a `[fields]` table in
  `CADDIS_JIRA_CONFIG` / `~/.caddis/jira.toml`. The environment wins over the file.

Host lock: every request goes to the scheme, host and port of `JIRA_URL`. A redirect is an error, never followed, so
the Authorization header never reaches another host. Every text from Jira goes through `caddis_redact` (secrets and
personal data) before it is printed.
Exit codes: 0 clean, 1 Jira refused (an HTTP error), 3 not configured or a network failure, 4 bad input.
"""

from __future__ import annotations

import argparse
import base64
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import sys
import tomllib
import urllib.error
from urllib.parse import quote, urlencode, urlsplit
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
from oss_model import _parse_keys_file

DEFAULT_KEYS_FILE = "~/.caddis/keys.env"
DEFAULT_JIRA_CONFIG = "~/.caddis/jira.toml"
MODES = ("dc", "cloud")
FIELD_NAMES = ("epic_link", "epic_name", "epic_status", "story_points", "sprint", "acceptance_criteria")
_FIELD_ID = re.compile(r"customfield_\d+|parent")
ISSUE_KEY = re.compile(r"[A-Z][A-Z0-9_]+-\d+")
_PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]+")
MAX_ERROR_TEXT = 300
MAX_COMMENT_PAGES = 20
WRITE_METHODS = ("POST", "PUT")
_KEY_PART = r"[A-Z][A-Z0-9_]+-\d+"
# The only writes caddis_jira makes, as paths below /rest/api/<2|3>. There is no DELETE: caddis never deletes.
_WRITE_ROUTES = (
    ("POST", re.compile(r"/issue")),                               # create a Story (sync-stories)
    ("PUT", re.compile(rf"/issue/{_KEY_PART}")),                   # update its summary and description
    ("POST", re.compile(rf"/issue/{_KEY_PART}/comment")),          # one approved Q&A round (qa-post)
    ("POST", re.compile(rf"/issue/{_KEY_PART}/transitions")),      # a workflow transition
    ("POST", re.compile(r"/filter")),                              # a saved JQL filter (dashboard-setup)
    ("PUT", re.compile(r"/filter/\d+")),                           # its JQL, when it changed
    ("POST", re.compile(r"/dashboard")),                           # the dev dashboard
    ("POST", re.compile(r"/dashboard/\d+/gadget")),                # a gadget on it
    ("PUT", re.compile(r"/dashboard/\d+/items/\d+/properties/[A-Za-z0-9_.-]+")),  # the gadget's configuration
)
# A Jira that does not offer the dashboard or filter-list calls (or locks them) answers with one of these.
DASHBOARD_REFUSED = (400, 401, 403, 404, 405, 501)
MAX_SNIPPET = 300
CHILDREN_MAX = 50
_ZERO_WIDTH = re.compile(r"[\u200b-\u200f\u2060\ufeff]")


# ---------------------------------------------------------------- config

class ConfigError(Exception):
    """A Jira key is missing or not usable. The text names the variable, never its value."""


@dataclass
class JiraConfig:
    base_url: str
    token: str
    mode: str = "dc"
    email: str | None = None
    fields: dict[str, str] = field(default_factory=dict)

    def __repr__(self) -> str:  # never show the token in a traceback or a log
        return f"JiraConfig(base_url={self.base_url!r}, mode={self.mode!r}, token='***')"


def _field_overrides(env: Mapping[str, str], file_keys: Mapping[str, str] | None = None) -> dict[str, str]:
    path = Path(env.get("CADDIS_JIRA_CONFIG") or DEFAULT_JIRA_CONFIG).expanduser()
    found: dict[str, str] = {}
    if path.is_file():
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot read the Jira config file: {type(exc).__name__}") from None
        table = data.get("fields") or {}
        if not isinstance(table, Mapping):
            raise ConfigError("the Jira config file [fields] must be a table")
        found.update({k: str(v).strip() for k, v in table.items() if k in FIELD_NAMES and str(v).strip()})
    for name in FIELD_NAMES:
        var = f"JIRA_{name.upper()}_FIELD"
        value = (env.get(var) or "").strip() or ((file_keys or {}).get(var) or "").strip()
        if value:
            found[name] = value
    for name, value in found.items():
        if not _FIELD_ID.fullmatch(value):
            raise ConfigError(f"the {name} field id must look like customfield_<n>")
    return found


def load_config(env: Mapping[str, str]) -> JiraConfig:
    """JIRA_URL, JIRA_TOKEN, JIRA_MODE, JIRA_EMAIL and field ids: the environment first, then the keys file."""
    keys_path = env.get("CADDIS_KEYS_FILE") or DEFAULT_KEYS_FILE
    try:
        file_keys = _parse_keys_file(keys_path)
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read the keys file: {type(exc).__name__}") from None

    def value(name: str) -> str:
        return (env.get(name) or "").strip() or (file_keys.get(name) or "").strip()

    for name in ("JIRA_URL", "JIRA_TOKEN"):
        if not value(name):
            raise ConfigError(f"{name} is not set (environment or keys file)")
    base_url = value("JIRA_URL").rstrip("/")
    parts = urlsplit(base_url)
    try:
        parts.port
    except ValueError:
        raise ConfigError("JIRA_URL has a port that is not a number") from None
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment or parts.username:
        raise ConfigError("JIRA_URL must be https://<host>[:port][/context], with no query or user info")
    mode = (value("JIRA_MODE") or "dc").lower()
    if mode not in MODES:
        raise ConfigError("JIRA_MODE must be dc or cloud")
    email = value("JIRA_EMAIL") or None
    if mode == "cloud" and not email:
        raise ConfigError("JIRA_EMAIL is not set (JIRA_MODE=cloud needs it for Basic auth)")
    return JiraConfig(base_url=base_url, token=value("JIRA_TOKEN"), mode=mode, email=email,
                      fields=_field_overrides(env, file_keys))


# ---------------------------------------------------------------- text: wiki markup and ADF

_WIKI_RULES = [
    (re.compile(r"\{(?:code|noformat)(?::[^}]*)?\}"), " "),
    (re.compile(r"\{color(?::[^}]*)?\}"), ""),
    (re.compile(r"\{quote\}|\{panel(?::[^}]*)?\}"), ""),
    (re.compile(r"^h[1-6]\.\s*", re.M), ""),
    (re.compile(r"\[([^|\]]+)\|[^\]]+\]"), r"\1"),
    (re.compile(r"\[(https?://[^\]]+)\]"), r"\1"),
    (re.compile(r"(?<![\w*])\*([^*\n]+)\*(?![\w*])"), r"\1"),
    (re.compile(r"(?<![\w_])_([^_\n]+)_(?![\w_])"), r"\1"),
    (re.compile(r"\{\{([^}]+)\}\}"), r"\1"),
]


def wiki_to_text(text: str | None) -> str:
    """Jira Data Center wiki markup as plain text (headings, emphasis, links and macros removed)."""
    if not text:
        return ""
    for rx, repl in _WIKI_RULES:
        text = rx.sub(repl, text)
    return re.sub(r"[ \t]+", " ", text).strip()


_ADF_BLOCKS = {"paragraph", "heading", "codeBlock", "blockquote", "panel", "rule", "mediaSingle", "table"}


def adf_to_text(node) -> str:
    """An Atlassian Document Format (Jira Cloud) body as plain text. A string passes through; None is ""."""
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    lines: list[str] = []

    def inline(n) -> str:
        kind = n.get("type")
        if kind == "text":
            return n.get("text", "")
        if kind == "hardBreak":
            return "\n"
        if kind == "mention":
            return (n.get("attrs") or {}).get("text", "")
        if kind == "emoji":
            return (n.get("attrs") or {}).get("shortName", "")
        if kind in ("inlineCard", "blockCard"):
            return (n.get("attrs") or {}).get("url", "")
        return "".join(inline(c) for c in n.get("content") or [])

    def block(n, prefix: str = "") -> None:
        kind = n.get("type")
        if kind in ("bulletList", "orderedList"):
            for i, item in enumerate(n.get("content") or [], 1):
                mark = "- " if kind == "bulletList" else f"{i}. "
                for child in item.get("content") or []:
                    block(child, prefix + mark)
            return
        if kind in ("doc", "blockquote", "panel", "table", "tableRow", "tableCell", "tableHeader", "listItem"):
            for child in n.get("content") or []:
                block(child, prefix)
            return
        text = inline(n)
        if kind in _ADF_BLOCKS or text:
            lines.append(prefix + text)
            if kind == "paragraph" and not prefix:
                lines.append("")

    block(node)
    return "\n".join(lines).strip("\n").replace("\n\n\n", "\n\n")


def text_to_adf(text: str) -> dict:
    """Plain text as a minimal ADF document: a blank line starts a paragraph, a line break is a hardBreak."""
    content = []
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    for para in re.split(r"\n\s*\n", text.strip()):
        nodes: list[dict] = []
        for i, line in enumerate(para.split("\n")):
            if i:
                nodes.append({"type": "hardBreak"})
            if line:
                nodes.append({"type": "text", "text": line})
        content.append({"type": "paragraph", "content": nodes})
    return {"type": "doc", "version": 1, "content": content}


# ---------------------------------------------------------------- transport

class JiraError(Exception):
    """A Jira call failed. `status` is the HTTP status, or None for a network failure, a timeout or a refused call.
    The message is already redacted and cut: it never holds the token."""

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


def _origin(url: str) -> tuple[str, str, int | None]:
    parts = urlsplit(url)
    port = parts.port or (443 if parts.scheme == "https" else 80 if parts.scheme == "http" else None)
    return parts.scheme, (parts.hostname or "").lower(), port


def check_key(key: str) -> str:
    key = (key or "").strip().upper()
    if not ISSUE_KEY.fullmatch(key):
        raise ValueError("an issue key looks like PROJ-123")
    return key


# ---------------------------------------------------------------- adapters

class JiraAdapter:
    """The seam between caddis and one Jira flavour. Subclasses set the REST version, auth and body format."""

    mode = ""
    api = ""

    def __init__(self, base_url: str, token: str, timeout: float = 20.0, send: Callable | None = None):
        self.base_url = base_url.rstrip("/")
        self._token = token
        self.timeout = timeout
        self._send = send or _default_send
        self.writes_armed = False
        secrets = caddis_redact.load_secrets(Path.home())
        if token:
            secrets = secrets + [token]
        self._secrets = sorted(set(secrets), key=len, reverse=True)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(base_url={self.base_url!r})"

    # -- hooks for the subclasses
    def _auth_header(self) -> str:
        raise NotImplementedError

    def body_text(self, value) -> str:
        raise NotImplementedError

    @staticmethod
    def children_jql(key: str) -> list[str]:
        raise NotImplementedError

    # -- text hygiene
    def clean(self, text: str, limit: int | None = MAX_SNIPPET) -> str:
        """Secrets and personal data masked, white space folded, cut to `limit` characters."""
        text = _ZERO_WIDTH.sub("", text or "")  # first: a hidden mark inside a secret must not dodge redaction
        text = caddis_redact.redact_pii(caddis_redact.redact(text, self._secrets))
        text = re.sub(r"\s+", " ", text).strip()
        return text[:limit] if limit else text

    # -- requests
    def request(self, method: str, path: str, query: dict | None = None) -> dict | list:
        """The read path: GET only. A write goes through `write()`, which a command must arm first."""
        if method != "GET":
            raise JiraError(None, f"caddis_jira request() is read-only: {method} refused (writes use write())")
        return self.get_url(self.base_url + path + ("?" + urlencode(query) if query else ""))

    def get_url(self, url: str) -> dict | list:
        """GET an absolute URL on the JIRA_URL origin (scheme, host and port). Any other origin is refused."""
        return self._call("GET", url)

    def arm_writes(self) -> None:
        """Allow `write()`. Only a command whose gate passed calls this (an approved hash, or no --dry-run)."""
        self.writes_armed = True

    def write(self, method: str, path: str, body: dict) -> dict:
        """POST or PUT one allow-listed REST path (`/issue`, `/issue/<KEY>`, `.../comment`, `.../transitions`).
        Refused before any request when not armed, for any other method or path, and never a DELETE."""
        if not self.writes_armed:
            raise JiraError(None, f"write refused: {method} {path} is not armed (a dry run or a failed gate); "
                                  "no request sent")
        if method not in WRITE_METHODS or not any(m == method and rx.fullmatch(path) for m, rx in _WRITE_ROUTES):
            raise JiraError(None, f"write refused: {method} {path} is not an allowed Jira write (caddis never "
                                  "deletes); no request sent")
        data = self._call(method, f"{self.base_url}/rest/api/{self.api}{path}", body)
        return data if isinstance(data, dict) else {}

    def _call(self, method: str, url: str, body: dict | None = None) -> dict | list:
        if _origin(url) != _origin(self.base_url):
            raise JiraError(None, "host lock: the URL is not on the JIRA_URL origin; no request sent")
        path = urlsplit(url).path
        data = None if body is None else json.dumps(body).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", self._auth_header())
        req.add_header("Accept", "application/json")
        if data is not None:
            req.add_header("Content-Type", "application/json")
        try:
            status, raw = self._send(req, self.timeout)
        except JiraError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            reason = self.clean(f"{type(exc).__name__}: {exc}", MAX_ERROR_TEXT)
            raise JiraError(None, f"network error {method} {path}: {reason}") from None
        text = (raw or b"").decode("utf-8", errors="replace")
        if 300 <= status < 400:
            raise JiraError(status, f"HTTP {status} {method} {path}: a redirect, not followed. JIRA_URL may miss "
                                    "the context path of the server (for example /jira)")
        if not 200 <= status < 300:
            raise JiraError(status, f"HTTP {status} {method} {path}: {self.clean(text, MAX_ERROR_TEXT)}")
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except ValueError:
            raise JiraError(status, f"HTTP {status} {method} {path}: the answer is not JSON") from None

    def _get(self, path: str, query: dict | None = None):
        return self.request("GET", f"/rest/api/{self.api}{path}", query)

    # -- reads
    def server_info(self) -> dict:
        data = self._get("/serverInfo")
        return {"mode": self.mode, "version": str(data.get("version") or ""),
                "deployment": str(data.get("deploymentType") or "")}

    def myself(self) -> dict:
        """Only an opaque id and the active flag: never a name or an e-mail address."""
        data = self._get("/myself")
        return {"id": str(data.get("accountId") or data.get("key") or data.get("name") or ""),
                "active": bool(data.get("active", True))}

    def get_issue(self, key: str) -> dict:
        key = check_key(key)
        raw = self._get(f"/issue/{quote(key)}")
        return self.normalize(raw)

    def normalize(self, raw: dict) -> dict:
        f = raw.get("fields") or {}
        status = f.get("status") or {}
        parent = f.get("parent") or {}
        return {
            "key": raw.get("key"),
            "type": (f.get("issuetype") or {}).get("name"),
            "subtask": bool((f.get("issuetype") or {}).get("subtask")),
            "status": status.get("name"),
            "status_category": (status.get("statusCategory") or {}).get("key"),
            "summary": self.clean(str(f.get("summary") or "")),
            "description": self.clean(self.body_text(f.get("description"))),
            "project": (f.get("project") or {}).get("key"),
            "parent": parent.get("key"),
            "labels": [self.clean(str(label), None) for label in f.get("labels") or []],
            "custom_set": sorted(k for k, v in f.items() if k.startswith("customfield_") and v not in (None, "", [])),
            "raw_fields": f,
        }

    def transitions(self, key: str) -> list[tuple[str, str]]:
        return [(t["name"], t["to"]) for t in self.transition_list(key)]

    def transition_list(self, key: str) -> list[dict]:
        """The transitions open from the issue's status now: id, name and the target status name."""
        data = self._get(f"/issue/{quote(check_key(key))}/transitions")
        return [{"id": str(t.get("id") or ""), "name": str(t.get("name") or ""),
                 "to": str((t.get("to") or {}).get("name") or "")} for t in data.get("transitions") or []]

    def comment_records(self, key: str) -> list[dict]:
        """Every comment as {id, created, text}: plain text with line breaks kept, NOT yet redacted (the caller
        redacts what it keeps). Pages through `startAt` with a hard cap."""
        key = check_key(key)
        out: list[dict] = []
        start = 0
        for _ in range(MAX_COMMENT_PAGES):
            data = self._get(f"/issue/{quote(key)}/comment", {"startAt": start, "maxResults": 100})
            page = data.get("comments") or []
            for c in page:
                out.append({"id": str(c.get("id") or ""), "created": str(c.get("created") or ""),
                            "text": _ZERO_WIDTH.sub("", self.body_text(c.get("body")))})
            start += len(page)
            total = data.get("total")
            if not page or not isinstance(total, int) or start >= total:
                break
        return out

    def comments(self, key: str) -> list[str]:
        data = self._get(f"/issue/{quote(check_key(key))}/comment")
        return [self.clean(self.body_text(c.get("body"))) for c in data.get("comments") or []]

    def field_list(self) -> list[dict]:
        data = self._get("/field")
        return [{"id": f.get("id"), "name": f.get("name"), "custom": (f.get("schema") or {}).get("custom")}
                for f in data if isinstance(f, dict)]

    def search(self, jql: str, fields: list[str], max_results: int = CHILDREN_MAX) -> dict:
        raise NotImplementedError

    def issue_types(self, project: str) -> list[dict]:
        if not _PROJECT_KEY.fullmatch(project or ""):
            raise ValueError("a project key looks like PROJ")
        data = self._get(f"/issue/createmeta/{quote(project)}/issuetypes")
        values = data.get("values") or data.get("issueTypes") or []
        return [{"id": str(t.get("id") or ""), "name": t.get("name"), "subtask": bool(t.get("subtask"))}
                for t in values]

    def create_screen_fields(self, project: str, type_id: str) -> set[str] | None:
        """The field ids on the create screen of one issue type, or None when Jira cannot say (old server)."""
        if not _PROJECT_KEY.fullmatch(project or "") or not re.fullmatch(r"\d+", type_id or ""):
            return None
        found: set[str] = set()
        start = 0
        for _ in range(10):
            try:
                data = self._get(f"/issue/createmeta/{quote(project)}/issuetypes/{type_id}",
                                 {"startAt": start, "maxResults": 200})
            except JiraError as err:
                if err.status in (400, 404) and start == 0:
                    return None
                raise
            values = data.get("values") or data.get("fields") or []
            found |= {str(v.get("fieldId") or v.get("key") or "") for v in values if isinstance(v, dict)}
            start += len(values)
            total = data.get("total")
            if not values or data.get("isLast") is True or not isinstance(total, int) or start >= total:
                break
        return found - {""}

    def project_components(self, project: str) -> list[str] | None:
        """The component names of a project (an empty list when it has none), or None when Jira cannot say."""
        if not _PROJECT_KEY.fullmatch(project or ""):
            return None
        try:
            data = self._get(f"/project/{quote(project)}/components")
        except JiraError as err:
            if err.status in (400, 401, 403, 404):
                return None
            raise
        if not isinstance(data, list):
            return None
        return [str(c.get("name") or "") for c in data if isinstance(c, dict)]

    # -- dashboard-setup reads (the writes go through write())
    @staticmethod
    def epics_clause(keys: list[str]) -> str:
        raise NotImplementedError

    def list_filters(self, prefix: str) -> list[dict]:
        """Filters this login can see, as {id, name, jql, source}. A call this Jira does not have is skipped."""
        raise NotImplementedError

    def find_dashboard(self, name: str) -> str | None:
        """The id of an existing dashboard with exactly this name, or None (also when Jira cannot list them)."""
        raise NotImplementedError

    def _filter_rows(self, path: str, source: str, query: dict | None = None) -> list[dict]:
        try:
            data = self._get(path, query)
        except JiraError as err:
            if err.status in DASHBOARD_REFUSED:
                return []
            raise
        items = data.get("values") if isinstance(data, dict) else data
        return [{"id": str(f.get("id") or ""), "name": str(f.get("name") or ""), "jql": str(f.get("jql") or ""),
                 "source": source} for f in items or [] if isinstance(f, dict) and f.get("id")]

    def filter_url(self, filter_id: str) -> str:
        return f"{self.base_url}/issues/?filter={quote(str(filter_id))}"

    def dashboard_url(self, dashboard_id: str) -> str:
        return f"{self.base_url}/secure/Dashboard.jspa?selectPageId={quote(str(dashboard_id))}"

    # -- body formats: DC wiki markup, Cloud ADF
    def qa_payload(self, epic: str, rnd: int, open_qs: list[dict], defaults: list[dict]) -> dict:
        raise NotImplementedError

    def story_description(self, goal: str, exit_gate: str, marker: str):
        raise NotImplementedError

    def epic_link(self, epic: str, epic_link_field: str | None) -> dict:
        raise NotImplementedError

    def text_value(self, text: str):
        """A plain paragraph in the body format of a multi-line text field (Acceptance Criteria)."""
        raise NotImplementedError


class JiraDCAdapter(JiraAdapter):
    """Jira Data Center / Server: REST v2, Bearer personal access token, wiki-markup bodies, Epic Link field."""

    mode = "dc"
    api = "2"

    def _auth_header(self) -> str:
        return f"Bearer {self._token}"

    def body_text(self, value) -> str:
        return wiki_to_text(value if isinstance(value, str) else adf_to_text(value))

    @staticmethod
    def children_jql(key: str) -> list[str]:
        return [f'"Epic Link" = {key}', f"parent = {key}"]

    def search(self, jql: str, fields: list[str], max_results: int = CHILDREN_MAX) -> dict:
        data = self._get("/search", {"jql": jql, "fields": ",".join(fields), "maxResults": max_results})
        issues = data.get("issues") or []
        total = data.get("total")
        return {"total": total if isinstance(total, int) else len(issues), "issues": issues,
                "more": isinstance(total, int) and total > len(issues)}

    def issue_types(self, project: str) -> list[dict]:
        try:
            return super().issue_types(project)
        except JiraError as err:
            if err.status != 404:
                raise
        # Jira before 8.4 has only the old createmeta form.
        data = self._get("/issue/createmeta", {"projectKeys": project})
        projects = data.get("projects") or [{}]
        return [{"id": str(t.get("id") or ""), "name": t.get("name"), "subtask": bool(t.get("subtask"))}
                for t in projects[0].get("issuetypes") or []]

    @staticmethod
    def epics_clause(keys: list[str]) -> str:
        return f'"Epic Link" in ({", ".join(keys)})'

    def list_filters(self, prefix: str) -> list[dict]:
        found: list[dict] = []
        for path, source in (("/filter/my", "my"), ("/filter/favourite", "favourite")):
            found += self._filter_rows(path, source)
        return found

    def find_dashboard(self, name: str) -> str | None:
        try:
            data = self._get("/dashboard", {"filter": "my", "maxResults": 100})
        except JiraError as err:
            if err.status in DASHBOARD_REFUSED:
                return None
            raise
        for d in (data.get("dashboards") if isinstance(data, dict) else None) or []:
            if isinstance(d, dict) and str(d.get("name") or "") == name and d.get("id"):
                return str(d["id"])
        return None

    def qa_payload(self, epic: str, rnd: int, open_qs: list[dict], defaults: list[dict]) -> dict:
        return {"body": qa_round_wiki(epic, rnd, open_qs, defaults)}

    def story_description(self, goal: str, exit_gate: str, marker: str) -> str:
        return "\n".join(["h3. Goal", _md_to_wiki(goal) or "-", "", "h3. Exit gate", _md_to_wiki(exit_gate) or "-",
                          "", "----", f"_{STORY_FOOTER}_ \\[{marker}\\]"])

    def epic_link(self, epic: str, epic_link_field: str | None) -> dict:
        if not epic_link_field:
            raise JiraError(None, "no Epic Link field found: set JIRA_EPIC_LINK_FIELD (or [fields] epic_link)")
        return {epic_link_field: epic}

    def text_value(self, text: str) -> str:
        return _md_to_wiki(text)


class JiraCloudAdapter(JiraAdapter):
    """Jira Cloud: REST v3, Basic e-mail + API token, ADF bodies, `parent` for the Epic, accountId users."""

    mode = "cloud"
    api = "3"

    def __init__(self, base_url: str, token: str, email: str | None = None, timeout: float = 20.0,
                 send: Callable | None = None):
        super().__init__(base_url, token, timeout=timeout, send=send)
        self._email = email or ""
        if token:
            pair = base64.b64encode(f"{self._email}:{token}".encode("utf-8")).decode("ascii")
            self._secrets = sorted(set(self._secrets + [pair]), key=len, reverse=True)

    def _auth_header(self) -> str:
        pair = f"{self._email}:{self._token}".encode("utf-8")
        return "Basic " + base64.b64encode(pair).decode("ascii")

    def body_text(self, value) -> str:
        return adf_to_text(value)

    @staticmethod
    def children_jql(key: str) -> list[str]:
        return [f"parent = {key}", f'"Epic Link" = {key}']

    def search(self, jql: str, fields: list[str], max_results: int = CHILDREN_MAX) -> dict:
        data = self._get("/search/jql", {"jql": jql, "fields": ",".join(fields), "maxResults": max_results})
        issues = data.get("issues") or []
        # /search/jql has no total: report what came back, and say when more pages exist.
        return {"total": len(issues), "issues": issues, "more": data.get("isLast") is False}

    @staticmethod
    def epics_clause(keys: list[str]) -> str:
        return f"parent in ({', '.join(keys)})"

    def list_filters(self, prefix: str) -> list[dict]:
        found = self._filter_rows("/filter/my", "my", {"expand": "jql"})
        found += self._filter_rows("/filter/favourite", "favourite", {"expand": "jql"})
        found += self._filter_rows("/filter/search", "search",
                                   {"filterName": prefix, "expand": "jql", "maxResults": 100})
        return found

    def find_dashboard(self, name: str) -> str | None:
        try:
            data = self._get("/dashboard/search", {"dashboardName": name, "maxResults": 100})
        except JiraError as err:
            if err.status in DASHBOARD_REFUSED:
                return None
            raise
        for d in (data.get("values") if isinstance(data, dict) else None) or []:
            if isinstance(d, dict) and str(d.get("name") or "") == name and d.get("id"):
                return str(d["id"])
        return None

    def qa_payload(self, epic: str, rnd: int, open_qs: list[dict], defaults: list[dict]) -> dict:
        return {"body": qa_round_to_adf(epic, rnd, open_qs, defaults)}

    def story_description(self, goal: str, exit_gate: str, marker: str) -> dict:
        return {"type": "doc", "version": 1, "content": [
            _adf_heading(3, "Goal"), _adf_para(goal or "-"), _adf_heading(3, "Exit gate"), _adf_para(exit_gate or "-"),
            {"type": "rule"}, _adf_para(f"{STORY_FOOTER} [{marker}]")]}

    def epic_link(self, epic: str, epic_link_field: str | None) -> dict:
        return {"parent": {"key": epic}}

    def text_value(self, text: str) -> dict:
        return {"type": "doc", "version": 1, "content": [_adf_para(text or "-")]}


def make_adapter(cfg: JiraConfig, send: Callable | None = None) -> JiraAdapter:
    if cfg.mode == "cloud":
        adapter: JiraAdapter = JiraCloudAdapter(cfg.base_url, cfg.token, email=cfg.email, send=send)
    else:
        adapter = JiraDCAdapter(cfg.base_url, cfg.token, send=send)
    adapter.field_overrides = dict(cfg.fields)
    return adapter


# ---------------------------------------------------------------- schema discovery

# Agile field types by their schema `custom` key: stable across instances, unlike the customfield number.
_SCHEMA_KEYS = {
    "epic_link": ("com.pyxis.greenhopper.jira:gh-epic-link",),
    "epic_name": ("com.pyxis.greenhopper.jira:gh-epic-label",),
    "epic_status": ("com.pyxis.greenhopper.jira:gh-epic-status",),
    "sprint": ("com.pyxis.greenhopper.jira:gh-sprint",),
    "story_points": ("com.pyxis.greenhopper.jira:jsw-story-points",),
}
_STORY_POINT_NAMES = ("story points", "story point estimate")
_ACCEPTANCE_NAMES = ("acceptance criteria",)


def discover_fields(fields: list[dict], overrides: Mapping[str, str] | None = None) -> dict[str, str | None]:
    """The agile field ids from `/field`, matched by schema type (Story Points also by name). Overrides win."""
    found: dict[str, str | None] = {name: None for name in FIELD_NAMES}
    for name, kinds in _SCHEMA_KEYS.items():
        for f in fields:
            if f.get("custom") in kinds:
                found[name] = f.get("id")
                break
    if found["story_points"] is None:
        for f in fields:
            if str(f.get("name") or "").strip().lower() in _STORY_POINT_NAMES and str(f.get("id")).startswith(
                    "customfield_"):
                found["story_points"] = f.get("id")
                break
    for f in fields:
        if str(f.get("name") or "").strip().lower() in _ACCEPTANCE_NAMES and str(f.get("id")).startswith(
                "customfield_"):
            found["acceptance_criteria"] = f.get("id")
            break
    found.update({k: v for k, v in (overrides or {}).items() if k in found})
    return found


def summarize_children(issues: list[dict], field_names: Mapping[str, str]) -> dict:
    """Counts of issue types and statuses and the custom fields the children use. No summaries, no people."""
    types: Counter = Counter()
    statuses: Counter = Counter()
    used: set[str] = set()
    for issue in issues:
        f = issue.get("fields") or {}
        types[(f.get("issuetype") or {}).get("name") or "?"] += 1
        statuses[(f.get("status") or {}).get("name") or "?"] += 1
        used.update(k for k, v in f.items() if k.startswith("customfield_") and v not in (None, "", []))
    return {"types": dict(types), "statuses": dict(statuses),
            "custom_fields": {k: field_names.get(k, "?") for k in sorted(used)}}


def find_children(adapter: JiraAdapter, key: str, fields: list[str],
                  max_results: int = CHILDREN_MAX) -> tuple[str | None, dict | None, str | None]:
    """(jql, result, error): the first child query that finds issues, else the first one Jira accepted."""
    key = check_key(key)
    accepted: tuple[str, dict] | None = None
    last_error = None
    for jql in adapter.children_jql(key):
        try:
            result = adapter.search(jql, fields, max_results)
        except JiraError as err:
            if err.status != 400:
                raise
            last_error = str(err)
            continue
        if result["issues"]:
            return jql, result, None
        accepted = accepted or (jql, result)
    if accepted:
        return accepted[0], accepted[1], None
    return None, None, last_error


# ---------------------------------------------------------------- opt-in: the plan's Epic

_NONE_VALUES = {"", "none", "null", "~", "n/a", "-"}


def resolve_plan_epic(plan) -> str | None:
    """The plan's `jira_epic:` key, or None when it is absent or `none`. A plan path or a parsed frontmatter dict.

    None means Jira does not apply to this work: every caller skips cleanly (exit 0). A value that is not an issue key
    raises ValueError, so a typo never reads as an opt-out."""
    if isinstance(plan, Mapping):
        meta = plan
    else:
        meta, _ = split_document(Path(plan).read_text(encoding="utf-8"))
    raw = str(meta.get("jira_epic") or "").strip().strip('"').strip("'")
    if raw.lower() in _NONE_VALUES:
        return None
    return check_key(raw)


# ---------------------------------------------------------------- leak lint (Phase 2): text that leaves for Jira

@dataclass
class LintHit:
    line: int
    rule: str
    excerpt: str


# A dotted name is a host name when it has 2+ dots and does not end in a file extension, or 1 dot and a host suffix.
_FILE_EXTS = frozenset(
    "py md ts tsx js jsx mjs cjs json yaml yml toml txt csv tsv html htm css scss sql ps1 psm1 sh bat cmd xml lock "
    "cfg ini env log png jpg jpeg gif svg pdf docx xlsx pptx zip gz whl ipynb rs go java kt cs cpp hpp rb php vue"
    .split())
_HOST_SUFFIXES = frozenset(
    "local lan internal corp intra intranet localdomain priv private com net org io biz info co uk ie eu de nl fr "
    "cloud dev app".split())
_URL = re.compile(r"\b[a-z][a-z0-9+.-]{1,15}://[^\s<>\"'`)\]|]+", re.I)
_IPV4 = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?!\.?\d)(?!\w)")
_DOTTED = re.compile(r"(?<![\w@./\\-])((?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+([A-Za-z]{2,24}))(?![\w-])")
_PATHS = (
    re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]"),                     # C:\ or C:/
    re.compile(r"\\\\[A-Za-z0-9._$-]+\\"),                            # \\server\share
    re.compile(r"(?<![\w.~/-])/(?:Users|home|root|etc|var|opt|srv|mnt|tmp|usr|private|Volumes)/"),
    re.compile(r"(?<![\w.])~[/\\]"),
)
_SQL_IDENT = r"[\w\[\]\".#@]+"
_SQL_DML = (
    re.compile(rf"\b(SELECT)\s+(?:TOP\s+\d+\s+|DISTINCT\s+)?(\*|{_SQL_IDENT}(?:\s*,\s*{_SQL_IDENT})*)\s+(FROM)\s+"
               rf"({_SQL_IDENT})", re.I),
    re.compile(rf"\b(INSERT)\s+(INTO)\s+({_SQL_IDENT})", re.I),
    re.compile(rf"\b(UPDATE)\s+({_SQL_IDENT})\s+(SET)\s+\w", re.I),
    re.compile(rf"\b(DELETE)\s+(FROM)\s+({_SQL_IDENT})", re.I),
)
_SQL_DDL = re.compile(r"\b(?:ALTER|CREATE|DROP|TRUNCATE)\s+(?:OR\s+(?:ALTER|REPLACE)\s+)?(?:TABLE|VIEW|PROC|PROCEDURE"
                      r"|INDEX|SCHEMA|DATABASE|FUNCTION|TRIGGER)\b|\bMERGE\s+INTO\b|\bEXEC(?:UTE)?\s+[\w\[\]]+\.[\w\[\]]+",
                      re.I)
_TABLES = (
    re.compile(r"(?<![\w.])(?:dbo|rs|stg|staging|dw|dwh|etl|ods|mart|lnd|landing|cdc)\.[A-Za-z_#][\w$#]*", re.I),
    re.compile(r"\[[^\]\s]+\]\.\[[^\]\s]+\]"),
    re.compile(r"(?<![\w])(?:rs|tbl|vw|usp|stg|dim|fact)_[A-Za-z0-9_]+", re.I),
)
_TOKENS = (
    re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_\w{20,}|xox[abposr]-[\w-]{10,}|AKIA[0-9A-Z]{16}"
               r"|sk-[A-Za-z0-9_-]{20,})"),
    re.compile(r"\beyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{4,}"),
    re.compile(r"\b(?:bearer|basic)\s+[A-Za-z0-9._~+/=-]{16,}", re.I),
    re.compile(r"\b(?:password|passwd|pwd|secret|token|api[_-]?key|client[_-]?secret)\s*[:=]\s*\S{4,}", re.I),
    re.compile(r"(?<![\w+/=-])(?=[A-Za-z0-9+/=]*\d)(?=[A-Za-z0-9+/=]*[A-Za-z])[A-Za-z0-9+/=]{32,}(?![\w+/=-])"),
)


def _sql_hit(m: re.Match) -> bool:
    """English says "select the report from the menu"; SQL says SELECT name FROM dbo.Bills. A match counts when its
    keywords are upper case, or the names in it look like code (a star, a comma list, a dot, an underscore, brackets)."""
    words = [g for g in m.groups() if g and g.upper() in ("SELECT", "FROM", "INSERT", "INTO", "UPDATE", "SET", "DELETE")]
    names = [g for g in m.groups() if g and g not in words]
    if words and all(w.isupper() for w in words):
        return True
    return any(re.search(r"[*,.\[\]_#@\"]", n) for n in names)


def leak_lint(text: str, secrets=(), allowed_origin: tuple | None = None) -> list[LintHit]:
    """Hits that block text from going to Jira: URLs (except https on the Jira origin), host names, IP addresses,
    absolute paths, SQL, table names, secrets and personal data. Each excerpt is redacted. Empty list = clean."""
    hits: list[LintHit] = []
    secrets = list(secrets or ())

    def hit(n: int, rule: str, raw: str) -> None:
        excerpt = caddis_redact.redact_pii(caddis_redact.redact(raw, secrets))
        for rx in _TOKENS:  # before the cut: a cut token is too short for the patterns
            excerpt = rx.sub("***", excerpt)
        excerpt = excerpt[:60]
        if not any(h.line == n and h.rule == rule for h in hits):
            hits.append(LintHit(n, rule, excerpt))

    for n, line in enumerate((text or "").splitlines() or [""], 1):
        line = _ZERO_WIDTH.sub("", line)
        rest = line
        for m in _URL.finditer(line):
            url = m.group(0).rstrip(".,;:!?")
            try:
                ok = url.lower().startswith("https://") and allowed_origin is not None and _origin(url) == allowed_origin
            except ValueError:
                ok = False
            if not ok:
                hit(n, "url", url)
            rest = rest.replace(m.group(0), " ")
        for m in _IPV4.finditer(rest):
            hit(n, "ip-address", m.group(0))
        for m in _DOTTED.finditer(rest):
            name, last = m.group(1), m.group(2)
            dots = name.count(".")
            if (dots >= 2 and last.lower() not in _FILE_EXTS) or (dots == 1 and last.lower() in _HOST_SUFFIXES):
                hit(n, "hostname", name)
        for rx in _PATHS:
            m = rx.search(rest)
            if m:
                hit(n, "path", rest[m.start():m.start() + 40])
        for rx in _SQL_DML:
            for m in rx.finditer(rest):
                if _sql_hit(m):
                    hit(n, "sql", m.group(0))
        m = _SQL_DDL.search(rest)
        if m:
            hit(n, "sql", m.group(0))
        for rx in _TABLES:
            m = rx.search(rest)
            if m:
                hit(n, "table-name", m.group(0))
        for rx in _TOKENS:
            m = rx.search(line)
            if m:
                hit(n, "secret", m.group(0))
        if secrets and caddis_redact.redact(line, secrets) != line:
            hit(n, "secret", line)
        if caddis_redact.redact_pii(line) != line:
            hit(n, "personal-data", line)
    return hits


def _lint_lines(hits: list[LintHit]) -> str:
    return "; ".join(f"{h.rule} (line {h.line}: {h.excerpt})" for h in hits)


# ---------------------------------------------------------------- body helpers: wiki markup and ADF for writes

_WIKI_SPECIAL = re.compile(r"([{}\[\]|*_^~+])")


def _wiki_escape(text: str) -> str:
    return _WIKI_SPECIAL.sub(r"\\\1", text or "")


def _md_to_wiki(text: str) -> str:
    """Plan Markdown (one paragraph) as safe wiki markup: `code` -> {{code}}, **bold** -> *bold*, the rest escaped."""
    out: list[str] = []
    for part in re.split(r"(`[^`]+`)", text or ""):
        if len(part) > 2 and part.startswith("`") and part.endswith("`"):
            out.append("{{" + part[1:-1].replace("{", "\\{").replace("}", "\\}") + "}}")
        else:
            bold = re.split(r"\*\*([^*]+)\*\*", part)
            out.append("".join(f"*{_wiki_escape(p)}*" if i % 2 else _wiki_escape(p) for i, p in enumerate(bold)))
    return "".join(out)


def _adf_para(text: str, strong: str | None = None) -> dict:
    nodes: list[dict] = []
    if strong:
        nodes.append({"type": "text", "text": strong, "marks": [{"type": "strong"}]})
    if text:
        nodes.append({"type": "text", "text": (" " if strong else "") + text})
    return {"type": "paragraph", "content": nodes}


def _adf_heading(level: int, text: str) -> dict:
    return {"type": "heading", "attrs": {"level": level}, "content": [{"type": "text", "text": text}]}


# ---------------------------------------------------------------- Q&A (Phase 2): ledger, editable draft, gate

QA_STATES = ("OPEN", "ANSWERED", "DEFAULTED", "PARKED")
DRAFT_STATES = ("OPEN", "DEFAULTED", "PARKED")
MAX_OPEN_PER_ROUND = 7
MAX_ANSWER = 2000
REMOVED_NOTE = "removed from the draft before posting"
QA_REPLY_HINT = ("Please reply in a new comment. Start each answer on its own line with the question id, "
                 "for example: Q1: your answer.")
QA_DEFAULTS_HEAD = "Defaults we will use unless you reply"
STABLE_RUN = 'python "<home>/.caddis/bin/caddis_run.py" caddis_jira.py'


def qa_marker(epic: str, rnd: int) -> str:
    return f"caddis-qa:{epic}:r{rnd}"


def _qa_rows(open_qs: list[dict], defaults: list[dict]) -> list[tuple[str, str, str]]:
    """The flat summary table: (id, blocking, status)."""
    return ([(q["id"], "yes" if q.get("blocking", True) else "no", "open") for q in open_qs]
            + [(q["id"], "yes" if q.get("blocking", True) else "no", "default") for q in defaults])


def qa_round_wiki(epic: str, rnd: int, open_qs: list[dict], defaults: list[dict]) -> str:
    """One Q&A round as Jira wiki markup (Data Center): numbered question blocks, then a flat summary table."""
    lines = [f"h3. Questions for {epic}, round {rnd}", QA_REPLY_HINT, ""]
    lines += [f"*{q['id']}* {_wiki_escape(q['text'])}" for q in open_qs]
    if defaults:
        lines += ["", f"h4. {QA_DEFAULTS_HEAD}"]
        lines += [f"*{q['id']}* {_wiki_escape(q['text'])} Default: {_wiki_escape(q.get('default') or '')}"
                  for q in defaults]
    lines += ["", "||Id||Blocking||Status||"] + [f"|{a}|{b}|{c}|" for a, b, c in _qa_rows(open_qs, defaults)]
    lines += ["", f"\\[{qa_marker(epic, rnd)}\\]"]
    return "\n".join(lines)


def _adf_table(header: tuple, rows: list[tuple]) -> dict:
    def cell(kind: str, text: str) -> dict:
        return {"type": kind, "content": [_adf_para(text)]}
    return {"type": "table", "content": [{"type": "tableRow", "content": [cell("tableHeader", h) for h in header]}]
            + [{"type": "tableRow", "content": [cell("tableCell", c) for c in row]} for row in rows]}


def qa_round_to_adf(epic: str, rnd: int, open_qs: list[dict], defaults: list[dict]) -> dict:
    """One Q&A round as an ADF document (Cloud): the ids in bold, one paragraph each, then a summary table."""
    content = [_adf_heading(3, f"Questions for {epic}, round {rnd}"), _adf_para(QA_REPLY_HINT)]
    content += [_adf_para(q["text"], strong=q["id"]) for q in open_qs]
    if defaults:
        content.append(_adf_heading(4, QA_DEFAULTS_HEAD))
        content += [_adf_para(f"{q['text']} Default: {q.get('default') or ''}", strong=q["id"]) for q in defaults]
    content.append(_adf_table(("Id", "Blocking", "Status"), _qa_rows(open_qs, defaults)))
    content.append(_adf_para(f"[{qa_marker(epic, rnd)}]"))
    return {"type": "doc", "version": 1, "content": content}


QA_FORMAT = 1  # bump when the rendered comment changes shape: an old approval then no longer matches


def qa_content_hash(epic: str, rnd: int, open_qs: list[dict], defaults: list[dict]) -> str:
    """sha256 of the canonical round content (epic, round, ids, texts, defaults, blocking flags). The DC and Cloud
    payloads are pure functions of it, so the hash is the same before and after the mode is known."""
    content = {"format": QA_FORMAT, "epic": epic, "round": rnd,
               "open": [{"id": q["id"], "text": q["text"], "blocking": q.get("blocking", True)} for q in open_qs],
               "defaults": [{"id": q["id"], "text": q["text"], "default": q.get("default"),
                             "blocking": q.get("blocking", True)} for q in defaults]}
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def approval_matches(given: str, digest: str) -> bool:
    """`--approve` takes the 8-character prefix or the full 64-character sha256 (hex, any case)."""
    given = (given or "").strip().lower()
    if len(given) not in (8, 64) or not re.fullmatch(r"[0-9a-f]+", given):
        return False
    return hmac.compare_digest(given, digest[:len(given)])


def is_headless(env: Mapping[str, str]) -> bool:
    value = (env.get("CADDIS_HEADLESS") or "").strip()
    return bool(value) and value != "0"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _cid(value) -> int:
    """A Jira comment id as a number (ids grow with time on DC and Cloud); -1 when it is not a number."""
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return -1


def qa_dir(root) -> Path:
    return Path(root) / ".caddis" / "qa"


def ledger_path(root, epic: str) -> Path:
    return qa_dir(root) / f"{epic}.yaml"


def draft_path(root, epic: str, rnd: int) -> Path:
    return qa_dir(root) / f"{epic}-round-{rnd}.draft.md"


def new_ledger(epic: str) -> dict:
    return {"_about": "caddis Q&A ledger. JSON, which is also valid YAML. Edit the round draft, not this file.",
            "epic": epic, "next_id": 1, "last_synced_comment_id": None, "rounds": [], "questions": [],
            "needs_confirmation": []}


def load_ledger(path: Path, epic: str) -> dict:
    """The ledger, or a new one when the file is missing. JSON first (stdlib); PyYAML only when installed."""
    if not path.is_file():
        return new_ledger(epic)
    text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except ValueError:
        try:
            import yaml  # optional: a person may have re-saved the ledger as block YAML
        except ImportError:
            raise ValueError(f"{path.name} is not JSON-compatible YAML and PyYAML is not installed") from None
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError(f"{path.name} is not valid YAML: {type(exc).__name__}") from None
    if not isinstance(data, dict) or not isinstance(data.get("questions"), list) or not isinstance(
            data.get("rounds"), list) or not isinstance(data.get("next_id"), int):
        raise ValueError(f"{path.name} is not a caddis Q&A ledger")
    if data.get("epic") != epic:
        raise ValueError(f"{path.name} belongs to {data.get('epic')}, not {epic}")
    return data


def save_ledger(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _round_rec(ledger: dict, rnd: int) -> dict | None:
    return next((r for r in ledger["rounds"] if r.get("round") == rnd), None)


def _round_qs(ledger: dict, rnd: int) -> list[dict]:
    return [q for q in ledger["questions"] if q.get("round") == rnd]


def _add_question(ledger: dict, rnd: int, text: str, state: str = "OPEN", default: str | None = None,
                  blocking: bool = True) -> dict:
    q = {"id": f"Q{ledger['next_id']}", "round": rnd, "state": state, "text": text, "default": default,
         "blocking": blocking, "answer": None, "answer_comment_id": None, "answered_at": None, "note": None,
         "decision": None}
    ledger["next_id"] += 1
    ledger["questions"].append(q)
    return q


def render_draft(ledger: dict, rnd: int) -> str:
    epic = ledger["epic"]
    lines = [f"<!-- caddis-qa draft: epic={epic} round={rnd} -->", f"# Questions for {epic}, round {rnd}", "",
             "Edit the questions, then preview the Jira comment and its approval hash:", "",
             f"    {STABLE_RUN} qa-post --epic {epic} --round {rnd}", "",
             "How to edit:",
             "- One question per `### Q<n>` heading. Change the text under it freely.",
             "- Add a question: a heading `### NEW` with the text under it. It gets the next free id.",
             "- Remove a question: delete its heading and text. Its id is parked and never reused.",
             "- Do not ask a question now: put `State: PARKED` on a line under its heading.",
             "- Use a default instead: put `State: DEFAULTED` and `Default: <the answer we assume>`.",
             "- A question that must not hold up the work: put `Blocking: no` (the gate waits for blocking ones).",
             f"- At most {MAX_OPEN_PER_ROUND} open questions in a round. Write no host names, file paths, SQL, "
             "table names, secrets or personal data: the preview blocks them.", "",
             "## Questions", ""]
    for q in _round_qs(ledger, rnd):
        if q.get("note") == REMOVED_NOTE:
            continue
        lines.append(f"### {q['id']}")
        if q["state"] != "OPEN":
            lines.append(f"State: {q['state']}")
        if q["state"] == "DEFAULTED":
            lines.append(f"Default: {q.get('default') or ''}")
        if not q.get("blocking", True):
            lines.append("Blocking: no")
        lines += [q["text"], ""]
    return "\n".join(lines).rstrip() + "\n"


_DRAFT_HEAD = re.compile(r"^###[ \t]+(.+?)[ \t]*$", re.M)
_DRAFT_STATE = re.compile(r"^state\s*:\s*(\w+)\s*$", re.I)
_DRAFT_DEFAULT = re.compile(r"^default\s*:\s*(.*)$", re.I)
_DRAFT_BLOCKING = re.compile(r"^blocking\s*:\s*(yes|no|true|false)\s*$", re.I)


def parse_draft(text: str) -> list[dict]:
    """The question entries of an edited draft: {id (None for NEW), state, text, default}."""
    _, sep, body = text.partition("\n## Questions")
    body = body if sep else text
    parts = _DRAFT_HEAD.split(body)
    entries: list[dict] = []
    for head, chunk in zip(parts[1::2], parts[2::2]):
        head = head.upper()
        if head != "NEW" and not re.fullmatch(r"Q\d+", head):
            raise ValueError(f"draft heading '### {head}' must be ### Q<n> or ### NEW")
        state, default, words, blocking = "OPEN", None, [], True
        for raw in chunk.splitlines():
            line = raw.strip()
            if not line or line.startswith("<!--"):
                continue
            if m := _DRAFT_STATE.match(line):
                state = m.group(1).upper()
            elif m := _DRAFT_BLOCKING.match(line):
                blocking = m.group(1).lower() in ("yes", "true")
            elif m := _DRAFT_DEFAULT.match(line):
                default = m.group(1).strip()
            else:
                words.append(line)
        if state not in DRAFT_STATES:
            raise ValueError(f"### {head}: State must be one of {', '.join(DRAFT_STATES)} in a draft")
        if state == "DEFAULTED" and not default:
            raise ValueError(f"### {head}: State DEFAULTED needs a 'Default: <answer>' line")
        entries.append({"id": None if head == "NEW" else head, "state": state, "text": " ".join(words),
                        "default": default if state == "DEFAULTED" else None, "blocking": blocking})
    return entries


def sync_draft(ledger: dict, rnd: int, entries: list[dict]) -> None:
    """Apply an edited draft to the round's questions. New ids for NEW; a removed question is PARKED (its id is
    never reused). Raises ValueError on a duplicate id, an id of another round or more than 7 OPEN."""
    own = {q["id"]: q for q in _round_qs(ledger, rnd)}
    every = {q["id"]: q for q in ledger["questions"]}
    seen: set[str] = set()
    for e in entries:
        qid = e["id"]
        if qid is None:
            continue
        if qid in seen:
            raise ValueError(f"{qid} appears twice in the draft")
        seen.add(qid)
        if qid not in own:
            where = f"it belongs to round {every[qid]['round']}" if qid in every else "no such question"
            raise ValueError(f"{qid} is not a question of round {rnd} ({where}); add a new question as ### NEW")
        if not e["text"]:
            raise ValueError(f"{qid} has no text; delete its heading to remove it")
    for e in entries:
        if e["id"] is None:
            if e["text"]:
                e["id"] = _add_question(ledger, rnd, e["text"], e["state"], e["default"], e["blocking"])["id"]
            continue
        own[e["id"]].update(text=e["text"], state=e["state"], default=e["default"], blocking=e["blocking"],
                            note=None)
    for qid, q in own.items():
        if qid not in seen:
            q.update(state="PARKED", note=REMOVED_NOTE)
    n_open = sum(1 for q in _round_qs(ledger, rnd) if q["state"] == "OPEN")
    if n_open > MAX_OPEN_PER_ROUND:
        raise ValueError(f"round {rnd} has {n_open} open questions; at most {MAX_OPEN_PER_ROUND} are allowed "
                         "(park or default the rest)")


def _sync_from_draft(ledger: dict, root, rnd: int) -> Path:
    path = draft_path(root, ledger["epic"], rnd)
    if path.is_file():
        sync_draft(ledger, rnd, parse_draft(path.read_text(encoding="utf-8")))
    return path


_ANSWER_LINE = re.compile(r"^\s*(?:[-*\u2022]\s+)?[*_]{0,2}(Q\d+)[*_]{0,2}(?!\w)\s*(?:[:.)\-\u2013\u2014]\s*)?(.*)$",
                          re.I)


def parse_answers(text: str) -> list[tuple[str, str]]:
    """(question id, answer) pairs from one reply: a line that starts with Q<n> opens an answer; the lines after it
    belong to it until the next Q<n> line."""
    found: list[list] = []
    for line in (text or "").splitlines():
        if line.lstrip().startswith(">"):  # a quote of the question is not an answer
            continue
        m = _ANSWER_LINE.match(line)
        if m:
            found.append([m.group(1).upper(), [m.group(2).strip()]])
        elif found and line.strip():
            found[-1][1].append(line.strip())
    return [(qid, " ".join(p for p in parts if p).strip()) for qid, parts in found]


def qa_counts(ledger: dict) -> dict[str, int]:
    counts = Counter(q.get("state") for q in ledger["questions"])
    return {state: counts.get(state, 0) for state in QA_STATES}


def blocking_open(ledger: dict) -> list[str]:
    return [q["id"] for q in ledger["questions"] if q.get("state") == "OPEN" and q.get("blocking", True)]


def promote_decision(root, ledger: dict, q: dict) -> Path | None:
    """Write an answered question as `.caddis/decisions/<date>-qa-<epic>-<qid>.md` (ADR header). Never overwrites:
    an existing file is left alone and None comes back."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = Path(root) / ".caddis" / "decisions" / f"{today}-qa-{_slug(ledger['epic'])}-{q['id'].lower()}.md"
    if path.exists():
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    rnd = _round_rec(ledger, q["round"]) or {}
    path.write_text("\n".join([
        "---", "type: adr", "status: current", f"found: {today}", "---", "",
        f"# {ledger['epic']} {q['id']}: {q['text']}", "",
        "## Context",
        f"Asked in the Jira Q&A round {q['round']} on {ledger['epic']} (comment {rnd.get('comment_id') or '-'}).", "",
        "## Decision", q.get("answer") or "", "",
        "## Consequences",
        f"Recorded by caddis qa-pull from Jira comment {q.get('answer_comment_id')}. A later answer in Jira needs a "
        "new decision record.", ""]), encoding="utf-8")
    return path


# ---------------------------------------------------------------- sync-stories (Phase 2): plan phases -> Jira

DEFAULT_STORY_TYPE = "Story"
SYNC_CHILDREN_MAX = 200
MAX_SUMMARY = 255
STORY_FOOTER = "Synced by caddis from the plan. Edit the plan, not this text."
_ISSUE_TYPE_NAME = re.compile(r"[A-Za-z][A-Za-z0-9 _-]{0,40}")


@dataclass
class PlanPhase:
    pid: str
    title: str
    goal: str = ""
    exit_gate: str = ""
    risk: str = ""
    status: str = ""
    jira_story: str = ""
    kind: str = "phase"  # "milestone": one unit of sync that stands for several phases
    members: list[str] = field(default_factory=list)  # a milestone: the ids of its phases
    unstamped: list[str] = field(default_factory=list)  # a milestone: members with no **Jira Story:** line yet

    @property
    def tag(self) -> str:
        """How a row names this unit: `P1` for a phase, `milestone M1` for a milestone."""
        return f"P{self.pid}" if self.kind == "phase" else f"milestone {self.pid}"


_PHASE_HEAD = re.compile(r"^###\s+Phase\s+([0-9][0-9A-Za-z.]*)\s*(?:\u2014|\u2013|-|:)\s*(.+?)\s*$")
_TRAILING_MARKS = re.compile(r"[\s\u2600-\u27bf\u2b00-\u2bff\ufe0f\U0001f000-\U0001faff]+$")
_LABEL_LINE = re.compile(r"^\*\*([^*:]+?):\*\*\s*(.*)$")
_PHASE_FIELDS = {"goal": "goal", "exit gate": "exit_gate", "risk": "risk", "jira story": "jira_story"}


def _tracker_rows(body: str) -> dict[str, dict]:
    """`## Tracker` rows by phase id (the first token of the Phase cell). The first row of an id wins."""
    rows: dict[str, dict] = {}
    _, sep, rest = body.partition("\n## Tracker")
    if not sep:
        return rows
    header: list[str] | None = None
    for line in rest.splitlines()[1:]:
        line = line.strip()
        if not line.startswith("|"):
            if header is not None:
                break
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if header is None:
            header = [c.lower() for c in cells]
            continue
        if all(set(c) <= set("-: ") for c in cells):
            continue
        row = dict(zip(header, cells))
        m = re.match(r"([0-9][0-9A-Za-z.]*)", row.get("phase", ""))
        if m:
            rows.setdefault(m.group(1).lower(), row)
    return rows


def parse_plan_phases(text: str) -> list[PlanPhase]:
    """`### Phase <id> — <title>` sections with their Goal, Exit gate and Risk lines, plus the Tracker status."""
    _, body = split_document(text)
    phases: list[PlanPhase] = []
    cur: PlanPhase | None = None
    field_name: str | None = None
    for line in body.splitlines():
        if m := _PHASE_HEAD.match(line):
            cur = PlanPhase(m.group(1), _TRAILING_MARKS.sub("", m.group(2)).strip())
            if any(p.pid.lower() == cur.pid.lower() for p in phases):
                raise ValueError(f"phase {cur.pid} appears twice in the plan")
            phases.append(cur)
            field_name = None
            continue
        if re.match(r"^#{1,3}\s", line):
            cur, field_name = None, None
            continue
        if cur is None:
            continue
        stripped = line.strip()
        if m := _LABEL_LINE.match(stripped):
            field_name = _PHASE_FIELDS.get(m.group(1).strip().lower())
            if field_name:
                setattr(cur, field_name, m.group(2).strip())
            if field_name == "jira_story":
                field_name = None  # one key, never continued by the next line
            continue
        if not stripped or re.match(r"^(?:[-*+]\s|\d+\.\s|\|)", stripped):
            field_name = None
            continue
        if field_name:
            setattr(cur, field_name, f"{getattr(cur, field_name)} {stripped}".strip())
    tracker = _tracker_rows(body)
    for p in phases:
        row = tracker.get(p.pid.lower()) or {}
        p.status = row.get("status", "")
        if not p.risk and row.get("risk"):
            p.risk = row["risk"]
        if p.jira_story:
            p.jira_story = check_key(p.jira_story.strip("`* "))
    return phases


def write_back_story_keys(path: Path, keys: dict[str, str]) -> None:
    """Put `**Jira Story:** <KEY>` under each created phase's heading, so a later rename of the plan or the phase
    title never makes a second Story. Only the phases in `keys` are touched."""
    with open(path, encoding="utf-8", newline="") as fh:  # newline="": keep CRLF files CRLF
        lines = fh.read().splitlines(keepends=True)
    out: list[str] = []
    for line in lines:
        out.append(line)
        m = _PHASE_HEAD.match(line.rstrip("\r\n"))
        if m and m.group(1) in keys:
            newline = "\r\n" if line.endswith("\r\n") or (not line.endswith("\n") and "\r\n" in "".join(lines)) \
                else "\n"
            if not line.endswith("\n"):
                out[-1] = line + newline
            out.append(f"**Jira Story:** {keys[m.group(1)]}{newline}")
    tmp = Path(path).with_name(Path(path).name + ".tmp")
    tmp.write_text("".join(out), encoding="utf-8", newline="")
    os.replace(tmp, path)


def risk_points(risk: str) -> int:
    word = (re.findall(r"[a-z]+", (risk or "").lower()) or [""])[0]
    return {"high": 5, "low": 2}.get(word, 3)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def plan_slug(plan_path) -> str:
    """The plan's slug: its file name without `.md`, folded. Labels, markers and summaries carry it."""
    return _slug(Path(plan_path).stem)


def story_label(slug: str, pid: str, kind: str = "phase") -> str:
    """`caddis-<plan>-p<n>` for a phase, `caddis-<plan>-m-<milestone>` for a milestone: the two never collide."""
    if kind == "milestone":
        return f"caddis-{_slug(slug)}-m-{_slug(pid)}"
    return f"caddis-{_slug(slug)}-p{_slug(pid)}"


def story_marker(slug: str, pid: str, kind: str = "phase") -> str:
    if kind == "milestone":
        return f"caddis:{_slug(slug)}#M-{_slug(pid)}"
    return f"caddis:{_slug(slug)}#P{pid}"


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def render_story(adapter: JiraAdapter, slug: str, phase: PlanPhase) -> dict:
    """The summary and description caddis writes for one phase (redacted, in the adapter's body format)."""
    summary = adapter.clean(f"[{_slug(slug)} {phase.tag}] {phase.title}", MAX_SUMMARY)
    description = adapter.story_description(adapter.clean(phase.goal, None), adapter.clean(phase.exit_gate, None),
                                            story_marker(slug, phase.pid, phase.kind))
    return {"summary": summary, "description": description}


def resolve_issue_type(cli_value: str | None, meta: Mapping, env: Mapping[str, str] | None = None) -> tuple[str, str]:
    """(issue type, where it came from): --issue-type, then the plan's jira_issue_type: or jira_story_type: (aliases),
    then JIRA_STORY_TYPE in the environment, then Story."""
    found = {}
    for key in ("jira_issue_type", "jira_story_type"):
        raw = str(meta.get(key) or "").strip().strip('"').strip("'")
        if raw.lower() not in _NONE_VALUES:
            found[key] = raw
    if len({v.lower() for v in found.values()}) > 1:
        raise ValueError("the plan sets jira_issue_type and jira_story_type to different values; keep one")
    env_value = ((env or {}).get("JIRA_STORY_TYPE") or "").strip()
    if cli_value and cli_value.strip():
        name, source = cli_value.strip(), "--issue-type"
    elif found:
        source, name = next(iter(found.items()))
    elif env_value:
        name, source = env_value, "JIRA_STORY_TYPE"
    else:
        name, source = DEFAULT_STORY_TYPE, "default"
    if not _ISSUE_TYPE_NAME.fullmatch(name):
        raise ValueError(f"issue type {name!r} is not a Jira issue type name")
    return name, source


GRANULARITIES = ("phase", "milestone")
_COMPONENT_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _./&()+-]{0,79}")
_MILESTONE_SPLIT = re.compile(r"\s+(?:—|–|-)\s+|\s*:\s+")
PLAN_UNIT = "plan"  # the one deliverable for phases with no milestone of their own


def resolve_granularity(cli_value: str | None, by_milestone: bool, meta: Mapping) -> tuple[str, str]:
    """(granularity, source): --granularity, --by-milestone, the plan's `jira_granularity:`, then `phase`."""
    if cli_value and by_milestone and cli_value != "milestone":
        raise ValueError("--by-milestone means --granularity milestone; do not combine it with --granularity phase")
    raw = str(meta.get("jira_granularity") or "").strip().strip('"').strip("'").lower()
    if cli_value:
        return cli_value, "--granularity"
    if by_milestone:
        return "milestone", "--by-milestone"
    if raw and raw not in _NONE_VALUES:
        if raw not in GRANULARITIES:
            raise ValueError(f"jira_granularity: must be one of {', '.join(GRANULARITIES)}, not {raw!r}")
        return raw, "jira_granularity"
    return "phase", "default"


def resolve_components(cli_values: list[str] | None, meta: Mapping) -> list[str]:
    """The component names to set: --component (repeat it or use commas) beats the plan's `jira_component:` (a
    string, a `[A, B]` list or a YAML list). Empty or `none` means unset: then no component is ever sent."""
    if cli_values is not None:
        raw: list = list(cli_values)
    else:
        value = meta.get("jira_component")
        raw = list(value) if isinstance(value, list) else [value or ""]
    names: list[str] = []
    for item in raw:
        text = str(item or "").strip()
        if text.startswith("[") and text.endswith("]"):
            text = text[1:-1]
        for part in text.split(","):
            part = part.strip().strip('"').strip("'").strip()
            if part.lower() in _NONE_VALUES:
                continue
            if not _COMPONENT_NAME.fullmatch(part):
                raise ValueError(f"component {part!r} is not a Jira component name")
            if part.lower() not in {n.lower() for n in names}:
                names.append(part)
    return names


def _milestone_cell(cell: str) -> tuple[str, str]:
    """(id, title) from a Tracker Milestone cell: `M1`, `M1 - Export`, `M1: Export` or just a name. ('', '') = none."""
    text = re.sub(r"[`*]", "", _TRAILING_MARKS.sub("", cell or "")).strip()
    if text.lower() in _NONE_VALUES or not _slug(text):
        return "", ""
    m = _MILESTONE_SPLIT.search(text)
    if m and _slug(text[:m.start()]):
        return text[:m.start()].strip(), text[m.end():].strip()
    return text, ""


def milestone_units(phases: list[PlanPhase], text: str, explicit: bool = False) -> list[PlanPhase]:
    """One unit per deliverable milestone of the plan's `## Tracker` (its `Milestone` column), in order of first
    appearance. Phases with no milestone share one plan-level unit. A plan with no milestone at all becomes that one
    plan-level unit, except when `explicit` (the person asked for milestones on the command line): then it is an error.
    Raises ValueError for that, and for phases of one milestone that already carry different Jira Story keys."""
    _, body = split_document(text)
    rows = _tracker_rows(body)
    groups: dict[str, dict] = {}
    for p in phases:
        mid, title = _milestone_cell((rows.get(p.pid.lower()) or {}).get("milestone", ""))
        key = _slug(mid) if mid else PLAN_UNIT
        g = groups.setdefault(key, {"id": mid or PLAN_UNIT, "title": title, "phases": []})
        g["title"] = g["title"] or title
        g["phases"].append(p)
    if explicit and not [k for k in groups if k != PLAN_UNIT]:
        raise ValueError("--by-milestone needs a 'Milestone' column in the plan's ## Tracker with at least one "
                         "milestone (none found); name the milestones or sync by phase")
    units: list[PlanPhase] = []
    for g in groups.values():
        members: list[PlanPhase] = g["phases"]
        mid = g["id"]
        stories = sorted({m.jira_story for m in members if m.jira_story})
        if len(stories) > 1:
            raise ValueError(f"milestone {mid}: its phases carry different **Jira Story:** keys ({', '.join(stories)});"
                             " one milestone has one Story (remove the lines of an earlier by-phase sync)")
        listing = "; ".join(f"P{m.pid} {m.title}" for m in members)
        title = g["title"] or ("Plan deliverable" if mid == PLAN_UNIT else "; ".join(m.title for m in members)[:120])
        head = "Plan deliverable" if mid == PLAN_UNIT else f"Milestone {mid}" + (f": {g['title']}" if g["title"] else "")
        gates = " ".join(f"P{m.pid}: {m.exit_gate}" for m in members if m.exit_gate)
        riskiest = max(members, key=lambda m: risk_points(m.risk))  # an unset risk counts as medium
        done = all(str(m.status).lower().startswith("done") for m in members)
        units.append(PlanPhase(pid=mid, title=title, goal=f"{head}. Phases: {listing}.", exit_gate=gates,
                               risk=riskiest.risk, status="done" if done else "open",
                               jira_story=stories[0] if stories else "", kind="milestone",
                               members=[m.pid for m in members], unstamped=[m.pid for m in members if not m.jira_story]))
    return units


def sync_units(text: str, phases: list[PlanPhase], granularity: str, explicit: bool = False) -> list[PlanPhase]:
    """The units sync-stories and gate2 plan rows for: the phases, or the milestones of the plan. By phase, two phases
    that carry one Story key are refused: a by-milestone sync stamped it, and a by-phase run would fight over it."""
    if granularity == "milestone":
        return milestone_units(phases, text, explicit)
    owner: dict[str, str] = {}
    for p in phases:
        if p.jira_story and owner.setdefault(p.jira_story, p.pid) != p.pid:
            raise ValueError(f"phases {owner[p.jira_story]} and {p.pid} carry the same **Jira Story:** "
                             f"{p.jira_story} (a by-milestone sync stamped it): use --by-milestone, or remove those "
                             "lines to sync by phase")
    return phases


def _child_matches(adapter: JiraAdapter, issue: dict, label: str, marker_rx: re.Pattern, key: str = "") -> bool:
    f = issue.get("fields") or {}
    if key and issue.get("key") == key:
        return True
    if label in (f.get("labels") or []):
        return True
    return bool(marker_rx.search(adapter.body_text(f.get("description"))))


def plan_story_rows(adapter: JiraAdapter, slug: str, phases: list[PlanPhase], children: list[dict], *, project: str,
                    epic: str, issue_type: str, epic_link_field: str | None, points_field: str | None,
                    ac_field: str | None = None, components: list[str] | None = None) -> list[dict]:
    """One row per unit (a phase, or a milestone): CREATE, UPDATE, UNCHANGED, BLOCKED (leak lint) or CONFLICT (two
    issues match). `components` are sent only when given: no component, no `components` field at all."""
    origin = _origin(adapter.base_url)
    rows = []
    for phase in phases:
        label = story_label(slug, phase.pid, phase.kind)
        marker_rx = re.compile(re.escape(story_marker(slug, phase.pid, phase.kind)) + r"(?![0-9A-Za-z.])")
        story = render_story(adapter, slug, phase)
        row = {"phase": phase.pid, "kind": phase.kind, "tag": phase.tag,
               "members": phase.members or [phase.pid], "unstamped": list(phase.unstamped),
               "title": adapter.clean(phase.title, MAX_SUMMARY), "status": phase.status, "label": label,
               "summary": story["summary"], "key": None, "changes": [], "lint": [], "points": None,
               "components": list(components or [])}
        for part in (phase.title, phase.goal, phase.exit_gate):
            row["lint"] += [f"{h.rule}: {h.excerpt}" for h in leak_lint(part, adapter._secrets, origin)]
        matches = [c for c in children if _child_matches(adapter, c, label, marker_rx, phase.jira_story)]
        ac_value = adapter.text_value(adapter.clean(phase.exit_gate, None)) if ac_field and phase.exit_gate else None
        if row["lint"]:
            row["action"] = "BLOCKED"
            row["key"] = ", ".join(c.get("key", "?") for c in matches) or None
        elif len(matches) > 1:
            row["action"] = "CONFLICT"
            row["key"] = ", ".join(c.get("key", "?") for c in matches)
        elif matches:
            child = matches[0]
            f = child.get("fields") or {}
            row["key"] = child.get("key")
            if _fold(str(f.get("summary") or "")) != _fold(story["summary"]):
                row["changes"].append("summary")
            if _fold(adapter.body_text(f.get("description"))) != _fold(adapter.body_text(story["description"])):
                row["changes"].append("description")
            if label not in (f.get("labels") or []):
                row["changes"].append("label")
            if ac_value is not None and _fold(adapter.body_text(f.get(ac_field))) != _fold(adapter.body_text(ac_value)):
                row["changes"].append("acceptance criteria")
            missing = []
            if components:
                have = {str(c.get("name") or "").lower() for c in f.get("components") or [] if isinstance(c, dict)}
                missing = [c for c in components if c.lower() not in have]
                if missing:
                    row["changes"].append("component")
            row["action"] = "UPDATE" if row["changes"] else "UNCHANGED"
            if row["changes"]:
                body: dict = {"fields": {"summary": story["summary"], "description": story["description"]}}
                if "acceptance criteria" in row["changes"]:
                    body["fields"][ac_field] = ac_value
                if "label" in row["changes"]:
                    body.setdefault("update", {})["labels"] = [{"add": label}]
                if missing:  # add only: a component a person set in Jira is never removed
                    body.setdefault("update", {})["components"] = [{"add": {"name": c}} for c in missing]
                row["body"] = body
        else:
            row["action"] = "CREATE"
            fields = {"project": {"key": project}, "issuetype": {"name": issue_type}, "summary": story["summary"],
                      "description": story["description"], "labels": [label],
                      **adapter.epic_link(epic, epic_link_field)}
            if components:
                fields["components"] = [{"name": c} for c in components]
            if points_field:
                row["points"] = fields[points_field] = risk_points(phase.risk)
            if ac_value is not None:
                fields[ac_field] = ac_value
            row["fields"] = fields
        rows.append(row)
    return rows


class SyncError(Exception):
    """sync-stories cannot plan the sync: `message` is the full line to print, `code` the exit code."""

    def __init__(self, message: str, code: int):
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class SyncPlan:
    resolved: str
    project: str
    issue_type: str
    epic_field: str | None
    points_field: str | None
    ac_field: str | None
    jql: str | None
    children: list[dict]
    notes: list[str]
    rows: list[dict]
    fetched_by_key: list[str] = field(default_factory=list)  # stamped Story keys the Epic child query did not list
    components: list[str] = field(default_factory=list)


def plan_sync(adapter: JiraAdapter, slug: str, phases: list[PlanPhase], epic: str, issue_type: str,
              components: list[str] | None = None) -> SyncPlan:
    """The read half of sync-stories (GET only, no write is ever armed here): read the Epic (a moved Epic is read by
    the key Jira returns), the project's issue types, the field schema and the Epic's children, then plan one row per
    unit (CREATE, UPDATE, UNCHANGED, BLOCKED or CONFLICT). `phases` holds phases or milestone units
    (`sync_units`). `components` is optional: empty means the project may have none, and none is sent.
    `caddis_gate.py gate2` calls it as well.
    Raises SyncError (with the exit code) when the sync cannot be planned, and JiraError on a failed request."""
    notes: list[str] = []
    epic_issue = adapter.get_issue(epic)
    resolved, project = epic_issue["key"] or epic, epic_issue["project"]
    if not project:
        raise SyncError(f"ERROR: Jira did not return the project of {epic}", caddis_exit.BLOCKED)
    types = [t for t in adapter.issue_types(project) if not t["subtask"]]
    match = [t for t in types if str(t["name"]).lower() == issue_type.lower()]
    if not match:
        raise SyncError(f"ERROR: issue type {issue_type!r} is not in project {project} (allowed: "
                        f"{', '.join(str(t['name']) for t in types)})", caddis_exit.ERROR)
    issue_type = str(match[0]["name"])
    fields = discover_fields(adapter.field_list(), getattr(adapter, "field_overrides", None) or {})
    screen = adapter.create_screen_fields(project, match[0]["id"])
    epic_field = fields["epic_link"] if adapter.mode == "dc" else "parent"
    if adapter.mode == "dc" and not epic_field:
        raise SyncError("NOT CONFIGURED: no Epic Link field found; set JIRA_EPIC_LINK_FIELD", caddis_exit.NOT_RUN)
    if screen is not None and epic_field not in screen:
        notes.append(f"WARN: {epic_field} is not on the {issue_type} create screen; Jira may refuse the create")
    points_field = fields["story_points"] if (screen and fields["story_points"] in screen) else None
    if fields["story_points"] and not points_field:
        notes.append(f"STORY POINTS: {fields['story_points']} is not on the create screen of {issue_type}: omitted")
    ac_field = fields["acceptance_criteria"] if (screen and fields["acceptance_criteria"] in screen) else None
    components = list(components or [])
    if components:
        known = adapter.project_components(project)
        if known is None:
            notes.append(f"WARN: the components of project {project} could not be read; "
                         f"{', '.join(components)} not checked")
        else:
            by_lower = {k.lower(): k for k in known}
            absent = [c for c in components if c.lower() not in by_lower]
            if absent:
                allowed = ", ".join(known) if known else "the project has no components"
                raise SyncError(f"ERROR: component {', '.join(absent)} is not in project {project} ({allowed}); "
                                "drop --component / jira_component: for a project without components", caddis_exit.ERROR)
            components = [by_lower[c.lower()] for c in components]
    wanted = (["summary", "description", "labels", "issuetype", "status"] + ([ac_field] if ac_field else [])
              + (["components"] if components else []))
    jql, found, error = find_children(adapter, resolved, wanted, SYNC_CHILDREN_MAX)
    if found is None:
        raise SyncError(f"ERROR: cannot list the children of {resolved}: {error}", caddis_exit.BLOCKED)
    children = list(found["issues"])
    if found.get("more"):
        notes.append(f"WARN: {resolved} has more than {SYNC_CHILDREN_MAX} children; matching may miss some")
    fetched: list[str] = []
    for p in phases:
        if p.jira_story and all(c.get("key") != p.jira_story for c in children):
            raw = adapter._get(f"/issue/{quote(p.jira_story)}", {"fields": ",".join(wanted)})
            p.jira_story = str(raw.get("key") or p.jira_story)
            if all(c.get("key") != p.jira_story for c in children):
                children.append(raw)
                fetched.append(p.jira_story)
    rows = plan_story_rows(adapter, slug, phases, children, project=project, epic=resolved, issue_type=issue_type,
                           epic_link_field=epic_field, points_field=points_field, ac_field=ac_field,
                           components=components)
    return SyncPlan(resolved, project, issue_type, epic_field, points_field, ac_field, jql, children, notes, rows,
                    fetched, components)


# ---------------------------------------------------------------- command line

def _failed(err: JiraError) -> int:
    print(f"ERROR: {err}", file=sys.stderr)
    return caddis_exit.NOT_RUN if err.status is None else caddis_exit.BLOCKED


def cmd_epic(args, env, factory) -> int:
    try:
        epic = resolve_plan_epic(args.plan)
    except (OSError, ValueError) as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return caddis_exit.ERROR
    print(f"EPIC: {epic}" if epic else "SKIPPED: no jira_epic")
    return caddis_exit.CLEAN


def _adapter(env, factory) -> JiraAdapter:
    return factory(load_config(env))


def cmd_check(args, env, factory) -> int:
    adapter = _adapter(env, factory)
    try:
        info = adapter.server_info()
        me = adapter.myself()
    except JiraError as err:
        return _failed(err)
    info["authenticated"] = bool(me["id"]) and me["active"]
    if args.json:
        print(json.dumps(info))
    else:
        print(f"mode: {info['mode']}")
        print(f"version: {info['version']}")
        print(f"deployment: {info['deployment']}")
        print(f"authenticated: {'yes' if info['authenticated'] else 'no'}")
    return caddis_exit.CLEAN if info["authenticated"] else caddis_exit.BLOCKED


def _counts(counter: Mapping[str, int]) -> str:
    return ", ".join(f"{k} x{v}" for k, v in counter.items()) or "-"


def cmd_read(args, env, factory) -> int:
    key = check_key(args.key)
    adapter = _adapter(env, factory)
    report: dict = {}
    try:
        issue = adapter.get_issue(key)
        report["transitions"] = [list(t) for t in adapter.transitions(key)]
        field_list = adapter.field_list() if (args.discover_schema or args.children) else []
        names = {f["id"]: f["name"] for f in field_list}
        cfg_fields = getattr(adapter, "field_overrides", None) or {}
        if args.discover_schema:
            report["fields"] = discover_fields(field_list, cfg_fields)
            report["custom_set"] = {k: names.get(k, "?") for k in issue["custom_set"]}
            report["issue_types"] = adapter.issue_types(issue["project"]) if issue["project"] else []
        if args.children:
            jql, found, error = find_children(adapter, key, ["*all"])
            report["children"] = ({"jql": jql, "total": found["total"], "more": found.get("more", False),
                                   **summarize_children(found["issues"], names)} if found else {"error": error})
        if args.comments:
            report["comments"] = adapter.comments(key)
    except JiraError as err:
        return _failed(err)
    issue.pop("raw_fields", None)
    report = {"issue": issue, **report}
    if args.json:
        print(json.dumps(report, indent=2))
        return caddis_exit.CLEAN
    print(f"ISSUE: {issue['key']}")
    print(f"type: {issue['type']}")
    print(f"status: {issue['status']} ({issue['status_category'] or '-'})")
    print(f"summary: {issue['summary']}")
    print(f"project: {issue['project'] or '-'}")
    if issue["parent"]:
        print(f"parent: {issue['parent']}")
    print(f"description: {issue['description'] or '-'}")
    print("transitions: " + ("; ".join(f"{a} -> {b}" for a, b in report["transitions"]) or "-"))
    if "fields" in report:
        print("fields: " + "; ".join(f"{k}={v} ({names.get(v, '?')})" if v else f"{k}=-"
                                     for k, v in report["fields"].items()))
        print("custom fields set: " + (", ".join(f"{k} ({v})" for k, v in report["custom_set"].items()) or "-"))
        print("issue types: " + (", ".join(t["name"] + (" (subtask)" if t["subtask"] else "")
                                           for t in report["issue_types"]) or "-"))
    if "children" in report:
        ch = report["children"]
        if "error" in ch:
            print(f"children: none found ({ch['error']})")
        else:
            print(f"children: {ch['total']}{'+' if ch.get('more') else ''} via {ch['jql']}")
            print(f"  types: {_counts(ch['types'])}")
            print(f"  statuses: {_counts(ch['statuses'])}")
            print("  custom fields used: " + (", ".join(f"{k} ({v})" for k, v in ch["custom_fields"].items()) or "-"))
    if "comments" in report:
        print(f"comments: {len(report['comments'])}")
        for text in report["comments"]:
            print(f"  - {text}")
    return caddis_exit.CLEAN


def _err(message: str, code: int) -> int:
    print(message, file=sys.stderr)
    return code


def _round_split(ledger: dict, rnd: int) -> tuple[list[dict], list[dict]]:
    qs = _round_qs(ledger, rnd)
    return [q for q in qs if q["state"] == "OPEN"], [q for q in qs if q["state"] == "DEFAULTED"]


def _round_lint(ledger: dict, rnd: int, secrets, origin) -> list[str]:
    open_qs, defaults = _round_split(ledger, rnd)
    found = []
    for q in open_qs + defaults:
        for part in (q["text"], q.get("default") or ""):
            found += [f"{q['id']} rule {h.rule}: {h.excerpt}" for h in leak_lint(part, secrets, origin)]
    return found


def cmd_qa_draft(args, env, factory) -> int:
    epic = check_key(args.epic)
    lp = ledger_path(args.dir, epic)
    ledger = load_ledger(lp, epic)
    last = ledger["rounds"][-1] if ledger["rounds"] else None
    if last and not last.get("comment_id"):
        rnd = last["round"]
        _sync_from_draft(ledger, args.dir, rnd)
    else:
        rnd = (last["round"] + 1) if last else 1
        ledger["rounds"].append({"round": rnd, "created_at": _now(), "posted_at": None, "comment_id": None,
                                 "approved_sha256": None, "question_ids": []})
    for text in args.question or []:
        text = re.sub(r"\s+", " ", text).strip()
        if text:
            _add_question(ledger, rnd, text)
    open_qs, defaults = _round_split(ledger, rnd)
    if len(open_qs) > MAX_OPEN_PER_ROUND:
        return _err(f"ERROR: round {rnd} would have {len(open_qs)} open questions; at most {MAX_OPEN_PER_ROUND}",
                    caddis_exit.ERROR)
    save_ledger(lp, ledger)
    dp = draft_path(args.dir, epic, rnd)
    dp.write_text(render_draft(ledger, rnd), encoding="utf-8")
    print(f"LEDGER: {lp}")
    print(f"DRAFT: {dp}")
    print(f"ROUND: {rnd} ({len(open_qs)} open, {len(defaults)} defaulted)")
    warnings = _round_lint(ledger, rnd, caddis_redact.load_secrets(Path.home()), None)
    for line in warnings:
        print(f"WARN: leak lint {line}")
    if open_qs and not warnings:
        print(f"HASH: {qa_content_hash(epic, rnd, open_qs, defaults)[:8]} (valid while the draft is unchanged)")
    print(f"NEXT: edit the draft, then preview: {STABLE_RUN} qa-post --epic {epic} --round {rnd}")
    return caddis_exit.CLEAN


def cmd_qa_post(args, env, factory) -> int:
    if is_headless(env):
        return _err("REFUSED: qa-post is a human step; it never runs when CADDIS_HEADLESS is set", caddis_exit.BLOCKED)
    epic = check_key(args.epic)
    lp = ledger_path(args.dir, epic)
    if not lp.is_file():
        return _err(f"ERROR: no Q&A ledger for {epic}: run qa-draft first", caddis_exit.ERROR)
    ledger = load_ledger(lp, epic)
    rec = _round_rec(ledger, args.round)
    if rec is None:
        return _err(f"ERROR: {epic} has no round {args.round}", caddis_exit.ERROR)
    if rec.get("comment_id"):
        return _err(f"REFUSED: round {args.round} is already posted (comment {rec['comment_id']})", caddis_exit.BLOCKED)
    dp = _sync_from_draft(ledger, args.dir, args.round)
    open_qs, defaults = _round_split(ledger, args.round)
    if not 1 <= len(open_qs) <= MAX_OPEN_PER_ROUND:
        return _err(f"ERROR: a round posts 1 to {MAX_OPEN_PER_ROUND} open questions; round {args.round} has "
                    f"{len(open_qs)}. Nothing was saved.", caddis_exit.ERROR)
    save_ledger(lp, ledger)
    dp.write_text(render_draft(ledger, args.round), encoding="utf-8")
    adapter = _adapter(env, factory)
    leaks = _round_lint(ledger, args.round, adapter._secrets, _origin(adapter.base_url))
    if leaks:
        for line in leaks:
            print(f"LEAK: {line}", file=sys.stderr)
        return _err(f"BLOCKED: fix the draft ({dp}) and preview again; nothing was sent", caddis_exit.BLOCKED)
    path = f"/issue/{quote(epic)}/comment"
    payload = adapter.qa_payload(epic, args.round, open_qs, defaults)
    digest = qa_content_hash(epic, args.round, open_qs, defaults)
    if not args.approve:
        print(f"PREVIEW: {adapter.mode} POST /rest/api/{adapter.api}{path}: {len(open_qs)} open, "
              f"{len(defaults)} defaulted. Nothing was sent.")
        print("-" * 60)
        body = payload["body"]
        print(body if isinstance(body, str) else adf_to_text(body))
        print("-" * 60)
        print(f"APPROVE_SHA256: {digest}")
        print(f"APPROVE: {digest[:8]}")
        print(f"NEXT: a person reads the preview, then runs: {STABLE_RUN} qa-post --epic {epic} --round {args.round} "
              f"--approve {digest[:8]}")
        return caddis_exit.CLEAN
    if not approval_matches(args.approve, digest):
        return _err("REFUSED: the approval does not match the text now (an edit after the preview, or a wrong hash). "
                    "Preview again and approve the new hash. Nothing was sent.", caddis_exit.BLOCKED)
    adapter.arm_writes()
    try:
        resp = adapter.write("POST", path, payload)
    except JiraError as err:
        return _failed(err)
    rec.update(comment_id=str(resp.get("id") or ""), posted_at=str(resp.get("created") or _now()),
               approved_sha256=digest, question_ids=[q["id"] for q in open_qs + defaults])
    save_ledger(lp, ledger)
    print(f"POSTED: comment {rec['comment_id']} on {epic}, round {args.round} ({len(open_qs)} questions)")
    return caddis_exit.CLEAN


def cmd_qa_pull(args, env, factory) -> int:
    epic = check_key(args.epic)
    lp = ledger_path(args.dir, epic)
    if not lp.is_file():
        return _err(f"ERROR: no Q&A ledger for {epic}: run qa-draft first", caddis_exit.ERROR)
    ledger = load_ledger(lp, epic)
    posted = {r["round"]: _cid(r["comment_id"]) for r in ledger["rounds"] if r.get("comment_id")}
    if not posted:
        print("NOTHING TO PULL: no round is posted yet")
        return caddis_exit.CLEAN
    adapter = _adapter(env, factory)
    try:
        records = adapter.comment_records(epic)
    except JiraError as err:
        return _failed(err)
    before = json.dumps(ledger, sort_keys=True)
    floor = max(_cid(ledger.get("last_synced_comment_id")), min(posted.values()))
    by_id = {q["id"]: q for q in ledger["questions"]}
    ledger.setdefault("needs_confirmation", [])
    changed: list[str] = []
    for c in sorted(records, key=lambda r: _cid(r["id"])):
        cid = _cid(c["id"])
        if cid <= floor:
            continue
        ledger["last_synced_comment_id"] = c["id"]
        if cid in posted.values():  # a round comment caddis posted; a reply that quotes it still counts
            continue
        answers = parse_answers(c["text"])
        problems = [] if answers else ["no Q<n> tag"]
        for qid, answer in answers:
            q = by_id.get(qid)
            if q is None or q["round"] not in posted or cid <= posted[q["round"]]:
                problems.append(f"{qid} is not a posted question")
            elif not answer:
                problems.append(f"{qid} has an empty answer")
            elif q["state"] == "PARKED":
                problems.append(f"{qid} is PARKED")
            else:
                q.update(state="ANSWERED", answer=adapter.clean(answer, MAX_ANSWER), answer_comment_id=c["id"],
                         answered_at=c["created"])
                changed.append(f"{qid} ANSWERED (comment {c['id']})")
        if problems:
            ledger["needs_confirmation"].append({"comment_id": c["id"], "created": c["created"],
                                                 "reason": "; ".join(problems),
                                                 "excerpt": adapter.clean(c["text"], 200)})
            print(f"NEEDS CONFIRMATION: comment {c['id']}: {'; '.join(problems)} (not applied; a person decides)")
    if args.promote_decisions:
        for q in ledger["questions"]:
            if q["state"] == "ANSWERED" and not q.get("decision"):
                path = promote_decision(args.dir, ledger, q)
                if path:
                    q["decision"] = path.relative_to(Path(args.dir)).as_posix()
                    print(f"DECISION: {q['decision']}")
    for line in changed:
        print(f"UPDATED: {line}")
    if json.dumps(ledger, sort_keys=True) != before:
        save_ledger(lp, ledger)
    counts = qa_counts(ledger)
    print("COUNTS: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return caddis_exit.CLEAN


def cmd_qa_status(args, env, factory) -> int:
    if args.plan:
        epic = resolve_plan_epic(args.plan)
        if epic is None:
            print(json.dumps({"skipped": True, "reason": "no jira_epic"}) if args.json else "SKIPPED: no jira_epic")
            return caddis_exit.CLEAN
        if args.epic and check_key(args.epic) != epic:
            raise ValueError(f"--epic {args.epic} is not the plan's jira_epic {epic}")
    elif args.epic:
        epic = check_key(args.epic)
    else:
        raise ValueError("give --epic <KEY> or --plan <path>")
    lp = ledger_path(args.dir, epic)
    ledger = load_ledger(lp, epic)
    counts = qa_counts(ledger)
    blocking = blocking_open(ledger)
    pending = len(ledger.get("needs_confirmation") or [])
    gate = "pass" if not blocking else "blocked"
    if args.json:
        print(json.dumps({"epic": epic, "ledger": lp.is_file(), "counts": counts, "blocking_open": blocking,
                          "needs_confirmation": pending, "gate": gate}))
    else:
        print(f"EPIC: {epic}")
        if not lp.is_file():
            print("NOTE: no Q&A ledger yet")
        for state, n in counts.items():
            print(f"{state}: {n}")
        if blocking:
            print("BLOCKING OPEN: " + ", ".join(blocking))
        if pending:
            print(f"NEEDS CONFIRMATION: {pending} reply(ies) a person must read")
        if args.gate:
            print(f"GATE: {gate}" + (f" ({len(blocking)} blocking question(s) open)" if blocking else ""))
    if args.gate and blocking:
        return caddis_exit.BLOCKED
    return caddis_exit.CLEAN


def _print_rows(rows: list[dict]) -> None:
    for r in rows:
        head = f"{r.get('tag') or 'P' + str(r['phase'])} {r['action']}"
        if r["action"] == "CREATE" or r["action"] == "PLANNED":
            extra = f" label={r['label']}" + (f" points={r['points']}" if r.get("points") else "")
            print(f"{head} {r['summary']}{extra}")
        elif r["action"] == "UPDATE":
            print(f"{head} {r['key']} ({', '.join(r['changes'])})")
        elif r["action"] == "BLOCKED":
            print(f"{head} leak lint: {'; '.join(r['lint'])}")
        else:
            print(f"{head} {r['key']}")
        if r.get("result"):
            print(f"  {r['result']}")


def cmd_sync_stories(args, env, factory) -> int:
    plan_path = Path(args.plan)
    text = plan_path.read_text(encoding="utf-8")
    meta, _ = split_document(text)
    epic = resolve_plan_epic(meta)
    if epic is None:
        print(json.dumps({"skipped": True, "reason": "no jira_epic"}) if args.json else "SKIPPED: no jira_epic")
        return caddis_exit.CLEAN
    slug = plan_slug(plan_path)
    phases = parse_plan_phases(text)
    if not phases:
        raise ValueError("the plan has no '### Phase <id> - <title>' sections")
    issue_type, type_source = resolve_issue_type(args.issue_type, meta, env)
    granularity, gran_source = resolve_granularity(args.granularity, args.by_milestone, meta)
    components = resolve_components(args.component, meta)
    units = sync_units(text, phases, granularity, explicit=gran_source.startswith("--"))
    if args.offline:
        print(f"PLAN: {slug} ({len(phases)} phases, {len(units)} {granularity} units)\nEPIC: {epic}\n"
              f"ISSUE TYPE: {issue_type} ({type_source})\nGRANULARITY: {granularity} ({gran_source})\n"
              f"COMPONENT: {', '.join(components) or '-'}")
        for p in units:
            print(f"{p.tag} PLANNED [{slug} {p.tag}] {p.title} label={story_label(slug, p.pid, p.kind)} "
                  f"points={risk_points(p.risk)}")
        print("OFFLINE: Jira was not read and nothing was sent")
        return caddis_exit.CLEAN
    adapter = _adapter(env, factory)
    try:
        sync = plan_sync(adapter, slug, units, epic, issue_type, components)
    except SyncError as err:
        return _err(err.message, err.code)
    except JiraError as err:
        return _failed(err)
    rows, notes, children = sync.rows, sync.notes, sync.children
    resolved, project, issue_type, jql = sync.resolved, sync.project, sync.issue_type, sync.jql
    epic_field, points_field, ac_field = sync.epic_field, sync.points_field, sync.ac_field
    created: dict[str, str] = {}
    failed = False
    if not args.dry_run:
        adapter.arm_writes()
        for r in rows:
            try:
                if r["action"] == "CREATE":
                    resp = adapter.write("POST", "/issue", {"fields": r["fields"]})
                    r["key"] = str(resp.get("key") or "")
                    r["result"] = f"CREATED {r['key']}"
                    if r["key"]:
                        created.update({pid: r["key"] for pid in r["members"]})
                elif r["action"] == "UPDATE":
                    adapter.write("PUT", f"/issue/{quote(r['key'])}", r["body"])
                    r["result"] = f"UPDATED {r['key']}"
            except JiraError as err:
                r["result"] = f"FAILED: {err}"
                failed = True
                break
            if r["kind"] == "milestone" and r["action"] in ("UPDATE", "UNCHANGED") and r["key"]:
                created.update({pid: r["key"] for pid in r["unstamped"] if pid not in created})  # a new phase joins
        if created:
            write_back_story_keys(plan_path, created)
    bad = [r for r in rows if r["action"] in ("BLOCKED", "CONFLICT")]
    tally = Counter(r["action"] for r in rows)
    report = {"plan": slug, "epic": epic, "resolved_epic": resolved, "project": project, "issue_type": issue_type,
              "issue_type_source": type_source, "epic_link_field": epic_field, "story_points_field": points_field,
              "acceptance_criteria_field": ac_field, "children_jql": jql, "dry_run": bool(args.dry_run),
              "granularity": granularity, "granularity_source": gran_source, "components": sync.components,
              "notes": notes, "rows": rows}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"PLAN: {slug} ({len(phases)} phases, {len(units)} {granularity} units)")
        print(f"EPIC: {epic}" + (f" (moved to {resolved})" if resolved != epic else "") + f", project {project}")
        print(f"ISSUE TYPE: {issue_type} ({type_source})")
        print(f"GRANULARITY: {granularity} ({gran_source})")
        print(f"COMPONENT: {', '.join(sync.components) or '-'}")
        print(f"EPIC LINK: {epic_field}")
        print(f"STORY POINTS: {points_field or '-'}")
        print(f"ACCEPTANCE CRITERIA: {ac_field or '-'}")
        print(f"CHILDREN: {len(children)} via {jql}")
        for line in notes:
            print(line)
        _print_rows(rows)
        summary = ", ".join(f"{k} {v}" for k, v in sorted(tally.items()))
        if args.dry_run:
            print(f"DRY RUN: no write sent ({summary})")
        else:
            print(f"DONE: {summary}" + (f"; plan updated with {len(created)} Jira Story key line(s)" if created else ""))
    if failed:
        return caddis_exit.BLOCKED
    return caddis_exit.BLOCKED if bad else caddis_exit.CLEAN


_FIX_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")


def _transition_issue(adapter: JiraAdapter, key: str, target: str, fix_version: str | None, dry_run: bool,
                      as_json: bool, extra: dict | None = None) -> int:
    """Move one issue to `target` (a status or a transition name) and add `fix_version`. Idempotent: an issue already
    in the status or already on the version is left alone."""
    try:
        issue = adapter.get_issue(key)
        key = check_key(issue["key"] or key)  # a moved issue: act on the key Jira returns
        current = str(issue["status"] or "")
        already = current.lower() == target.lower()
        options = [] if already else adapter.transition_list(key)
    except JiraError as err:
        return _failed(err)
    versions = {str(v.get("name") or "").lower() for v in (issue.get("raw_fields") or {}).get("fixVersions") or []
                if isinstance(v, dict)}
    has_version = bool(fix_version) and fix_version.lower() in versions
    pick = None
    if not already:
        by_status = [t for t in options if t["to"].lower() == target.lower()]
        by_name = [t for t in options if t["name"].lower() == target.lower()]
        if len(by_status) > 1:
            by_status = [t for t in by_status if t in by_name] or by_status
        candidates = by_status or by_name
        if len(candidates) > 1:
            return _err(f"ERROR: more than one transition leads to {target!r}: "
                        + "; ".join(f"{t['name']} (id {t['id']})" for t in candidates), caddis_exit.BLOCKED)
        if not candidates:
            return _err(f"NO TRANSITION: {key} is {current}; no transition to {target!r}. Valid: "
                        + ("; ".join(f"{t['name']} -> {t['to']}" for t in options) or "none"), caddis_exit.BLOCKED)
        pick = candidates[0]
    result = {**(extra or {}), "key": key, "from": current, "to": pick["to"] if pick else current,
              "id": pick["id"] if pick else None, "name": pick["name"] if pick else None,
              "fix_version": fix_version, "dry_run": bool(dry_run)}
    if not dry_run:
        adapter.arm_writes()
        try:
            if fix_version and not has_version:
                adapter.write("PUT", f"/issue/{quote(key)}",
                              {"update": {"fixVersions": [{"add": {"name": fix_version}}]}})
            if pick:
                adapter.write("POST", f"/issue/{quote(key)}/transitions", {"transition": {"id": pick["id"]}})
        except JiraError as err:
            return _failed(err)
    if as_json:
        print(json.dumps(result))
        return caddis_exit.CLEAN
    if fix_version:
        if has_version:
            print(f"FIX VERSION ALREADY: {key} {fix_version}")
        else:
            print(f"{'WOULD SET' if dry_run else 'SET'} FIX VERSION: {key} {fix_version}")
    if pick is None:
        print(f"ALREADY: {key} is {current}")
    elif dry_run:
        print(f'WOULD TRANSITION: {key} {current} -> {pick["to"]} via "{pick["name"]}" (id {pick["id"]})')
    else:
        print(f'TRANSITIONED: {key} {current} -> {pick["to"]} via "{pick["name"]}" (id {pick["id"]})')
    return caddis_exit.CLEAN


def _check_transition_input(target: str | None, fix_version: str | None) -> str:
    target = (target or "").strip()
    if not target:
        raise ValueError("--to needs a status name")
    if fix_version and not _FIX_VERSION.fullmatch(fix_version):
        raise ValueError("--fix-version looks like v2026.11.25.1 (letters, digits, . _ + -)")
    return target


def cmd_transition(args, env, factory) -> int:
    key = check_key(args.key)
    target = _check_transition_input(args.to, args.fix_version)
    adapter = _adapter(env, factory)
    return _transition_issue(adapter, key, target, args.fix_version, args.dry_run, args.json)


def cmd_transition_milestone(args, env, factory) -> int:
    """Move the Story of one plan milestone (found by its label under the plan's Epic, else by the key stamped on its
    phases) to a status, and set the fix version. Re-running it is a no-op."""
    target = _check_transition_input(args.to, args.fix_version)
    plan_path = Path(args.plan)
    text = plan_path.read_text(encoding="utf-8")
    meta, _ = split_document(text)
    epic = resolve_plan_epic(meta)
    if epic is None:
        print(json.dumps({"skipped": True, "reason": "no jira_epic"}) if args.json else "SKIPPED: no jira_epic")
        return caddis_exit.CLEAN
    slug = plan_slug(plan_path)
    phases = parse_plan_phases(text)
    wanted = _slug(args.milestone)
    unit = next((u for u in milestone_units(phases, text) if _slug(u.pid) == wanted), None)
    if not wanted or unit is None:
        known = ", ".join(u.pid for u in milestone_units(phases, text)) or "none"
        raise ValueError(f"the plan has no milestone {args.milestone!r} (milestones: {known})")
    label = story_label(slug, unit.pid, "milestone")
    adapter = _adapter(env, factory)
    try:
        epic_key = adapter.get_issue(epic)["key"] or epic
        jql, found, error = find_children(adapter, epic_key, ["summary", "labels", "status"], SYNC_CHILDREN_MAX)
    except JiraError as err:
        return _failed(err)
    if found is None:
        return _err(f"ERROR: cannot list the children of {epic_key}: {error}", caddis_exit.BLOCKED)
    matches = [c for c in found["issues"]
               if label in ((c.get("fields") or {}).get("labels") or []) or (unit.jira_story and c.get("key") == unit.jira_story)]
    if len(matches) > 1:
        return _err(f"CONFLICT: {len(matches)} issues carry {label}: " + ", ".join(str(c.get("key")) for c in matches),
                    caddis_exit.BLOCKED)
    if not matches:
        return _err(f"NOT SYNCED: no Story with the label {label} under {epic_key}; run sync-stories --plan "
                    f"{plan_path.name} --by-milestone first", caddis_exit.BLOCKED)
    return _transition_issue(adapter, str(matches[0].get("key")), target, args.fix_version, args.dry_run, args.json,
                             {"milestone": unit.pid, "label": label})


# ---------------------------------------------------------------- dashboard-setup (Phase 2b): filters + dev dashboard

SHARE_MODES = ("private", "project", "global")
DASHBOARD_FORMAT = 1  # bump when the filters or gadgets change shape: an old approval then no longer matches
MAX_EPICS = 50
GADGET_PREFIX = "com.atlassian.jira.gadgets:"
_LABEL = re.compile(r"[A-Za-z0-9_.:-]{1,255}")
_TITLE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _./&:()+-]{0,60}")
_GADGET_COLUMNS = "issuetype|issuekey|summary|status|assignee|fixVersions"
# The four gadgets of the dev dashboard. `filter` names the saved filter that feeds the gadget; `config` is the
# gadget's saved preferences; `settings` is the same thing in words, for the blueprint a person follows by hand.
_GADGETS = (
    {"title": "Status Breakdown", "module": "pie-chart-gadget", "kind": "Pie Chart", "filter": "all",
     "position": {"row": 0, "column": 0},
     "config": {"statType": "statuses", "isConfigured": "true", "refresh": "false"},
     "settings": "Statistic Type = Status"},
    {"title": "Status x Fix Version Matrix", "module": "two-dimensional-stats-gadget",
     "kind": "Two Dimensional Filter Statistics", "filter": "all", "position": {"row": 0, "column": 1},
     "config": {"xstattype": "statuses", "ystattype": "fixVersions", "sortDirection": "asc", "sortBy": "natural",
                "numberToShow": "10", "isConfigured": "true", "refresh": "false"},
     "settings": "X axis = Status; Y axis = Fix Version"},
    {"title": "Active Work", "module": "filter-results-gadget", "kind": "Filter Results", "filter": "active",
     "position": {"row": 1, "column": 0},
     "config": {"num": "15", "columnNames": _GADGET_COLUMNS, "isConfigured": "true", "refresh": "false"},
     "settings": "Columns = Type, Key, Summary, Status, Assignee, Fix Version; Number of results = 15"},
    {"title": "Blocked / Waiting", "module": "filter-results-gadget", "kind": "Filter Results", "filter": "blocked",
     "position": {"row": 1, "column": 1},
     "config": {"num": "15", "columnNames": _GADGET_COLUMNS, "isConfigured": "true", "refresh": "false"},
     "settings": "Columns = Type, Key, Summary, Status, Assignee, Fix Version; Number of results = 15"},
)


def _jql_quote(text: str) -> str:
    """A JQL string literal. A control character is refused; a quote or a backslash is escaped."""
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError("a JQL value must not hold a control character")
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def check_jql_clause(jql: str) -> str:
    """A raw `--jql` clause, white space folded. It must be balanced (every quote and parenthesis closes inside it,
    so it cannot break out of the parentheses caddis wraps it in) and must not hold ORDER BY."""
    text = re.sub(r"\s+", " ", jql or "").strip()
    if not text:
        raise ValueError("--jql is empty")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValueError("--jql must not hold a control character")
    depth, quote_ch, escaped, outside = 0, "", False, []
    for ch in text:
        if quote_ch:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote_ch:
                quote_ch = ""
            continue
        if ch in "\"'":
            quote_ch = ch
            continue
        outside.append(ch)
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("--jql has a closing parenthesis with no opening one")
    if quote_ch:
        raise ValueError("--jql has a quote that is never closed")
    if depth:
        raise ValueError("--jql has a parenthesis that is never closed")
    if re.search(r"\border\s+by\b", "".join(outside), re.I):
        raise ValueError("--jql must be a filter clause with no ORDER BY (caddis adds the order)")
    return text


def dashboard_scope(adapter: JiraAdapter, project: str | None, components: list[str], epics: str | None,
                    label: str | None, jql: str | None) -> tuple[str, str]:
    """(scope JQL, default title prefix) from any mix of selectors. Every value is checked, then quoted, so a
    selector can never add a clause of its own. The component is optional: without it nothing names a component."""
    clauses: list[str] = []
    proj = (project or "").strip().upper()
    if project is not None and not _PROJECT_KEY.fullmatch(proj):
        raise ValueError("--project looks like PROJ")
    if proj:
        clauses.append(f"project = {_jql_quote(proj)}")
    if components:
        clauses.append("component in (" + ", ".join(_jql_quote(c) for c in components) + ")")
    keys: list[str] = []
    for part in (epics or "").split(","):
        if part.strip():
            key = check_key(part)
            if key not in keys:
                keys.append(key)
    if epics is not None and not keys:
        raise ValueError("--epics needs Epic keys such as PROJ-1,PROJ-2")
    if len(keys) > MAX_EPICS:
        raise ValueError(f"--epics takes at most {MAX_EPICS} keys")
    if keys:
        clauses.append(adapter.epics_clause(keys))
    if label is not None:
        if not _LABEL.fullmatch(label.strip()):
            raise ValueError("--label is one Jira label (letters, digits, . _ : -; no spaces)")
        clauses.append(f"labels = {_jql_quote(label.strip())}")
    if jql is not None:
        clauses.append(f"({check_jql_clause(jql)})")
    if not clauses:
        raise ValueError("dashboard-setup needs at least one scope: --project, --component, --epics, --label or "
                         "--jql")
    names = " + ".join(components)  # a comma is not allowed in a title
    prefix = (f"{proj} - {names}" if proj and components else proj or names or "Engineering")[:61].rstrip(" -+")
    return " AND ".join(clauses), prefix


def dashboard_plan(adapter: JiraAdapter, prefix: str, scope: str, share: str, project: str | None) -> dict:
    """The whole plan as plain data: four filters and the dashboard with its gadgets. The approval hash is over it."""
    if not _TITLE.fullmatch(prefix):
        raise ValueError(f"the title {prefix!r} is not a plain name (letters, digits, spaces and . _ / & : ( ) + -)")
    filters = [
        {"slot": "all", "name": f"{prefix}: All Deliverables", "jql": f"{scope} ORDER BY updated DESC, key ASC"},
        {"slot": "active", "name": f"{prefix}: Active / In Progress",
         "jql": f'({scope}) AND statusCategory = "In Progress" ORDER BY updated DESC, key ASC'},
        {"slot": "delivered", "name": f"{prefix}: Delivered by Fix Version",
         "jql": f"({scope}) AND statusCategory = Done AND fixVersion is not EMPTY "
                "ORDER BY fixVersion DESC, updated DESC"},
        {"slot": "blocked", "name": f"{prefix}: Blocked / Waiting",
         "jql": f'({scope}) AND (status in ("Blocked", "Waiting", "On Hold") OR labels in (blocked, waiting)) '
                "ORDER BY updated DESC"},
    ]
    return {"format": DASHBOARD_FORMAT, "mode": adapter.mode, "prefix": prefix, "share": share,
            "project": (project or "").strip().upper() or None, "scope": scope, "filters": filters,
            "dashboard": {"name": f"{prefix}: Dev Dashboard", "gadgets": [dict(g) for g in _GADGETS]}}


def dashboard_hash(plan: dict) -> str:
    """sha256 of the canonical plan. It does not depend on what Jira holds now, only on what would be written."""
    canonical = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def plan_filter_rows(plan: dict, existing: list[dict]) -> list[dict]:
    """One row per filter: CREATE, UPDATE (the JQL differs), UNCHANGED or CONFLICT (two filters share the name)."""
    rows = []
    for f in plan["filters"]:
        same = [e for e in existing if e["name"] == f["name"]]
        ids = sorted({e["id"] for e in same})
        row = {"slot": f["slot"], "name": f["name"], "jql": f["jql"], "id": None, "action": "CREATE"}
        if len(ids) > 1:
            row.update(action="CONFLICT", id=", ".join(ids))
        elif ids:
            row["id"] = ids[0]
            row["action"] = "UNCHANGED" if _fold(same[0]["jql"]) == _fold(f["jql"]) else "UPDATE"
        rows.append(row)
    return rows


def _share_permissions(adapter: JiraAdapter, plan: dict) -> list[dict]:
    if plan["share"] == "global":
        return [{"type": "global"}]
    if plan["share"] == "project":
        found = adapter._get(f"/project/{quote(plan['project'] or '')}")
        pid = str((found or {}).get("id") or "")
        if not pid.isdigit():
            raise JiraError(None, "cannot share with the project: Jira did not return its id")
        return [{"type": "project", "project": {"id": pid}}]
    return []


def _write_filters(adapter: JiraAdapter, plan: dict, rows: list[dict], perms: list[dict]) -> bool:
    """Create or update the filters (idempotent by exact name; never a DELETE). False on the first failed write."""
    desc = "Created by caddis dashboard-setup. Change the scope there and run it again."
    for r in rows:
        try:
            if r["action"] == "CREATE":
                body = {"name": r["name"], "description": desc, "jql": r["jql"], "favourite": True}
                if perms:
                    body["sharePermissions"] = perms
                resp = adapter.write("POST", "/filter", body)
                r["id"] = str(resp.get("id") or "")
                if not r["id"].isdigit():
                    raise JiraError(None, "Jira did not return the id of the new filter")
                r["result"] = f"CREATED filter {r['id']}"
            elif r["action"] == "UPDATE":
                body = {"name": r["name"], "jql": r["jql"]}
                if perms:
                    body["sharePermissions"] = perms
                adapter.write("PUT", f"/filter/{r['id']}", body)
                r["result"] = f"UPDATED filter {r['id']}"
            else:
                r["result"] = f"UNCHANGED filter {r['id']}"
        except JiraError as err:
            r["result"] = f"FAILED: {err}"
            return False
    return True


def _write_dashboard(adapter: JiraAdapter, plan: dict, rows: list[dict], perms: list[dict]) -> dict:
    """Create the dashboard and its gadgets, best effort. Many Jira servers lock these calls: a refusal is not an
    error but the `blueprint_fallback` mode (the filters stay, and the blueprint says how to finish by hand)."""
    spec = plan["dashboard"]
    out: dict = {"mode": "created", "name": spec["name"], "id": None, "url": None, "gadgets": [], "note": ""}
    ids = {r["slot"]: r["id"] for r in rows}
    try:
        existing = adapter.find_dashboard(spec["name"])
        if existing:
            out.update(mode="existing", id=existing, url=adapter.dashboard_url(existing),
                       note="a dashboard with this name exists; its gadgets were not changed")
            return out
        resp = adapter.write("POST", "/dashboard", {
            "name": spec["name"], "description": "Created by caddis dashboard-setup.",
            "sharePermissions": perms, "editPermissions": []})
        dash = str(resp.get("id") or "")
        if not dash.isdigit():
            raise JiraError(404, "Jira did not return a usable dashboard id")
        out.update(id=dash, url=adapter.dashboard_url(dash))
        for g in spec["gadgets"]:
            made = adapter.write("POST", f"/dashboard/{dash}/gadget", {
                "moduleKey": GADGET_PREFIX + g["module"], "title": g["title"], "position": g["position"],
                "color": "blue"})
            item = str(made.get("id") or "")
            if not item.isdigit():
                raise JiraError(404, "Jira did not return a usable gadget id")
            adapter.write("PUT", f"/dashboard/{dash}/items/{item}/properties/config",
                          {**g["config"], "filterId": f"filter-{ids[g['filter']]}"})
            out["gadgets"].append(g["title"])
    except JiraError as err:
        text = adapter.clean(str(err), MAX_ERROR_TEXT)
        if err.status in DASHBOARD_REFUSED:
            out.update(mode="blueprint_fallback", note=f"this Jira refused the dashboard calls ({text})")
        else:
            out.update(mode="failed", note=text, status=err.status)
    return out


def _dashboard_text(adapter: JiraAdapter, plan: dict, rows: list[dict], dash: dict | None, digest: str | None,
                    preview: bool) -> list[str]:
    """The printable report. Every line is redacted by the caller."""
    lines = [f"DASHBOARD SETUP: {plan['prefix']} ({plan['mode']}, share {plan['share']})", f"SCOPE: {plan['scope']}"]
    for n, r in enumerate(rows, 1):
        lines.append(f"FILTER {n} {r['action']}{' ' + r['id'] if r['id'] and r['action'] != 'CREATE' else ''}: "
                     f"{r['name']}")
        lines.append(f"  JQL: {r['jql']}")
        if r.get("result"):
            lines.append(f"  {r['result']}")
    spec = plan["dashboard"]
    if preview:
        lines.append(f"DASHBOARD PLAN: {spec['name']} with {len(spec['gadgets'])} gadgets (best effort: if this Jira "
                     "refuses the dashboard calls, a blueprint is printed instead and the filters stay)")
        for g in spec["gadgets"]:
            lines.append(f"  GADGET: {g['title']} ({g['kind']}) <- filter {g['filter']}")
        if digest:
            lines += [f"APPROVE_SHA256: {digest}", f"APPROVE: {digest[:8]}"]
        return lines
    if dash:
        lines.append(f"DASHBOARD: {dash['mode']}" + (f" ({dash['note']})" if dash.get("note") else ""))
        if dash.get("url"):
            lines.append(f"  URL: {dash['url']}")
        if dash["mode"] in ("blueprint_fallback", "failed"):
            lines += _blueprint_lines(adapter, plan, rows)
    return lines


def _blueprint_lines(adapter: JiraAdapter, plan: dict, rows: list[dict]) -> list[str]:
    """The copy-paste Dev Dashboard Gadget Blueprint: each filter with its id, link and JQL, and the four gadgets."""
    by_slot = {r["slot"]: r for r in rows}
    lines = ["DEV DASHBOARD GADGET BLUEPRINT",
             f'In Jira, create a dashboard named "{plan["dashboard"]["name"]}" with two columns, then add:']
    for n, g in enumerate(plan["dashboard"]["gadgets"], 1):
        r = by_slot[g["filter"]]
        lines += [f"  GADGET {n} (row {g['position']['row'] + 1}, column {g['position']['column'] + 1}): "
                  f"{g['title']} - gadget \"{g['kind']}\"",
                  f"    Saved filter: {r['name']} (id {r['id'] or '-'})", f"    Settings: {g['settings']}"]
    lines.append("SAVED FILTERS")
    for r in rows:
        lines += [f"  FILTER ID {r['id'] or '-'}: {r['name']}"]
        if r["id"]:
            lines.append(f"    URL: {adapter.filter_url(r['id'])}")
        lines.append(f"    JQL: {r['jql']}")
    return lines


def cmd_dashboard_setup(args, env, factory) -> int:
    """Four saved JQL filters and a dev dashboard for any scope. Without --approve (or with --dry-run) it only reads
    Jira and prints the plan and its sha256. `--approve <hash>` writes, and is refused when CADDIS_HEADLESS is set."""
    if args.approve and is_headless(env):
        return _err("REFUSED: dashboard-setup --approve is a human step; it never runs when CADDIS_HEADLESS is set",
                    caddis_exit.BLOCKED)
    if not (args.project or args.component or args.epics or args.label or args.jql):
        raise ValueError("dashboard-setup needs at least one scope: --project, --component, --epics, --label or "
                         "--jql")
    if args.share == "project" and not args.project:
        raise ValueError("--share project needs --project")
    components = resolve_components(args.component, {})
    adapter = _adapter(env, factory)
    scope, default_prefix = dashboard_scope(adapter, args.project, components, args.epics, args.label, args.jql)
    prefix = (args.name or "").strip() or default_prefix
    plan = dashboard_plan(adapter, prefix, scope, args.share, args.project)
    digest = dashboard_hash(plan)
    preview = args.dry_run or not args.approve
    if not preview and not approval_matches(args.approve, digest):
        return _err("REFUSED: the approval does not match the plan now (a changed scope, name or share, or a wrong "
                    "hash). Preview again and approve the new hash. Nothing was sent.", caddis_exit.BLOCKED)
    try:
        rows = plan_filter_rows(plan, adapter.list_filters(prefix))
        existing_dash = adapter.find_dashboard(plan["dashboard"]["name"]) if preview else None
    except JiraError as err:
        return _failed(err)
    conflicts = [r for r in rows if r["action"] == "CONFLICT"]
    dash: dict | None = None
    code = caddis_exit.CLEAN
    if conflicts and not preview:
        for r in conflicts:
            print(f"CONFLICT: more than one filter is named {r['name']!r} (ids {r['id']}); rename or merge them in "
                  "Jira. Nothing was sent.", file=sys.stderr)
        return caddis_exit.BLOCKED
    if not preview:
        try:
            perms = _share_permissions(adapter, plan)  # one GET (project share only), before any write
        except JiraError as err:
            return _failed(err)
        adapter.arm_writes()
        if not _write_filters(adapter, plan, rows, perms):
            code = caddis_exit.BLOCKED
        else:
            dash = _write_dashboard(adapter, plan, rows, perms)
            if dash["mode"] == "failed":
                code = caddis_exit.NOT_RUN if dash.get("status") is None else caddis_exit.BLOCKED
    report = {"preview": preview, "digest": digest, "plan": plan, "filters": [
        {**r, "url": adapter.filter_url(r["id"]) if r["id"] and str(r["id"]).isdigit() else None} for r in rows],
              "dashboard_mode": (dash or {}).get("mode") or ("existing" if existing_dash else "preview"),
              "dashboard": dash}
    if dash and dash["mode"] in ("blueprint_fallback", "failed"):
        report["blueprint"] = _blueprint_lines(adapter, plan, rows)
    if args.json:
        print(_dashboard_json(adapter, report))
        return code
    lines = _dashboard_text(adapter, plan, rows, dash, digest if preview else None, preview)
    if preview and any(r["action"] == "UPDATE" for r in rows):
        lines.append("NOTE: a filter with this name exists and its JQL differs: approving rewrites it. Use --name to "
                     "keep two scopes apart.")
    if preview and existing_dash:
        lines.append(f"NOTE: a dashboard named {plan['dashboard']['name']!r} exists (id {existing_dash}); "
                     "it is not changed")
    if preview:
        lines.append("PREVIEW: nothing was sent" + (" (--dry-run)" if args.approve else ""))
        lines.append(f"NEXT: a person reads the plan, then runs: {STABLE_RUN} dashboard-setup <the same selectors> "
                     f"--approve {digest[:8]}")
    for line in lines:
        print(_safe_text(adapter, line))
    return code


def _safe_text(adapter: JiraAdapter, text: str) -> str:
    """Secrets and personal data masked on every line of a report; line breaks are kept."""
    text = _ZERO_WIDTH.sub("", text or "")
    return caddis_redact.redact_pii(caddis_redact.redact(text, adapter._secrets))


def _dashboard_json(adapter: JiraAdapter, report: dict) -> str:
    return _safe_text(adapter, json.dumps(report, indent=2))


def _default_factory(cfg: JiraConfig) -> JiraAdapter:
    return make_adapter(cfg)


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="caddis_jira.py", description="Jira for the AI Software Factory: reads, the "
                                "human-gated Q&A loop, story sync and transitions.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="prove the Jira login: mode, version, authenticated")
    c.add_argument("--json", action="store_true")
    r = sub.add_parser("read", help="read one issue (redacted)")
    r.add_argument("key")
    r.add_argument("--comments", action="store_true")
    r.add_argument("--children", action="store_true", help="child issues of an Epic: counts only")
    r.add_argument("--discover-schema", action="store_true", help="agile field ids and the project's issue types")
    r.add_argument("--json", action="store_true")
    e = sub.add_parser("epic", help="print the plan's jira_epic, or SKIPPED when it has none")
    e.add_argument("--plan", required=True)
    qd = sub.add_parser("qa-draft", help="start or refresh the editable Q&A round draft (no network)")
    qd.add_argument("--epic", required=True)
    qd.add_argument("--question", action="append", help="add one OPEN question (repeat for more)")
    qd.add_argument("--dir", default=".", help="the repo root that holds .caddis/qa/")
    qp = sub.add_parser("qa-post", help="preview a round and its hash; --approve <hash> posts it (a person only)")
    qp.add_argument("--epic", required=True)
    qp.add_argument("--round", type=int, required=True)
    qp.add_argument("--approve", help="the 8-character prefix or the full sha256 from the preview")
    qp.add_argument("--dir", default=".")
    ql = sub.add_parser("qa-pull", help="read the answers from Jira comments into the ledger (GET only)")
    ql.add_argument("--epic", required=True)
    ql.add_argument("--promote-decisions", action="store_true",
                    help="write each new answer as .caddis/decisions/<date>-qa-<epic>-<qid>.md")
    ql.add_argument("--dir", default=".")
    qs = sub.add_parser("qa-status", help="counts by state; --gate exits 1 while a blocking question is OPEN")
    qs.add_argument("--epic")
    qs.add_argument("--plan", help="read the Epic from the plan (SKIPPED when it has no jira_epic)")
    qs.add_argument("--gate", action="store_true")
    qs.add_argument("--json", action="store_true")
    qs.add_argument("--dir", default=".")
    ss = sub.add_parser("sync-stories", help="one Jira Story per plan phase, idempotent by label; never deletes")
    ss.add_argument("--plan", required=True)
    ss.add_argument("--issue-type", help="beats jira_issue_type: / jira_story_type: in the plan (default Story)")
    ss.add_argument("--granularity", choices=GRANULARITIES,
                    help="phase (default): a Story per phase; milestone: a Story per Tracker milestone "
                         "(beats jira_granularity: in the plan)")
    ss.add_argument("--by-milestone", action="store_true", help="the same as --granularity milestone")
    ss.add_argument("--component", action="append",
                    help="a Jira component (repeat or use commas); beats jira_component:. Unset = none is sent")
    ss.add_argument("--dry-run", action="store_true", help="read Jira, print the plan of changes, write nothing")
    ss.add_argument("--offline", action="store_true", help="no Jira at all: print the phases that would sync")
    ss.add_argument("--json", action="store_true")
    t = sub.add_parser("transition", help="move an issue to a target status by the workflow's transition")
    t.add_argument("key")
    t.add_argument("--to", required=True, help="the target status (or the transition name)")
    t.add_argument("--fix-version", help="also add this fix version (for example v2026.11.25.1)")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--json", action="store_true")
    tm = sub.add_parser("transition-milestone", help="move the Story of one plan milestone (and set its fix version)")
    tm.add_argument("--plan", required=True)
    tm.add_argument("--milestone", required=True, help="the milestone id from the plan's Tracker, for example M1")
    tm.add_argument("--to", required=True, help="the target status (or the transition name)")
    tm.add_argument("--fix-version", help="also add this fix version (for example v2026.11.25.1)")
    tm.add_argument("--dry-run", action="store_true")
    tm.add_argument("--json", action="store_true")
    ds = sub.add_parser("dashboard-setup", help="four saved JQL filters and a dev dashboard for any scope; "
                                                "preview first, --approve <hash> writes")
    ds.add_argument("--project", help="a Jira project key")
    ds.add_argument("--component", action="append", help="a component (repeat or use commas); optional")
    ds.add_argument("--epics", help="Epic keys, comma separated: the issues under those Epics")
    ds.add_argument("--label", help="a Jira label")
    ds.add_argument("--jql", help="an extra JQL filter clause (no ORDER BY), wrapped in parentheses")
    ds.add_argument("--name", help="the title prefix of the filters and the dashboard")
    ds.add_argument("--share", choices=SHARE_MODES, default="private",
                    help="who may see the new filters and dashboard (default private)")
    ds.add_argument("--dry-run", action="store_true", help="preview only, even with --approve")
    ds.add_argument("--approve", help="the 8-character prefix or the full sha256 from the preview (a person only)")
    ds.add_argument("--json", action="store_true")
    return p


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None,
         adapter_factory: Callable[[JiraConfig], JiraAdapter] | None = None) -> int:
    env = os.environ if env is None else env
    factory = adapter_factory or _default_factory
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return caddis_exit.CLEAN if exc.code == 0 else caddis_exit.ERROR
    handlers = {"check": cmd_check, "read": cmd_read, "epic": cmd_epic, "qa-draft": cmd_qa_draft,
                "qa-post": cmd_qa_post, "qa-pull": cmd_qa_pull, "qa-status": cmd_qa_status,
                "sync-stories": cmd_sync_stories, "transition": cmd_transition,
                "transition-milestone": cmd_transition_milestone, "dashboard-setup": cmd_dashboard_setup}
    try:
        return handlers[args.cmd](args, env, factory)
    except ConfigError as exc:
        print(f"NOT CONFIGURED: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    except (ValueError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return caddis_exit.ERROR


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):  # a Windows console is cp1252: Jira text holds any character
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
