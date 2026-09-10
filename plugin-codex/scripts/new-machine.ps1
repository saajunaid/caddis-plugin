<#
.SYNOPSIS
  Set up a new Windows machine with the caddis toolchain, in the right order.

.DESCRIPTION
  The ORDER matters, and it is the only thing this script really encodes:

    1. Agents first.  caddis is a META-installer — `caddis init` detects which agents are
       present and installs into each. An agent installed AFTER it is simply not seen,
       and you get a silent no-op rather than an error.

       Note the rule is about `caddis init`, NOT about installing the CLI. The npm package
       has no postinstall step; it only puts binaries on PATH. Installing it early is safe.
    2. caddis CLI second, which brings the model-lane binaries with it.
    3. Keys and status line last. Both depend on the CLI being on PATH.

  Fetch this script on a machine that has no caddis yet (the SOURCE repo is private; the
  public mirror is what a new machine can reach):

    irm https://raw.githubusercontent.com/saajunaid/caddis-plugin/main/plugin/scripts/new-machine.ps1 -OutFile $env:TEMP
ew-machine.ps1

  Everything is idempotent: re-running skips what is already correct.

  This script NEVER installs an agent for you. Each vendor's installer is theirs, changes
  without notice, and may need an interactive login. It checks, reports, and tells you the
  one command to run — then verifies afterwards.

.PARAMETER SkipKeys
  Do not run `caddis keys` (which prompts). Use on a machine that only needs Claude.

.PARAMETER WhatIf
  Report what would happen; change nothing.

.EXAMPLE
  .\new-machine.ps1
  .\new-machine.ps1 -SkipKeys
#>
[CmdletBinding(SupportsShouldProcess)]
param(
    [switch]$SkipKeys
)

$ErrorActionPreference = 'Stop'
$script:Problems = @()

function Step($n, $text) { Write-Host "`n[$n] $text" -ForegroundColor Cyan }
function Ok($text)       { Write-Host "   OK    $text" -ForegroundColor Green }
function Missing($text)  { Write-Host "   TODO  $text" -ForegroundColor Yellow }
function Bad($text)      { Write-Host "   FAIL  $text" -ForegroundColor Red; $script:Problems += $text }
function Note($text)     { Write-Host "         $text" -ForegroundColor DarkGray }

function Test-Bin($name) { $null -ne (Get-Command $name -ErrorAction SilentlyContinue) }

# ── 0. prerequisites ────────────────────────────────────────────────────────────────────
Step 0 'Prerequisites'

foreach ($p in @(
    @{ bin = 'node';   why = 'runs the caddis CLI and every agent installer'; get = 'winget install OpenJS.NodeJS.LTS' },
    @{ bin = 'python'; why = 'runs the caddis hooks and the status line';     get = 'winget install Python.Python.3.12' },
    @{ bin = 'git';    why = 'the status line and most commands read git state'; get = 'winget install Git.Git' }
)) {
    if (Test-Bin $p.bin) { Ok "$($p.bin) — $($p.why)" }
    else { Bad "$($p.bin) is missing — $($p.why).  Install: $($p.get)" }
}

if ($script:Problems.Count -gt 0) {
    Write-Host "`nStopping: the prerequisites above are required before anything else works." -ForegroundColor Red
    exit 1
}

# ── 1. the agents — BEFORE caddis, or caddis cannot see them ────────────────────────────
Step 1 'Agents (install these BEFORE caddis)'
Note 'caddis installs INTO an agent. One added later needs a re-run of `caddis init`.'

$agents = @(
    @{ bin = 'claude'; name = 'Claude Code'; get = 'npm i -g @anthropic-ai/claude-code'; login = 'claude  (log in on first run)' },
    @{ bin = 'agy';    name = 'Antigravity (agy)'; get = 'download from antigravity.google'; login = 'agy  (log in on first run)' },
    @{ bin = 'codex';  name = 'Codex';       get = 'npm i -g @openai/codex'; login = 'codex login   (INTERACTIVE — a script cannot do this)' }
)

$present = @()
foreach ($a in $agents) {
    if (Test-Bin $a.bin) {
        $ver = (& $a.bin --version 2>&1 | Select-Object -First 1)
        Ok "$($a.name) — $ver"
        $present += $a.name
    } else {
        Missing "$($a.name) not found.  Install: $($a.get)"
        Note "then: $($a.login)"
    }
}

if ($present.Count -eq 0) {
    Write-Host "`nStopping: no agents found, so caddis would install into nothing." -ForegroundColor Red
    exit 1
}

# ── 2. caddis CLI ───────────────────────────────────────────────────────────────────────
Step 2 'caddis CLI'
Note 'Brings claude-oss / claude-glm / claude-deepseek onto PATH as well — no profile edit.'

if (Test-Bin 'caddis') {
    Ok "caddis CLI present — $(caddis --version 2>&1 | Select-Object -First 1)"
} elseif ($PSCmdlet.ShouldProcess('npm', 'install -g @caddis/cli')) {
    npm i -g '@caddis/cli'
    if (Test-Bin 'caddis') { Ok 'caddis CLI installed' } else { Bad 'npm reported success but `caddis` is not on PATH — open a new shell and re-run' ; exit 1 }
}

# ── 3. drive each agent ─────────────────────────────────────────────────────────────────
Step 3 'Install caddis into every detected agent'
if ($PSCmdlet.ShouldProcess('agents', 'caddis init')) {
    caddis init
}

# ── 4. provider keys ────────────────────────────────────────────────────────────────────
Step 4 'Provider API keys (GLM / DeepSeek)'
if ($SkipKeys) {
    Note 'Skipped (-SkipKeys). Run `caddis keys` later to enable the OSS model lanes.'
} elseif ($PSCmdlet.ShouldProcess('~/.caddis/keys.env', 'caddis keys')) {
    Note 'Prompts per provider, validates against the live endpoint, never prints a key.'
    caddis keys
}

# ── 5. status line ──────────────────────────────────────────────────────────────────────
Step 5 'Status line (Claude Code + agy, user scope, once per machine)'
$statusline = Join-Path $HOME '.caddis\statusline.py'
if (Test-Path $statusline) {
    if ($PSCmdlet.ShouldProcess($statusline, 'install')) { python $statusline --install }
} else {
    Missing "statusline.py not found at $statusline"
    Note 'It ships with the plugin. Run `/caddis:statusline` in a Claude Code session, or'
    Note 'python PLUGIN_ROOT/scripts/caddis_statusline.py --install'
}

# ── 6. verify ───────────────────────────────────────────────────────────────────────────
Step 6 'Verify'

caddis status

if (Test-Path $statusline) {
    python $statusline --check
}

if (-not $SkipKeys -and (Test-Bin 'caddis')) {
    Note 'Validating keys against the live endpoints...'
    caddis keys --check
}

Write-Host "`n-- Per repo, not per machine --" -ForegroundColor Cyan
Note 'In each project, once:   /caddis:setup-project-ai'
Note 'The status line is deliberately NOT per-repo — one renderer serves every project.'

Write-Host "`n-- Known gotchas on this platform --" -ForegroundColor Cyan
Note 'codex headless: pass -c model_reasoning_effort=low. The default `high` can exceed 300s'
Note '                on a trivial call.'
Note '`codex doctor` is NOT an auth check — it validates the auth FILE, not the token, and'
Note '                reports healthy against a dead one. Real check:'
Note '                codex exec --skip-git-repo-check -s read-only "Reply OK"'
Note 'agy statusLine is NOT parsed through a shell, so its path must be UNQUOTED. --install'
Note '                handles this; if you wire it by hand, do not add quotes.'
Note 'Codex has NO status line and cannot have one — no status_line key in config.toml and'
Note '                nothing in `codex --help` (measured on codex-cli 0.150.1). Upstream limit,'
Note '                not a caddis gap. Two profiles exist because two hosts can call them.'

if ($script:Problems.Count -gt 0) {
    Write-Host "`n$($script:Problems.Count) problem(s) above." -ForegroundColor Red
    exit 1
}
Write-Host "`nDone." -ForegroundColor Green
