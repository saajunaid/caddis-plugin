"""Auto-lint after Edit/Write (PostToolUse). Runs ruff for .py, eslint for .ts/.tsx/.js/.jsx.

Surfaces lint findings on the just-edited file so they're fixed in the same loop rather
than at CI time. Best-effort: if the linter isn't installed or the payload is unexpected,
it exits silently — linting must never block an edit. Cross-platform (pure Python).
"""
import json
import os
import shutil
import subprocess
import sys

# No child process of this hook opens a console window on Windows (scripts/no_window.py). The inline
# fallback keeps a hook from ever dying on an import problem.
try:
    _nw_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
    if _nw_dir not in sys.path:
        sys.path.insert(0, _nw_dir)
    from no_window import NO_WINDOW_KW  # noqa: E402
except Exception:  # pragma: no cover - defensive
    NO_WINDOW_KW = {"creationflags": 0x08000000} if os.name == "nt" else {}

# Linter output may contain Unicode (paths, glyphs); force UTF-8 stdout so a
# narrow Windows console can't raise UnicodeEncodeError.
_reconfig = getattr(sys.stdout, "reconfigure", None)
if _reconfig:
    try:
        _reconfig(encoding="utf-8")
    except Exception:
        pass

try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

if data.get("tool_name") not in ("Edit", "Write", "MultiEdit"):
    sys.exit(0)

file_path = data.get("tool_input", {}).get("file_path", "")
if not file_path or not os.path.isfile(file_path):
    sys.exit(0)

ext = os.path.splitext(file_path)[1].lower()

# Every printed line lands in the model's context after each edit, so the output is bounded.
MAX_FINDINGS = 20


def run(cmd):
    """Run a linter, tolerating a missing executable (returns None then)."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **NO_WINDOW_KW)
    except (FileNotFoundError, OSError):
        return None


if ext == ".py":
    # E501 is ignored: with no ruff config every line over 88 chars was a finding, and the
    # default "full" format printed a source snippet for each - 32,305 chars into context
    # for one 63-finding file. Concise format is one line per finding; the cap bounds the rest.
    r = run(["ruff", "check", "--select", "E,F,W", "--ignore", "E501",
             "--output-format", "concise", "--quiet", file_path])
    if r and r.stdout.strip():
        findings = r.stdout.strip().splitlines()
        shown = "\n".join(findings[:MAX_FINDINGS])
        extra = len(findings) - MAX_FINDINGS
        if extra > 0:
            shown += (f"\n... {extra} more findings "
                      "(run: ruff check --select E,F,W --ignore E501 <file>)")
        print(f"[lint] ruff:\n{shown}", flush=True)

elif ext in (".ts", ".tsx", ".js", ".jsx"):
    # Windows CreateProcess will not resolve the `npx.CMD` shim from a bare "npx", so this
    # branch raised FileNotFoundError and run() swallowed it — JS/TS lint silently never
    # happened on the primary platform. Resolve the real executable first.
    _npx = shutil.which("npx")
    if not _npx:
        sys.exit(0)
    r = run([_npx, "--no", "eslint", "--format", "compact", file_path])
    if r and r.returncode != 0 and r.stdout.strip():
        print(f"[lint] eslint:\n{r.stdout.strip()[:600]}", flush=True)

sys.exit(0)
