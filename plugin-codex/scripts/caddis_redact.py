#!/usr/bin/env python3
"""caddis_redact - keep provider keys out of caddis logs and captured output.

Why: on 10 Oct 2026 a review launcher session printed the GLM API key into its local session log while
debugging (caddis-next proposal, issue 4); the owner had to rotate the key. caddis captures model and
launcher output into review files, lane packets and printed summaries. Every such text goes through
`redact()` (or `redact_obj()` for a packet) first.

Secrets are the VALUES (never the names) of:
- every `NAME=value` line in the keys file whose NAME looks secret (contains KEY, TOKEN, SECRET, PASS,
  AUTH or CREDENTIAL): `$CADDIS_KEYS_FILE` if set (with `~` expanded, as oss_model and oss_review do),
  else `~/.caddis/keys.env`; optional `export `, quotes stripped the way the key consumers strip them;
- the same kind of variables in the environment (`REVIEW_API_KEY`, `OSS_API_KEY`, `<P>_API_KEY`, which
  the consumers prefer over the file).
Values shorter than 8 characters are ignored. Each value is also masked in its JSON-escaped form, so a key
with `\\`, `"` or `<>&` (Go-style `\\u003c`) does not survive inside raw JSON output.

Limit: only whole, exact copies are masked. A key split across lines, cut short (`sk-abc...xyz`) or
re-encoded (base64) passes.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

MIN_SECRET_LEN = 8
MASK = "***"
_SENSITIVE_NAME = re.compile(r"KEY|TOKEN|SECRET|PASS|AUTH|CREDENTIAL", re.I)


def keys_file(home: Path) -> Path:
    override = os.environ.get("CADDIS_KEYS_FILE")
    return Path(override).expanduser() if override else home / ".caddis" / "keys.env"


def _forms(value: str) -> set[str]:
    """The value and the forms it takes inside raw JSON output (standard and Go-style escapes)."""
    forms = {value}
    escaped = json.dumps(value)[1:-1]
    forms.add(escaped)
    forms.add(escaped.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026"))
    return forms


def load_secrets(home: Path) -> list[str]:
    """The secret values in every form to mask, longest first (so a key that contains another is masked whole)."""
    values: set[str] = set()
    try:
        text = keys_file(home).read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        text = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        name, value = line.split("=", 1)
        if not _SENSITIVE_NAME.search(name):
            continue
        value = value.strip()
        # The consumers (oss_model, oss_review) use .strip('"').strip("'"); mask that value AND the
        # balanced-quote value, so an unbalanced quote cannot leave the key that is really used unmasked.
        for candidate in {value.strip('"').strip("'"),
                          value[1:-1] if len(value) >= 2 and value[0] == value[-1] and value[0] in "'\"" else value}:
            if len(candidate) >= MIN_SECRET_LEN:
                values.add(candidate)
    for name, value in os.environ.items():
        if (_SENSITIVE_NAME.search(name) and len(value) >= MIN_SECRET_LEN and name not in ("CADDIS_KEYS_FILE",)
                and not name.startswith("GIT_CONFIG_")):  # GIT_CONFIG_KEY_<n> holds a setting NAME, not a secret
            values.add(value)
    forms: set[str] = set()
    for value in values:
        forms |= _forms(value)
    return sorted(forms, key=len, reverse=True)


def redact(text: str, secrets: list[str]) -> str:
    """`text` with every secret form replaced by ***."""
    if not text:
        return text
    for secret in secrets:
        if secret in text:
            text = text.replace(secret, MASK)
    return text


def redact_obj(obj, secrets: list[str]):
    """A copy of a JSON-able packet (dict/list/str) with every string redacted."""
    if isinstance(obj, str):
        return redact(obj, secrets)
    if isinstance(obj, dict):
        return {k: redact_obj(v, secrets) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact_obj(v, secrets) for v in obj]
    return obj
