#!/usr/bin/env pwsh
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repoRoot = (git rev-parse --show-toplevel 2>$null)
if (-not $repoRoot) {
    throw "Not inside a git repository."
}

$repoRoot = $repoRoot.Trim()
$hooksSource = Join-Path $repoRoot ".github/hooks"
$hooksTarget = Join-Path $repoRoot ".git/hooks"

if (-not (Test-Path $hooksSource)) {
    throw "Hooks source folder not found: $hooksSource"
}

if (-not (Test-Path $hooksTarget)) {
    throw "Git hooks target folder not found: $hooksTarget"
}

$preCommitWrapper = @'
#!/usr/bin/env sh
set -eu

if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoProfile -ExecutionPolicy Bypass -File ".github/hooks/pre-commit-quality-gate.ps1"
else
  sh ".github/hooks/pre-commit-quality-gate.sh"
fi
'@

$commitMsgWrapper = @'
#!/usr/bin/env sh
set -eu

sh ".github/hooks/commit-msg-conventional.sh" "$1"
'@

$prePushWrapper = @'
#!/usr/bin/env sh
set -eu

if command -v pwsh >/dev/null 2>&1; then
  pwsh -NoProfile -ExecutionPolicy Bypass -File ".github/hooks/pre-push-quality-gate.ps1"
else
  sh ".github/hooks/pre-push-quality-gate.sh"
fi
'@

Set-Content -Path (Join-Path $hooksTarget "pre-commit") -Value $preCommitWrapper -NoNewline
Set-Content -Path (Join-Path $hooksTarget "commit-msg") -Value $commitMsgWrapper -NoNewline
Set-Content -Path (Join-Path $hooksTarget "pre-push") -Value $prePushWrapper -NoNewline

Write-Host "Installed hooks:" -ForegroundColor Green
Write-Host "- .git/hooks/pre-commit"
Write-Host "- .git/hooks/commit-msg"
Write-Host "- .git/hooks/pre-push"
