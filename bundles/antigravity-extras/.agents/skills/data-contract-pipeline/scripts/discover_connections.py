"""Discover connection configuration in an app repository.

This script scans common config files for DB/API/file connection hints and
emits a masked connection_manifest.json. It never prints secret values.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path


SECRET_RE = re.compile(
    r"(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)",
    re.IGNORECASE,
)
KEY_VALUE_RE = re.compile(r"^\s*([A-Z0-9_.-]+)\s*[:=]\s*(.+?)\s*$", re.IGNORECASE)
CONNECTION_KEYS = (
    "DB_",
    "DATABASE",
    "SQL",
    "MSSQL",
    "POSTGRES",
    "MYSQL",
    "ODBC",
    "JDBC",
    "CONNECTION",
    "API_",
    "FILE_",
)
DEFAULT_SUFFIXES = {".ini", ".toml", ".yaml", ".yml", ".json", ".config"}
CONFIG_NAME_HINTS = (
    ".env",
    "settings",
    "config",
    "docker-compose",
    "compose",
    "alembic",
    "database",
    "connection",
    "deploy",
    "deployment",
    "readme",
    "runbook",
)
SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "dist",
    "build",
    "__pycache__",
    ".next",
    ".turbo",
}


@dataclass
class ConnectionHint:
    file: str
    key: str
    value: str
    secret: bool


def is_candidate_file(path: Path) -> bool:
    if any(part in SKIP_DIRS for part in path.parts):
        return False
    name = path.name.lower()
    if any(hint in name for hint in CONFIG_NAME_HINTS):
        return True
    if path.suffix.lower() in DEFAULT_SUFFIXES:
        return True
    return False


def mask_value(key: str, value: str) -> tuple[str, bool]:
    is_secret = bool(SECRET_RE.search(key))
    if is_secret:
        return "***", True
    if SECRET_RE.search(value):
        return re.sub(r"(?i)(pwd|password|token|secret)=([^;\\s]+)", r"\1=***", value), True
    return value.strip().strip('"').strip("'"), False


def scan_file(path: Path, root: Path) -> list[ConnectionHint]:
    hints: list[ConnectionHint] = []
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return hints

    for line in text.splitlines():
        match = KEY_VALUE_RE.match(line)
        if not match:
            continue
        key, raw_value = match.group(1), match.group(2)
        if raw_value.strip() in {"(", "{", "["}:
            continue
        if not key.upper().startswith(CONNECTION_KEYS) and "CONNECTION" not in key.upper():
            continue
        value, secret = mask_value(key, raw_value)
        hints.append(
            ConnectionHint(
                file=str(path.relative_to(root)),
                key=key,
                value=value,
                secret=secret,
            )
        )
    return hints


def infer_summary(hints: list[ConnectionHint]) -> dict[str, str]:
    by_key = {h.key.upper(): h.value for h in hints if not h.secret}
    return {
        "host": by_key.get("DB_HOST") or by_key.get("DATABASE_HOST") or "",
        "port": by_key.get("DB_PORT") or by_key.get("DATABASE_PORT") or "",
        "database": by_key.get("DB_NAME") or by_key.get("DATABASE") or "",
        "driver": by_key.get("DB_DRIVER") or by_key.get("ODBC_DRIVER") or "",
        "auth_mode": (
            "trusted"
            if by_key.get("DB_TRUSTED_CONNECTION", "").lower() in {"yes", "true", "1"}
            else "credential-or-unknown"
        ),
    }


def discover(app_path: Path) -> dict[str, object]:
    root = app_path.resolve()
    hints: list[ConnectionHint] = []
    for path in root.rglob("*"):
        if path.is_file() and is_candidate_file(path):
            hints.extend(scan_file(path, root))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "app_path": str(root),
        "summary": infer_summary(hints),
        "connection_hints": [asdict(h) for h in hints],
        "notes": [
            "Secret values are masked.",
            "Validate stale or conflicting configs before using a connection.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover masked connection config in an app repo.")
    parser.add_argument("--app", type=Path, required=True, help="Application repository path")
    parser.add_argument("--output", type=Path, help="Output connection_manifest.json path")
    args = parser.parse_args()

    manifest = discover(args.app)
    text = json.dumps(manifest, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text + "\n", encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
