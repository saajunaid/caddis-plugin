# claude-oss / claude-glm — launch a Claude Code session against an OSS provider's
# Anthropic-protocol endpoint (GLM, DeepSeek, or a custom OSS_BASE_URL/OSS_MODEL;
# OpenRouter/local models need an Anthropic-compatible gateway — see LOCAL-MODELS.md).
#
# Usage:
#   claude-oss <provider> [claude args...]     # e.g. claude-oss glm -p "say ok"
#   claude-glm [claude args...]                # convenience alias (provider = glm)
#
# Endpoint/model/key are resolved by oss_model.py (keys are never hardcoded — see
# CADDIS_KEYS_FILE). This reads $args directly and declares NO parameter block: a
# declared parameter would swallow claude's own flags (e.g. -p) before claude sees them.
# The ANTHROPIC_* env is saved and RESTORED in finally, so your default `claude` in this
# session is untouched.
$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$invoked = [System.IO.Path]::GetFileNameWithoutExtension($MyInvocation.MyCommand.Name)

# claude-glm forces provider=glm and passes every arg to claude; otherwise the first
# arg is the provider and the rest go to claude.
if ($invoked -like "claude-glm*") {
  $provider = "glm"
  $rest = $args
} else {
  $provider = if ($args.Count -ge 1) { $args[0] } else { $null }
  $rest = if ($args.Count -ge 2) { $args[1..($args.Count - 1)] } else { @() }
}

if (-not $provider) {
  Write-Error "usage: claude-oss <provider> [claude args...]   (providers: deepseek, glm, openrouter)"
  exit 2
}

# Save the current ANTHROPIC_* so we can restore them — this launcher shares the session.
$restore = @{}
foreach ($name in "ANTHROPIC_BASE_URL", "ANTHROPIC_MODEL", "ANTHROPIC_AUTH_TOKEN", "CADDIS_HEADLESS") {
  $restore[$name] = [Environment]::GetEnvironmentVariable($name)
}

# claude's -p/--print means no human is watching. Say so in the env so the caddis hooks can
# act on it — the SessionStart relay injection is skipped for headless runs, because a run
# handed its task on the command line does not need a resume pointer and was observed
# EXECUTING the relay's leftover next step before its own prompt.
$headless = $false
foreach ($a in $rest) { if ($a -eq "-p" -or $a -eq "--print") { $headless = $true } }
if ($headless) { $env:CADDIS_HEADLESS = "1" }

try {
  # Resolve endpoint/model/key. The three stdout lines are captured into a variable and
  # assigned to the env — the key is never written to the console.
  $cfg = & python "$scriptDir\oss_model.py" $provider
  if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

  $env:ANTHROPIC_BASE_URL   = $cfg[0]
  $env:ANTHROPIC_MODEL      = $cfg[1]
  $env:ANTHROPIC_AUTH_TOKEN = $cfg[2]

  & claude @rest
  exit $LASTEXITCODE
} finally {
  foreach ($name in $restore.Keys) {
    Set-Item -Path "Env:$name" -Value $restore[$name] -ErrorAction SilentlyContinue
    if ($null -eq $restore[$name]) { Remove-Item -Path "Env:$name" -ErrorAction SilentlyContinue }
  }
}
