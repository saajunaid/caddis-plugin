"""PostToolUse — re-warn when an Edit/Write/MultiEdit touches an always-loaded rules file
(AGENTS.md / CLAUDE.md) that is already over the line budget, or crosses it as a result of
this edit.

The SessionStart/PreCompact nudge (claudster_doctor.nudge_line) only fires at those two
points, so a long session that keeps appending to an already-oversize AGENTS.md gets no
signal until the next session start or compaction — register 0e's gap. This closes it
deterministically: a pure file check (line count vs. the one shared budget in
claudster_doctor.AGENTS_MD_BUDGET), no subprocess, no LLM, no auto-fix. The curator stays
human-triggered; this only prints a nudge.
"""
import json
import os
import sys

_HOOKS_DIR = os.path.dirname(os.path.abspath(__file__))
# Two candidate layouts: the installed/exported plugin has hooks/ and scripts/ as siblings
# (one level up from hooks/); the raw claudster-source repo keeps claudster_doctor.py at the
# repo-root scripts/ instead, two levels up from claude-harness/hooks/. Try both so the hook
# resolves identically whether it's running installed or straight out of this source tree
# (the latter is what the test suite exercises).
for _cand in (
    os.path.join(os.path.dirname(_HOOKS_DIR), "scripts"),
    os.path.join(os.path.dirname(os.path.dirname(_HOOKS_DIR)), "scripts"),
):
    if os.path.isdir(_cand) and _cand not in sys.path:
        sys.path.insert(0, _cand)

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

tool_input = data.get("tool_input") or {}
file_path = str(tool_input.get("file_path") or tool_input.get("path") or "")
if not file_path or os.path.basename(file_path) not in ("AGENTS.md", "CLAUDE.md"):
    sys.exit(0)

try:
    import claudster_doctor as _cd

    if not os.path.isfile(file_path):
        sys.exit(0)
    lines = len(open(file_path, encoding="utf-8", errors="replace").read().splitlines())
    if lines > _cd.AGENTS_MD_BUDGET:
        root = data.get("cwd") or os.getcwd()
        try:
            rel = os.path.relpath(file_path, root).replace(os.sep, "/")
        except Exception:
            rel = os.path.basename(file_path)
        print(f"[caddis] {_cd.oversize_message(rel, lines)}", flush=True)
except Exception:
    pass

sys.exit(0)
