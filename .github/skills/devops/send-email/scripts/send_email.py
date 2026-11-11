#!/usr/bin/env python3
"""Send one email with Microsoft Graph (sendMail, client credentials) or SMTP.

Settings come from three places. The first one that has a value wins:
  1. a command-line flag
  2. an environment variable (CADDIS_EMAIL_*)
  3. the config file ~/.caddis/email.toml  (see email.toml.example)

Secrets (Graph client secret, SMTP password) are never read from the config file. They come from
the process environment or from the env file named by `env_file`. The script never prints a
secret or a token. Errors show the provider, the HTTP or SMTP status code and the error name only.

Exit codes: 0 done, 1 provider error, 2 missing or invalid setting.
Standard library only.
"""
from __future__ import annotations

import argparse
import base64
import html
import json
import mimetypes
import os
import re
import smtplib
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path

import tomllib

PROVIDERS = ("graph", "smtp")
SECURITY = ("starttls", "ssl", "none")
SMTP_PORTS = {"starttls": 587, "ssl": 465, "none": 25}
DEFAULT_GRAPH_KEYS = ("ALERT_GRAPH_TENANT_ID", "ALERT_GRAPH_CLIENT_ID", "ALERT_GRAPH_CLIENT_SECRET")
DEFAULT_SMTP_PASSWORD_KEY = "EMAIL_SMTP_PASSWORD"
STYLE = "font-family:Segoe UI,Arial,sans-serif;font-size:14px;line-height:1.5;color:#222"
SIGN_OFF = re.compile(r"^(thanks|thank you|many thanks|regards|kind regards|best regards|best|cheers),?$", re.I)


class ConfigError(Exception):
    """A setting is invalid. The message never holds a secret."""


# ---------------------------------------------------------------- markdown

def extract_section(md: str) -> str:
    md = re.sub(r"\A---\n.*?\n---\n", "", md, flags=re.DOTALL)
    m = re.search(r"<!-- email-start -->(.*?)<!-- email-end -->", md, flags=re.DOTALL)
    return m.group(1) if m else md


def inline(text: str) -> str:
    text = html.escape(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    return re.sub(r"`(.+?)`", r"<code>\1</code>", text)


def md_to_html(md: str) -> str:
    md = extract_section(md)
    out, para, lines, i = [], [], md.splitlines(), 0

    def flush():
        # Wrapped lines join into one paragraph, as in Markdown. A line keeps its break when it
        # ends in "\" or two spaces, or when it is a sign-off such as "Thanks," before the name.
        if para:
            text = ""
            for n, raw in enumerate(para):
                hard = raw.endswith("  ") or raw.rstrip().endswith("\\")
                line = raw.strip().removesuffix("\\").rstrip()
                text += inline(line)
                if n < len(para) - 1:
                    text += "<br>" if hard or SIGN_OFF.match(line) else " "
            out.append(f"<p>{text}</p>")
            para.clear()

    def cells(row):
        return [c.strip() for c in row.strip("|").split("|")]

    while i < len(lines):
        s = lines[i].strip()
        if not s:
            flush()
        elif s == "---":
            flush()
            out.append("<hr>")
        elif s.startswith("#"):
            flush()
            n = min(len(s) - len(s.lstrip("#")), 4)
            out.append(f"<h{n}>{inline(s.lstrip('#').strip())}</h{n}>")
        elif s.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|$", lines[i + 1].strip()):
            flush()
            rows = [s]
            i += 2
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            i -= 1
            t = '<table style="border-collapse:collapse" border="1" cellpadding="6"><tr>'
            t += "".join(f"<th>{inline(c)}</th>" for c in cells(rows[0])) + "</tr>"
            for r in rows[1:]:
                t += "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in cells(r)) + "</tr>"
            out.append(t + "</table>")
        elif re.match(r"^[-*] ", s) or re.match(r"^\d+[.)] ", s):
            flush()
            ordered = bool(re.match(r"^\d", s))
            marker = re.compile(r"^\s*\d+[.)] " if ordered else r"^\s*[-*] ")
            start = int(re.match(r"\d+", s).group()) if ordered else 1
            items = []
            while i < len(lines) and marker.match(lines[i]):
                item = marker.sub("", lines[i])
                i += 1
                while (i < len(lines) and lines[i].startswith("  ") and lines[i].strip()
                       and not marker.match(lines[i])):
                    item += " " + lines[i].strip()
                    i += 1
                items.append(f"<li>{inline(item)}</li>")
            i -= 1
            tag = "ol" if ordered else "ul"
            attr = f' start="{start}"' if start != 1 else ""
            out.append(f"<{tag}{attr}>" + "".join(items) + f"</{tag}>")
        else:
            para.append(lines[i])
        i += 1
    flush()
    return f'<div style="{STYLE}">' + "\n".join(out) + "</div>"


# ---------------------------------------------------------------- config

@dataclass
class Config:
    provider: str = "graph"
    sender: str = ""
    env_file: str = ""
    # graph: names of the keys that hold the secrets (not the secrets)
    tenant_key: str = DEFAULT_GRAPH_KEYS[0]
    client_id_key: str = DEFAULT_GRAPH_KEYS[1]
    client_secret_key: str = DEFAULT_GRAPH_KEYS[2]
    # smtp
    smtp_host: str = ""
    smtp_port: int = 0
    smtp_security: str = "starttls"
    smtp_username: str = ""
    smtp_password_key: str = DEFAULT_SMTP_PASSWORD_KEY
    smtp_timeout: float = 30.0
    smtp_allow_insecure_auth: bool = False


def config_path(flag: str | None) -> Path:
    chosen = flag or os.environ.get("CADDIS_EMAIL_CONFIG")
    return Path(chosen).expanduser() if chosen else Path.home() / ".caddis" / "email.toml"


def read_toml(path: Path) -> dict:
    if not path.is_file():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as e:
        raise ConfigError(f"cannot read config file ({type(e).__name__})") from None


def read_env(path: Path) -> dict:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def _pick(flag, env_names, file_value, default=""):
    """flag, then the first set env var, then the config file value, then the default."""
    if flag not in (None, ""):
        return flag
    for name in env_names:
        v = os.environ.get(name)
        if v:
            return v
    if file_value not in (None, ""):
        return file_value
    return default


def _number(value, name, cast):
    try:
        return cast(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{name} must be a number") from None


def load_config(a: argparse.Namespace) -> Config:
    f = read_toml(config_path(a.config))
    g, s = f.get("graph", {}) or {}, f.get("smtp", {}) or {}
    c = Config()
    c.provider = str(_pick(a.provider, ["CADDIS_EMAIL_PROVIDER"], f.get("provider"), "graph")).lower()
    if c.provider not in PROVIDERS:
        raise ConfigError(f"provider must be one of {', '.join(PROVIDERS)}")
    c.sender = _pick(a.sender, ["CADDIS_EMAIL_SENDER", "GRAPH_EMAIL_SENDER"], f.get("sender"))
    c.env_file = _pick(a.env_file, ["CADDIS_EMAIL_ENV_FILE", "GRAPH_EMAIL_ENV_FILE"], f.get("env_file"))
    c.tenant_key = g.get("tenant_id_key") or c.tenant_key
    c.client_id_key = g.get("client_id_key") or c.client_id_key
    c.client_secret_key = g.get("client_secret_key") or c.client_secret_key
    c.smtp_host = _pick(a.smtp_host, ["CADDIS_EMAIL_SMTP_HOST"], s.get("host"))
    c.smtp_security = str(_pick(a.smtp_security, ["CADDIS_EMAIL_SMTP_SECURITY"], s.get("security"),
                                "starttls")).lower()
    if c.smtp_security not in SECURITY:
        raise ConfigError(f"smtp security must be one of {', '.join(SECURITY)}")
    port = _pick(a.smtp_port, ["CADDIS_EMAIL_SMTP_PORT"], s.get("port"), SMTP_PORTS[c.smtp_security])
    c.smtp_port = _number(port, "smtp port", int)
    c.smtp_username = _pick(a.smtp_username, ["CADDIS_EMAIL_SMTP_USERNAME"], s.get("username"))
    c.smtp_password_key = s.get("password_key") or c.smtp_password_key
    c.smtp_timeout = _number(_pick(a.smtp_timeout, ["CADDIS_EMAIL_SMTP_TIMEOUT"], s.get("timeout"), 30),
                             "smtp timeout", float)
    # Only a real TOML boolean true opts in; a string such as "true" does not.
    c.smtp_allow_insecure_auth = s.get("allow_insecure_auth") is True
    return c


def check_smtp_security(cfg: Config) -> None:
    """Refuse a login (username or password) over security "none" unless the user opted in.

    The message names settings only. It never holds a username, a password or a host.
    """
    if cfg.provider != "smtp" or cfg.smtp_security != "none" or cfg.smtp_allow_insecure_auth:
        return
    if cfg.smtp_username or get_secret(cfg, cfg.smtp_password_key):
        raise ConfigError('smtp security is off and a login is set, so the login would go in clear text; '
                          'set security to "starttls" or "ssl"')


def _env_file_values(cfg: Config) -> dict:
    if not cfg.env_file:
        return {}
    try:
        return read_env(Path(cfg.env_file).expanduser())
    except (OSError, UnicodeDecodeError):
        return {}


def get_secret(cfg: Config, key: str) -> str:
    """The process environment first, then the env file. Never the config file."""
    return os.environ.get(key) or _env_file_values(cfg).get(key, "")


def missing_settings(cfg: Config) -> list[str]:
    """Names of settings that are not set. Never a value."""
    miss = []
    if not cfg.sender:
        miss.append("sender")
    if cfg.provider == "graph":
        keys = (cfg.tenant_key, cfg.client_id_key, cfg.client_secret_key)
    else:
        if not cfg.smtp_host:
            miss.append("smtp.host")
        keys = (cfg.smtp_password_key,) if cfg.smtp_username else ()
    absent = [k for k in keys if not get_secret(cfg, k)]
    if absent:
        miss.extend(["env_file"] if not cfg.env_file else absent)
    return miss


# ---------------------------------------------------------------- attachments and messages

def _ctype(name: str) -> str:
    return mimetypes.guess_type(name)[0] or "application/octet-stream"


def build_graph_payload(subject, html_body, to, attach_paths) -> dict:
    attachments = []
    for p in attach_paths:
        pp = Path(p)
        attachments.append({
            "@odata.type": "#microsoft.graph.fileAttachment", "name": pp.name,
            "contentType": _ctype(pp.name),
            "contentBytes": base64.b64encode(pp.read_bytes()).decode(),
        })
    return {"message": {
        "subject": subject, "body": {"contentType": "HTML", "content": html_body},
        "toRecipients": [{"emailAddress": {"address": t}} for t in to],
        "attachments": attachments}, "saveToSentItems": True}


def build_smtp_message(sender, to, subject, plain, html_body, attach_paths) -> EmailMessage:
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = sender, ", ".join(to), subject
    msg.set_content(plain)
    msg.add_alternative(html_body, subtype="html")
    for p in attach_paths:
        pp = Path(p)
        main, _, sub = _ctype(pp.name).partition("/")
        msg.add_attachment(pp.read_bytes(), maintype=main, subtype=sub or "octet-stream", filename=pp.name)
    return msg


# ---------------------------------------------------------------- senders

def post(url: str, data: bytes, headers: dict, timeout: float = 30):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _err_name(raw: bytes) -> str:
    try:
        err = json.loads(raw or b"{}").get("error", "unknown")
    except (ValueError, AttributeError):
        return "unknown"
    if isinstance(err, dict):
        err = err.get("code", "unknown")
    return str(err) if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", str(err)) else "unknown"


def send_graph(cfg: Config, a, html_body: str) -> int:
    tenant = get_secret(cfg, cfg.tenant_key)
    tok_url = f"https://login.microsoftonline.com/{urllib.parse.quote(tenant)}/oauth2/v2.0/token"
    form = urllib.parse.urlencode({
        "client_id": get_secret(cfg, cfg.client_id_key), "client_secret": get_secret(cfg, cfg.client_secret_key),
        "scope": "https://graph.microsoft.com/.default", "grant_type": "client_credentials",
    }).encode()
    try:
        status, raw = post(tok_url, form, {"Content-Type": "application/x-www-form-urlencoded"})
        if status != 200:
            print(f"error: provider graph, token request failed, HTTP {status}, {_err_name(raw)}", file=sys.stderr)
            return 1
        token = json.loads(raw)["access_token"]
        payload = build_graph_payload(a.subject, html_body, a.to, a.attach)
        url = f"https://graph.microsoft.com/v1.0/users/{urllib.parse.quote(cfg.sender)}/sendMail"
        status, raw = post(url, json.dumps(payload).encode(),
                           {"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    except (OSError, ValueError, KeyError) as e:
        print(f"error: provider graph, request failed, {type(e).__name__}", file=sys.stderr)
        return 1
    if status == 202:
        print(f"sent: provider graph, HTTP 202 (accepted for delivery) to {', '.join(a.to)} subject '{a.subject}'")
        return 0
    print(f"error: provider graph, sendMail failed, HTTP {status}, {_err_name(raw)}", file=sys.stderr)
    return 1


def send_smtp(cfg: Config, a, html_body: str, plain: str) -> int:
    try:
        msg = build_smtp_message(cfg.sender, a.to, a.subject, plain, html_body, a.attach)
        password = get_secret(cfg, cfg.smtp_password_key) if cfg.smtp_username else ""
        # smtplib's own default context does not check the certificate; this one does.
        ctx = ssl.create_default_context()
        if cfg.smtp_security == "ssl":
            conn = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=cfg.smtp_timeout, context=ctx)
        else:
            conn = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=cfg.smtp_timeout)
        with conn as s:
            if cfg.smtp_security == "starttls":
                s.ehlo()
                s.starttls(context=ctx)
                s.ehlo()
            if cfg.smtp_username:
                s.login(cfg.smtp_username, password)
            s.send_message(msg)
    except smtplib.SMTPResponseException as e:
        print(f"error: provider smtp, SMTP {e.smtp_code}, {type(e).__name__}", file=sys.stderr)
        return 1
    except (smtplib.SMTPException, OSError) as e:
        print(f"error: provider smtp, {type(e).__name__}", file=sys.stderr)
        return 1
    print(f"sent: provider smtp, accepted by server for {', '.join(a.to)} subject '{a.subject}'")
    return 0


# ---------------------------------------------------------------- cli

def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Send one email with Microsoft Graph or SMTP.")
    ap.add_argument("--to", action="append")
    ap.add_argument("--subject")
    ap.add_argument("--body-file")
    ap.add_argument("--attach", action="append", default=[])
    ap.add_argument("--dry-run", action="store_true", help="write <body>.preview.html, send nothing")
    ap.add_argument("--check", action="store_true", help="validate settings, send nothing, print no secret")
    ap.add_argument("--config", help="config file (default ~/.caddis/email.toml)")
    ap.add_argument("--provider")
    ap.add_argument("--sender")
    ap.add_argument("--env-file")
    ap.add_argument("--smtp-host")
    ap.add_argument("--smtp-port")
    ap.add_argument("--smtp-security")
    ap.add_argument("--smtp-username")
    ap.add_argument("--smtp-timeout")
    a = ap.parse_args(argv)
    if not a.check and not (a.to and a.subject and a.body_file):
        ap.error("--to, --subject and --body-file are required (unless --check)")
    return a


def check(cfg: Config) -> int:
    miss = missing_settings(cfg)
    print(f"provider: {cfg.provider}")
    print(f"sender: {'set' if cfg.sender else 'MISSING'}")
    if cfg.provider == "smtp":
        print(f"smtp: host {'set' if cfg.smtp_host else 'MISSING'}, port {cfg.smtp_port}, "
              f"security {cfg.smtp_security}, login {'yes' if cfg.smtp_username else 'no'}")
    if miss:
        print(f"missing: {', '.join(miss)}")
        return 2
    print("check ok: all settings and credentials are present (nothing sent)")
    return 0


def main(argv=None) -> int:
    a = parse_args(argv)
    if a.dry_run and not a.check:
        body = md_to_html(Path(a.body_file).read_text(encoding="utf-8"))
        out = Path(a.body_file).with_suffix(".preview.html")
        out.write_text(f"<html><body>{body}</body></html>", encoding="utf-8")
        print(f"dry run: preview written to {out}; nothing sent")
        return 0
    try:
        cfg = load_config(a)
        check_smtp_security(cfg)
    except ConfigError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if a.check:
        return check(cfg)
    miss = missing_settings(cfg)
    if miss:
        print(f"error: missing settings for provider {cfg.provider}: {', '.join(miss)}", file=sys.stderr)
        return 2
    md = Path(a.body_file).read_text(encoding="utf-8")
    html_body = md_to_html(md)
    if cfg.provider == "smtp":
        return send_smtp(cfg, a, html_body, extract_section(md).strip())
    return send_graph(cfg, a, html_body)


if __name__ == "__main__":
    sys.exit(main())
