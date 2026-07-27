#!/usr/bin/env bash
# caddis status line for Antigravity (agy). Shipped IN the agy plugin bundle (lands at
# ~/.gemini/config/plugins/caddis/statusline-command-agy.sh on install). Wire it once per machine in
# ~/.gemini/antigravity-cli/settings.json — use the SHORT bash path (agy runs the command via cmd.exe,
# where a bare `bash` is not on PATH and quoted spaced paths break):
#   "statusLine": {"type":"command",
#     "command":"C:\\PROGRA~1\\Git\\bin\\bash.exe ~/.gemini/config/plugins/caddis/statusline-command-agy.sh",
#     "enabled":true}
# Reads agy's status JSON on stdin and prints one compact, colorized line, styled like the Claude Code
# status line (statusline-command.sh):  dir · branch ±dirty · model · ctx% · mode · q%
# agy's payload field names differ from Claude Code's — this is a sibling, not a copy.
input=$(cat)

# Parse the agy status JSON via Python; emit shell var assignments to eval into scope.
eval "$(python -c '
import sys, json, shlex
try:
    d = json.load(sys.stdin)
except Exception:
    d = {}
def g(*keys):
    v = d
    for k in keys:
        if not isinstance(v, dict): return ""
        v = v.get(k)
    if v is None or v is False or v == "": return ""
    return str(v)
cwd      = g("workspace","current_dir") or g("cwd")
branch   = g("vcs","branch")
model    = g("model","display_name") or g("model","id")
used_pct = g("context_window","used_percentage")
mode     = g("execution_mode")
# quota: agy sends {name: {remaining_fraction, reset_time, ...}}. Show the BINDING (min-remaining) as a %.
quota_pct = ""
q = d.get("quota")
if isinstance(q, dict) and q:
    fr = [v.get("remaining_fraction") for v in q.values()
          if isinstance(v, dict) and isinstance(v.get("remaining_fraction"), (int, float))]
    if fr:
        quota_pct = str(int(round(min(fr) * 100)))
for name, val in [
    ("cwd",cwd),("branch",branch),("model",model),("used_pct",used_pct),("mode",mode),("quota_pct",quota_pct),
]:
    print(f"{name}={shlex.quote(val)}")
' <<< "$input")"

# Fall back to git for branch when the payload omits it.
if [ -z "$branch" ] && [ -n "$cwd" ]; then
  branch=$(git -C "$cwd" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null || true)
fi

# Uncommitted-change count (time-to-commit signal), from git.
dirty=""
if [ -n "$cwd" ]; then
  n=$(git -C "$cwd" --no-optional-locks status --porcelain 2>/dev/null | grep -c . || true)
  [ -n "$n" ] && [ "$n" -gt 0 ] 2>/dev/null && dirty="$n"
fi

# Colors (ANSI).
C_DIM=$'\033[2m'; C_CYAN=$'\033[36m'; C_YEL=$'\033[33m'; C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_RST=$'\033[0m'

# Context %: green < 50, yellow < 80, red >= 80. (used_pct may be a float string.)
ctx_int="${used_pct%%.*}"; ctxcol="$C_GRN"
if [ -n "$ctx_int" ] 2>/dev/null; then
  if   [ "$ctx_int" -ge 80 ] 2>/dev/null; then ctxcol="$C_RED"
  elif [ "$ctx_int" -ge 50 ] 2>/dev/null; then ctxcol="$C_YEL"; fi
fi
# Quota % REMAINING: red <= 15, yellow <= 40, else green.
qcol="$C_GRN"
if [ -n "$quota_pct" ] 2>/dev/null; then
  if   [ "$quota_pct" -le 15 ] 2>/dev/null; then qcol="$C_RED"
  elif [ "$quota_pct" -le 40 ] 2>/dev/null; then qcol="$C_YEL"; fi
fi

sep="${C_DIM} · ${C_RST}"
segs=()
[ -n "$cwd" ]      && segs+=("${C_DIM}$(basename "$cwd")${C_RST}")
if [ -n "$branch" ]; then
  b="${C_CYAN}${branch}${C_RST}"; [ -n "$dirty" ] && b="${b} ${C_YEL}±${dirty}${C_RST}"; segs+=("$b")
fi
[ -n "$model" ]    && segs+=("$model")
[ -n "$ctx_int" ]  && segs+=("${ctxcol}ctx ${ctx_int}%${C_RST}")
[ -n "$mode" ]     && segs+=("${C_DIM}${mode}${C_RST}")
[ -n "$quota_pct" ] && segs+=("${qcol}q ${quota_pct}%${C_RST}")

out=""
for i in "${!segs[@]}"; do
  [ "$i" -gt 0 ] && out="${out}${sep}"
  out="${out}${segs[$i]}"
done
printf '%b' "$out"
