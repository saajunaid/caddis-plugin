#!/usr/bin/env bash
# caddis status line. Deployed by setup-project-ai to .claude/statusline-command.sh
# and referenced from .claude/settings.json. Reads the Claude Code status JSON on stdin
# and prints one compact, colorized line: dir · repo:branch[worktree] ±dirty · model vN ·
# ctx% (color-coded) · effort · style · thinking · rate limits · PR · vim · relay.
input=$(cat)

# Parse the status JSON via Python; emit shell var assignments to eval into scope.
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
cwd          = g("cwd") or g("workspace","current_dir")
repo_owner   = g("workspace","repo","owner")
repo_name    = g("workspace","repo","name")
repo         = f"{repo_owner}/{repo_name}" if repo_owner and repo_name else ""
branch       = g("worktree","branch")
git_worktree = g("workspace","git_worktree")
model        = g("model","display_name")
version      = g("version")
used_pct     = g("context_window","used_percentage")
effort       = g("effort","level")
style        = g("output_style","name")
thinking     = g("thinking","enabled")
five_hr      = g("rate_limits","five_hour","used_percentage")
seven_day    = g("rate_limits","seven_day","used_percentage")
pr_num       = g("pr","number")
pr_state     = g("pr","review_state")
vim_mode     = g("vim","mode")
session_name = g("session_name")
for name, val in [
    ("cwd",cwd),("repo",repo),("branch",branch),("git_worktree",git_worktree),
    ("model",model),("version",version),("used_pct",used_pct),("effort",effort),
    ("style",style),("thinking",thinking),("five_hr",five_hr),("seven_day",seven_day),
    ("pr_num",pr_num),("pr_state",pr_state),("vim_mode",vim_mode),("session_name",session_name),
]:
    print(f"{name}={shlex.quote(val)}")
' <<< "$input")"

# Fall back to git for branch if not in payload
if [ -z "$branch" ] && [ -n "$cwd" ]; then
  branch=$(git -C "$cwd" --no-optional-locks rev-parse --abbrev-ref HEAD 2>/dev/null || true)
fi

# Uncommitted-change count (time-to-commit signal)
dirty=""
if [ -n "$cwd" ]; then
  n=$(git -C "$cwd" --no-optional-locks status --porcelain 2>/dev/null | grep -c . || true)
  [ -n "$n" ] && [ "$n" -gt 0 ] 2>/dev/null && dirty="$n"
fi

# relay present? (context resumes next session) — prefer .caddis, then the legacy repo-root relay.md
relay=""
[ -n "$cwd" ] && { [ -f "$cwd/.caddis/relay.md" ] || [ -f "$cwd/relay.md" ]; } && relay="relay"

# Directory basename
dir=$(echo "$cwd" | sed 's|.*[/\\]||')

CYAN=$'\e[96m'; YELLOW=$'\e[93m'; GREEN=$'\e[92m'; MAGENTA=$'\e[95m'
BLUE=$'\e[94m'; RED=$'\e[91m'; WHITE=$'\e[97m'; DIM=$'\e[90m'; RESET=$'\e[0m'
CTX_LOW=$'\e[30;106m'; CTX_MED=$'\e[30;103m'; CTX_HIGH=$'\e[97;101m'

parts=()
[ -n "$dir" ] && parts+=("${CYAN}${dir}${RESET}")

if [ -n "$repo" ]; then
  repo_str="$repo"
  [ -n "$branch" ] && repo_str="${repo_str}:${branch}"
  [ -n "$git_worktree" ] && repo_str="${repo_str}[${git_worktree}]"
  [ -n "$dirty" ] && repo_str="${repo_str} ${RED}±${dirty}${YELLOW}"
  parts+=("${YELLOW}${repo_str}${RESET}")
elif [ -n "$branch" ]; then
  b="${branch}"
  [ -n "$dirty" ] && b="${b} ${RED}±${dirty}${YELLOW}"
  parts+=("${YELLOW}${b}${RESET}")
fi

if [ -n "$model" ]; then
  model_str="$model"
  [ -n "$version" ] && model_str="${model_str} v${version}"
  parts+=("${GREEN}${model_str}${RESET}")
fi

if [ -n "$used_pct" ]; then
  ctx_int=$(printf "%.0f" "$used_pct")
  if [ "$ctx_int" -ge 80 ]; then ctx_color="$CTX_HIGH"
  elif [ "$ctx_int" -ge 60 ]; then ctx_color="$CTX_MED"
  else ctx_color="$CTX_LOW"; fi
  parts+=(" ${ctx_color} ctx:${ctx_int}% ${RESET}")
fi

[ -n "$effort" ] && parts+=("${BLUE}effort:${effort}${RESET}")
if [ -n "$style" ] && [ "$style" != "default" ] && [ "$style" != "Default" ]; then
  parts+=("${BLUE}style:${style}${RESET}")
fi
[ "$thinking" = "true" ] && parts+=("${MAGENTA}thinking${RESET}")

if [ -n "$five_hr" ] || [ -n "$seven_day" ]; then
  rate_str=""
  [ -n "$five_hr" ]   && rate_str="5h:$(printf '%.0f' "$five_hr")%"
  [ -n "$five_hr" ] && [ -n "$seven_day" ] && rate_str="${rate_str} 7d:$(printf '%.0f' "$seven_day")%"
  [ -z "$five_hr" ] && [ -n "$seven_day" ] && rate_str="7d:$(printf '%.0f' "$seven_day")%"
  parts+=("${YELLOW}${rate_str}${RESET}")
fi

if [ -n "$pr_num" ]; then
  pr_str="PR#${pr_num}"
  [ -n "$pr_state" ] && pr_str="${pr_str}(${pr_state})"
  parts+=("${GREEN}${pr_str}${RESET}")
fi

[ -n "$vim_mode" ] && parts+=("${WHITE}[${vim_mode}]${RESET}")
[ -n "$relay" ] && parts+=("${DIM}⏺ ${relay}${RESET}")
[ -n "$session_name" ] && parts+=("${DIM}\"${session_name}\"${RESET}")

if [ ${#parts[@]} -gt 0 ]; then
  result=""
  for i in "${!parts[@]}"; do
    if [ "$i" -eq 0 ]; then result="${parts[$i]}"
    else result="${result} ${DIM}|${RESET} ${parts[$i]}"; fi
  done
  printf "%s\n" "$result"
fi
