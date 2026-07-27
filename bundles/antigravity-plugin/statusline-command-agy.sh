#!/usr/bin/env bash
# caddis status line for Antigravity (agy). Shipped IN the agy plugin bundle (lands at
# ~/.gemini/config/plugins/caddis/statusline-command-agy.sh on install). Wire it once per machine in
# ~/.gemini/antigravity-cli/settings.json:  "statusLine": {"type":"command",
# "command":"bash ~/.gemini/config/plugins/caddis/statusline-command-agy.sh","enabled":true}
# Reads agy's status JSON on stdin and prints one compact, colorized line:
#   dir · branch ±dirty · model · ctx% (color-coded) · mode · quota
# The agy payload field names differ from Claude Code's, so this is a sibling of statusline-command.sh,
# not a copy. Keep the two in sync in spirit (same look), not field-for-field.
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
dirty    = g("vcs","dirty")
model    = g("model","display_name") or g("model","id")
used_pct = g("context_window","used_percentage")
mode     = g("execution_mode")
quota    = g("quota","used_percentage") or g("quota")
for name, val in [
    ("cwd",cwd),("branch",branch),("dirty_flag",dirty),("model",model),
    ("used_pct",used_pct),("mode",mode),("quota",quota),
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

# Context %: green < 50, yellow < 80, red >= 80.
ctxcol="$C_GRN"; pct_int="${used_pct%%.*}"
if [ -n "$pct_int" ] 2>/dev/null; then
  if [ "$pct_int" -ge 80 ] 2>/dev/null; then ctxcol="$C_RED"
  elif [ "$pct_int" -ge 50 ] 2>/dev/null; then ctxcol="$C_YEL"; fi
fi

sep=" ${C_DIM}·${C_RST} "
out=""
[ -n "$cwd" ]      && out="${C_DIM}$(basename "$cwd")${C_RST}"
[ -n "$branch" ]   && out="${out}${sep}${C_CYAN}${branch}${C_RST}"
[ -n "$dirty" ]    && out="${out} ${C_YEL}±${dirty}${C_RST}"
[ -n "$model" ]    && out="${out}${sep}${model}"
[ -n "$used_pct" ] && out="${out}${sep}${ctxcol}ctx ${pct_int}%${C_RST}"
[ -n "$mode" ]     && out="${out}${sep}${mode}"
[ -n "$quota" ]    && out="${out}${sep}quota ${quota%%.*}%"
printf '%b' "$out"
