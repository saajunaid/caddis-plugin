<#
.SYNOPSIS
  After pushing a feature branch, prove GitHub could PARSE its workflows.

.DESCRIPTION
  GitHub cannot evaluate the triggers of a workflow file it cannot parse, so an invalid file
  produces a failed run with ZERO jobs ("startup_failure") on every push, even on a branch its
  triggers would never match. A valid file whose triggers do not match produces no run at all.

  So, for the pushed commit:
    a run with conclusion startup_failure, or failure with zero jobs  -> INVALID (exit 1)
    no run, or runs with real jobs                                     -> parsed (exit 0)

  Waits -WaitSeconds for GitHub to react, because an invalid file's run appears within seconds
  and "no run" is only meaningful after that window.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Owner,
    [Parameter(Mandatory)][string]$Repo,
    [Parameter(Mandatory)][string]$Branch,
    [string]$Sha,
    [int]$WaitSeconds = 60
)

$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'PortCommon.ps1')
$full = "$Owner/$Repo"

if (-not $Sha) {
    $Sha = (& gh api "repos/$full/commits/$Branch" --jq .sha 2>&1)
    if ($LASTEXITCODE -ne 0) { throw "Branch $Branch not found on ${full}: $Sha" }
}
Write-PortStep "Watching $full @ $($Sha.Substring(0,12)) on $Branch for $WaitSeconds s"

$deadline = (Get-Date).AddSeconds($WaitSeconds)
$invalid = @()
$runs = @()
do {
    Start-Sleep -Seconds 10
    $json = & gh api "repos/$full/actions/runs?head_sha=$Sha&per_page=50" 2>&1
    if ($LASTEXITCODE -ne 0) { throw "Cannot list runs: $json" }
    $runs = @(($json | ConvertFrom-Json).workflow_runs)
    $invalid = @()
    foreach ($r in $runs) {
        if ($r.conclusion -eq 'startup_failure') { $invalid += $r; continue }
        if ($r.status -eq 'completed' -and $r.conclusion -eq 'failure') {
            $jobs = (& gh api "repos/$full/actions/runs/$($r.id)/jobs" --jq .total_count 2>$null)
            if ("$jobs" -eq '0') { $invalid += $r }
        }
    }
    if ($invalid.Count -gt 0) { break }
} while ((Get-Date) -lt $deadline)

if ($invalid.Count -gt 0) {
    foreach ($r in $invalid) { Write-PortFail "INVALID workflow: '$($r.name)' ($($r.path)) - $($r.html_url)" }
    Write-Host '    GitHub gives no line number. Look first for an empty ${{ }}; then bisect by removing jobs from the END (removing a middle job breaks needs: and fails the same way).'
    exit 1
}
if ($runs.Count -eq 0) { Write-PortOk "No run for this commit: every workflow parsed and none matched a branch push. This is the expected result for main-only triggers." }
else { foreach ($r in $runs) { Write-PortOk "Run '$($r.name)' has real jobs ($($r.status)/$($r.conclusion)): the file parsed. $($r.html_url)" } }
exit 0
