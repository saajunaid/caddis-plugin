"""Shared Confluence publish engine (AI Software Factory, Phase 1): one marked section per document, diagrams as PNGs.

`check [--json]` proves the Confluence login (GET only) and reports whether the diagram renderer is ready.
`render-diagrams --input <md|xhtml> --slug <slug> --out-dir <dir>` renders every Mermaid block to a 2x PNG on a white
canvas and checks it, with no network. Use it to preview figures.
`publish --page-id <id> --slug <slug> --input <md|xhtml> [--dry-run] [--force-overwrite] [--out-dir <dir>]` writes the
document into the page's marked section:
- Markdown becomes Confluence storage XHTML. Each Mermaid block becomes a PNG attachment
  `<slug>-fig<N>-<sha256_8>.png` and an `<ac:image>` that points to it. No SVG, no foreignObject, no PlantUML is ever
  sent to Confluence. A diagram that fails a render check stops the publish before any request.
- The section sits between two anchor macros, `caddis-doc-<slug>-start-<hash8>` and `caddis-doc-<slug>-end`. hash8
  is the sha256 of the canonical section body. Every byte outside the markers stays as it is.
- Anti-overwrite: before a write, the section on the live page is hashed again. When that hash differs from the
  marker's hash, a person edited the section in Confluence: the publish stops (exit 1) and prints a unified diff of
  the live section and the new one. Only a person may pass `--force-overwrite`; it is refused when CADDIS_HEADLESS
  is set.
- HTTP 409 (someone saved the page in between): read the page again, run the anti-overwrite check on the fresh body
  and write again, at most MAX_CONFLICT_RETRIES times.
- After the write, the page is read back. When Confluence stored the section in a form the canonical hash does not
  absorb, the marker is stamped again with the live hash, so the next publish does not see its own section as an edit.
`publish-catalog --page-id <id> [--slug db-catalog] --input <summary.md> [--attach <file> ...]
[--state-hash-file <path>] [--dry-run] [--force-overwrite]` is the post-deploy hook for a generated catalog:
- One SHA-256 covers the summary and every attached file. The section shows it, with a link and a hash per file, so
  a change to any file changes the section marker. The same anti-overwrite check and 409 retry apply.
- A `--state-hash-file` that holds the same combined hash ends the run before any request (`ACTION: unchanged`).
  Otherwise the live page decides: when the section and every attachment comment (`caddis sha256:<hex>`) match, the
  run writes nothing (`ACTION: unchanged`). When only an attachment is missing or different, only that file is
  uploaded (`ACTION: attachments`). When the hash changed, only the changed files are uploaded and only the catalog
  section is rewritten (`ACTION: add` or `update`). The state file is written after each run that is not a dry run.
- The summary must hold no Mermaid block (exit 4): render diagrams with `publish`.

Renderer: headless Microsoft Edge (`channel="msedge"`) through Playwright for Python, with a LOCAL mermaid.min.js:
`CADDIS_MERMAID_JS`, else `~/.caddis/vendor/mermaid.min.js`. No CDN, no mmdc, no browser download.

Keys (the environment first, then `CADDIS_KEYS_FILE` or `~/.caddis/keys.env`): `CONFLUENCE_URL` (https only) and
`CONFLUENCE_TOKEN`; `CONFLUENCE_MODE` `dc` (default, Bearer personal access token) or `cloud` (Basic
`CONFLUENCE_EMAIL` + API token; CONFLUENCE_URL then ends in /wiki). Every request goes to the CONFLUENCE_URL origin
only, a redirect is an error, and every text from Confluence goes through `caddis_redact`.
Exit codes: 0 clean, 1 refused (hand edit, bad diagram, Confluence error), 3 not configured, renderer missing or
network failure, 4 bad input.
"""

from __future__ import annotations

import argparse
import base64
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import difflib
import hashlib
import html
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import sys
import tempfile
import urllib.error
from urllib.parse import quote, urlencode, urlsplit
import urllib.request
import uuid

try:
    import caddis_exit
except ModuleNotFoundError as exc:
    if exc.name != "caddis_exit":
        raise
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "claude-harness" / "scripts"))
    import caddis_exit

import caddis_redact
from caddis_stories import MarkerError, _marker_re
from oss_model import _parse_keys_file

PREFIX = "caddis-doc"
DEFAULT_KEYS_FILE = "~/.caddis/keys.env"
DEFAULT_MERMAID_JS = "~/.caddis/vendor/mermaid.min.js"
MODES = ("dc", "cloud")
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
PAGE_ID = re.compile(r"[0-9]{1,20}")
MAX_CONFLICT_RETRIES = 3
MAX_ERROR_TEXT = 300
MAX_DIFF_LINES = 200
SCALE = 2

__all__ = ["MarkerError"]


# ---------------------------------------------------------------- config

class ConfigError(Exception):
    """A Confluence key is missing or not usable. The text names the variable, never its value."""


@dataclass
class ConfluenceConfig:
    base_url: str
    token: str
    mode: str = "dc"
    email: str | None = None

    def __repr__(self) -> str:  # never show the token in a traceback or a log
        return f"ConfluenceConfig(base_url={self.base_url!r}, mode={self.mode!r}, token='***')"


def load_config(env: Mapping[str, str]) -> ConfluenceConfig:
    keys_path = env.get("CADDIS_KEYS_FILE") or DEFAULT_KEYS_FILE
    try:
        file_keys = _parse_keys_file(keys_path)
    except (OSError, UnicodeDecodeError) as exc:
        raise ConfigError(f"cannot read the keys file: {type(exc).__name__}") from None

    def value(name: str) -> str:
        return (env.get(name) or "").strip() or (file_keys.get(name) or "").strip()

    for name in ("CONFLUENCE_URL", "CONFLUENCE_TOKEN"):
        if not value(name):
            raise ConfigError(f"{name} is not set (environment or keys file)")
    base_url = value("CONFLUENCE_URL").rstrip("/")
    parts = urlsplit(base_url)
    try:
        parts.port
    except ValueError:
        raise ConfigError("CONFLUENCE_URL has a port that is not a number") from None
    if parts.scheme != "https" or not parts.hostname or parts.query or parts.fragment or parts.username:
        raise ConfigError("CONFLUENCE_URL must be https://<host>[:port][/path], with no query or user info")
    mode = (value("CONFLUENCE_MODE") or "dc").lower()
    if mode not in MODES:
        raise ConfigError("CONFLUENCE_MODE must be dc or cloud")
    email = value("CONFLUENCE_EMAIL") or None
    if mode == "cloud" and not email:
        raise ConfigError("CONFLUENCE_EMAIL is not set (CONFLUENCE_MODE=cloud needs it for Basic auth)")
    return ConfluenceConfig(base_url=base_url, token=value("CONFLUENCE_TOKEN"), mode=mode, email=email)


# ---------------------------------------------------------------- client

class ConfluenceError(Exception):
    """A Confluence call failed. `status` is the HTTP status, or None for a network failure or a refused call.
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


class Client:
    """Confluence REST (Server/DC and Cloud share /rest/api/content). Host-locked to the CONFLUENCE_URL origin."""

    def __init__(self, base_url: str, token: str, mode: str = "dc", email: str | None = None, timeout: float = 30.0,
                 send: Callable | None = None):
        self.base_url = base_url.rstrip("/")
        self.mode = mode
        self._token = token
        self._email = email or ""
        self.timeout = timeout
        self._send = send or _default_send
        secrets = caddis_redact.load_secrets(Path.home())
        if token:
            secrets = secrets + [token, base64.b64encode(f"{self._email}:{token}".encode()).decode("ascii")]
        self._secrets = sorted(set(secrets), key=len, reverse=True)

    def __repr__(self) -> str:
        return f"Client(base_url={self.base_url!r}, mode={self.mode!r})"

    def _auth(self) -> str:
        if self.mode == "cloud":
            return "Basic " + base64.b64encode(f"{self._email}:{self._token}".encode()).decode("ascii")
        return f"Bearer {self._token}"

    def clean(self, text: str, limit: int | None = MAX_ERROR_TEXT) -> str:
        text = caddis_redact.redact_pii(caddis_redact.redact(text or "", self._secrets))
        return text[:limit] if limit else text

    def request(self, method: str, path: str, query: dict | None = None, body: dict | None = None,
                data: bytes | None = None, headers: dict | None = None) -> dict:
        url = self.base_url + path + ("?" + urlencode(query) if query else "")
        return self.request_url(method, url, body=body, data=data, headers=headers)

    def request_url(self, method: str, url: str, body: dict | None = None, data: bytes | None = None,
                    headers: dict | None = None) -> dict:
        if _origin(url) != _origin(self.base_url):
            raise ConfluenceError(None, "host lock: the URL is not on the CONFLUENCE_URL origin; no request sent")
        path = urlsplit(url).path
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers = {**(headers or {}), "Content-Type": "application/json"}
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", self._auth())
        req.add_header("Accept", "application/json")
        for name, value in (headers or {}).items():
            req.add_header(name, value)
        try:
            status, raw = self._send(req, self.timeout)
        except ConfluenceError:
            raise
        except (OSError, http.client.HTTPException) as exc:
            raise ConfluenceError(None, f"network error {method} {path}: {self.clean(f'{type(exc).__name__}: {exc}')}"
                                  ) from None
        text = (raw or b"").decode("utf-8", errors="replace")
        if 300 <= status < 400:
            raise ConfluenceError(status, f"HTTP {status} {method} {path}: a redirect, not followed. CONFLUENCE_URL "
                                          "may miss the context path of the server (for example /confluence)")
        if not 200 <= status < 300:
            raise ConfluenceError(status, f"HTTP {status} {method} {path}: {self.clean(text)}")
        if not text.strip():
            return {}
        try:
            return json.loads(text)
        except ValueError:
            raise ConfluenceError(status, f"HTTP {status} {method} {path}: the answer is not JSON") from None

    def current_user(self) -> dict:
        return self.request("GET", "/rest/api/user/current")

    def get_page(self, page_id: str) -> dict:
        return self.request("GET", f"/rest/api/content/{quote(page_id, safe='')}",
                            {"expand": "body.storage,version,space"})

    def update_page(self, page: dict, storage: str) -> dict:
        """PUT the new body with version + 1. Confluence answers 409 when someone saved the page in between."""
        return self.request("PUT", f"/rest/api/content/{quote(str(page['id']), safe='')}", body={
            "id": page["id"], "type": "page", "title": page["title"], "space": {"key": page["space"]["key"]},
            "version": {"number": page["version"]["number"] + 1, "minorEdit": True},
            "body": {"storage": {"value": storage, "representation": "storage"}}})

    def find_attachment(self, page_id: str, filename: str) -> dict | None:
        data = self.request("GET", f"/rest/api/content/{quote(page_id, safe='')}/child/attachment",
                            {"filename": filename, "expand": "version,metadata"})
        results = data.get("results") or []
        return results[0] if results else None

    def upload_attachment(self, page_id: str, filename: str, payload: bytes, comment: str,
                          existing: dict | None = None, content_type: str = "image/png") -> dict:
        """A new attachment, or a new version of `existing`. Multipart, with the XSRF bypass header."""
        boundary = "caddis" + uuid.uuid4().hex
        parts = [
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n".encode() + payload + b"\r\n",
            f'--{boundary}\r\nContent-Disposition: form-data; name="comment"\r\n\r\n{comment}\r\n'.encode(),
            f'--{boundary}\r\nContent-Disposition: form-data; name="minorEdit"\r\n\r\ntrue\r\n'.encode(),
            f"--{boundary}--\r\n".encode(),
        ]
        path = f"/rest/api/content/{quote(page_id, safe='')}/child/attachment"
        if existing:
            path += f"/{quote(str(existing['id']), safe='')}/data"
        return self.request("POST", path, data=b"".join(parts), headers={
            "X-Atlassian-Token": "nocheck", "Content-Type": f"multipart/form-data; boundary={boundary}"})


def make_client(cfg: ConfluenceConfig) -> Client:
    return Client(cfg.base_url, cfg.token, mode=cfg.mode, email=cfg.email)


# ---------------------------------------------------------------- canonical hash and the marked section

_VOLATILE_ATTRS = re.compile(r'\s+(?:ac:macro-id|ac:local-id|local-id|ac:schema-version|data-[a-z-]+)="[^"]*"')


def canonical(xhtml: str) -> str:
    """The section body in a form that Confluence's own re-serialization does not change (for hashing only)."""
    text = html.unescape(_VOLATILE_ATTRS.sub("", xhtml or ""))
    text = re.sub(r"\s*/>", "/>", text)
    text = re.sub(r">\s+<", "><", text)
    return re.sub(r"\s+", " ", text).strip()


def content_hash(inner: str) -> str:
    return hashlib.sha256(canonical(inner).encode("utf-8")).hexdigest()[:8]


def _anchor(name: str) -> str:
    return (f'<p><ac:structured-macro ac:name="anchor"><ac:parameter ac:name="">{name}</ac:parameter>'
            f'</ac:structured-macro></p>')


def build_section(slug: str, inner: str, stamp: str | None = None) -> str:
    return (_anchor(f"{PREFIX}-{slug}-start-{stamp or content_hash(inner)}") + inner
            + _anchor(f"{PREFIX}-{slug}-end"))


class DriftError(Exception):
    """The section on the live page was edited in Confluence since caddis wrote it. `diff` is live vs new."""

    def __init__(self, slug: str, diff: str):
        super().__init__(f"the {slug} section was edited in Confluence; refusing to overwrite it")
        self.diff = diff


@dataclass
class LiveSection:
    start: int          # offset of the start marker
    inner_start: int    # offset just after the start marker
    inner_end: int      # offset of the end marker
    end: int            # offset just after the end marker
    stored: str | None  # the hash in the start marker
    live: str           # the hash of the live inner body

    @property
    def edited(self) -> bool:
        return self.stored != self.live


def locate(body: str, slug: str) -> LiveSection | None:
    starts = list(_marker_re(slug, "start", PREFIX).finditer(body))
    ends = list(_marker_re(slug, "end", PREFIX).finditer(body))
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1:
        raise MarkerError(f"{len(starts)} start and {len(ends)} end markers for {slug}")
    s, e = starts[0], ends[0]
    if e.start() < s.end():
        raise MarkerError(f"the end marker of {slug} is before its start marker")
    inner = body[s.end():e.start()]
    return LiveSection(s.start(), s.end(), e.start(), e.end(), s.group(1) or s.group(2), content_hash(inner))


def _pretty(xhtml: str) -> list[str]:
    return canonical(xhtml).replace("><", ">\n<").splitlines(keepends=False)


def drift_diff(live_inner: str, new_inner: str) -> str:
    lines = list(difflib.unified_diff(_pretty(live_inner), _pretty(new_inner), "live (edited in Confluence)",
                                      "caddis (to publish)", lineterm=""))
    if len(lines) > MAX_DIFF_LINES:
        lines = lines[:MAX_DIFF_LINES] + [f"... {len(lines) - MAX_DIFF_LINES} more lines"]
    return "\n".join(lines)


def plan_update(body: str, slug: str, inner: str, force: bool = False,
                clean: Callable[[str], str] | None = None) -> tuple[str, str]:
    """(new body, action) with action add | update | unchanged. Raises DriftError on a hand edit (unless `force`)
    and MarkerError on broken markers. Every byte outside the markers stays the same."""
    found = locate(body, slug)
    section = build_section(slug, inner)
    if found is None:
        return body + section, "add"
    live_inner = body[found.inner_start:found.inner_end]
    if found.edited and not force:
        diff = drift_diff(live_inner, inner)
        raise DriftError(slug, clean(diff) if clean else caddis_redact.redact_pii(diff))
    if not found.edited and found.live == content_hash(inner):
        return body, "unchanged"
    return body[:found.start] + section + body[found.end:], "update"


# ---------------------------------------------------------------- Markdown to storage XHTML (the subset caddis docs use)

def _cdata(text: str) -> str:
    return "<![CDATA[" + text.replace("]]>", "]]]]><![CDATA[>") + "]]>"


def code_macro(language: str, text: str) -> str:
    lang = f'<ac:parameter ac:name="language">{html.escape(language)}</ac:parameter>' if language else ""
    return f'<ac:structured-macro ac:name="code">{lang}<ac:plain-text-body>{_cdata(text)}</ac:plain-text-body>' \
           "</ac:structured-macro>"


_EMPHASIS = [
    (re.compile(r"\*\*(.+?)\*\*"), r"<strong>\1</strong>"),
    (re.compile(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"), r"<em>\1</em>"),
    (re.compile(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])"), r"<em>\1</em>"),
]
# A link, or inline code: both are cut out BEFORE emphasis runs, so `_` or `*` in a URL or in code stays as it is.
_TOKENS = re.compile(r"(`[^`]+`|\[[^\]]+\]\(https?://[^)\s\"<>]+\))")
_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s\"<>]+)\)")


def _emphasis(text: str) -> str:
    text = html.escape(text, quote=False)
    for rx, repl in _EMPHASIS:
        text = rx.sub(repl, text)
    return text


def _inline(text: str) -> str:
    out = []
    for piece in _TOKENS.split(text):
        if piece.startswith("`") and piece.endswith("`") and len(piece) > 1:
            out.append(f"<code>{html.escape(piece[1:-1], quote=False)}</code>")
            continue
        link = _LINK.fullmatch(piece)
        if link:
            out.append(f'<a href="{html.escape(link.group(2), quote=True)}">{_emphasis(link.group(1))}</a>')
            continue
        out.append(_emphasis(piece))
    return "".join(out)


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def md_to_storage(md: str) -> str:
    """Headings, paragraphs, flat lists, pipe tables, block quotes, rules and fenced code (Mermaid included)."""
    lines = md.replace("\r\n", "\n").split("\n")
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                lines = lines[i + 1:]
                break
    out: list[str] = []
    para: list[str] = []
    i = 0

    def flush() -> None:
        if para:
            out.append("<p>" + _inline(" ".join(p.strip() for p in para)) + "</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        fence = re.match(r"^\s*(`{3,}|~{3,})\s*([\w+-]*)\s*$", line)
        if fence:
            flush()
            mark, lang, body = fence.group(1), fence.group(2), []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(mark):
                body.append(lines[i])
                i += 1
            out.append(code_macro(lang, "\n".join(body)))
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.+?)(?:\s+#+)?\s*$", line)
        if heading:
            flush()
            n = len(heading.group(1))
            out.append(f"<h{n}>{_inline(heading.group(2))}</h{n}>")
        elif re.match(r"^\s*\|.*\|\s*$", line):
            flush()
            rows = []
            while i < len(lines) and re.match(r"^\s*\|.*\|\s*$", lines[i]):
                rows.append(lines[i])
                i += 1
            html_rows = []
            for n, row in enumerate(rows):
                if n == 1 and re.fullmatch(r"[\s|:-]+", row):
                    continue
                tag = "th" if n == 0 and len(rows) > 1 and re.fullmatch(r"[\s|:-]+", rows[1]) else "td"
                html_rows.append("<tr>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in _cells(row)) + "</tr>")
            out.append("<table><tbody>" + "".join(html_rows) + "</tbody></table>")
            continue
        elif re.match(r"^\s*([-*+]|\d+[.)])\s+", line):
            flush()
            ordered = bool(re.match(r"^\s*\d+[.)]\s+", line))
            items = []
            while i < len(lines) and re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]):
                items.append("<li>" + _inline(re.sub(r"^\s*([-*+]|\d+[.)])\s+", "", lines[i])) + "</li>")
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        elif line.startswith(">"):
            flush()
            quote_lines = []
            while i < len(lines) and lines[i].startswith(">"):
                quote_lines.append(lines[i].lstrip(">").strip())
                i += 1
            out.append("<blockquote><p>" + _inline(" ".join(quote_lines)) + "</p></blockquote>")
            continue
        elif re.fullmatch(r"\s*(-{3,}|\*{3,})\s*", line):
            flush()
            out.append("<hr/>")
        elif not line.strip():
            flush()
        else:
            para.append(line)
        i += 1
    flush()
    return "".join(out)


# ---------------------------------------------------------------- Mermaid figures

_MERMAID_MACRO = re.compile(
    r'<ac:structured-macro\b[^>]*\bac:name="code"[^>]*>'
    r'(?:(?!</ac:structured-macro>).)*?<ac:parameter\b[^>]*\bac:name="language"[^>]*>\s*mermaid\s*</ac:parameter>'
    r'(?:(?!</ac:structured-macro>).)*?<ac:plain-text-body>\s*<!\[CDATA\[(.*?)\]\]>\s*</ac:plain-text-body>'
    r'\s*</ac:structured-macro>', re.S)


@dataclass
class MermaidBlock:
    index: int
    source: str
    start: int
    end: int


def extract_mermaid(storage: str) -> list[MermaidBlock]:
    return [MermaidBlock(n, m.group(1).replace("]]]]><![CDATA[>", "]]>"), m.start(), m.end())
            for n, m in enumerate(_MERMAID_MACRO.finditer(storage), 1)]


# The architecture palette for SYS_xx systems (nodes) and INT_xx interfaces (edge labels). A flowchart that uses
# `:::existingStyle` (and the others) gets the class definition when it does not define it itself.
PALETTE = {
    "existingStyle": "fill:#EFF6FF,stroke:#2563EB,stroke-width:2px,color:#1E40AF",
    "newStyle": "fill:#FEF2F2,stroke:#DC2626,stroke-width:2px,color:#991B1B",
    "changedStyle": "fill:#FFFBEB,stroke:#D97706,stroke-width:2px,color:#92400E",
    "externalStyle": "fill:#F8FAFC,stroke:#64748B,stroke-width:2px,color:#334155,stroke-dasharray:4 3",
    "dataStyle": "fill:#ECFDF5,stroke:#059669,stroke-width:2px,color:#065F46",
    "retiredStyle": "fill:#F5F5F4,stroke:#A8A29E,stroke-width:1px,color:#78716C,stroke-dasharray:2 2",
}


def apply_palette(source: str) -> str:
    lines = source.split("\n")
    header = next((n for n, l in enumerate(lines) if l.strip() and not l.strip().startswith("%%")), None)
    if header is None or not re.match(r"\s*(flowchart|graph)\b", lines[header]):
        return source
    used = [name for name in PALETTE if f":::{name}" in source or re.search(rf"\bclass\s+[\w,]+\s+{name}\b", source)]
    missing = [name for name in used if not re.search(rf"\bclassDef\s+{name}\b", source)]
    if not missing:
        return source
    defs = [f"    classDef {name} {PALETTE[name]};" for name in missing]
    return "\n".join(lines[:header + 1] + defs + lines[header + 1:])


def figure_name(slug: str, n: int, source: str) -> str:
    if not SLUG.fullmatch(slug or ""):
        raise ValueError("a slug is lower-case letters, digits and dashes")
    return f"{slug}-fig{n}-{hashlib.sha256(source.encode('utf-8')).hexdigest()[:8]}.png"


def image_macro(filename: str, alt: str) -> str:
    return (f'<p><ac:image ac:alt="{html.escape(alt)}"><ri:attachment ri:filename="{html.escape(filename)}" />'
            "</ac:image></p>")


def png_size(data: bytes) -> tuple[int, int]:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        raise ValueError("not a PNG file")
    return struct.unpack(">II", data[16:24])


@dataclass
class RenderStats:
    css_width: float
    css_height: float
    box_width: float      # the white canvas box (diagram + padding), CSS pixels
    box_height: float
    png_width: int
    png_height: int
    nodes: int
    overlaps: int         # node boxes that overlap other node boxes
    overflows: int        # node labels larger than their node shape (cut off)
    outside: int          # text outside the SVG box (cut off)
    foreign: int          # foreignObject elements (must be 0: htmlLabels off)
    ink: float            # share of non-white pixels
    border_ink: int       # non-white pixels in the outer ring (content touches the edge)
    corner_white: bool
    error: str | None = None


MIN_INK = 0.002


def validate_stats(s: RenderStats, scale: int = SCALE) -> list[str]:
    """Every reason the figure must not be published. An empty list means the PNG passes."""
    if s.error:
        return [f"mermaid {s.error}"]
    problems = []
    if s.css_width < 10 or s.css_height < 10:
        problems.append("empty diagram: the SVG has no size")
    if s.foreign:
        problems.append(f"{s.foreign} foreignObject element(s): labels must be SVG text")
    if s.overlaps:
        problems.append(f"{s.overlaps} overlapping node pair(s)")
    if s.overflows:
        problems.append(f"{s.overflows} node label(s) larger than their shape (clipped)")
    if s.outside:
        problems.append(f"{s.outside} text element(s) outside the diagram box (clipped)")
    if abs(s.png_width - round(s.box_width * scale)) > 2 or abs(s.png_height - round(s.box_height * scale)) > 2:
        problems.append(f"PNG {s.png_width}x{s.png_height} is not {scale}x the canvas "
                        f"{s.box_width:.0f}x{s.box_height:.0f}")
    if not s.corner_white:
        problems.append("the canvas is not white")
    if s.border_ink:
        problems.append(f"{s.border_ink} dark pixel(s) at the image edge (clipped)")
    if s.ink < MIN_INK:
        problems.append("the PNG is blank")
    return problems


class RendererUnavailable(Exception):
    """Playwright for Python, Microsoft Edge or the local mermaid.min.js is missing."""


class DiagramError(Exception):
    """One or more figures failed the render check. Nothing was sent to Confluence."""


def find_mermaid_js(env: Mapping[str, str]) -> Path | None:
    configured = (env.get("CADDIS_MERMAID_JS") or "").strip()
    path = Path(configured or DEFAULT_MERMAID_JS).expanduser()
    return path if path.is_file() else None


_PAGE = ("<!doctype html><html><head><meta charset=\"utf-8\"><style>"
         "html,body{margin:0;padding:0;background:#ffffff}"
         "#wrap{display:inline-block;padding:24px;background:#ffffff}"
         "#fig .edgeLabel rect,#fig .labelBkg{fill:#ffffff!important;opacity:1!important}"
         "</style></head><body><div id=\"wrap\"><div id=\"fig\"></div></div></body></html>")

_RENDER_JS = """async (src) => {
  const font = 'Arial, Helvetica, sans-serif';
  const off = {useMaxWidth: false};
  mermaid.initialize({startOnLoad: false, securityLevel: 'strict', theme: 'base', htmlLabels: false,
    fontFamily: font, themeVariables: {background: '#ffffff', primaryColor: '#ffffff', primaryBorderColor: '#334155',
      lineColor: '#475569', textColor: '#0f172a', edgeLabelBackground: '#ffffff', fontFamily: font, fontSize: '14px'},
    flowchart: {htmlLabels: false, useMaxWidth: false, padding: 12}, sequence: off, class: off, er: off,
    state: off, gantt: off, journey: off});
  try { await mermaid.parse(src); } catch (e) { return {error: 'parse error: ' + String((e && e.message) || e).slice(0, 300)}; }
  let out;
  try { out = await mermaid.render('caddisfig', src); }
  catch (e) { return {error: 'render error: ' + String((e && e.message) || e).slice(0, 300)}; }
  const host = document.getElementById('fig');
  host.innerHTML = out.svg;
  const svg = host.querySelector('svg');
  if (!svg) return {error: 'render error: no svg'};
  const box = (el) => { const r = el.getBoundingClientRect(); return {l: r.left, t: r.top, r: r.right, b: r.bottom, w: r.width, h: r.height}; };
  const sb = box(svg), wb = box(document.getElementById('wrap'));
  const nodes = [...svg.querySelectorAll('g.node')].map(box).filter((b) => b.w > 0 && b.h > 0);
  let overlaps = 0;
  for (let i = 0; i < nodes.length; i++) for (let j = i + 1; j < nodes.length; j++) {
    const a = nodes[i], b = nodes[j];
    if (Math.min(a.r, b.r) - Math.max(a.l, b.l) > 2 && Math.min(a.b, b.b) - Math.max(a.t, b.t) > 2) overlaps++;
  }
  let overflows = 0;
  for (const g of svg.querySelectorAll('g.node')) {
    const shape = g.querySelector('rect, polygon, circle, ellipse, path');
    const label = g.querySelector('g.label') || g.querySelector('text');
    if (!shape || !label) continue;
    const s = box(shape), t = box(label);
    if (t.w > s.w + 2 || t.h > s.h + 2) overflows++;
  }
  const outside = [...svg.querySelectorAll('text')].map(box)
    .filter((t) => t.w > 0 && (t.l < sb.l - 1 || t.t < sb.t - 1 || t.r > sb.r + 1 || t.b > sb.b + 1)).length;
  return {width: sb.w, height: sb.h, box_width: wb.w, box_height: wb.h, nodes: nodes.length, overlaps, overflows,
          outside, foreign: svg.querySelectorAll('foreignObject').length};
}"""

_PIXELS_JS = """async (b64) => {
  const img = new Image();
  img.src = 'data:image/png;base64,' + b64;
  await img.decode();
  const c = document.createElement('canvas');
  c.width = img.width; c.height = img.height;
  const ctx = c.getContext('2d');
  ctx.drawImage(img, 0, 0);
  const d = ctx.getImageData(0, 0, c.width, c.height).data;
  const W = c.width, H = c.height, ring = 8;
  let ink = 0, border = 0;
  for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const i = (y * W + x) * 4;
    if (d[i] > 244 && d[i + 1] > 244 && d[i + 2] > 244) continue;
    ink++;
    if (x < ring || y < ring || x >= W - ring || y >= H - ring) border++;
  }
  return {ink: ink / (W * H), border, corner_white: d[0] === 255 && d[1] === 255 && d[2] === 255 && d[3] === 255};
}"""


class EdgeRenderer:
    """Mermaid source -> 2x PNG on a white canvas, in headless Microsoft Edge. One browser for many figures."""

    def __init__(self, mermaid_js: Path, channel: str = "msedge", scale: int = SCALE):
        if importlib.util.find_spec("playwright") is None:
            raise RendererUnavailable("playwright for Python is not installed (pip install playwright; the installed "
                                      "Microsoft Edge is used, no browser download is needed)")
        from playwright.sync_api import Error as PlaywrightError, sync_playwright
        self._error = PlaywrightError
        self._pw = sync_playwright().start()
        try:
            self._browser = self._pw.chromium.launch(channel=channel, headless=True)
        except PlaywrightError as exc:
            self._pw.stop()
            raise RendererUnavailable(f"cannot start headless {channel}: {str(exc).splitlines()[0][:200]}") from None
        self._context = self._browser.new_context(device_scale_factor=scale, viewport={"width": 2400, "height": 1600})
        # No network: a diagram that names an http(s) resource must not make the browser fetch it.
        self._context.route("**/*", lambda route: route.abort() if route.request.url.startswith(("http:", "https:"))
                            else route.continue_())
        self._mermaid_js = str(mermaid_js)

    def render(self, source: str) -> tuple[bytes, RenderStats]:
        page = self._context.new_page()
        try:
            return self._render(page, source)
        except self._error as exc:
            reason = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
            return b"", RenderStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0, True, error=f"browser error: {reason}")
        finally:
            page.close()

    def _render(self, page, source: str) -> tuple[bytes, RenderStats]:
        page.set_content(_PAGE)
        page.add_script_tag(path=self._mermaid_js)
        info = page.evaluate(_RENDER_JS, source)
        if info.get("error"):
            return b"", RenderStats(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0.0, 0, True, error=info["error"])
        png = page.locator("#wrap").screenshot(type="png", animations="disabled")
        pixels = page.evaluate(_PIXELS_JS, base64.b64encode(png).decode("ascii"))
        width, height = png_size(png)
        return png, RenderStats(info["width"], info["height"], info["box_width"], info["box_height"], width, height,
                                info["nodes"], info["overlaps"], info["overflows"], info["outside"],
                                info["foreign"], pixels["ink"], pixels["border"], pixels["corner_white"])

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()


def default_renderer(env: Mapping[str, str]) -> EdgeRenderer:
    js = find_mermaid_js(env)
    if js is None:
        raise RendererUnavailable("no local mermaid.min.js: set CADDIS_MERMAID_JS or put it at "
                                  "~/.caddis/vendor/mermaid.min.js")
    return EdgeRenderer(js)


@dataclass
class Figure:
    index: int
    name: str
    path: Path
    sha256: str
    stats: RenderStats
    problems: list[str]


def render_all(storage: str, slug: str, renderer, out_dir: Path) -> list[Figure]:
    """Render and check every Mermaid figure; write each PNG that passes to `out_dir`."""
    out_dir.mkdir(parents=True, exist_ok=True)
    figures = []
    for block in extract_mermaid(storage):
        source = apply_palette(block.source)
        name = figure_name(slug, block.index, source)
        png, stats = renderer.render(source)
        problems = validate_stats(stats)
        path = out_dir / name
        if not problems:
            path.write_bytes(png)
        figures.append(Figure(block.index, name, path, hashlib.sha256(png).hexdigest(), stats, problems))
    return figures


def render_figures(storage: str, slug: str, renderer, out_dir: Path) -> tuple[str, list[Figure]]:
    """(storage with each Mermaid macro replaced by an <ac:image>, figures). Raises DiagramError on any bad figure."""
    figures = render_all(storage, slug, renderer, out_dir)
    bad = [f"fig{f.index} ({f.name}): {'; '.join(f.problems)}" for f in figures if f.problems]
    if bad:
        raise DiagramError("diagram check failed, nothing published: " + " | ".join(bad))
    by_index = {f.index: f for f in figures}
    return _with_images(storage, lambda block: by_index[block.index].name), figures


def _with_images(storage: str, name_of: Callable[[MermaidBlock], str]) -> str:
    """`storage` with each Mermaid macro replaced by an <ac:image> of the attachment `name_of(block)`."""
    pieces, last = [], 0
    for block in extract_mermaid(storage):
        pieces.append(storage[last:block.start])
        pieces.append(image_macro(name_of(block), f"Figure {block.index}"))
        last = block.end
    pieces.append(storage[last:])
    return "".join(pieces)


def expected_inner(storage: str, slug: str) -> str:
    """The section body that `publish` writes for `storage`, with no renderer: a figure's attachment name is the
    sha256 of its Mermaid source (after the palette), so a changed diagram changes the body too."""
    return _with_images(storage, lambda block: figure_name(slug, block.index, apply_palette(block.source)))


def section_state(client: "Client", page_id: str, slug: str, inner: str) -> str:
    """Where the page's `slug` section stands against `inner`, by one GET (no write, no renderer):
    missing (no markers), edited (a person changed it in Confluence), stale (a publish would update it) or current
    (a publish would print `ACTION: unchanged`). Broken markers raise MarkerError."""
    try:
        _, action = plan_update(_body(client.get_page(page_id)), slug, inner)
    except DriftError:
        return "edited"
    return {"add": "missing", "update": "stale", "unchanged": "current"}[action]


# ---------------------------------------------------------------- publish

@dataclass
class PublishResult:
    action: str
    version: int | None
    uploaded: int
    skipped: int
    restamped: bool = False
    pending: int = 0    # a dry run: the attachments a real run would upload


def _body(page: dict) -> str:
    return ((page.get("body") or {}).get("storage") or {}).get("value") or ""


def _version(page: dict) -> int | None:
    number = (page.get("version") or {}).get("number")
    return number if isinstance(number, int) else None


def _stale_attachments(client: Client, page_id: str, files: list) -> list[tuple[object, dict | None]]:
    """(file, live attachment or None) for each file whose live attachment lacks its `caddis sha256:` comment.
    Read-only: one GET per file."""
    stale = []
    for f in files:
        existing = client.find_attachment(page_id, f.name)
        if not existing or ((existing.get("metadata") or {}).get("comment") or "") != f"caddis sha256:{f.sha256}":
            stale.append((f, existing))
    return stale


def _upload(client: Client, page_id: str, stale: list[tuple[object, dict | None]]) -> int:
    for f, existing in stale:
        client.upload_attachment(page_id, f.name, f.path.read_bytes(), f"caddis sha256:{f.sha256}", existing,
                                 getattr(f, "content_type", "image/png"))
    return len(stale)


def upload_figures(client: Client, page_id: str, figures: list) -> tuple[int, int]:
    """Upload each file whose live attachment does not carry its sha256. (uploaded, skipped)."""
    uploaded = _upload(client, page_id, _stale_attachments(client, page_id, figures))
    return uploaded, len(figures) - uploaded


def _restamp(client: Client, page_id: str, slug: str, written: int | None) -> tuple[bool, int | None]:
    """Read the page back; when Confluence stored the section in a form whose hash differs, stamp the live hash.

    Only when the page is still at the version caddis just wrote: a newer version may hold a person's edit, and
    stamping its hash would hide that edit from the next anti-overwrite check. A 409 here leaves the page as it is."""
    page = client.get_page(page_id)
    if _version(page) != written:
        return False, written
    body = _body(page)
    found = locate(body, slug)
    if found is None or not found.edited:
        return False, _version(page)
    inner = body[found.inner_start:found.inner_end]
    new_body = body[:found.start] + build_section(slug, inner, stamp=found.live) + body[found.end:]
    try:
        return True, _version(client.update_page(page, new_body))
    except ConfluenceError as err:
        if err.status != 409:
            raise
        return False, written


def publish(client: Client, page_id: str, slug: str, inner: str, figures: list[Figure], dry_run: bool = False,
            force: bool = False) -> PublishResult:
    def clean(text: str) -> str:
        return client.clean(text, None)

    page = client.get_page(page_id)
    new_body, action = plan_update(_body(page), slug, inner, force, clean)
    if dry_run or action == "unchanged":
        return PublishResult(action, _version(page), 0, 0)
    uploaded, skipped = upload_figures(client, page_id, figures)
    action, version, restamped = _write_section(client, page_id, page, slug, inner, new_body, action, force, clean)
    return PublishResult(action, version, uploaded, skipped, restamped)


def _write_section(client: Client, page_id: str, page: dict, slug: str, inner: str, new_body: str, action: str,
                   force: bool, clean: Callable[[str], str]) -> tuple[str, int | None, bool]:
    """PUT the new body. On HTTP 409, read the page again and run the anti-overwrite check again, at most
    MAX_CONFLICT_RETRIES times. Then read the page back and restamp when needed. (action, version, restamped)."""
    for attempt in range(MAX_CONFLICT_RETRIES + 1):
        try:
            updated = client.update_page(page, new_body)
            break
        except ConfluenceError as err:
            if err.status != 409 or attempt == MAX_CONFLICT_RETRIES:
                raise
            page = client.get_page(page_id)
            new_body, action = plan_update(_body(page), slug, inner, force, clean)
            if action == "unchanged":
                return action, _version(page), False
    restamped, version = _restamp(client, page_id, slug, _version(updated))
    return action, version if restamped else _version(updated), restamped


# ---------------------------------------------------------------- hash-gated catalog publish (post-deploy hook)

ATTACH_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
CONTENT_TYPES = {
    ".png": "image/png", ".json": "application/json", ".csv": "text/csv", ".md": "text/markdown",
    ".txt": "text/plain", ".sql": "text/plain", ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}


class InputError(Exception):
    """Bad command-line input, found before any request (exit 4)."""


@dataclass
class Attachment:
    name: str
    path: Path
    sha256: str
    content_type: str


def load_attachments(paths: list[str]) -> list[Attachment]:
    """One Attachment per `--attach` file, in name order. The page attachment name is the file name, so names must
    be safe in a multipart header and unique."""
    out: list[Attachment] = []
    seen: set[str] = set()
    for raw in paths:
        path = Path(raw)
        if not ATTACH_NAME.fullmatch(path.name):
            raise InputError(f"attachment name {path.name!r}: use letters, digits, '.', '-' and '_' only")
        if path.name in seen:
            raise InputError(f"two --attach files have the name {path.name}")
        if not path.is_file():
            raise InputError(f"--attach {path.name}: no such file")
        seen.add(path.name)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        out.append(Attachment(path.name, path, digest,
                              CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")))
    return sorted(out, key=lambda a: a.name)


def catalog_hash(summary: bytes, files: list) -> str:
    """One SHA-256 over the summary and every catalog file (name and content), in name order. `files` holds
    Attachments (their digest is reused, so each file is read once) or paths."""
    def entry(f) -> tuple[str, str]:
        if isinstance(f, Attachment):
            return f.name, f.sha256
        return Path(f).name, hashlib.sha256(Path(f).read_bytes()).hexdigest()

    h = hashlib.sha256(b"summary\0" + hashlib.sha256(summary).hexdigest().encode() + b"\n")
    for name, digest in sorted(entry(f) for f in files):
        h.update(f"{name}\0{digest}\n".encode())
    return h.hexdigest()


def catalog_inner(storage: str, files: list[Attachment], combined: str) -> str:
    """The summary, a table that links each attachment with its hash, and the combined hash. A change to any file
    changes the section, so the section marker hash also gates the attachments."""
    table = ""
    if files:
        rows = "".join(f'<tr><td><ac:link><ri:attachment ri:filename="{html.escape(f.name)}" /></ac:link></td>'
                       f"<td><code>{f.sha256[:12]}</code></td></tr>" for f in files)
        table = f"<h3>Catalog files</h3><table><tbody><tr><th>File</th><th>SHA-256</th></tr>{rows}</tbody></table>"
    return f"{storage}{table}<p>Catalog hash: <code>sha256:{combined}</code></p>"


def publish_catalog(client: Client, page_id: str, slug: str, inner: str, files: list[Attachment],
                    dry_run: bool = False, force: bool = False) -> PublishResult:
    """Write the catalog section and upload only the attachments whose live `caddis sha256:` comment differs.

    action: add | update (the section changed), attachments (the section matches but a file on the page does not),
    or unchanged (no write at all). A dry run makes only GET requests."""
    def clean(text: str) -> str:
        return client.clean(text, None)

    page = client.get_page(page_id)
    new_body, action = plan_update(_body(page), slug, inner, force, clean)
    stale = _stale_attachments(client, page_id, files)
    if action == "unchanged":
        if not stale:
            return PublishResult("unchanged", _version(page), 0, len(files))
        action = "attachments"
    if dry_run:
        return PublishResult(action, _version(page), 0, len(files) - len(stale), pending=len(stale))
    uploaded = _upload(client, page_id, stale)
    if action == "attachments":
        return PublishResult(action, _version(page), uploaded, len(files) - uploaded)
    action, version, restamped = _write_section(client, page_id, page, slug, inner, new_body, action, force, clean)
    return PublishResult(action, version, uploaded, len(files) - uploaded, restamped)


# ---------------------------------------------------------------- command line

def _read_input(path: str) -> str:
    text = Path(path).read_text(encoding="utf-8")
    return text if Path(path).suffix.lower() in (".xhtml", ".html", ".xml") else md_to_storage(text)


def _headless(env: Mapping[str, str]) -> bool:
    return (env.get("CADDIS_HEADLESS") or "").strip().lower() not in ("", "0", "false", "no")


def cmd_check(args, env, client_factory, renderer_factory) -> int:
    client = client_factory(load_config(env))
    try:
        user = client.current_user()
    except ConfluenceError as err:
        print(f"ERROR: {err}", file=sys.stderr)
        return caddis_exit.NOT_RUN if err.status is None else caddis_exit.BLOCKED
    if str(user.get("type") or "").lower() == "anonymous":
        print("ERROR: Confluence answered as an anonymous user: the token was not accepted", file=sys.stderr)
        return caddis_exit.BLOCKED
    renderer = "ready" if importlib.util.find_spec("playwright") and find_mermaid_js(env) else \
        "missing (pip install playwright; set CADDIS_MERMAID_JS to a local mermaid.min.js)"
    if args.json:
        print(json.dumps({"mode": client.mode, "authenticated": True, "renderer": renderer.split(" ")[0]}))
    else:
        print(f"mode: {client.mode}")
        print("authenticated: yes")
        print(f"renderer: {renderer}")
    return caddis_exit.CLEAN


def _with_renderer(env, renderer_factory, work: Callable) -> int:
    try:
        renderer = renderer_factory(env)
    except RendererUnavailable as exc:
        print(f"NOT RUN: renderer unavailable: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    try:
        return work(renderer)
    finally:
        renderer.close()


def cmd_render(args, env, client_factory, renderer_factory) -> int:
    storage = _read_input(args.input)
    if not extract_mermaid(storage):
        print("no Mermaid blocks")
        return caddis_exit.CLEAN

    def work(renderer) -> int:
        figures = render_all(storage, args.slug, renderer, Path(args.out_dir))
        for f in figures:
            verdict = "ok" if not f.problems else "FAIL: " + "; ".join(f.problems)
            print(f"FIG {f.name} {f.stats.png_width}x{f.stats.png_height} nodes={f.stats.nodes} {verdict}")
        return caddis_exit.BLOCKED if any(f.problems for f in figures) else caddis_exit.CLEAN

    return _with_renderer(env, renderer_factory, work)


def cmd_publish(args, env, client_factory, renderer_factory) -> int:
    if args.force_overwrite and _headless(env):
        print("REFUSED: --force-overwrite needs a person; CADDIS_HEADLESS is set", file=sys.stderr)
        return caddis_exit.BLOCKED
    storage = _read_input(args.input)
    client = client_factory(load_config(env))

    def work(renderer) -> int:
        with tempfile.TemporaryDirectory(prefix="confluence-figs-") as tmp:
            out_dir = Path(args.out_dir) if args.out_dir else Path(tmp)
            inner, figures = render_figures(storage, args.slug, renderer, out_dir)
            result = publish(client, args.page_id, args.slug, inner, figures, args.dry_run, args.force_overwrite)
        print(f"ACTION: {result.action}{' (dry run)' if args.dry_run else ''}")
        print(f"PAGE: {args.page_id} version {result.version}")
        print(f"FIGURES: {len(figures)}")
        print(f"UPLOADED: {result.uploaded} SKIPPED: {result.skipped}")
        if result.restamped:
            print("RESTAMPED: the marker now carries the hash of the stored form")
        return caddis_exit.CLEAN

    if not extract_mermaid(storage):
        return work(None)
    return _with_renderer(env, renderer_factory, work)


def cmd_publish_catalog(args, env, client_factory, renderer_factory) -> int:
    """The post-deploy hook: publish the generated catalog only when its combined hash changed."""
    if args.force_overwrite and _headless(env):
        print("REFUSED: --force-overwrite needs a person; CADDIS_HEADLESS is set", file=sys.stderr)
        return caddis_exit.BLOCKED
    if not Path(args.input).is_file():
        raise InputError(f"--input {Path(args.input).name}: no such file")
    summary = Path(args.input).read_bytes()
    files = load_attachments(args.attach or [])
    storage = _read_input(args.input)
    if extract_mermaid(storage):
        raise InputError("the catalog summary holds a Mermaid block: publish diagrams with `publish`, "
                         "or attach a rendered file")
    combined = catalog_hash(summary, files)
    state = Path(args.state_hash_file) if args.state_hash_file else None
    if state and state.exists() and not state.is_file():
        raise InputError("--state-hash-file is not a file")  # found before any write, not after it
    if state and not args.force_overwrite and state.is_file() \
            and state.read_text(encoding="utf-8", errors="replace").strip() == combined:
        print("ACTION: unchanged (state hash file matches, no request made)")
        print(f"CATALOG: sha256:{combined}")
        return caddis_exit.CLEAN
    client = client_factory(load_config(env))
    result = publish_catalog(client, args.page_id, args.slug, catalog_inner(storage, files, combined), files,
                             args.dry_run, args.force_overwrite)
    print(f"ACTION: {result.action}{' (dry run)' if args.dry_run else ''}")
    print(f"PAGE: {args.page_id} version {result.version}")
    print(f"CATALOG: sha256:{combined}")
    print(f"UPLOADED: {result.uploaded} SKIPPED: {result.skipped}")
    if args.dry_run:
        print(f"WOULD UPLOAD: {result.pending}")
    if result.restamped:
        print("RESTAMPED: the marker now carries the hash of the stored form")
    if state and not args.dry_run:
        state.parent.mkdir(parents=True, exist_ok=True)
        state.write_text(combined + "\n", encoding="utf-8")
    return caddis_exit.CLEAN


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="caddis_confluence.py", description="Confluence publish engine.")
    sub = p.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="prove the Confluence login (GET) and report the renderer")
    c.add_argument("--json", action="store_true")
    r = sub.add_parser("render-diagrams", help="render and check every Mermaid figure, no network")
    r.add_argument("--input", required=True)
    r.add_argument("--slug", required=True)
    r.add_argument("--out-dir", required=True)
    u = sub.add_parser("publish", help="write the document into the page's marked section")
    u.add_argument("--page-id", required=True)
    u.add_argument("--slug", required=True)
    u.add_argument("--input", required=True)
    u.add_argument("--out-dir")
    u.add_argument("--dry-run", action="store_true")
    u.add_argument("--force-overwrite", action="store_true", help="a person only: overwrite a hand-edited section")
    k = sub.add_parser("publish-catalog", help="post-deploy: publish a generated catalog only when its hash changed")
    k.add_argument("--page-id", required=True)
    k.add_argument("--slug", default="db-catalog")
    k.add_argument("--input", required=True, help="the catalog summary (Markdown, no Mermaid)")
    k.add_argument("--attach", action="append", default=[], help="a catalog file to attach; repeat for more")
    k.add_argument("--state-hash-file", help="the last published combined hash; a match skips every request")
    k.add_argument("--dry-run", action="store_true")
    k.add_argument("--force-overwrite", action="store_true", help="a person only: overwrite a hand-edited section")
    return p


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None,
         client_factory: Callable | None = None, renderer_factory: Callable | None = None) -> int:
    env = os.environ if env is None else env
    try:
        args = _parser().parse_args(argv)
    except SystemExit as exc:
        return caddis_exit.CLEAN if exc.code == 0 else caddis_exit.ERROR
    if getattr(args, "slug", None) is not None and not SLUG.fullmatch(args.slug):
        print("ERROR: a slug is lower-case letters, digits and dashes", file=sys.stderr)
        return caddis_exit.ERROR
    if getattr(args, "page_id", None) is not None and not PAGE_ID.fullmatch(args.page_id):
        print("ERROR: a page id is digits only", file=sys.stderr)
        return caddis_exit.ERROR
    handlers = {"check": cmd_check, "render-diagrams": cmd_render, "publish": cmd_publish,
                "publish-catalog": cmd_publish_catalog}
    try:
        return handlers[args.cmd](args, env, client_factory or make_client, renderer_factory or default_renderer)
    except ConfigError as exc:
        print(f"NOT CONFIGURED: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN
    except InputError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return caddis_exit.ERROR
    except DriftError as exc:
        print(f"REFUSED: {exc}. A person may review the diff and pass --force-overwrite.", file=sys.stderr)
        print(exc.diff)
        return caddis_exit.BLOCKED
    except (DiagramError, MarkerError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return caddis_exit.BLOCKED
    except ConfluenceError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return caddis_exit.NOT_RUN if exc.status is None else caddis_exit.BLOCKED
    except (OSError, UnicodeDecodeError) as exc:
        print(f"ERROR: cannot read the input: {type(exc).__name__}", file=sys.stderr)
        return caddis_exit.ERROR


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
