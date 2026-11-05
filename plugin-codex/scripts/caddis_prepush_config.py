"""Generate the `[pre_push]` section of `.caddis/config.toml` from a repo's app-ci caller.

The pre-push gate must run the same fast checks as CI, with the same scope. For a repo whose
`.github/workflows/ci.yml` calls the shared app-ci workflow, this module reads the caller's pinned tag
and its `with:` inputs, and derives the check list. The hook reads only the TOML at push time; this
line parser runs once, at generation, where a failure is loud.

Stdlib only: no yaml import. Plan: `.caddis/plans/prepush-gate-matches-ci.md`, Phase 2.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

# Match the workflow path and the `@` only. The owner/repo part is never named here (privacy scan).
APP_CI_SUFFIX = "/.github/workflows/app-ci.yml@"


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _is_content(line: str) -> bool:
    """True for a line that carries YAML content (not blank, not a whole-line comment)."""
    stripped = line.strip()
    return bool(stripped) and not stripped.startswith("#")


def _scalar(raw: str) -> str:
    """A YAML scalar as a plain string: quotes removed, an inline `#` comment cut off."""
    value = raw.strip()
    if value.startswith("#"):  # `key: # comment` is an empty value
        return ""
    if value[:1] in ("'", '"'):
        quote = value[0]
        end = value.find(quote, 1)
        if end != -1:
            return value[1:end]
        return value[1:]
    cut = value.find(" #")
    if cut != -1:
        value = value[:cut]
    return value.strip()


def parse_app_ci_caller(text: str) -> tuple[str, dict[str, str]] | None:
    """`(tag, with_inputs)` for the job that calls app-ci, or `None` when no job calls it.

    Only the `with:` block of the job that holds the `uses:` line is read. Values are plain strings.
    """
    lines = text.replace("\r\n", "\n").split("\n")
    uses_idx = None
    tag = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("uses:"):
            continue
        value = _scalar(stripped[len("uses:"):])
        if APP_CI_SUFFIX in value:
            uses_idx = i
            tag = value.split("@", 1)[1].strip()
            break
    if uses_idx is None:
        return None

    key_indent = _indent(lines[uses_idx])
    # The job header is the nearest content line above with a smaller indent.
    start = 0
    for j in range(uses_idx - 1, -1, -1):
        if _is_content(lines[j]) and _indent(lines[j]) < key_indent:
            start = j + 1
            break
    end = len(lines)
    for j in range(uses_idx + 1, len(lines)):
        if _is_content(lines[j]) and _indent(lines[j]) < key_indent:
            end = j
            break

    inputs: dict[str, str] = {}
    j = start
    while j < end:
        line = lines[j]
        if _is_content(line) and _indent(line) == key_indent and line.strip().split("#", 1)[0].strip() == "with:":
            child_indent = None
            k = j + 1
            while k < end:
                child = lines[k]
                if not _is_content(child):
                    k += 1
                    continue
                ind = _indent(child)
                if ind <= key_indent:
                    break
                if child_indent is None:
                    child_indent = ind
                if ind == child_indent and ":" in child:
                    key, raw = child.strip().split(":", 1)
                    inputs[key.strip()] = _scalar(raw)
                k += 1
            break
        j += 1
    return tag, inputs


def ci_caller_sha256(text: str) -> str:
    """SHA-256 hex of the caller text with CRLF normalised to LF (an autocrlf checkout hashes the same)."""
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


# -- derivation ---------------------------------------------------------------------------------------

_PY_PATHS = ["src/", "tests/", "pyproject.toml"]


def _off(inputs: dict[str, str], key: str) -> bool:
    return inputs.get(key, "").strip().lower() == "false"


def derive_checks(tag: str, inputs: dict[str, str], repo: Path) -> list[dict]:
    """The pre-push checks app-ci v1.x runs for these caller inputs, in the plan's derivation-map order.

    Never derived: pytest, frontend unit tests, build, the frontend hook, docs drift (PR only).
    `measured_s` is not set: the rollout measures each check on this box. A tag outside app-ci v1
    is an error, not a guess.
    """
    if not tag.startswith("app-ci-v1."):
        raise ValueError(f"unknown app-ci version {tag!r}: this generator knows app-ci-v1.x only")
    checks: list[dict] = [
        {
            "name": "ruff-check",
            "ci_step": "ci / lint_and_test / Ruff lint",
            "cwd": ".",
            "argv": ["{py}", "-m", "ruff", "check", "src/", "tests/"],
            "paths": list(_PY_PATHS),
            "enabled": True,
        },
        {
            "name": "ruff-format",
            "ci_step": "ci / lint_and_test / Ruff format check",
            "cwd": ".",
            "argv": ["{py}", "-m", "ruff", "format", "--check", "src/", "tests/"],
            "paths": list(_PY_PATHS),
            "enabled": True,
        },
    ]
    if not _off(inputs, "mypy"):
        checks.append({
            "name": "mypy",
            "ci_step": "ci / lint_and_test / Mypy",
            "cwd": ".",
            "argv": ["{py}", "-m", "mypy", "src/"],
            "paths": ["src/", "pyproject.toml"],
            "enabled": True,
        })
    frontend = inputs.get("frontend", "").strip() == "required" or (repo / "frontend" / "package.json").is_file()
    if frontend:
        if not _off(inputs, "typescript_check"):
            checks.append({
                "name": "tsc",
                "ci_step": "ci / frontend_checks / TypeScript check",
                "cwd": "frontend",
                "argv": ["npx", "tsc", "--noEmit"],
                "paths": ["frontend/"],
                "enabled": True,
            })
        lint_script = inputs.get("frontend_lint_script", "").strip()
        checks.append({
            "name": "eslint",
            "ci_step": "ci / frontend_checks / ESLint",
            "cwd": "frontend",
            "argv": ["npm", "run", lint_script] if lint_script else ["npx", "eslint", "src/"],
            "paths": ["frontend/"],
            "enabled": True,
        })
    hook = inputs.get("checks_hook", "").strip()
    if hook:
        # App content: it may hold slow or test-like steps. The rollout enables it per repo after reading it.
        checks.append({
            "name": "checks-hook",
            "ci_step": "ci / lint_and_test / App checks hook",
            "cwd": ".",
            "argv": ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", hook],
            "enabled": False,
        })
    return checks


# -- rendering ----------------------------------------------------------------------------------------


def _toml_value(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        # A JSON string with ASCII escapes is a valid TOML basic string.
        return json.dumps(value, ensure_ascii=True)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    raise TypeError(f"cannot write {type(value).__name__} to TOML: {value!r}")


def render_pre_push_section(
    checks: list[dict], *, source: str, derived_from: str, ci_sha256: str, budget_s: int = 30
) -> str:
    """The `[pre_push]` section as TOML text; `tomllib.loads` gives back the same check dicts."""
    out = [
        "[pre_push]",
        f"source = {_toml_value(source)}",
        f"derived_from = {_toml_value(derived_from)}",
        f"ci_caller_sha256 = {_toml_value(ci_sha256)}",
        f"budget_s = {_toml_value(budget_s)}",
    ]
    for check in checks:
        out.append("")
        out.append("[[pre_push.check]]")
        for key, value in check.items():
            out.append(f"{key} = {_toml_value(value)}")
    return "\n".join(out) + "\n"
