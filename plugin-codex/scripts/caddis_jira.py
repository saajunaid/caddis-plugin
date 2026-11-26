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
blocking question is OPEN. `sync-stories --plan <p> [--issue-type T] [--dry-run]` makes one Story per plan phase,
idempotent by the label `caddis-<plan>-p<n>`, and never deletes. `transition <KEY> --to <status>` moves an issue.
`JiraAdapter.request` stays GET only; a write goes through `JiraAdapter.write`, which refuses until the command arms
it, allows only POST/PUT on four REST paths and never DELETE.

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
)
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


def story_label(slug: str, pid: str) -> str:
    return f"caddis-{_slug(slug)}-p{_slug(pid)}"


def story_marker(slug: str, pid: str) -> str:
    return f"caddis:{_slug(slug)}#P{pid}"


def _fold(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def render_story(adapter: JiraAdapter, slug: str, phase: PlanPhase) -> dict:
    """The summary and description caddis writes for one phase (redacted, in the adapter's body format)."""
    summary = adapter.clean(f"[{_slug(slug)} P{phase.pid}] {phase.title}", MAX_SUMMARY)
    description = adapter.story_description(adapter.clean(phase.goal, None), adapter.clean(phase.exit_gate, None),
                                            story_marker(slug, phase.pid))
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


def _child_matches(adapter: JiraAdapter, issue: dict, label: str, marker_rx: re.Pattern, key: str = "") -> bool:
    f = issue.get("fields") or {}
    if key and issue.get("key") == key:
        return True
    if label in (f.get("labels") or []):
        return True
    return bool(marker_rx.search(adapter.body_text(f.get("description"))))


def plan_story_rows(adapter: JiraAdapter, slug: str, phases: list[PlanPhase], children: list[dict], *, project: str,
                    epic: str, issue_type: str, epic_link_field: str | None, points_field: str | None,
                    ac_field: str | None = None) -> list[dict]:
    """One row per phase: CREATE, UPDATE, UNCHANGED, BLOCKED (leak lint) or CONFLICT (two issues match)."""
    origin = _origin(adapter.base_url)
    rows = []
    for phase in phases:
        label = story_label(slug, phase.pid)
        marker_rx = re.compile(re.escape(story_marker(slug, phase.pid)) + r"(?![0-9A-Za-z.])")
        story = render_story(adapter, slug, phase)
        row = {"phase": phase.pid, "title": adapter.clean(phase.title, MAX_SUMMARY), "status": phase.status,
               "label": label,
               "summary": story["summary"], "key": None, "changes": [], "lint": [], "points": None}
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
            row["action"] = "UPDATE" if row["changes"] else "UNCHANGED"
            if row["changes"]:
                body: dict = {"fields": {"summary": story["summary"], "description": story["description"]}}
                if "acceptance criteria" in row["changes"]:
                    body["fields"][ac_field] = ac_value
                if "label" in row["changes"]:
                    body["update"] = {"labels": [{"add": label}]}
                row["body"] = body
        else:
            row["action"] = "CREATE"
            fields = {"project": {"key": project}, "issuetype": {"name": issue_type}, "summary": story["summary"],
                      "description": story["description"], "labels": [label],
                      **adapter.epic_link(epic, epic_link_field)}
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


def plan_sync(adapter: JiraAdapter, slug: str, phases: list[PlanPhase], epic: str, issue_type: str) -> SyncPlan:
    """The read half of sync-stories (GET only, no write is ever armed here): read the Epic (a moved Epic is read by
    the key Jira returns), the project's issue types, the field schema and the Epic's children, then plan one row per
    phase (CREATE, UPDATE, UNCHANGED, BLOCKED or CONFLICT). `caddis_gate.py gate2` calls it as well.
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
    wanted = ["summary", "description", "labels", "issuetype", "status"] + ([ac_field] if ac_field else [])
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
                           epic_link_field=epic_field, points_field=points_field, ac_field=ac_field)
    return SyncPlan(resolved, project, issue_type, epic_field, points_field, ac_field, jql, children, notes, rows,
                    fetched)


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
        head = f"P{r['phase']} {r['action']}"
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
    if args.offline:
        print(f"PLAN: {slug} ({len(phases)} phases)\nEPIC: {epic}\nISSUE TYPE: {issue_type} ({type_source})")
        for p in phases:
            print(f"P{p.pid} PLANNED [{slug} P{p.pid}] {p.title} label={story_label(slug, p.pid)} "
                  f"points={risk_points(p.risk)}")
        print("OFFLINE: Jira was not read and nothing was sent")
        return caddis_exit.CLEAN
    adapter = _adapter(env, factory)
    try:
        sync = plan_sync(adapter, slug, phases, epic, issue_type)
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
                        created[r["phase"]] = r["key"]
                elif r["action"] == "UPDATE":
                    adapter.write("PUT", f"/issue/{quote(r['key'])}", r["body"])
                    r["result"] = f"UPDATED {r['key']}"
            except JiraError as err:
                r["result"] = f"FAILED: {err}"
                failed = True
                break
        if created:
            write_back_story_keys(plan_path, created)
    bad = [r for r in rows if r["action"] in ("BLOCKED", "CONFLICT")]
    tally = Counter(r["action"] for r in rows)
    report = {"plan": slug, "epic": epic, "resolved_epic": resolved, "project": project, "issue_type": issue_type,
              "issue_type_source": type_source, "epic_link_field": epic_field, "story_points_field": points_field,
              "acceptance_criteria_field": ac_field, "children_jql": jql, "dry_run": bool(args.dry_run),
              "notes": notes, "rows": rows}
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"PLAN: {slug} ({len(phases)} phases)")
        print(f"EPIC: {epic}" + (f" (moved to {resolved})" if resolved != epic else "") + f", project {project}")
        print(f"ISSUE TYPE: {issue_type} ({type_source})")
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
            print(f"DONE: {summary}" + (f"; plan updated with {len(created)} Jira Story key(s)" if created else ""))
    if failed:
        return caddis_exit.BLOCKED
    return caddis_exit.BLOCKED if bad else caddis_exit.CLEAN


_FIX_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,63}")


def cmd_transition(args, env, factory) -> int:
    key = check_key(args.key)
    target = (args.to or "").strip()
    if not target:
        raise ValueError("--to needs a status name")
    if args.fix_version and not _FIX_VERSION.fullmatch(args.fix_version):
        raise ValueError("--fix-version looks like v2026.11.25.1 (letters, digits, . _ + -)")
    adapter = _adapter(env, factory)
    try:
        issue = adapter.get_issue(key)
        key = check_key(issue["key"] or key)  # a moved issue: act on the key Jira returns
        current = str(issue["status"] or "")
        already = current.lower() == target.lower()
        options = [] if already else adapter.transition_list(key)
    except JiraError as err:
        return _failed(err)
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
    result = {"key": key, "from": current, "to": pick["to"] if pick else current, "id": pick["id"] if pick else None,
              "name": pick["name"] if pick else None, "fix_version": args.fix_version, "dry_run": bool(args.dry_run)}
    if not args.dry_run:
        adapter.arm_writes()
        try:
            if args.fix_version:
                adapter.write("PUT", f"/issue/{quote(key)}",
                              {"update": {"fixVersions": [{"add": {"name": args.fix_version}}]}})
            if pick:
                adapter.write("POST", f"/issue/{quote(key)}/transitions", {"transition": {"id": pick["id"]}})
        except JiraError as err:
            return _failed(err)
    if args.json:
        print(json.dumps(result))
        return caddis_exit.CLEAN
    if args.fix_version:
        print(f"{'WOULD SET' if args.dry_run else 'SET'} FIX VERSION: {key} {args.fix_version}")
    if pick is None:
        print(f"ALREADY: {key} is {current}")
    elif args.dry_run:
        print(f'WOULD TRANSITION: {key} {current} -> {pick["to"]} via "{pick["name"]}" (id {pick["id"]})')
    else:
        print(f'TRANSITIONED: {key} {current} -> {pick["to"]} via "{pick["name"]}" (id {pick["id"]})')
    return caddis_exit.CLEAN


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
    ss.add_argument("--dry-run", action="store_true", help="read Jira, print the plan of changes, write nothing")
    ss.add_argument("--offline", action="store_true", help="no Jira at all: print the phases that would sync")
    ss.add_argument("--json", action="store_true")
    t = sub.add_parser("transition", help="move an issue to a target status by the workflow's transition")
    t.add_argument("key")
    t.add_argument("--to", required=True, help="the target status (or the transition name)")
    t.add_argument("--fix-version", help="also add this fix version (for example v2026.11.25.1)")
    t.add_argument("--dry-run", action="store_true")
    t.add_argument("--json", action="store_true")
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
                "sync-stories": cmd_sync_stories, "transition": cmd_transition}
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
